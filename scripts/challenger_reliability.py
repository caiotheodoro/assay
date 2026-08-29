#!/usr/bin/env python3
"""How often does the Challenger actually find the exploit?

It found `harbor/self-graded` at turn 8 with gap 1.00, and then missed the same
environment on the next run. A probe backed by a sampled model is not a
deterministic check, and reporting one successful run as "the Challenger finds
this" would be a capability claim the evidence does not support.

So: k independent attempts, report hits/k. This is pass^k rather than pass@1,
for the same reason tau-bench uses it -- a system that succeeds once in five
tries is not a system that succeeds.

Usage:
  uv run --extra adapters python scripts/challenger_reliability.py --k 5
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.adapters import HarborAdapter  # noqa: E402
from assay.challenger import CompositeChallenger, ScriptedChallenger  # noqa: E402
from assay.challenger.prompted import PromptedChallenger  # noqa: E402
from assay.llm import ClaudeCLIClient, OllamaClient  # noqa: E402
from assay.sandbox import AutoApprove, DockerSandbox  # noqa: E402
from assay.types import DefectClass  # noqa: E402

SUITE = Path(__file__).resolve().parents[1] / "src" / "assay" / "fixtures" / "harbor_suite"


def build(task: str) -> HarborAdapter:
    root = Path(tempfile.mkdtemp(prefix="assay-rel-"))
    shutil.copytree(SUITE / task, root / task)
    return HarborAdapter(
        root, sandbox=DockerSandbox(AutoApprove("reliability run")), env_id=f"harbor/{task}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="self-graded")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--model", default="claude")
    ap.add_argument("--out", default="results/challenger_reliability.json")
    args = ap.parse_args()

    client = ClaudeCLIClient() if args.model == "claude" else OllamaClient(args.model)
    usable, reason = client.availability()
    if not usable:
        print(f"cannot run: {reason}")
        return 1

    attempts = []
    for i in range(1, args.k + 1):
        challenger = CompositeChallenger(
            [ScriptedChallenger(), PromptedChallenger(client=client, turns=args.turns)]
        )
        started = time.time()
        with build(args.task) as adapter:
            report = audit(adapter, {"challenger": challenger})
        found = DefectClass.REWARD_HACKABLE in report.detected
        probe = [r for r in report.results if r.family == "reward_hackability"][0]
        per_task = next(iter(probe.detail.get("per_task", {}).values()), {})
        best = max((a["gap"] for a in per_task.get("attempts", [])), default=0.0)
        attempts.append(
            {
                "run": i,
                "found": found,
                "best_gap": round(best, 4),
                "seconds": round(time.time() - started, 1),
            }
        )
        print(
            f"  run {i}/{args.k}: {'FOUND' if found else 'missed':6} "
            f"gap={best:.2f}  {attempts[-1]['seconds']:.0f}s",
            flush=True,
        )

    hits = sum(a["found"] for a in attempts)
    body = {
        "task": args.task,
        "challenger": f"scripted+prompted[{client.name}]",
        "k": args.k,
        "turns": args.turns,
        "hits": hits,
        "hit_rate": round(hits / args.k, 3),
        "attempts": attempts,
        "note": (
            "A probe backed by a sampled model is not a deterministic check. Reporting a "
            "single successful run as a capability claim would overstate what the evidence "
            "supports, which is why this is hits/k rather than 'it works'."
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(body, indent=2))
    print(f"\n{hits}/{args.k} runs found the exploit (hit rate {hits/args.k:.0%})")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
