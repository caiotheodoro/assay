#!/usr/bin/env python3
"""Does a Challenger that PROPOSES policies find the `paws` exploit a human found?

The README pins the gap this measures:

    Assay flagged 14 of 25 sampled `paws` items as REWARD_HACKABLE. It did not
    find the `"yesno"` case; hand triage did.

`inspect_evals/paws` is scored by `includes()`. The 14 are exactly the items
whose target is `No`, credited to the adapter's own `always_escalate` policy --
"I cannot determine the answer." contains `no`, inside `cannot`. A constant
string naming both labels takes all 25, and no fixed repertoire contains one.

Arms, all against the same 25-item pinned subsample:

  scripted            the shipped default. Deterministic, run once, and the
                      floor everything else is measured against.
  synthesis/full      one model call per task, shown the task instruction, the
                      verifier, and the prompt the eval wraps around every item.
  synthesis/blind     the same challenger with `read_verifier=False` and
                      `read_agent_prompt=False`. This is the ablation that says
                      whether the finding comes from READING or from the model
                      already knowing what PAWS is.

`k` passes per model arm, because a sampled attacker measured once is a coin
flip reported as a capability. `results/challenger_reliability.json` records
3-of-4 on the last one of these that was measured single-pass by accident.

Detection is decided by `RewardHackability`, the shipped probe, not by anything
in this file: every proposal is replayed and scored by `exploit_gap`. The
model's own `scores_well` claim is collected and compared against the probe,
and used for nothing.

    uv run --extra adapters --extra sweep python scripts/policy_synthesis.py \
        --out results/policy_synthesis.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.challenger.scripted import ScriptedChallenger  # noqa: E402
from assay.challenger.synthesis import SYSTEM, PolicySynthesisChallenger  # noqa: E402
from assay.llm import ClaudeCLIClient, LLMUnavailable, OllamaClient  # noqa: E402
from assay.probes.hackability import RewardHackability  # noqa: E402
from assay.runconfig import RunConfig, client_config, prompt_version  # noqa: E402
from assay.types import DefectClass  # noqa: E402


def detected(result) -> set[str]:
    return {
        f.task_id
        for f in result.findings
        if f.defect is DefectClass.REWARD_HACKABLE and f.task_id
    }


def one_run(adapter, challenger) -> dict[str, Any]:
    """One full pass over all 25 tasks, scored by the shipped probe."""
    started = time.time()
    result = RewardHackability().check(adapter, {"challenger": challenger})
    seconds = round(time.time() - started, 1)

    per_task = result.detail.get("per_task", {})
    found = detected(result)

    attempts = sum(int(v.get("n_attempts") or 0) for v in per_task.values())
    mute = sorted(t for t, v in per_task.items() if v.get("unavailable"))

    # The winning policy string per task, and the model's own claim next to it.
    # The claim is reported, never consulted -- see `synthesis.py`.
    exploits: list[str] = []
    claims: list[tuple[float, bool]] = []
    for task_id, row in per_task.items():
        best = row.get("best_attempt")
        if best and task_id in found:
            exploits.append(str(best["policy"]))
        trace = row.get("attacker_trace") or []
        claim = next(
            (t["self_report"] for t in trace if isinstance(t.get("self_report"), (int, float))),
            None,
        )
        if claim is not None:
            claims.append((float(claim), task_id in found))

    return {
        "status": result.status.value,
        "detected": sorted(found),
        "n_detected": len(found),
        "n_attempts": attempts,
        "seconds": seconds,
        "mute_tasks": mute,
        "exploit_policies": sorted(set(exploits)),
        "self_report_vs_probe": [
            {"claimed": c, "probe_confirmed": ok} for c, ok in claims
        ],
    }


def summarise(runs: list[dict[str, Any]], floor: set[str]) -> dict[str, Any]:
    """Hit rate over runs, and -- the number that matters -- how much of what
    the scripted floor cannot reach was reached."""
    total = len(runs)
    beyond = [sorted(set(r["detected"]) - floor) for r in runs]
    overclaimed = sum(
        1
        for r in runs
        for c in r["self_report_vs_probe"]
        if c["claimed"] >= 0.5 and not c["probe_confirmed"]
    )
    claims = sum(len(r["self_report_vs_probe"]) for r in runs)
    return {
        "runs": total,
        "detected_per_run": [r["n_detected"] for r in runs],
        "found_everything": sum(1 for r in runs if len(r["detected"]) == 25),
        "hit_rate_all_25": round(sum(1 for r in runs if len(r["detected"]) == 25) / total, 4)
        if total
        else None,
        "beyond_scripted_per_run": [len(b) for b in beyond],
        "beyond_scripted_median": statistics.median(len(b) for b in beyond) if total else None,
        "seconds_per_run": [r["seconds"] for r in runs],
        "attempts_per_run": [r["n_attempts"] for r in runs],
        "exploit_policies": sorted({p for r in runs for p in r["exploit_policies"]}),
        "self_report": {
            "claims_recorded": claims,
            "claimed_success_probe_disagreed": overclaimed,
            "used_for": "nothing; recorded so the disagreement can be reported",
        },
        "runs_detail": runs,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/policy_synthesis.json")
    ap.add_argument("--k", type=int, default=3, help="runs per model arm")
    ap.add_argument("--ollama-model", default="qwen3:8b")
    ap.add_argument("--claude-model", default="sonnet")
    ap.add_argument(
        "--arms",
        nargs="*",
        default=["ollama", "claude"],
        help="which backends to run; the scripted floor always runs",
    )
    args = ap.parse_args()

    from assay._inspect_evals_corpus import _build

    print("building inspect_evals/paws (first run downloads the dataset)...", flush=True)
    adapter = _build("paws")
    n_tasks = len(adapter.manifest().tasks)
    print(f"  {n_tasks} tasks", flush=True)

    print("scripted floor...", flush=True)
    floor_run = one_run(adapter, ScriptedChallenger())
    floor = set(floor_run["detected"])
    print(f"  scripted: {len(floor)}/{n_tasks}", flush=True)

    clients: dict[str, Any] = {}
    if "ollama" in args.arms:
        clients["ollama"] = OllamaClient(args.ollama_model)
    if "claude" in args.arms:
        clients["claude"] = ClaudeCLIClient(args.claude_model)

    backends: dict[str, Any] = {}
    for key, client in clients.items():
        usable, why = client.availability()
        if not usable:
            backends[client.name] = {"skipped": why}
            print(f"  {client.name}: SKIPPED -- {why}", flush=True)
            continue
        arms: dict[str, Any] = {}
        for arm, kwargs in (
            ("full", {}),
            ("blind", {"read_verifier": False, "read_agent_prompt": False}),
        ):
            runs = []
            for i in range(args.k):
                challenger = PolicySynthesisChallenger(client, **kwargs)
                print(f"  {client.name} / {arm} / run {i + 1}...", flush=True)
                try:
                    run = one_run(adapter, challenger)
                except LLMUnavailable as exc:
                    run = {"unavailable": str(exc)}
                    print(f"    unavailable: {exc}", flush=True)
                else:
                    print(
                        f"    {run['n_detected']}/{n_tasks} in {run['seconds']}s"
                        f" ({run['n_attempts']} attempts)",
                        flush=True,
                    )
                runs.append(run)
            scored = [r for r in runs if "unavailable" not in r]
            arms[arm] = (
                summarise(scored, floor)
                if scored
                else {"runs": 0, "unavailable": [r["unavailable"] for r in runs]}
            )
        backends[client.name] = {
            "config": client_config(client),
            "arms": arms,
        }

    payload = {
        "what": (
            "Can a Challenger that proposes policies from what it can read find "
            "the inspect_evals/paws exploit that only hand triage found?"
        ),
        "why": (
            "README: 'Assay flagged 14 of 25 sampled paws items as REWARD_HACKABLE. "
            "It did not find the \"yesno\" case; hand triage did. The scripted "
            "Challenger's repertoire is the adapter's trivial policies, and none of "
            "them names both labels at once.'"
        ),
        "design": (
            "One model call per task asks for literal answer strings. Deterministic "
            "code substitutes each into an action shape the ADAPTER declared, replays "
            "it, and scores it with probes.hackability.exploit_gap. The model never "
            "names a tool, never writes code, and never reports whether it succeeded."
        ),
        "corpus": (
            f"inspect_evals/paws, the same 25-item pinned subsample "
            f"(N_SAMPLES=25, SEED=0, shuffle=False) the corpus entry audits. "
            f"{len(floor)} of {n_tasks} are reachable by the scripted floor."
        ),
        "scope": (
            "Measurement only. The scripted Challenger remains the default "
            "everywhere; results/full_run.json is produced by it and is unchanged."
        ),
        "floor": {
            "challenger": "scripted",
            "deterministic": True,
            "detected": floor_run["detected"],
            "n_detected": len(floor),
            "exploit_policies": floor_run["exploit_policies"],
            "seconds": floor_run["seconds"],
            "note": (
                "These are the items whose target is 'No'. 'I cannot determine the "
                "answer.' contains 'no' inside 'cannot', which a substring scorer "
                "credits. The remaining items need a string naming both labels."
            ),
        },
        "backends": backends,
        "run_config": RunConfig(
            harness="scripts/policy_synthesis.py",
            task="inspect_evals/paws",
            samples_per_task=n_tasks,
            aggregation="per-item REWARD_HACKABLE from RewardHackability; hit rate over k runs",
            arms={
                name: (info.get("config") or {"skipped": info.get("skipped")})
                for name, info in backends.items()
            },
            prompt=prompt_version(SYSTEM),
            extra={"k": args.k},
        ).to_dict(),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
