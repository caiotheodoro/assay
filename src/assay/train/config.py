"""GRPO hyperparameters, and a defence against TRL's API drifting under us.

TRL renames and removes `GRPOConfig` fields between minor versions. Passing an
unknown keyword is a hard TypeError at construction, which on a spot instance
means the run dies after the model has been downloaded and before a single step
has been taken. So the wanted settings are assembled as a plain dict and
filtered against `dataclasses.fields(GRPOConfig)` at call time, and whatever
was dropped is PRINTED -- a silently discarded hyperparameter is a run that
trained something other than what the log says it trained.

Pattern reused from `suture/model/src/suture_model/rlvr_train.py`; see
docs/LINEAGE.md.
"""

from __future__ import annotations

import dataclasses
from typing import Any

#: Qwen3-1.7B class, per the workstream brief. Small enough for one A10G at
#: 4-bit with room for a group of rollouts, big enough to emit valid JSON.
DEFAULT_MODEL = "Qwen/Qwen3-1.7B"

#: A tiny model for the CPU smoke gate. It will not learn anything useful; the
#: gate is about the wiring, not the weights.
SMOKE_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"


def grpo_kwargs(
    *,
    smoke: bool = False,
    max_steps: int = 300,
    group_size: int = 8,
    learning_rate: float = 1e-5,
    beta: float = 0.02,
    temperature: float = 1.0,
    top_p: float = 0.95,
    top_k: int = 0,
    max_completion_length: int = 160,
    max_prompt_length: int = 640,
    grad_accum: int = 1,
    output_dir: str = "checkpoints/grpo",
) -> dict[str, Any]:
    """Every setting we want, before any of it is checked against TRL.

    `num_generations` is the GRPO group size and has to divide the effective
    batch, so the per-device batch is pinned to it rather than set separately.
    Completions are capped short on purpose: the policies are tool calls, and
    an unbounded budget just buys the model room to argue with itself.
    """
    if smoke:
        max_steps, group_size, grad_accum = 2, 2, 1
    return {
        "output_dir": output_dir,
        "max_steps": max_steps,
        "num_generations": group_size,
        "per_device_train_batch_size": group_size,
        "gradient_accumulation_steps": grad_accum,
        "learning_rate": learning_rate,
        "beta": beta,
        "temperature": temperature,
        # GRPO needs the rollouts in a group to DIFFER. If they do not, the
        # group-relative advantage is exactly zero and there is no gradient at
        # all -- which is not slow learning, it is no learning.
        "top_p": top_p,
        **({"top_k": top_k} if top_k else {}),
        "max_completion_length": max_completion_length,
        "max_prompt_length": max_prompt_length,
        "logging_steps": 1,
        "save_steps": max(max_steps, 1) if smoke else 25,
        "save_total_limit": 3,
        "report_to": "none",
        "gradient_checkpointing": not smoke,
        "log_completions": True,
        "num_completions_to_print": 2,
        # Qwen3 thinks by default. A <think> block inside a 160-token budget
        # eats the whole completion and the policy never gets emitted, which
        # shows up as a parse rate of zero and looks exactly like a model that
        # cannot follow the format.
        "chat_template_kwargs": {"enable_thinking": False},
        "seed": 0,
    }


def filter_for(config_cls: Any, wanted: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """(accepted, dropped). `output_dir` is always kept -- it is required.

    Observed drop on TRL 1.12.0: `max_prompt_length`, which that version moved
    out of GRPOConfig entirely. Harmless here -- these prompts are ~150 tokens
    -- but it is the exact shape of failure this filter exists for, and it was
    found by the smoke gate rather than by a spot instance dying at step zero.
    """
    accepted = {f.name for f in dataclasses.fields(config_cls)}
    keep = {k: v for k, v in wanted.items() if k in accepted or k == "output_dir"}
    dropped = sorted(set(wanted) - set(keep))
    return keep, dropped


def lora_kwargs(*, r: int = 16, alpha: int = 32, dropout: float = 0.05) -> dict[str, Any]:
    """QLoRA adapter shape. `all-linear` so the wrap does not depend on this
    week's module names for a given architecture."""
    return {
        "r": r,
        "lora_alpha": alpha,
        "lora_dropout": dropout,
        "target_modules": "all-linear",
        "task_type": "CAUSAL_LM",
        "bias": "none",
    }
