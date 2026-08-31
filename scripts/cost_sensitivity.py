#!/usr/bin/env python3
"""Does the ranking survive the cost weights being wrong?

Every expected-loss number this project publishes is denominated in
"engineer-hours-equivalent", and `research-run.yaml` prices a missed CRITICAL
defect at 120 of them. Nothing derives that 120. It is a considered guess, and
every headline scales linearly with it -- which means a reader is entitled to
ask whether the conclusion is a property of the detectors or of a number
somebody picked.

This answers that without pretending to derive the constant. It sweeps the
CRITICAL miss cost across three orders of magnitude and reports, at each point,
which arm wins. If the ranking is stable across the sweep, the constant does not
carry the conclusion and the guess is harmless. Where the ranking flips, the
crossover is the honest thing to publish: it is the exchange rate at which a
reader's own cost structure would change the answer.

The one anchor available: SWE-bench Verified needed **93 developers** reading
tasks by hand to establish ground truth on 500 instances. That is the observed
price of finding these defects the other way, and it is why a missed CRITICAL is
priced far above a false alarm rather than near it.

Usage:
  uv run --extra adapters python scripts/cost_sensitivity.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from assay.costs import CostProfile, load  # noqa: E402
from assay.types import DEFAULT_SEVERITY, Severity  # noqa: E402
from intervals import load_arms  # noqa: E402

#: Ratios of CRITICAL-miss cost to false-alarm cost. The shipped profile sits
#: at 120. A ratio of 1 says a missed critical defect and an hour of reading a
#: card cost the same, which nobody believes but bounds the sweep honestly.
RATIOS = [1, 2, 5, 10, 20, 40, 80, 120, 130, 140, 145, 150, 160, 200, 400, 800, 2000]


def scaled(base: CostProfile, critical: float) -> CostProfile:
    """Hold the shipped severity *shape* and move only the CRITICAL anchor."""
    factor = critical / base.miss[Severity.CRITICAL]
    return CostProfile(
        name=f"{base.name}@critical={critical:g}",
        description=base.description,
        miss={sev: cost * factor for sev, cost in base.miss.items()},
        false_alarm=base.false_alarm,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results/full_run.json")
    ap.add_argument("--profile", default="research-run")
    ap.add_argument("--out", default="results/cost_sensitivity.json")
    args = ap.parse_args()

    payload = json.loads(Path(args.results).read_text())
    arms, truth = load_arms(payload)
    base = load(args.profile)

    rows = []
    for ratio in RATIOS:
        profile = scaled(base, float(ratio))
        losses = {name: arm.expected_loss(profile) for name, arm in arms.items()}
        winner = min(losses, key=lambda n: losses[n])
        rows.append(
            {
                "critical_miss_cost": ratio,
                "false_alarm_cost": base.false_alarm,
                "ratio": ratio / base.false_alarm,
                "loss": {k: round(v, 2) for k, v in sorted(losses.items())},
                "winner": winner,
                "assay_beats_flag_everything": (
                    losses["assay"] < losses.get("flag_everything", float("inf"))
                ),
            }
        )

    # The crossover is analytic, not a bisection artefact -- but it is an
    # affine solve, not a proportional one, and getting that wrong is what this
    # block used to do.
    #
    # `scaled()` moves every severity by the same factor about the CRITICAL
    # anchor, so the part of Assay's loss that comes from *misses* is linear in
    # C. The part that comes from *false alarms* is not: it is
    # `n_spurious * false_alarm` and does not move with C at all. So
    #
    #     assay(C) = (assay(shipped) - fa) * C / shipped + fa
    #
    # and the old `assay(shipped) * C / shipped` was the fa = 0 special case.
    # It held for as long as Assay had perfect precision and broke silently the
    # moment the tau2 environments introduced three false alarms -- reporting a
    # crossover of 1099.53 where the true one is 1173.0, and printing a "tie"
    # row at a cost where Assay is actually at 369.5 against 394.0.
    #
    # flag_everything never misses, so its loss is pure false alarms and is
    # constant in C. They cross where the line above meets that constant.
    crossover = None
    if "flag_everything" in arms:
        shipped_c = base.miss[Severity.CRITICAL]
        fe = arms["flag_everything"].expected_loss(base)
        assay_arm = arms["assay"]
        fa = sum(len(o.spurious) for o in assay_arm.outcomes) * base.false_alarm
        miss_component = assay_arm.expected_loss(base) - fa
        if miss_component > 0:
            crossover = round(shipped_c * (fe - fa) / miss_component, 2)

    winners = [r["winner"] for r in rows]
    flips = [
        (rows[i - 1]["critical_miss_cost"], rows[i]["critical_miss_cost"])
        for i in range(1, len(rows))
        if winners[i] != winners[i - 1]
    ]
    beats = [r["critical_miss_cost"] for r in rows if r["assay_beats_flag_everything"]]

    body = {
        "measurement": "sensitivity of the arm ranking to the unjustified cost constant",
        "why": (
            "research-run.yaml prices a missed CRITICAL at 120 engineer-hours-"
            "equivalent and nothing derives it. Every published number scales "
            "linearly with it, so the question is whether the ranking is a "
            "property of the detectors or of the constant."
        ),
        "shipped_value": base.miss[Severity.CRITICAL],
        "false_alarm": base.false_alarm,
        "method": (
            "The severity shape (CRITICAL:HIGH:MEDIUM:LOW) is held fixed and "
            "scaled about the CRITICAL anchor, so only the miss/false-alarm "
            "exchange rate moves."
        ),
        "n_environments": len(truth),
        "winner_flips_between": flips,
        "exact_crossover_critical_cost": crossover,
        "margin": (
            None
            if crossover is None
            else {
                "shipped": base.miss[Severity.CRITICAL],
                "crossover": crossover,
                "ratio": round(crossover / base.miss[Severity.CRITICAL], 3),
                "reading": (
                    "Assay beats flag_everything only while a missed CRITICAL is "
                    f"priced below {crossover}. The shipped profile says "
                    f"{base.miss[Severity.CRITICAL]:g}. The headline therefore "
                    f"survives a {round((crossover / base.miss[Severity.CRITICAL] - 1) * 100)}% "
                    "error in a constant nothing derives, and no more."
                ),
            }
        ),
        "assay_beats_flag_everything_when_critical_at_least": min(beats) if beats else None,
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(body, indent=2) + "\n")
    print(f"wrote {args.out}\n")

    names = sorted(arms)
    print(f"{'CRIT cost':>10}  " + "".join(f"{n[:18]:>19}" for n in names) + "   winner")
    for r in rows:
        cells = "".join(f"{r['loss'][n]:>19.1f}" for n in names)
        star = " *" if r["critical_miss_cost"] == base.miss[Severity.CRITICAL] else "  "
        print(f"{r['critical_miss_cost']:>10}{star}{cells}   {r['winner']}")
    print("\n* the shipped value")
    if crossover is not None:
        print(f"\nexact crossover: CRITICAL = {crossover}  (shipped: "
              f"{base.miss[Severity.CRITICAL]:g})")
        print(body["margin"]["reading"])
    elif flips:
        print(f"ranking changes between: {flips}")
    else:
        print("the winner never changes across three orders of magnitude")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
