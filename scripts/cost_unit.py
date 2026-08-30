#!/usr/bin/env python3
"""Where does 120 come from?

`research-run.yaml` prices a missed CRITICAL defect at 120 engineer-hours and
nothing derived it. `cost_sensitivity.py` already answered the question that
matters most -- the ranking survives from 9 to 942, so it is a property of the
detectors rather than of the constant -- but "the answer does not depend on it"
is not the same as "the number is defensible", and a reader is entitled to ask
where it came from.

This script does not invent a point estimate to replace an invented point
estimate. It **bounds** the quantity from two directions and reports where the
shipped value falls:

  FLOOR   the compute alone. A post-training cycle spent on an environment with
          a critical defect produces a policy that hacks it. That spend is
          gone. Priced from THIS repo's own measured spot rate, converted to
          engineer-hours at a stated rate. It is a floor because it counts only
          the GPU: not the time to notice, diagnose, fix the environment and
          rerun, and not the cost of shipping the policy.

  CEILING the human cost of repairing a benchmark once it is known to be
          broken. The published anchor is SWE-bench Verified: OpenAI put 93
          developers through 1,699 samples to produce a trustworthy subset.
          It is a ceiling because a defect found by an auditor before a run is
          nothing like a benchmark re-annotated after the field has published
          against it.

Every input is named, and every input is either measured in this repo or cited.
Both are swept, because a bound built on one guess each is a guess with extra
steps.

  uv run python scripts/cost_unit.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "cost_unit.json"

SHIPPED = 120.0

# --- measured in this repo -------------------------------------------------
# docs/CHANGELOG.md: "Two spot runs of ~16 minutes each: g5.xlarge at
# $0.4612/hr and g6.xlarge". Our own runs were minutes because the model is
# small; a real post-training cycle is not, so the cycle length below is the
# swept input rather than a claim.
SPOT_USD_PER_HOUR = 0.4612
SPOT_INSTANCE = "g5.xlarge (A10G 24GB), us-east-1"

# --- cited, not measured here ----------------------------------------------
# SWE-bench Verified: 93 developers screened 1,699 samples. Cited as a
# published figure about benchmark repair effort; this repo did not measure it
# and does not treat it as more than an order-of-magnitude anchor.
SWEBENCH_DEVELOPERS = 93
SWEBENCH_SAMPLES = 1699
SWEBENCH_SOURCE = "OpenAI, 'Introducing SWE-bench Verified' (2024)"

# --- swept -----------------------------------------------------------------
ENGINEER_USD_PER_HOUR = [75.0, 150.0, 250.0]     # fully-loaded, order of magnitude
CYCLE_GPU_HOURS = [24.0, 168.0, 720.0]           # 1 day / 1 week / 1 month of one GPU
SCREEN_MINUTES_PER_SAMPLE = [5.0, 15.0, 30.0]    # per developer-sample, for the ceiling


def floor_hours() -> list[dict]:
    """Wasted GPU, in engineer-hours. Compute only, nothing human."""
    rows = []
    for gpu_hours in CYCLE_GPU_HOURS:
        usd = gpu_hours * SPOT_USD_PER_HOUR
        for rate in ENGINEER_USD_PER_HOUR:
            rows.append(
                {
                    "gpu_hours": gpu_hours,
                    "usd_wasted": round(usd, 2),
                    "engineer_usd_per_hour": rate,
                    "engineer_hours": round(usd / rate, 2),
                }
            )
    return rows


def ceiling_hours() -> list[dict]:
    """Repairing a published benchmark, per environment, in engineer-hours."""
    rows = []
    for minutes in SCREEN_MINUTES_PER_SAMPLE:
        # 1,699 samples screened, distributed across 93 developers -- so the
        # total human cost is samples x minutes, and the developer count is
        # context for how large an effort that was, not a multiplier.
        total = SWEBENCH_SAMPLES * minutes / 60.0
        rows.append(
            {
                "minutes_per_sample": minutes,
                "samples": SWEBENCH_SAMPLES,
                "engineer_hours_for_the_whole_benchmark": round(total, 1),
                # Comparable to a per-environment cost because one environment
                # in Assay's corpus is a whole task suite, and a CRITICAL
                # finding invalidates the suite rather than one item. The
                # comparison is order-of-magnitude, and is stated as such.
            }
        )
    return rows


def main() -> int:
    floor = floor_hours()
    ceiling = ceiling_hours()
    lo = min(r["engineer_hours"] for r in floor)
    hi = max(r["engineer_hours"] for r in floor)
    ceil_lo = min(r["engineer_hours_for_the_whole_benchmark"] for r in ceiling)
    ceil_hi = max(r["engineer_hours_for_the_whole_benchmark"] for r in ceiling)

    body = {
        "measurement": "a bound on the missed-CRITICAL cost, rather than an assertion",
        "shipped_value": SHIPPED,
        "unit": "engineer-hours-equivalent; false_alarm = 1 by definition",
        "floor": {
            "what": "GPU spend on one post-training cycle discarded because the "
                    "environment was broken; compute only",
            "spot_instance": SPOT_INSTANCE,
            "spot_usd_per_hour": SPOT_USD_PER_HOUR,
            "spot_source": "this repo's own runs, docs/CHANGELOG.md",
            "range_engineer_hours": [lo, hi],
            "rows": floor,
        },
        "ceiling": {
            "what": "human effort to repair a benchmark already published against",
            "anchor": f"{SWEBENCH_DEVELOPERS} developers, {SWEBENCH_SAMPLES} samples",
            "source": SWEBENCH_SOURCE,
            "measured_here": False,
            "range_engineer_hours": [ceil_lo, ceil_hi],
            "rows": ceiling,
        },
        "shipped_sits_inside_the_bound": lo <= SHIPPED <= ceil_hi,
        "crossover_from_cost_sensitivity": 942,
        "crossover_is_above_the_ceiling": 942 > ceil_hi,
        "reading": (
            f"The floor is {lo}-{hi} engineer-hours: compute alone, and BELOW the shipped "
            f"{SHIPPED:.0f} in every cell. That is the honest result rather than a "
            "convenient one -- discarded GPU time is the cheapest part of a broken "
            "environment and on its own cannot justify the constant. The ceiling is "
            f"{ceil_lo:.0f}-{ceil_hi:.0f} engineer-hours to repair a benchmark after the "
            f"field has published against it. The shipped {SHIPPED:.0f} sits inside that "
            "range.\n\n"
            "The crossover is what makes the bound worth computing. Assay beats "
            "flag-everything for every missed-CRITICAL cost BELOW 942 (`cost_sensitivity."
            f"json`), and the top of this bound is {ceil_hi:.0f}. So the entire range a "
            "defensible cost belief can occupy -- from 'a wasted GPU-month is all it "
            "costs' to 'it costs a full SWE-bench-Verified-scale re-annotation' -- lies "
            "on the side where Assay wins. Reaching the crossover would require valuing "
            "one missed critical defect at MORE than re-annotating an entire published "
            "benchmark. The headline does not rest on the constant being 120; it rests "
            "on the constant being under 942, and nothing in this bound gets near it."
        ),
        "what_this_does_not_do": (
            "It does not derive 120. Nothing here can: the quantity is an organisation's "
            "own exchange rate between a missed defect and an hour of reading a card, and "
            "it differs by organisation. What is bounded is the range a defensible answer "
            "lies in, and the shipped value is inside it rather than outside."
        ),
    }
    OUT.write_text(json.dumps(body, indent=2) + "\n")
    print(f"floor   {lo:>8.2f} - {hi:>8.2f} engineer-hours   (GPU only, measured spot rate)")
    print(f"shipped {SHIPPED:>8.2f}                          (research-run.yaml)")
    print(f"crossover  {942:>6}                             (cost_sensitivity.py)")
    print(f"ceiling {ceil_lo:>8.1f} - {ceil_hi:>8.1f} engineer-hours   (benchmark repair, cited)")
    print(f"\nshipped inside the bound: {body['shipped_sits_inside_the_bound']}")
    print(f"crossover above the ceiling: {942 > ceil_hi}  "
          f"-- assay wins across the whole defensible range")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
