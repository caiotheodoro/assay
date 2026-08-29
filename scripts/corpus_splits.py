#!/usr/bin/env python3
"""Score the corpus split by where its environments came from.

A red-team pass established that half the 24-environment corpus is this repo's
own pytest fixtures, and that `tests/test_probes_fire.py` asserts exact
detection on all twelve of them. Assay's score there is a CI gate: anything
other than perfect is a red build. Reporting it pooled with the third-party
environments lets a passing test masquerade as a measurement.

It also established that both of Assay's misses are Harbor, so dropping Docker
does not merely shrink the corpus -- it removes every environment Assay gets
wrong, and the floor comparison flips.

Neither split was published. This script publishes both, and is deliberately
unflattering: the number to read is `no-fixture`, the twelve environments this
repo did not write.

Usage:
  uv run --extra adapters python scripts/corpus_splits.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from assay.costs import load  # noqa: E402
from intervals import bootstrap, load_arms  # noqa: E402

PROFILES = ["research-run", "production-training", "benchmark-publication", "flat"]

SPLITS = {
    "all": (None, "the published corpus"),
    "no-fixture": (
        lambda e: not e.startswith("fixture/"),
        "third-party environments only -- the honest number",
    ),
    "fixture-only": (
        lambda e: e.startswith("fixture/"),
        "this repo's own pytest fixtures, asserted exactly by the test suite",
    ),
    "no-harbor": (
        lambda e: not e.startswith("harbor/"),
        "what a machine without Docker actually runs",
    ),
    "harbor-only": (
        lambda e: e.startswith("harbor/"),
        "the only environments Assay gets wrong",
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results/full_run.json")
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="results/corpus_splits.json")
    args = ap.parse_args()

    payload = json.loads(Path(args.results).read_text())
    out: dict[str, dict] = {}

    for split, (keep, why) in SPLITS.items():
        arms, truth = load_arms(payload, keep)
        if not truth:
            continue
        row: dict = {
            "why": why,
            "n_environments": len(truth),
            "n_planted": sum(len(t) for t in truth.values()),
            "environments": sorted(truth),
            "profiles": {},
        }
        for pname in PROFILES:
            profile = load(pname)
            row["profiles"][pname] = {
                name: arm.profile_row(profile) for name, arm in sorted(arms.items())
            }
        # the paired claim, on the split that matters
        row["paired_vs_flag_everything"] = bootstrap(
            arms, load("research-run"), args.resamples, args.seed
        )
        out[split] = row

    body = {
        "measurement": "expected loss by corpus provenance",
        "resamples": args.resamples,
        "seed": args.seed,
        "resampling_unit": "environment",
        "read_this_one": "no-fixture",
        "caveat": (
            "fixture-only is not a measurement. tests/test_probes_fire.py asserts "
            "detected == planted on exactly those twelve environments, so a loss "
            "above zero there is a failing build, not a result."
        ),
        "splits": out,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(body, indent=2) + "\n")
    print(f"wrote {args.out}\n")

    hdr = f"{'split':<14}{'n':>4}{'planted':>9}  " + "".join(f"{p[:12]:>14}" for p in PROFILES)
    print(hdr)
    for split, row in out.items():
        for arm in ("assay", "flag_everything"):
            cells = "".join(
                f"{row['profiles'][p][arm]['expected_loss']:>14.1f}" for p in PROFILES
            )
            label = f"{split}/{arm.split('_')[0]}"
            print(f"{label:<14}{row['n_environments']:>4}{row['n_planted']:>9}  {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
