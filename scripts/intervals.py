#!/usr/bin/env python3
"""Bootstrap confidence intervals over the audited corpus.

Every number this project publishes is computed over 24 environments. A point
estimate from 24 samples, reported bare, invites the reader to believe a
precision it does not have -- and a benchmark repo is held to a stricter bar
than a model card, because publishing an eval invites people to score against
it and everything they cannot bound they will discount.

Resampling is over ENVIRONMENTS, not over defects. Defects within one
environment are not independent: a verifier that always passes fails six probes
at once. Resampling defects would treat those six as six pieces of evidence and
report an interval far tighter than the data supports.

Also reports the paired difference between an arm and the strongest baseline,
because "A beats B" is the claim, and two overlapping one-sample intervals do
not establish it.

Usage:
  uv run --extra adapters python scripts/intervals.py --resamples 10000 --seed 11
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.costs import load  # noqa: E402
from assay.metrics import ArmResult, Outcome  # noqa: E402
from assay.types import DefectClass  # noqa: E402


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = (len(ordered) - 1) * q
    low, high = int(idx), min(int(idx) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (idx - low)


def _resample(arm: ArmResult, rng: random.Random) -> ArmResult:
    n = len(arm.outcomes)
    return ArmResult(arm.arm, [arm.outcomes[rng.randrange(n)] for _ in range(n)])


def bootstrap(
    arms: dict[str, ArmResult], profile, resamples: int, seed: int
) -> dict[str, dict]:
    """One shared resample per iteration, so paired differences are honest."""
    rng = random.Random(seed)
    names = list(arms)
    n = len(next(iter(arms.values())).outcomes)
    draws: dict[str, dict[str, list[float]]] = {
        name: {"expected_loss": [], "recall": [], "precision": []} for name in names
    }
    # Paired against EVERY other arm. Two overlapping one-sample intervals do
    # not settle "A beats B", and the arm that matters most here is the trivial
    # floor, not the incumbent -- beating a tool that detects nothing is a much
    # weaker claim than beating flag-everything.
    paired: dict[tuple[str, str], list[float]] = {
        (a, b): [] for a in names for b in names if a != b
    }

    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        sampled = {
            name: ArmResult(name, [arm.outcomes[i] for i in idx])
            for name, arm in arms.items()
        }
        losses = {name: arm.expected_loss(profile) for name, arm in sampled.items()}
        for name, arm in sampled.items():
            draws[name]["expected_loss"].append(losses[name])
            draws[name]["recall"].append(arm.recall)
            draws[name]["precision"].append(arm.precision)
        for (a, b), acc in paired.items():
            acc.append(losses[b] - losses[a])  # loss saved by a, relative to b

    out = {}
    for name, arm in arms.items():
        row = {}
        points = {
            "expected_loss": arm.expected_loss(profile),
            "recall": arm.recall,
            "precision": arm.precision,
        }
        for metric, values in draws[name].items():
            row[metric] = {
                "point": round(points[metric], 4),
                "ci95": [round(_percentile(values, 0.025), 4), round(_percentile(values, 0.975), 4)],
            }
        row["loss_saved_vs"] = {}
        for other in names:
            if other == name:
                continue
            diffs = paired[(name, other)]
            lo, hi = _percentile(diffs, 0.025), _percentile(diffs, 0.975)
            row["loss_saved_vs"][other] = {
                "point": round(
                    arms[other].expected_loss(profile) - arm.expected_loss(profile), 4
                ),
                "ci95": [round(lo, 4), round(hi, 4)],
                "separated": lo > 0 or hi < 0,
            }
        out[name] = row
    return out


def load_arms(
    payload: dict, keep=None
) -> tuple[dict[str, "ArmResult"], dict[str, frozenset]]:
    """Rebuild every arm from a full_run payload, optionally on a subset.

    `keep` is a predicate on env_id. Splitting the corpus has to reuse this
    loader rather than reimplement it -- a subset scored by a second
    implementation is the failure this repository documents elsewhere.
    """
    truth = {
        env: frozenset(DefectClass(d) for d in row["planted"])
        for env, row in payload["per_env"].items()
        if keep is None or keep(env)
    }
    arms: dict[str, ArmResult] = {}
    arms["assay"] = ArmResult(
        "assay",
        [
            Outcome(env, truth[env], frozenset(DefectClass(d) for d in row["assay_detected"]))
            for env, row in payload["per_env"].items()
            if env in truth
        ],
    )
    everything = frozenset(DefectClass)
    recorded = payload.get("arm_detections", {})
    # Every arm the run recorded, not a list written here. A hardcoded list
    # silently drops any baseline added later -- which is how the
    # stratified-random floor stayed out of the paired comparison for as long
    # as it did. The fallbacks are only for a results file predating this.
    fallbacks = {
        "check_env": frozenset(),
        "flag_nothing": frozenset(),
        "flag_everything": everything,
    }
    # `assay` itself is rebuilt above from per_env, so skip it here. The guard
    # used to be `name.startswith("assay")`, which also dropped every arm the
    # agent runs in -- `assay+auditor` and `assay+<composite>` were recorded by
    # the run, carried into full_run.json, and then filtered out of the only
    # comparison that says whether a difference clears resampling noise. The
    # comment above this loop warns against exactly that, about a different
    # arm.
    #
    # An arm whose detections are identical to `assay`'s is still skipped: with
    # `--challenger` the assay arm *is* the composite under another name, and
    # bootstrapping a set against itself reports a 0.0 difference that means
    # nothing.
    assay_outcomes = {o.env_id: o.detected for o in arms["assay"].outcomes}
    for name in sorted(set(recorded) | set(fallbacks)):
        if name in arms:
            continue
        if name != "assay" and recorded.get(name) is not None:
            same = {
                env: frozenset(DefectClass(d) for d in per_env_row)
                for env, per_env_row in recorded[name].items()
                if env in truth
            }
            if same == assay_outcomes:
                continue
        per_env = recorded.get(name)
        if per_env is None and name not in fallbacks:
            continue
        arms[name] = ArmResult(
            name,
            [
                Outcome(
                    env,
                    t,
                    frozenset(DefectClass(d) for d in per_env[env])
                    if per_env and env in per_env
                    else fallbacks.get(name, frozenset()),
                )
                for env, t in truth.items()
            ],
        )
    return arms, truth


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results/full_run.json")
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--profile", default="research-run")
    ap.add_argument("--out", default="results/intervals.json")
    args = ap.parse_args()

    payload = json.loads(Path(args.results).read_text())
    arms, truth = load_arms(payload)

    profile = load(args.profile)
    result = bootstrap(arms, profile, args.resamples, args.seed)
    body = {
        "resamples": args.resamples,
        "seed": args.seed,
        "cost_profile": profile.name,
        "n_environments": len(truth),
        "resampling_unit": "environment",
        "why": (
            "Defects within one environment are not independent -- a verifier that always "
            "passes fails six probes at once -- so resampling defects would report an "
            "interval far tighter than the data supports."
        ),
        "arms": result,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(body, indent=2))

    print(f"{len(truth)} environments, {args.resamples} resamples, seed {args.seed}, "
          f"profile {profile.name}\n")
    print(f"{'arm':16} {'exp.loss':>9}  {'95% CI':>20}  {'recall':>7}")
    print("-" * 60)
    for name, row in sorted(result.items(), key=lambda kv: kv[1]["expected_loss"]["point"]):
        el, rc = row["expected_loss"], row["recall"]
        print(
            f"{name:16} {el['point']:>9.1f}  [{el['ci95'][0]:>8.1f},{el['ci95'][1]:>8.1f}]  "
            f"{rc['point']:>7.3f}"
        )

    print("\nPaired differences in expected loss (positive = the row saves loss):")
    print(f"  {'arm':16} {'vs':16} {'saved':>9}  {'95% CI':>20}  separated")
    for name in sorted(result):
        for other, d in sorted(result[name]["loss_saved_vs"].items()):
            if d["point"] <= 0:
                continue
            mark = "YES" if d["separated"] else "no -- overlaps zero"
            print(
                f"  {name:16} {other:16} {d['point']:>9.1f}  "
                f"[{d['ci95'][0]:>8.1f},{d['ci95'][1]:>8.1f}]  {mark}"
            )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
