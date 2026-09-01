#!/usr/bin/env python
"""What the gate's memory saves, and what it now costs.

`results/auditor_memory.json` shipped with no `harness` field and no script that
emits it -- the same shape as `docs/RETRACTIONS.md` entry 20, where a figure led
the agent paragraph and nothing could reproduce it. Its numbers are also stale
twice over: `Auditor` now caches only `has_correct_answer`
(`docs/changelog/123-one-call-decided-five-environments.md`) and requires two
independent replies to agree before withholding
(`docs/changelog/124-ask-again-before-deleting.md`). Both change the call count
in the direction that costs more, so leaving the old figure would understate it.

    uv run --extra adapters python scripts/auditor_memory.py --backend qwen3:8b

The corpus is the twelve toy-triage fixtures: one ticket-classification prompt
paired with twelve different planted defects, which is the case `Auditor.shape()`
exists for. Only the environments whose battery flagged something in
`SEMANTIC_SCOPE` reach the gate at all, so a healthy environment costs nothing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assay.auditor import Auditor  # noqa: E402
from assay.corpus import scored_entries  # noqa: E402


def _revision() -> dict:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def _run(client, fixtures, *, remember: bool) -> dict:
    auditor = Auditor(client)
    verdicts: dict[str, str] = {}
    started = time.time()
    for env_id, factory in fixtures:
        adapter = factory()
        try:
            if not remember:
                auditor._by_shape.clear()
            report = auditor.audit(adapter)
            verdicts[env_id] = ",".join(sorted(d.value for d in report.detected)) or "-"
        finally:
            close = getattr(adapter, "close", None)
            if close:
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
    return {
        "model_calls": auditor.calls,
        "seconds": round(time.time() - started, 1),
        "verdicts": verdicts,
        "consulted": sum(1 for d in auditor.decisions),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", default="qwen3:8b")
    ap.add_argument("--out", default=str(ROOT / "results/auditor_memory.json"))
    args = ap.parse_args()

    from assay.llm import ClaudeCLIClient, OllamaClient

    client = ClaudeCLIClient() if args.backend == "claude" else OllamaClient(args.backend)
    usable, reason = client.availability()
    if not usable:
        raise SystemExit(f"backend unavailable: {reason}")

    fixtures = [(e, f) for e, f, _ in scored_entries() if e.startswith("fixture/")]
    print(f"{len(fixtures)} fixtures, backend {client.name}", flush=True)

    without = _run(client, fixtures, remember=False)
    print(f"  without memory: {without['model_calls']} calls, {without['seconds']}s", flush=True)
    with_memory = _run(client, fixtures, remember=True)
    print(f"  with memory:    {with_memory['model_calls']} calls, {with_memory['seconds']}s", flush=True)

    identical = without["verdicts"] == with_memory["verdicts"]
    payload = {
        "what": "What Auditor.shape()'s memory saves across environments that pose "
                "the same question, and what it costs now that only the safe verdict "
                "is cached and withholding needs two replies to agree.",
        "why": "The previous version of this file had no harness field and no script "
               "that emitted it, which is docs/RETRACTIONS.md entry 20's failure. Its "
               "figures also predate two changes that both cost calls.",
        "harness": f"uv run --extra adapters python scripts/auditor_memory.py "
                   f"--backend {args.backend}",
        "assay_revision": _revision(),
        "backend": client.name,
        "consensus": Auditor(client).consensus,
        "corpus": "the 12 toy-triage fixtures, which share one instruction shape",
        "without_memory": without,
        "with_memory": with_memory,
        "verdicts_identical": identical,
        "reading": (
            f"{without['model_calls']} model calls become {with_memory['model_calls']}, "
            f"and {without['seconds']}s becomes {with_memory['seconds']}s, with every "
            f"verdict {'identical' if identical else 'CHANGED -- investigate'}. "
            f"Only the environments whose battery flagged something in SEMANTIC_SCOPE "
            f"reach the gate, so a healthy environment costs nothing."
        ),
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print("\n" + payload["reading"])
    print(f"wrote {args.out}")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
