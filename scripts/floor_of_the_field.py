#!/usr/bin/env python3
"""What a published audit recall means, as a function of the number nobody reports.

This repository applies a trivial-floor rule to every environment it audits:
if a detector cannot beat the best policy that ignores its input, it has not
earned its existence. Applied to our own external measurement it was fatal --
recall 0.339 against 62 tau2-bench defects turned out to be indistinguishable
from flagging tasks at random, one-sided p = 0.486.

The obvious next question is what the same test says about the numbers this
category publishes. It mostly cannot be asked, and the reason is specific
rather than sloppy.

BenchGuard (arXiv 2604.24955) Table 2 reports, on ScienceAgentBench, 12
confirmed defects across 102 tasks and per-model recall up to 83.3%. Its
precision column is **flagged-task precision**, defined in the caption as
"computed over findings within tasks containing confirmed defects", and
"Find. = number of findings on defective tasks". Findings on the other 90 tasks
are outside both columns.

The authors state the choice and defend it: "For a human-in-the-loop auditing
tool, recall is the primary objective: missing a genuine defect risks
corrupting leaderboard conclusions, whereas a false positive costs only a few
seconds of expert review." That is a coherent position about triage, and this
script is not an argument against it.

It is an argument about what can be concluded from the published table. A
random flagger that picks n of 102 tasks recovers 12n/102 defects in
expectation. Whether 10 of 12 is remarkable or unremarkable depends entirely on
how many tasks were flagged to get it -- and that count is the one quantity the
reporting convention omits. This script sweeps it.

Usage:
  uv run --extra adapters python scripts/floor_of_the_field.py
"""

from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path

#: (label, n_tasks, n_positives, n_detected, source)
PUBLISHED = [
    (
        "BenchGuard / SAB / Opus 4.6, definition-only",
        102, 12, 10,
        "arXiv 2604.24955 Table 2: 12 confirmed defects, 102 tasks, Rec_A 83.3%",
    ),
    (
        "BenchGuard / SAB / ensemble, Rec_A",
        102, 12, 11,
        "arXiv 2604.24955 Table 2: ensemble Rec_A 91.7%",
    ),
    (
        "BenchGuard / SAB / most single models",
        102, 12, 7,
        "arXiv 2604.24955 Table 2: Rec_A 58.3% for Gemini 3.0 Flash, Gemini 3.1 Pro, GPT-5.4, Sonnet 4.6",
    ),
]


def p_at_least(tp: int, n: int, positives: int, flagged: int) -> float:
    """One-sided hypergeometric P(X >= tp) for a flagger picking `flagged` of `n`."""
    if flagged < tp:
        return float("nan")
    return sum(
        comb(positives, i) * comb(n - positives, flagged - i)
        for i in range(tp, min(positives, flagged) + 1)
    ) / comb(n, flagged)


def smallest_uninformative(n: int, positives: int, tp: int, alpha: float = 0.05) -> int | None:
    """Fewest flags at which the observed hit count stops clearing the floor."""
    for flagged in range(tp, n + 1):
        if p_at_least(tp, n, positives, flagged) >= alpha:
            return flagged
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/floor_of_the_field.json")
    ap.add_argument("--alpha", type=float, default=0.05)
    args = ap.parse_args()

    rows = []
    for label, n, positives, tp, source in PUBLISHED:
        knee = smallest_uninformative(n, positives, tp, args.alpha)
        sweep = {
            str(f): round(p_at_least(tp, n, positives, f), 4)
            for f in (tp, 20, 30, 40, 50, 60, 70, 80, 90, n)
            if f >= tp
        }
        rows.append(
            {
                "claim": label,
                "source": source,
                "n_tasks": n,
                "n_positives": positives,
                "base_rate": round(positives / n, 4),
                "n_detected": tp,
                "recall": round(tp / positives, 4),
                "n_flagged": None,
                "n_flagged_is_reported": False,
                "why_not": (
                    "Table 2's precision is flagged-task precision, computed over "
                    "findings within tasks that contain confirmed defects; findings "
                    "on the other tasks are outside both columns, so the total "
                    "number of tasks flagged is not recoverable from the table."
                ),
                "p_by_n_flagged": sweep,
                f"stops_clearing_the_floor_at_or_above": knee,
                "reading": (
                    f"Flagging {knee} or more of {n} tasks makes {tp} of {positives} "
                    f"unremarkable at alpha={args.alpha}; flagging fewer makes it a "
                    "real result. The published table does not say which."
                )
                if knee
                else "clears the floor at every flag count consistent with the observation",
            }
        )

    body = {
        "measurement": (
            "what a published audit recall implies, swept over the flag count "
            "the reporting convention omits"
        ),
        "method": (
            "One-sided hypergeometric. A flagger picking n of N tasks at random "
            "recovers K*n/N defects in expectation; the p-value is the chance it "
            "matches or beats the reported hit count."
        ),
        "not_a_criticism_of_care": (
            "BenchGuard states and defends the convention -- recall is primary for "
            "triage, and a false positive costs a few seconds of expert review. "
            "This is about what the published table supports, not about rigour."
        ),
        "our_own_number_for_comparison": (
            "results/tau2_recall.json publishes the full confusion matrix, so its "
            "floor is computable and it failed: recall 0.339 at p = 0.486, "
            "indistinguishable from random. That is the only reason this script "
            "can be pointed at anyone else."
        ),
        "alpha": args.alpha,
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(body, indent=2) + "\n")
    print(f"wrote {args.out}\n")

    for r in rows:
        print(f"{r['claim']}")
        print(
            f"  {r['n_detected']}/{r['n_positives']} defects on {r['n_tasks']} tasks "
            f"(recall {r['recall']:.3f}, base rate {r['base_rate']:.3f})"
        )
        print(f"  tasks flagged: NOT REPORTED")
        print(f"  {'flagged':>9}  {'p(>= observed)':>15}")
        for f, p in r["p_by_n_flagged"].items():
            mark = "  <- stops clearing" if r["stops_clearing_the_floor_at_or_above"] and int(f) >= r["stops_clearing_the_floor_at_or_above"] else ""
            print(f"  {f:>9}  {p:>15.4f}{mark}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
