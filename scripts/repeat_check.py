#!/usr/bin/env python
"""Run the deterministic battery over the corpus twice and diff the two passes.

`docs/REPRODUCTION.md` claims the headline reruns byte-identically, and that
claim had never been checked by anything that runs. It came up because one
auditor-arm run reported `openenv/textarena-wordle` with no defects where every
other run reports NONDETERMINISM, and there was no instrument that could say
whether the battery was reproducible or not -- only reruns that happened to
agree.

Two passes in one process, because that is the shape `full_run.py` has when it
runs more than one arm: the second arm audits every environment again, on a
process that has already audited all of them once.

    ASSAY_APPROVE_ALL="repeat check" uv run --extra adapters --extra sweep \
        --extra openenv --extra tau2 python scripts/repeat_check.py

Exit 1 on any divergence. What it compares is the detected defect classes and
each probe's status, so a probe that quietly changes from PASS to NOT_APPLICABLE
between passes is a divergence even when the detections match.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assay.corpus import scored_entries  # noqa: E402
from assay.runner import audit  # noqa: E402


def _revision() -> dict[str, object]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def one_pass(corpus, label: str) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for env_id, factory, _planted in corpus:
        adapter = factory()
        try:
            report = audit(adapter, None)
            seen[env_id] = {
                "detected": sorted(d.value for d in report.detected),
                "status": {r.probe: r.status.value for r in report.results},
            }
        finally:
            close = getattr(adapter, "close", None)
            if close:
                try:
                    close()
                except Exception:  # noqa: BLE001 - closing must not mask the result
                    pass
        print(f"  {label}: {env_id} -> {seen[env_id]['detected'] or '-'}", flush=True)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "results/repeat_check.json"))
    ap.add_argument("--passes", type=int, default=2)
    args = ap.parse_args()

    corpus = list(scored_entries())
    print(f"corpus: {len(corpus)} environments, {args.passes} passes", flush=True)
    passes = [one_pass(corpus, f"pass{i}") for i in range(args.passes)]

    first = passes[0]
    divergences = []
    for later, run in enumerate(passes[1:], start=1):
        for env_id in sorted(set(first) | set(run)):
            a, b = first.get(env_id), run.get(env_id)
            if a == b:
                continue
            divergences.append({
                "env_id": env_id,
                "pass0": a,
                f"pass{later}": b,
                "detections_differ": (a or {}).get("detected") != (b or {}).get("detected"),
            })

    payload = {
        "what": "The same deterministic battery over the same corpus, twice in one "
                "process, compared on detections and on every probe's status.",
        "why": "docs/REPRODUCTION.md claims the headline reruns identically. Nothing "
               "that runs had ever checked it, and one auditor-arm run disagreed with "
               "every other on openenv/textarena-wordle with no mechanism ever found.",
        "harness": "uv run --extra adapters --extra sweep --extra openenv --extra tau2 "
                   "python scripts/repeat_check.py",
        "assay_revision": _revision(),
        "corpus_size": len(corpus),
        "passes": args.passes,
        "n_divergences": len(divergences),
        "divergences": divergences,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\n{len(divergences)} divergences over {args.passes} passes -> {args.out}")
    for d in divergences:
        print(f"  {d['env_id']}: {d['pass0']} != {d.get('pass1')}")
    return 1 if divergences else 0


if __name__ == "__main__":
    raise SystemExit(main())
