"""Train the Challenger with GRPO against the exploit-gap reward.

Run it:

    # wiring gate, CPU, tiny model, no GPU and no Docker needed
    uv run --extra train --extra adapters python -m assay.train.run --smoke

    # the real thing, on one A10G
    uv run --extra train --extra adapters python -m assay.train.run \
        --model Qwen/Qwen3-1.7B --steps 300 --group-size 8 \
        --only fixture harbor --holdout harbor/self-graded \
        --out checkpoints/grpo

What makes this different from an ordinary GRPO loop is that the reward runs
the environment. Every rollout is replayed in a real workspace -- a Docker
container, for the Harbor tasks -- and scored twice, by the environment's own
verifier and by an independent one. So the wall clock is dominated by the
environment, not the model, and the group size is the knob that matters most.

Nothing here is needed to audit an environment. The artifact this produces is
an optional LoRA adapter; the scripted Challenger is the floor and needs none
of it.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from .config import DEFAULT_MODEL, SMOKE_MODEL, filter_for, grpo_kwargs, lora_kwargs
from .dataset import training_data
from .reward import make_reward_func


def _device_report() -> dict[str, Any]:
    import torch

    cuda = torch.cuda.is_available()
    return {
        "torch": torch.__version__,
        "cuda": cuda,
        "gpu": torch.cuda.get_device_name(0) if cuda else None,
        "mps": bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()),
        "platform": platform.platform(),
    }


def _load_model(model_id: str, *, four_bit: bool):
    """4-bit QLoRA where CUDA exists, plain weights where it does not.

    Refusing to run without a GPU would make the smoke gate need one, and the
    gate exists precisely so that the first thing a spot instance does is not
    discover a typo. Falling back is stated in the log, never assumed.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    kwargs: dict[str, Any] = {"dtype": "auto"}
    if four_bit and torch.cuda.is_available():
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        kwargs["device_map"] = {"": 0}
    elif four_bit:
        print("NOTE: no CUDA, so 4-bit is off and this is not the QLoRA path", flush=True)

    model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model.config.use_cache = False
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    return model, tokenizer


