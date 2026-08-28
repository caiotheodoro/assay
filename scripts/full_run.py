#!/usr/bin/env python3
"""Run every arm over the audited corpus and write the evidence tree.

Arms available without an API key or a GPU:
  assay            the full probe battery
  check_env        the incumbent structural linter (gymnasium/SB3 equivalent)
  flag_nothing     trivial detector
  flag_everything  trivial detector

The LLM arms (one direct prompt, one general agent with tools) are added by
`--arms` once credentials are configured; they are deliberately not required
to reproduce the headline comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.baselines import StructuralCheckArm  # noqa: E402
from assay.corpus import availability, entries, ground_truth  # noqa: E402
from assay.costs import all_profiles, load  # noqa: E402
from assay.metrics import ArmResult, Outcome, normalized_loss, trivial_arms  # noqa: E402


def _closing(adapter):
    """Some adapters hold a container open; give them the chance to clean up."""
    return adapter if hasattr(adapter, "__enter__") else _NullCtx(adapter)


class _NullCtx:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *exc):
        return False


def run_assay(corpus) -> ArmResult:
    arm = ArmResult("assay")
    for env_id, factory, planted in corpus:
        with _closing(factory()) as adapter:
            report = audit(adapter)
        arm.outcomes.append(Outcome(env_id, planted, frozenset(report.detected)))
    return arm


def run_check_env(corpus) -> tuple[ArmResult, dict]:
    arm = ArmResult("check_env")
    issues = {}
    checker = StructuralCheckArm()
    for env_id, factory, planted in corpus:
        with _closing(factory()) as adapter:
            detected, found = checker.run(adapter)
        arm.outcomes.append(Outcome(env_id, planted, detected))
        issues[env_id] = found
    return arm, issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    ap.add_argument("--profile", default="research-run")
    ap.add_argument("--no-inspect", action="store_true")
    ap.add_argument("--no-harbor", action="store_true")
    args = ap.parse_args()

    have = availability()
    corpus = entries(
        include_inspect=not args.no_inspect, include_harbor=not args.no_harbor
    )
    truth = ground_truth(
        include_inspect=not args.no_inspect, include_harbor=not args.no_harbor
    )
    profile = load(args.profile)

    arms = {"assay": run_assay(corpus)}
    check_arm, check_issues = run_check_env(corpus)
    arms["check_env"] = check_arm
    arms.update(trivial_arms(truth))

    rows = {}
    for name, arm in arms.items():
        row = arm.profile_row(profile)
        row["normalized_loss"] = round(normalized_loss(arm, truth, profile), 4)
        rows[name] = row

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "runtime_availability": have,
        "corpus_size": len(corpus),
        "total_planted_defects": sum(len(v) for v in truth.values()),
        "cost_profile": {"name": profile.name, "description": profile.description},
        "arms": rows,
        "per_env": {
            o.env_id: {
                "planted": sorted(d.value for d in o.planted),
                "assay_detected": sorted(d.value for d in o.detected),
                "missed": sorted(d.value for d in o.missed),
                "spurious": sorted(d.value for d in o.spurious),
            }
            for o in arms["assay"].outcomes
        },
        "check_env_structural_issues": check_issues,
    }
    (out / "full_run.json").write_text(json.dumps(payload, indent=2, sort_keys=True))

    width = max(len(n) for n in rows)
    print(f"corpus: {len(corpus)} environments, {payload['total_planted_defects']} planted defects")
    missing = [k for k, v in have.items() if not v]
    if missing:
        print(f"WARNING: unavailable here, corpus is reduced: {', '.join(missing)}")
    print(f"cost profile: {profile.name}\n")
    header = f"{'arm':{width}}  {'exp.loss':>9} {'norm':>7} {'recall':>7} {'prec':>7} {'miss':>5} {'spur':>5}"
    print(header)
    print("-" * len(header))
    for name, row in sorted(rows.items(), key=lambda kv: kv[1]["expected_loss"]):
        print(
            f"{name:{width}}  {row['expected_loss']:>9.1f} {row['normalized_loss']:>7.3f} "
            f"{row['recall']:>7.3f} {row['precision']:>7.3f} "
            f"{row['n_missed']:>5} {row['n_spurious']:>5}"
        )
    print(f"\nwrote {out / 'full_run.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
