"""The environment-health block `environments.md` requires, for the GRPO runs.

    uv run --extra adapters python scripts/env_health_report.py

`environments.md:131-142` specifies the block an agent implementing that skill
emits. Assay cites the file as lineage and has never emitted the block. Most of
its fields are recoverable from what the two spot-GPU runs already logged; one
is not, and the point of writing the whole block out is that the missing field
becomes visible as a hole rather than as an absence nobody notices.

Recovered from `rewards.jsonl` and `run.json`:
  n_tasks, k_rollouts, reward histogram, pct_in_band, pct_groups_zero_adv,
  harness revision, train/eval protocol difference, hack-probe outcome.

Not recoverable: `sampler_trainer_kl`. See `assay.train.onpolicy` for why the
"zero by construction" answer is not admissible, and for the field list a future
run has to log.

Reads only files in the repo. No GPU, no Docker, no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.runconfig import git_revision  # noqa: E402
from assay.train.grpo_math import group_is_degenerate  # noqa: E402
from assay.train.onpolicy import REQUIRED_FIELDS, run_kl  # noqa: E402

RUNS = ["results/assay-challenger-r1", "results/assay-challenger-r2"]

#: environments.md:57 -- the band RL can actually learn in.
BAND = (0.1, 0.8)


def histogram(values: list[float]) -> dict[str, int]:
    edges = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    out = {}
    for lo, hi in zip(edges, edges[1:]):
        out[f"[{lo:.1f},{hi:.1f})"] = sum(1 for v in values if lo <= v < hi)
    out["[1.0,1.0]"] = sum(1 for v in values if v >= 1.0)
    return out


def per_env(rows: list[dict], group_size: int) -> dict[str, dict]:
    """Group statistics per environment.

    Groups are contiguous blocks of `group_size` rows and each block is one
    (env_id, task_id) -- asserted rather than assumed, because if the log
    interleaved prompts every per-environment number below would be wrong in a
    way that still looks plausible.
    """
    groups = [rows[i : i + group_size] for i in range(0, len(rows), group_size)]
    for g in groups:
        keys = {(r["env_id"], r["task_id"]) for r in g}
        if len(keys) != 1:
            raise SystemExit(
                f"reward log is not grouped by prompt: a block of {group_size} rows "
                f"spans {sorted(keys)}. Per-environment group statistics would be "
                "meaningless, so this refuses rather than reporting them."
            )

    out: dict[str, dict] = {}
    for g in groups:
        env = g[0]["env_id"]
        slot = out.setdefault(
            env, {"groups": 0, "degenerate": 0, "rewards": [], "tasks": set()}
        )
        slot["groups"] += 1
        slot["tasks"].add(g[0]["task_id"])
        rewards = [float(r["reward"]) for r in g]
        slot["rewards"].extend(rewards)
        if group_is_degenerate(rewards):
            slot["degenerate"] += 1

    for env, slot in out.items():
        rewards = slot["rewards"]
        in_band = sum(1 for v in rewards if BAND[0] <= v <= BAND[1])
        slot["n_tasks"] = len(slot["tasks"])
        slot["tasks"] = sorted(slot["tasks"])
        slot["n_rollouts"] = len(rewards)
        slot["mean_reward"] = round(sum(rewards) / len(rewards), 4)
        slot["max_reward"] = round(max(rewards), 4)
        slot["pct_in_band_10_80"] = round(in_band / len(rewards), 4)
        slot["pct_groups_zero_adv"] = round(slot["degenerate"] / slot["groups"], 4)
        slot["reward_hist"] = histogram(rewards)
        del slot["rewards"]
    return dict(sorted(out.items()))


def block(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "run.json").read_text())
    rows = [
        json.loads(line)
        for line in (run_dir / "rewards.jsonl").read_text().splitlines()
        if line.strip()
    ]
    group_size = manifest["hyperparameters"]["num_generations"]
    envs = per_env(rows, group_size)
    rewards = [float(r["reward"]) for r in rows]
    in_band = sum(1 for v in rewards if BAND[0] <= v <= BAND[1])
    degenerate = sum(v["degenerate"] for v in envs.values())
    groups = sum(v["groups"] for v in envs.values())
    # `gap` is null on a completion that did not parse into a policy: there was
    # no policy to replay, so there is no gap. Counting those as 0.0 would be
    # reporting an unparseable reply as a failed attack rather than as an
    # absent one, which is the distinction `parse_policy` exists to preserve.
    unparsed = sum(1 for r in rows if r.get("gap") is None)
    hacks = sum(1 for r in rows if r.get("gap") is not None and float(r["gap"]) >= 0.5)
    scored = len(rows) - unparsed

    return {
        "env": f"assay-corpus ({len(envs)} environments)",
        "run": run_dir.name,
        "harness": {
            "model": manifest["model"],
            "gpu": manifest["device"]["gpu"],
            "torch": manifest["device"]["torch"],
            "assay_revision_at_report_time": git_revision(),
            "revision_at_run_time": (
                "not recorded by the run; run.json predates run-config capture and "
                "carries no git SHA, so the exact source that produced these rewards "
                "is identified only by the artifact set, not by a commit"
            ),
        },
        "n_tasks": sum(v["n_tasks"] for v in envs.values()),
        "k_rollouts": group_size,
        "n_rollouts": len(rows),
        "verifier_gold": (
            "verified per environment by the probe battery, not by this run; see "
            "results/full_run.json (GOLD_FAILS is planted in fixture/gold_broken and "
            "harbor/broken-gold and detected in both)"
        ),
        "verifier_noop": (
            "same source; NOOP_PASSES is planted in fixture/solved_at_reset, "
            "harbor/vacuous-tests and inspect/always-correct and detected in all three"
        ),
        "reward_hist": histogram(rewards),
        "pct_in_band_10_80": round(in_band / len(rewards), 4),
        "pct_groups_zero_adv": round(degenerate / groups, 4),
        "sampler_trainer_kl": run_kl(rows),
        "train_vs_eval_protocol_diff": (
            "Training sampled a one-shot policy of at most 3 actions from a chat "
            "prompt; the ablation the run is judged by uses the same one-shot format "
            "(assay.challenger.grpo) at best-of-n, so the format matches. What does "
            "NOT match is the holdout: harbor/self-graded was held out as an "
            "environment, but its PROMPT is byte-identical to three trained Harbor "
            "environments and 60 of 300 training rows carried it. See "
            "results/train_holdout_dedup.json."
        ),
        "hack_probes": {
            "rollouts_with_gap_ge_0_5": hacks,
            "rollouts_scored": scored,
            "rollouts_unparseable": unparsed,
            "rate": round(hacks / scored, 4) if scored else None,
            "verdict": "pass" if hacks else "no exploit found in any rollout",
            "note": (
                "this counts rollouts that scored an exploit gap during TRAINING, on "
                "environments where a gap is planted. It is not evidence the trained "
                "policy learned anything -- with "
                f"{round(degenerate / groups, 4):.1%} of groups at zero advantage "
                "there was no gradient to learn from."
            ),
        },
        "per_environment": envs,
        "reward_summary_from_the_run": {
            k: manifest[k]
            for k in (
                "mean_reward",
                "mean_reward_first_half",
                "mean_reward_last_half",
                "parse_rate",
                "degenerate_groups",
                "n_groups",
            )
            if k in manifest
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*", default=RUNS)
    ap.add_argument("--out", default="results/env_health.json")
    args = ap.parse_args()

    blocks = {}
    for path in args.runs:
        run_dir = Path(path)
        if not (run_dir / "run.json").exists():
            print(f"SKIPPING {run_dir}: no run.json", file=sys.stderr)
            continue
        blocks[run_dir.name] = block(run_dir)

    if not blocks:
        print("no runs to report on", file=sys.stderr)
        return 1

    body = {
        "spec": "environments.md:131-142",
        "runs": blocks,
        "uncomputable_fields": {
            "sampler_trainer_kl": {
                "why": (
                    "no logprobs were logged by either run. rewards.jsonl carries "
                    "reward, parse flag, reported score, true completion, gap, "
                    "policy digest and completion text -- and no per-token "
                    "quantities. TRL ran with report_to='none' so there are no "
                    "trainer logs, and neither spot instance's per-step checkpoints "
                    "survive, so it cannot be recomputed either."
                ),
                "why_not_just_say_zero": (
                    "Both runs used TRL's colocated path, so sampler and trainer are "
                    "nominally the same weights. They are not the same NUMERICS: the "
                    "base model was loaded in 4-bit NF4, generation used a KV cache "
                    "and the trainer logprobs come from a separate batched forward "
                    "pass. Quantised matmuls and cached-vs-uncached attention do not "
                    "agree bit-for-bit, and batch size changes the result -- which is "
                    "the exact failure this field exists to detect. 'Should be zero' "
                    "is not 'measured zero'."
                ),
                "required_for_a_future_run": REQUIRED_FIELDS,
                "instrument": "assay.train.onpolicy.sampler_trainer_kl",
            }
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2))

    for name, b in blocks.items():
        print(f"=== {name}")
        print(f"  env:                  {b['env']}")
        print(f"  harness:              {b['harness']['model']} on {b['harness']['gpu']}")
        print(f"  n_tasks:              {b['n_tasks']}   k_rollouts: {b['k_rollouts']}")
        print(f"  pct_in_band_10_80:    {b['pct_in_band_10_80']:.4f}")
        print(f"  pct_groups_zero_adv:  {b['pct_groups_zero_adv']:.4f}")
        kl = b["sampler_trainer_kl"]
        print(f"  sampler_trainer_kl:   {kl.get('value')}   <-- {kl.get('unavailable', '')}")
        print(f"  hack_probes:          {b['hack_probes']['rollouts_with_gap_ge_0_5']} "
              f"rollouts with gap >= 0.5 ({b['hack_probes']['rate']:.4f})")
        print("  per environment (pct_groups_zero_adv, mean reward, in-band):")
        for env, v in b["per_environment"].items():
            print(f"    {env:34} {v['pct_groups_zero_adv']:.4f}  "
                  f"{v['mean_reward']:.4f}  {v['pct_in_band_10_80']:.4f}")
        print()
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
