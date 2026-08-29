#!/usr/bin/env python3
"""What the agentic Challenger buys, and what it costs, over k runs.

Assay's headline arm is `ScriptedChallenger`: no model, no key, deterministic,
22 seconds. Its entire loss across the corpus is two missed `REWARD_HACKABLE`
defects. Family 9 -- the only probe backed by an agent -- exists to close
exactly those, and until now it had never been run over the full corpus, only
over the Harbor slice, once.

One run is not a capability. A probe backed by a sampled model is not a
deterministic check, so the honest output is a distribution: per-environment hit
rate over k independent runs, and the loss those runs imply. `criteria.md` says
report a profile, never one number, and pass^k, never pass@1. This is that,
applied to the auditor rather than to a model it audits.

The cost axis is not decoration. A reader choosing between the two arms is
choosing between 22 seconds at zero marginal cost with a known 240.0, and tens
of minutes of paid sampling with a loss that varies run to run. Publishing the
mean without the spread and the wall clock would hide the actual trade.

Usage:
  uv run --extra adapters python scripts/agentic_profile.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.costs import load  # noqa: E402
from assay.metrics import ArmResult, Outcome  # noqa: E402
from assay.types import DefectClass  # noqa: E402

PROFILES = ["research-run", "production-training", "benchmark-publication", "flat"]


def _arm(payload: dict, key: str) -> tuple[ArmResult, dict]:
    truth = {
        env: frozenset(DefectClass(d) for d in row["planted"])
        for env, row in payload["per_env"].items()
    }
    outcomes = [
        Outcome(env, truth[env], frozenset(DefectClass(d) for d in row[key]))
        for env, row in payload["per_env"].items()
    ]
    return ArmResult("assay", outcomes), truth


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="results/agentic_runs")
    ap.add_argument("--scripted", default="results/full_run.json")
    ap.add_argument("--out", default="results/agentic_profile.json")
    args = ap.parse_args()

    paths = sorted(Path(args.runs).glob("run_*.json"))
    if not paths:
        print(f"no runs in {args.runs}", file=sys.stderr)
        return 2

    runs, misses = [], Counter()
    envs_seen: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text())
        arm, truth = _arm(payload, "assay_detected")
        envs_seen |= set(truth)
        for o in arm.outcomes:
            if o.missed:
                misses[o.env_id] += 1
        runs.append(
            {
                "run": path.stem,
                "n_environments": len(truth),
                "recall": round(arm.recall, 4),
                "precision": round(arm.precision, 4),
                "n_missed": arm.n_missed,
                "n_spurious": arm.n_spurious,
                "missed": sorted(
                    f"{o.env_id}:{d.value}" for o in arm.outcomes for d in o.missed
                ),
                "loss": {p: round(arm.expected_loss(load(p)), 4) for p in PROFILES},
            }
        )

    k = len(runs)
    losses = {p: [r["loss"][p] for r in runs] for p in PROFILES}

    scripted = None
    sp = Path(args.scripted)
    if sp.exists():
        arm, _ = _arm(json.loads(sp.read_text()), "assay_detected")
        scripted = {
            "recall": round(arm.recall, 4),
            "n_missed": arm.n_missed,
            "loss": {p: round(arm.expected_loss(load(p)), 4) for p in PROFILES},
        }

    body = {
        "measurement": "what the agentic Challenger buys over k independent runs",
        "k": k,
        "arm": "assay+scripted+prompted[claude-cli:sonnet]",
        "why_a_distribution": (
            "A probe backed by a sampled model is not a deterministic check. "
            "Reporting one run as a capability claim would overstate the "
            "evidence, which is the failure this project exists to catch."
        ),
        "per_environment_miss_rate": {
            env: {
                "missed_in_runs": misses[env],
                "of_k": k,
                "miss_rate": round(misses[env] / k, 4),
                "found_rate": round(1 - misses[env] / k, 4),
            }
            for env in sorted(envs_seen)
            if misses[env]
        },
        "never_missed": sorted(e for e in envs_seen if not misses[e]),
        "loss_distribution": {
            p: {
                "min": min(v),
                "median": statistics.median(v),
                "mean": round(statistics.fmean(v), 4),
                "max": max(v),
                "stdev": round(statistics.stdev(v), 4) if len(v) > 1 else 0.0,
                "values": v,
            }
            for p, v in losses.items()
        },
        "deterministic_arm": scripted,
        "runs": runs,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(body, indent=2) + "\n")
    print(f"wrote {args.out}\n")

    print(f"k = {k} independent full-corpus runs\n")
    print(f"{'environment':<28}{'missed':>8}{'found rate':>12}")
    for env, row in body["per_environment_miss_rate"].items():
        print(f"{env:<28}{row['missed_in_runs']:>3}/{k:<4}{row['found_rate']:>12.2f}")
    if not body["per_environment_miss_rate"]:
        print("  (nothing was missed in any run)")
    print()
    print(f"{'profile':<24}{'scripted':>10}{'agentic min':>13}{'median':>9}{'max':>9}")
    for p in PROFILES:
        d = body["loss_distribution"][p]
        s = scripted["loss"][p] if scripted else float("nan")
        print(f"{p:<24}{s:>10.1f}{d['min']:>13.1f}{d['median']:>9.1f}{d['max']:>9.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
