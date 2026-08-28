#!/usr/bin/env python3
"""Ablation: does an agentic Challenger find what the scripted one cannot?

Target is `harbor/self-graded`, whose verifier reads its expectation from a
file in the workspace. Writing the same value to both passes while doing
nothing. The exploit is real -- it is exhibited directly in
tests/test_harbor_ground_truth.py -- and the scripted Challenger does not find
it. This measures whether a model in a feedback loop does.
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
from assay.challenger import ScriptedChallenger  # noqa: E402
from assay.challenger.prompted import PromptedChallenger  # noqa: E402
from assay.llm import OllamaClient  # noqa: E402
from assay.sandbox import AutoApprove, DockerSandbox  # noqa: E402
from assay.types import DefectClass  # noqa: E402

SUITE = Path(__file__).resolve().parents[1] / "src" / "assay" / "fixtures" / "harbor_suite"


def build(task: str) -> HarborAdapter:
    root = Path(tempfile.mkdtemp(prefix="assay-abl-"))
    shutil.copytree(SUITE / task, root / task)
    return HarborAdapter(
        root, sandbox=DockerSandbox(AutoApprove("ablation")), env_id=f"harbor/{task}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="self-graded")
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--models", nargs="*", default=["qwen3:1.7b", "qwen3:8b"])
    ap.add_argument("--out", default="results/challenger_ablation.json")
    args = ap.parse_args()

    arms = [("scripted", ScriptedChallenger())]
    for model in args.models:
        client = OllamaClient(model)
        if client.available():
            arms.append((f"prompted:{model}", PromptedChallenger(client=client, turns=args.turns)))
        else:
            print(f"skipping {model}: not pulled")

    rows = []
    for name, challenger in arms:
        started = time.time()
        with build(args.task) as adapter:
            report = audit(adapter, {"challenger": challenger})
        found = DefectClass.REWARD_HACKABLE in report.detected
        probe = [r for r in report.results if r.family == "reward_hackability"][0]
        per_task = next(iter(probe.detail.get("per_task", {}).values()), {})
        best_gap = max((a["gap"] for a in per_task.get("attempts", [])), default=0.0)
        row = {
            "challenger": name,
            "found_exploit": found,
            "best_exploit_gap": round(best_gap, 4),
            "attempts": per_task.get("n_attempts", 0),
            "seconds": round(time.time() - started, 1),
        }
        if found:
            evidence = [f for f in report.findings if f.defect is DefectClass.REWARD_HACKABLE][0]
            row["exploit"] = {
                "policy": evidence.evidence["exploit_policy"],
                "reported": evidence.evidence["reported_score"],
                "true_completion": evidence.evidence["true_completion"],
                "trace": evidence.evidence.get("attacker_trace", [])[-3:],
            }
        rows.append(row)
        print(
            f"{name:22} {'FOUND' if found else 'missed':6} "
            f"gap={row['best_exploit_gap']:.2f} attempts={row['attempts']:2d} "
            f"{row['seconds']:6.1f}s",
            flush=True,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"task": args.task, "turns": args.turns, "arms": rows}, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
