#!/usr/bin/env python
"""How much does the semantic gate's verdict move between identical runs?

The paired bootstrap in `scripts/intervals.py` resamples *environments*. It
cannot see the other source of variance in `assay+auditor`: the model is asked a
question once per environment per run, and asked twice it does not always answer
the same. Two runs of the same corpus on the same commit returned 43.0 and
122.0, the second because the gate concluded `tau2/airline` -- a customer
service task graded on database state -- had no correct answer and withheld 25
findings, two of them real planted defects.

That is `docs/PRE-REGISTRATION-NOANSWER.md` criterion 1, and a single run cannot
detect it. This runs the arm k times and reports the distribution.

    uv run --extra adapters --extra sweep --extra openenv --extra tau2 \
        python scripts/gate_reliability.py --k 5

`--from-runs DIR` aggregates per-run summaries already produced instead of
running them again, which is how the first measurement was assembled: five runs
from the loop above plus the two full-corpus runs that exposed the problem.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Environments the gate is *supposed* to withhold on: nothing is planted in
#: them and they have no correct answer. Anything else it withholds is a real
#: finding it deleted.
LEGITIMATE = (
    "inspect_evals/personality_BFI",
    "inspect_evals/stereoset",
    "toy-triage/preference",
    "noanswer/ranking",
    "noanswer/openended",
)


def _revision() -> dict[str, object]:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def summarise(payload: dict) -> dict:
    a, b = payload["arms"]["assay+auditor"], payload["arms"]["assay"]
    logs = payload.get("arm_logs", {}).get("assay+auditor", {})
    decisions = logs.get("decisions", [])
    withheld = sorted(x["env_id"] for x in decisions if x.get("outcome") == "withheld")
    return {
        "corpus_size": payload["corpus_size"],
        "assay": {k: b.get(k) for k in ("expected_loss", "recall", "precision",
                                        "n_missed", "n_unchecked", "n_spurious")},
        "assay+auditor": {k: a.get(k) for k in ("expected_loss", "recall", "precision",
                                                "n_missed", "n_unchecked", "n_spurious")},
        "model_calls": logs.get("model_calls"),
        "withheld": withheld,
        "false_overrides": [e for e in withheld if e not in LEGITIMATE],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--backend", default="claude")
    ap.add_argument("--from-runs", default=None,
                    help="aggregate per-run summaries in this directory instead of running")
    ap.add_argument("--out", default=str(ROOT / "results/gate_reliability.json"))
    args = ap.parse_args()

    runs: list[dict] = []
    if args.from_runs:
        for path in sorted(Path(args.from_runs).glob("*.json")):
            runs.append(json.loads(path.read_text()))
    else:
        for k in range(args.k):
            out = Path(f"/tmp/gate_reliability_run{k}.json")
            print(f"run {k + 1} of {args.k} ...", flush=True)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/full_run.py"),
                 "--auditor-arm", args.backend, "--out", str(out)],
                cwd=ROOT, check=True,
            )
            runs.append(summarise(json.loads(out.read_text())))

    losses = [r["assay+auditor"]["expected_loss"] for r in runs]
    base = [r["assay"]["expected_loss"] for r in runs]
    saved = [b - a for a, b in zip(losses, base)]
    bad = [r for r in runs if r["false_overrides"]]

    payload = {
        "what": "The same auditor arm, on the same corpus, run repeatedly.",
        "why": "The paired bootstrap resamples environments and cannot see "
               "run-to-run variance in the model's own answers. Two runs "
               "returned 43.0 and 122.0.",
        "harness": "uv run --extra adapters --extra sweep --extra openenv "
                   "--extra tau2 python scripts/gate_reliability.py --k 5",
        "assay_revision": _revision(),
        "n_runs": len(runs),
        "deterministic_arm": {"expected_loss": base[0] if base else None,
                              "identical_every_run": len(set(base)) == 1},
        "auditor_arm": {
            # The mean is first because expected loss is an expectation. A
            # median hides the run that cost 65, and choosing the kinder of two
            # statistics is the move this repository criticises elsewhere.
            "expected_loss": {"mean": round(statistics.mean(losses), 2),
                              "min": min(losses), "median": statistics.median(losses),
                              "max": max(losses), "values": losses},
            "saved_vs_deterministic": {"mean": round(statistics.mean(saved), 2),
                                       "min": min(saved),
                                       "median": statistics.median(saved),
                                       "max": max(saved), "values": saved},
        },
        "false_override_rate": {
            "runs_with_a_false_override": len(bad),
            "of_runs": len(runs),
            "environments": sorted({e for r in bad for e in r["false_overrides"]}),
            "why_it_matters": "A false override deletes findings on an environment "
                              "that does have a correct answer. Those findings can be "
                              "real planted defects, so the agent trades a false "
                              "positive for a hidden true one.",
        },
        "reading": "",
        "runs": runs,
    }
    payload["reading"] = (
        f"Over {len(runs)} identical runs the agent saved a MEAN of "
        f"{round(statistics.mean(saved), 2)} -- median {statistics.median(saved)}, range "
        f"{min(saved)} to {max(saved)}. The mean is the number that matters, because "
        f"expected loss is an expectation and {len(bad)} of {len(runs)} runs deleted real "
        f"findings. The deterministic arm returned the same number every time. A single "
        f"run of this arm is not a result, and neither is the median of several."
    )
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print(payload["reading"])
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