def train(
    *,
    model_id: str = DEFAULT_MODEL,
    smoke: bool = False,
    steps: int = 300,
    group_size: int = 8,
    learning_rate: float = 1e-5,
    beta: float = 0.02,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    holdout: list[str] | None = None,
    out: str = "checkpoints/grpo",
    reward_log: str = "",
    seed: int = 0,
) -> dict[str, Any]:
    from peft import LoraConfig, get_peft_model
    from trl import GRPOConfig, GRPOTrainer

    started = time.time()
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    reward_log_path = Path(reward_log or (out_dir / "rewards.jsonl"))

    hp = grpo_kwargs(
        smoke=smoke,
        max_steps=steps,
        group_size=group_size,
        learning_rate=learning_rate,
        beta=beta,
        output_dir=str(out_dir / "trl"),
    )
    # One prompt per optimisation step; TRL samples `num_generations` rollouts
    # from each. Cycling keeps the environments balanced at any prefix, which
    # matters because a spot instance can be reclaimed mid-run.
    target = max(hp["max_steps"] * hp["gradient_accumulation_steps"], 1)
    selection, prompts = training_data(
        only=only, skip=skip, holdout=holdout, target=target, seed=seed
    )
    print(selection.report(), flush=True)
    print(prompts.report(), flush=True)
    if not len(prompts):
        raise SystemExit(
            "no trainable environments here. Every candidate was excluded above, "
            "with a reason; training against a corpus that silently shrank would "
            "produce a number about this machine, not about the method."
        )

    manifest: dict[str, Any] = {
        "model": model_id,
        "smoke": smoke,
        "hyperparameters": hp,
        "environments": selection.pool.env_ids(),
        "excluded": selection.excluded,
        "unavailable_ecosystems": selection.unavailable,
        "prompt_counts": prompts.counts(),
        "device": _device_report(),
        "reward_log": str(reward_log_path),
    }
    print(json.dumps(manifest, indent=2), flush=True)

    model, tokenizer = _load_model(model_id, four_bit=not smoke)
    model = get_peft_model(model, LoraConfig(**lora_kwargs()))
    model.print_trainable_parameters()

    cfg_kw, dropped = filter_for(GRPOConfig, hp)
    if dropped:
        # Loud on purpose: a hyperparameter TRL silently ignored is a run that
        # trained something other than what the manifest above says.
        import trl

        print(f"WARNING: TRL {trl.__version__} does not accept {dropped}", flush=True)
    manifest["dropped_hyperparameters"] = dropped

    reward_func = make_reward_func(selection.pool, log_path=reward_log_path)

    try:
        trainer = GRPOTrainer(
            model=model,
            reward_funcs=reward_func,
            processing_class=tokenizer,
            args=GRPOConfig(**cfg_kw),
            train_dataset=prompts.to_hf(),
        )
        trainer.train()
        final = out_dir / "final"
        trainer.save_model(str(final))
        manifest["adapter"] = str(final)
        manifest["status"] = "ok"
    finally:
        selection.pool.close()

    manifest["seconds"] = round(time.time() - started, 1)
    manifest.update(summarise_rewards(reward_log_path, group_size=hp["num_generations"]))
    (out_dir / "run.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in manifest.items() if k != "hyperparameters"}, indent=2))
    if smoke:
        print("GRPO SMOKE OK", flush=True)
    return manifest


def summarise_rewards(path: str | Path, *, group_size: int) -> dict[str, Any]:
    """The numbers a write-up needs, computed from the log rather than recalled.

    `degenerate_groups` is the one to read first. GRPO's advantage is zero
    whenever every rollout in a group scored the same, so a run whose groups
    were mostly degenerate did not fail to converge -- it was never trained,
    and that is a different finding with a different fix.
    """
    from .grpo_math import group_is_degenerate

    p = Path(path)
    if not p.exists():
        return {"reward_rows": 0, "reason": f"no reward log at {p}"}
    rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    if not rows:
        return {"reward_rows": 0, "reason": f"reward log at {p} is empty"}

    values = [float(r["reward"]) for r in rows]
    groups = [values[i : i + group_size] for i in range(0, len(values), group_size)]
    n = len(values)
    parsed = sum(1 for r in rows if r.get("parsed"))
    gaps = [float(r["gap"]) for r in rows if r.get("gap") is not None]
    half = max(n // 2, 1)
    return {
        "reward_rows": n,
        "mean_reward": round(sum(values) / n, 4),
        "mean_reward_first_half": round(sum(values[:half]) / half, 4),
        "mean_reward_last_half": round(sum(values[half:]) / max(n - half, 1), 4),
        "max_reward": round(max(values), 4),
        "parse_rate": round(parsed / n, 4),
        "mean_gap_when_parsed": round(sum(gaps) / len(gaps), 4) if gaps else None,
        "hack_rate_gap_ge_0_5": round(sum(1 for g in gaps if g >= 0.5) / n, 4),
        "degenerate_groups": round(
            sum(1 for g in groups if group_is_degenerate(g)) / len(groups), 4
        ),
        "n_groups": len(groups),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="")
    ap.add_argument("--smoke", action="store_true", help="CPU wiring gate, tiny model, 2 steps")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--group-size", type=int, default=8)
    ap.add_argument("--learning-rate", type=float, default=1e-5)
    ap.add_argument("--beta", type=float, default=0.02)
    ap.add_argument("--only", nargs="*", default=["fixture", "harbor"])
    ap.add_argument("--skip", nargs="*", default=None)
    ap.add_argument(
        "--holdout",
        nargs="*",
        default=["harbor/self-graded"],
        help="env_ids kept out of training so the ablation is not train-on-test",
    )
    ap.add_argument("--out", default="checkpoints/grpo")
    ap.add_argument("--reward-log", default="")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    model_id = args.model or (SMOKE_MODEL if args.smoke else DEFAULT_MODEL)
    train(
        model_id=model_id,
        smoke=args.smoke,
        steps=args.steps,
        group_size=args.group_size,
        learning_rate=args.learning_rate,
        beta=args.beta,
        only=args.only or None,
        skip=args.skip,
        holdout=args.holdout or None,
        out=args.out,
        reward_log=args.reward_log,
        seed=args.seed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
