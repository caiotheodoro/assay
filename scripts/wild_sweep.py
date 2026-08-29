"""Sweep published inspect_evals tasks and write the full record.

    uv run --extra adapters --extra sweep python scripts/wild_sweep.py

Writes `results/wild_sweep.json`: every registered task, every exclusion with
its reason, and every candidate finding. Reporting zero real defects is an
acceptable outcome; reporting a task as absent without a reason is not, so the
output is a partition of the registry, checked before it is written.

Calling a task factory materialises its dataset from the HF Hub, so this needs
network -- roughly one hit per attempted task, then whatever `datasets` has
cached. `--only` re-runs a single task for triage at no further cost.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.sweep import TaskSweep, sweep  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "results" / "wild_sweep.json"


def _line(result: TaskSweep) -> str:
    head = f"{result.status:12} {result.task:34}"
    if result.status == "SWEPT":
        return (
            f"{head} {result.protocol:15} "
            f"n={result.n_sampled} anchored={result.n_anchored} "
            f"ran={len(result.probes_passed) + len(result.findings)} "
            f"findings={len(result.findings)} {result.verdict}"
        )
    return f"{head} {(result.reason or '')[:110]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="sweep only these task names")
    parser.add_argument("--samples", type=int, default=25)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=300, help="seconds per dataset")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument(
        "--triage",
        default=str(OUT.parent / "wild_sweep_triage.json"),
        help="hand-written triage verdicts, embedded verbatim under 'triage'",
    )
    args = parser.parse_args()

    started = time.time()
    record = sweep(
        only=args.only,
        n_samples=args.samples,
        seed=args.seed,
        timeout=args.timeout,
        on_task=lambda r: print(_line(r), flush=True),
    )
    record["wall_seconds"] = round(time.time() - started, 1)

    statuses = Counter(t["status"] for t in record["tasks"])
    findings = [
        {"task": t["task"], **f} for t in record["tasks"] for f in t["findings"]
    ]
    record["summary"] = {
        "n_registered": record["n_registered_tasks"],
        "n_static_excluded": record["n_static_excluded"],
        "n_attempted": record["n_attempted"],
        "by_status": dict(statuses),
        "n_candidate_findings": len(findings),
        "candidate_findings_by_class": dict(Counter(f["defect"] for f in findings)),
        "tasks_with_findings": sorted({f["task"] for f in findings}),
        # A zero-finding sweep only means something if the probes ran. Counted
        # here so the headline number cannot be read as "clean" when it was
        # really "nothing was checkable".
        "probes_passed_total": dict(
            Counter(p for t in record["tasks"] for p in t["probes_passed"])
        ),
        "not_applicable_total": dict(
            Counter(na["probe"] for t in record["tasks"] for na in t["not_applicable"])
        ),
    }

    # Every registered task is accounted for exactly once, or the numbers above
    # are a subset of the truth presented as all of it.
    accounted = (
        {e["task"] for e in record["static_exclusions"]}
        | {t["task"] for t in record["tasks"]}
        | {e["task"] for e in record["out_of_scope"]}
    )
    if not args.only and len(accounted) != record["n_registered_tasks"]:
        print(
            f"UNACCOUNTED: {record['n_registered_tasks']} registered but "
            f"{len(accounted)} recorded",
            file=sys.stderr,
        )
        return 2

    # The triage is hand-written and is embedded, not merged: the machine record
    # of what the probes reported and the human verdict on whether it is real are
    # different kinds of claim, and a reader has to be able to tell which is
    # which. A missing triage file is recorded as missing rather than skipped.
    triage_path = Path(args.triage)
    if triage_path.exists():
        record["triage"] = json.loads(triage_path.read_text())
        record["triage"]["_source"] = str(triage_path.name)
    else:
        record["triage"] = {
            "_missing": f"{triage_path} not found; no finding in this run has been "
            "hand-verified, and none should be read as confirmed"
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True, default=str))

    print()
    print(f"registered      {record['n_registered_tasks']}")
    print(f"static excluded {record['n_static_excluded']}")
    print(f"attempted       {record['n_attempted']}")
    for status, n in sorted(statuses.items()):
        print(f"  {status:12} {n}")
    print(f"candidate findings {len(findings)}")
    for defect, n in sorted(record["summary"]["candidate_findings_by_class"].items()):
        print(f"  {defect:26} {n}")
    print(f"wrote {out}  ({record['wall_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
