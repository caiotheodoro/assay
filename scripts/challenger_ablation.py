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
from assay.challenger.grpo import GRPOChallenger, TransformersClient  # noqa: E402
from assay.challenger.prompted import PromptedChallenger  # noqa: E402
from assay.llm import ClaudeCLIClient, OllamaClient  # noqa: E402
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
    ap.add_argument(
        "--claude",
        action="store_true",
        help="also run a stronger model via the Claude CLI, to separate a loop "
        "that cannot find the exploit from a model that cannot",
    )
    ap.add_argument(
        "--grpo-adapter",
        default="",
        help="LoRA adapter from assay.train.run. Optional: without it the "
        "trained arm is reported as skipped, and every other arm still runs.",
    )
    ap.add_argument("--grpo-model", default="Qwen/Qwen3-1.7B")
    ap.add_argument(
        "--grpo-base",
        nargs="*",
        default=[],
        help="ollama models to run through the GRPO one-shot prompt WITHOUT the "
        "trained adapter. This is the control that separates what the training "
        "did from what the prompt format did.",
    )
    ap.add_argument("--samples", type=int, default=8, help="best-of-n for the GRPO arms")
    ap.add_argument("--out", default="results/challenger_ablation.json")
    args = ap.parse_args()

    arms = [("scripted", ScriptedChallenger())]
    skipped = []
    for model in args.models:
        client = OllamaClient(model)
        usable, reason = client.availability()
        if usable:
            arms.append((f"prompted:{model}", PromptedChallenger(client=client, turns=args.turns)))
        else:
            skipped.append({"model": model, "reason": reason})
            print(f"SKIPPING {model}: {reason}")
    if args.claude:
        client = ClaudeCLIClient()
        usable, reason = client.availability()
        if usable:
            arms.append(("prompted:claude-cli", PromptedChallenger(client=client, turns=args.turns)))
        else:
            skipped.append({"model": "claude-cli", "reason": reason})
            print(f"SKIPPING claude-cli: {reason}")
    # The GRPO prompt format on an untrained model: if this arm finds the
    # exploit too, the training was not what found it.
    for model in args.grpo_base:
        client = OllamaClient(model)
        usable, reason = client.availability()
        if usable:
            arms.append(
                (
                    f"grpo-format-untrained:{model}",
                    GRPOChallenger(
                        client=client, samples=args.samples, label="grpo-format-untrained"
                    ),
                )
            )
        else:
            skipped.append({"model": f"grpo-format-untrained:{model}", "reason": reason})
            print(f"SKIPPING grpo-format-untrained:{model}: {reason}")

    if args.grpo_adapter:
        client = TransformersClient(model_id=args.grpo_model, adapter_path=args.grpo_adapter)
        usable, reason = client.availability()
        if usable:
            arms.append(
                ("grpo-trained", GRPOChallenger(client=client, samples=args.samples))
            )
        else:
            skipped.append({"model": "grpo-trained", "reason": reason})
            print(f"SKIPPING grpo-trained: {reason}")
    else:
        reason = (
            "no --grpo-adapter given; the trained Challenger is an optional "
            "artifact and the comparison runs without it"
        )
        skipped.append({"model": "grpo-trained", "reason": reason})
        # Every other skip prints. This one recorded the reason in the JSON and
        # said nothing on the console, so the banner below appeared over an
        # empty list and the reader had to open the file to learn which arm was
        # missing. A check that cannot run says so where the run is being read.
        print(f"SKIPPING grpo-trained: {reason}")

    if skipped:
        print("an arm missing from a comparison is a result about the run, not the method\n")

    rows = []
    for name, challenger in arms:
        started = time.time()
        with build(args.task) as adapter:
            report = audit(adapter, {"challenger": challenger})
        found = DefectClass.REWARD_HACKABLE in report.detected
        probe = [r for r in report.results if r.family == "reward_hackability"][0]
        if probe.status.value in ("NOT_APPLICABLE", "ERROR"):
            # A challenger that could not speak is not a challenger that found
            # nothing. Report which, or the row is a lie.
            print(f"{name:22} {probe.status.value}: {probe.reason}", flush=True)
            rows.append(
                {
                    "challenger": name,
                    "found_exploit": False,
                    "probe_status": probe.status.value,
                    "reason": probe.reason,
                    "seconds": round(time.time() - started, 1),
                }
            )
            continue
        per_task = next(iter(probe.detail.get("per_task", {}).values()), {})
        best_gap = max((a["gap"] for a in per_task.get("attempts", [])), default=0.0)
        row = {
            "challenger": name,
            "found_exploit": found,
            "best_exploit_gap": round(best_gap, 4),
            "attempts": per_task.get("n_attempts", 0),
            "seconds": round(time.time() - started, 1),
        }
        # Recorded either way. What the attacker tried and failed at is the
        # part that tells you whether to reach for a better model or a better
        # loop.
        row["attacker_trace"] = per_task.get("attacker_trace", [])
        if found:
            evidence = [f for f in report.findings if f.defect is DefectClass.REWARD_HACKABLE][0]
            row["exploit"] = {
                "policy": evidence.evidence["exploit_policy"],
                "reported": evidence.evidence["reported_score"],
                "true_completion": evidence.evidence["true_completion"],
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
    out.write_text(
        json.dumps(
            {"task": args.task, "turns": args.turns, "arms": rows, "skipped": skipped},
            indent=2,
        )
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
