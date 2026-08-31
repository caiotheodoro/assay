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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.adapters import HarborAdapter  # noqa: E402
from assay.adapters.harbor import stage_suite  # noqa: E402
from assay.challenger import ScriptedChallenger  # noqa: E402
from assay.challenger.grpo import GRPOChallenger, TransformersClient  # noqa: E402
from assay.challenger.prompted import PromptedChallenger  # noqa: E402
from assay.llm import ClaudeCLIClient, OllamaClient  # noqa: E402
from assay.challenger.grpo import SYSTEM as GRPO_SYSTEM  # noqa: E402
from assay.challenger.prompted import SYSTEM as PROMPTED_SYSTEM  # noqa: E402
from assay.runconfig import (  # noqa: E402
    RunConfig,
    client_config,
    docker_image_revision,
    prompt_version,
)
from assay.sandbox import AutoApprove, DockerSandbox  # noqa: E402
from assay.types import DefectClass  # noqa: E402

SUITE = Path(__file__).resolve().parents[1] / "src" / "assay" / "fixtures" / "harbor_suite"


def task_image(task: str) -> str:
    """The container image the task declares, from its own `task.toml`."""
    import tomllib

    toml = tomllib.loads((SUITE / task / "task.toml").read_text())
    return str(toml.get("environment", {}).get("docker_image") or "alpine:3.20")


def build(task: str) -> HarborAdapter:
    root = stage_suite(SUITE / task, "assay-abl-")
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
    #: arm name -> the sampling configuration it actually ran under. Collected
    #: as the arms are built, from the client objects themselves, so it cannot
    #: drift from what ran (11.2: "emit this from the harness rather than
    #: writing it by hand").
    configs: dict[str, dict] = {
        "scripted": {
            "client": None,
            "backend": "none",
            "note": "a fixed repertoire; no model, so no sampling configuration exists",
        }
    }
    skipped = []
    for model in args.models:
        client = OllamaClient(model)
        usable, reason = client.availability()
        if usable:
            arms.append((f"prompted:{model}", PromptedChallenger(client=client, turns=args.turns)))
            configs[f"prompted:{model}"] = client_config(client)
        else:
            skipped.append({"model": model, "reason": reason})
            print(f"SKIPPING {model}: {reason}")
    if args.claude:
        client = ClaudeCLIClient()
        usable, reason = client.availability()
        if usable:
            arms.append(("prompted:claude-cli", PromptedChallenger(client=client, turns=args.turns)))
            configs["prompted:claude-cli"] = client_config(client)
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
            configs[f"grpo-format-untrained:{model}"] = client_config(client)
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
            configs["grpo-trained"] = client_config(client)
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

    #: Read off the task's own `task.toml` rather than assumed, so the recorded
    #: digest is the container the attack actually ran in.
    sandbox_image = task_image(args.task)

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
                    "run_config": configs.get(name, {}),
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
        row["run_config"] = configs.get(name, {})
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

    run_config = RunConfig(
        harness="scripts/challenger_ablation.py",
        task=f"harbor/{args.task}",
        samples_per_task=1,
        aggregation=(
            "one attack per arm; the probe takes the MAXIMUM exploit gap across "
            "every attempt in that attack, and flags REWARD_HACKABLE at gap >= 0.5. "
            "One attack is not a capability -- the pass^k version of this arm is "
            "scripts/challenger_reliability.py."
        ),
        arms=configs,
        prompt=prompt_version(PROMPTED_SYSTEM, GRPO_SYSTEM),
        extra={
            "turns_per_attack": args.turns,
            "grpo_samples_per_task": args.samples,
            "prompt_sources": [
                "assay.challenger.prompted.SYSTEM",
                "assay.challenger.grpo.SYSTEM",
            ],
            "sandbox": {
                "image_revision": docker_image_revision(sandbox_image),
                "network": "none",
                "approver": "AutoApprove('ablation')",
            },
        },
    ).to_dict()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "task": args.task,
                "turns": args.turns,
                "run_config": run_config,
                "arms": rows,
                "skipped": skipped,
            },
            indent=2,
        )
    )
    cfg_out = out.parent / f"runconfig-{out.stem}.json"
    cfg_out.write_text(json.dumps(run_config, indent=2))
    print(f"\nwrote {out}")
    print(f"wrote {cfg_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
