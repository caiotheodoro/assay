#!/usr/bin/env python
"""How often does the shipped gate withhold on an environment that has an answer?

`results/gate_reliability.json` measures this at the level of a whole run and
found 1 run in 7 -- too rare for corpus-level runs to bound at any affordable k,
since at that rate five clean runs happen about 46% of the time by chance.

This measures the same thing per environment, which is where the decision is
actually made. One `Auditor.classify()` call is seconds rather than the ten
minutes a corpus run costs, so k can be large enough to bound the rate instead
of merely observing it.

    uv run --extra adapters --extra sweep --extra openenv --extra tau2 \
        python scripts/false_override_rate.py --k 30 --env tau2/airline

The default environment is the one that failed: `tau2/airline`, a multi-turn
customer-service dialogue graded on the end state of a database. It plainly has
a correct answer, so every `no_correct_answer` here is a false override.

A fresh Auditor per trial, so the shape memory never carries a verdict in, and
the full shipped path -- the question, the abstention guard, and the consensus
requirement -- rather than a raw model call.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assay.auditor import Auditor  # noqa: E402
from assay.corpus import scored_entries  # noqa: E402


def _revision() -> dict:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def _upper_bound(failures: int, trials: int) -> float:
    """One-sided 95% upper bound on the rate, by exact binomial search."""
    if trials == 0:
        return 1.0
    from math import comb

    def tail(p: float) -> float:
        return sum(comb(trials, i) * p**i * (1 - p) ** (trials - i)
                   for i in range(failures + 1))

    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if tail(mid) > 0.05:
            lo = mid
        else:
            hi = mid
    return round(hi, 4)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", type=int, default=30)
    ap.add_argument("--env", default="tau2/airline")
    ap.add_argument("--backend", default="claude")
    ap.add_argument("--out", default=str(ROOT / "results/false_override_rate.json"))
    args = ap.parse_args()

    from assay.llm import ClaudeCLIClient, OllamaClient

    client = ClaudeCLIClient() if args.backend == "claude" else OllamaClient(args.backend)
    usable, reason = client.availability()
    if not usable:
        raise SystemExit(f"backend unavailable: {reason}")

    factory = next(f for e, f, _ in scored_entries() if e == args.env)
    adapter = factory()
    counts, rows = Counter(), []
    started = time.time()
    for i in range(args.k):
        auditor = Auditor(client)
        try:
            answer = auditor.classify(adapter)
        except Exception as exc:  # noqa: BLE001
            counts["unusable"] += 1
            rows.append({"trial": i, "error": type(exc).__name__})
            print(f"  {i + 1}/{args.k}: unusable", flush=True)
            continue
        verdict = (answer or {}).get("verdict")
        counts[str(verdict)] += 1
        rows.append({"trial": i, "verdict": verdict, "calls": auditor.calls,
                     "model_said": (answer or {}).get("model_said"),
                     "compared_against": (answer or {}).get("compared_against"),
                     "abstained": (answer or {}).get("abstained")})
        print(f"  {i + 1}/{args.k}: {verdict} (calls {auditor.calls})", flush=True)

    withheld = counts.get("no_correct_answer", 0)
    scored = args.k - counts.get("unusable", 0)
    bound = _upper_bound(withheld, scored)
    payload = {
        "what": f"How often the shipped semantic gate calls {args.env} an environment "
                "with no correct answer. It has one.",
        "why": "gate_reliability.json measures this per run and found 1 in 7, which no "
               "affordable number of corpus runs can bound. Per environment the same "
               "decision costs seconds, so it can be bounded rather than observed.",
        "harness": f"uv run ... python scripts/false_override_rate.py --k {args.k} "
                   f"--env {args.env}",
        "assay_revision": _revision(),
        "environment": args.env,
        "backend": client.name,
        "consensus": Auditor(client).consensus,
        "trials": args.k,
        "scored": scored,
        "false_overrides": withheld,
        "counts": dict(counts),
        "rate": round(withheld / scored, 4) if scored else None,
        "upper_95": bound,
        "seconds": round(time.time() - started),
        "reading": (
            f"{withheld} false overrides in {scored} trials on the shipped path. "
            f"One-sided 95% upper bound on the per-decision rate: {bound:.1%}. "
            "That is a bound, not a demonstration that the rate is zero."
        ),
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print("\n" + payload["reading"])
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
