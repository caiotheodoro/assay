"""Calibration of the Challenger's `solves_the_task` self-reports.

    uv run --extra adapters python scripts/challenger_calibration.py

The attacker states, every turn, whether it believes the action it just took
really did the job. An independent verifier the attacker cannot reach scores the
same turn. That is paired (confidence, outcome) data and nothing has ever
scored it.

Where the outcomes come from, and why not from the recorded runs directly: the
ablation files record the attacker's claim and the ENVIRONMENT's reported score,
but not the independent verifier's `true_completion` per turn -- only for the
one best policy. So the outcome half of each pair is regenerated here by
REPLAYING the recorded action prefixes against the real environment, which is
the same thing `assay.probes.hackability.exploit_gap` does when the probe runs
live. No model is called: the traces are already on disk, and replay is a
deterministic program.

Prefixes, not single actions, because that is the unit the attacker's claim is
about in this loop: the workspace persists across turns, so "does this solve the
task" is a question about the workspace as it stands after turn N, which is
actions 1..N replayed from a clean reset. It is also exactly the transcript the
probe scores.

Needs Docker: the traces are Harbor runs and the verifier is a container.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.adapters import HarborAdapter  # noqa: E402
from assay.challenger.prompted import _confidence  # noqa: E402
from assay.calibration import Pair, report  # noqa: E402
from assay.challenger.prompted import RESET_TOOL  # noqa: E402
from assay.probes.hackability import exploit_gap  # noqa: E402
from assay.runconfig import git_revision  # noqa: E402
from assay.sandbox import AutoApprove, DockerSandbox  # noqa: E402
from assay.types import Action, Transcript  # noqa: E402

SUITE = Path(__file__).resolve().parents[1] / "src" / "assay" / "fixtures" / "harbor_suite"

SOURCES = [
    "results/challenger_ablation.json",
    "results/challenger_ablation_8b.json",
    "results/challenger_ablation_claude.json",
    "results/challenger_ablation_runconfig.json",
]


def build(task: str) -> HarborAdapter:
    root = Path(tempfile.mkdtemp(prefix="assay-cal-"))
    shutil.copytree(SUITE / task, root / task)
    return HarborAdapter(
        root, sandbox=DockerSandbox(AutoApprove("calibration replay")), env_id=f"harbor/{task}"
    )


def prefixes(trace: list[dict]) -> list[dict]:
    """Rebuild the (actions-so-far, claim) sequence the loop produced.

    Mirrors `PromptedChallenger.attack`: a malformed reply produces no attempt,
    `reset_environment` discards everything before it, and only a real action
    extends the prefix. Getting this wrong would silently misalign every claim
    with the wrong workspace.
    """
    out, actions = [], []
    for turn in trace:
        action = turn.get("action") or {}
        if "malformed" in action or "unavailable" in action:
            continue
        tool = action.get("tool")
        if tool is None:
            continue
        if tool == RESET_TOOL:
            actions = []
            continue
        actions.append(Action(tool, dict(action.get("args") or {})))
        out.append(
            {
                "turn": turn["turn"],
                "actions": list(actions),
                # Read as a probability. Traces recorded before the attacker
                # emitted one carry a bool, and those map to the endpoints --
                # which is exactly why this file used to report an ECE over two
                # distinct forecast values.
                "claim": _confidence(turn.get("solves_the_task")),
                "reported_at_the_time": turn.get("reported"),
            }
        )
    return out


def score(task: str, trace: list[dict]) -> list[dict]:
    rows = []
    steps = prefixes(trace)
    if not steps:
        return rows
    with build(task) as adapter:
        task_id = adapter.manifest().tasks[0].task_id
        for step in steps:
            transcript = Transcript(task_id=task_id, seed=0, actions=list(step["actions"]))
            gap, reported, true = exploit_gap(adapter, transcript)
            rows.append(
                {
                    "turn": step["turn"],
                    "n_actions": len(step["actions"]),
                    "claim_solves_the_task": step["claim"],
                    "true_completion": true,
                    "reported_score": reported,
                    "exploit_gap": round(gap, 4),
                    "reported_at_the_time": step["reported_at_the_time"],
                    "reported_matches_replay": (
                        None
                        if step["reported_at_the_time"] is None
                        else abs(step["reported_at_the_time"] - reported) < 1e-9
                    ),
                }
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="*", default=SOURCES)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--out", default="results/calibration.json")
    args = ap.parse_args()

    per_arm: dict[str, dict] = {}
    all_pairs: list[Pair] = []
    skipped: list[dict] = []

    for source in args.sources:
        path = Path(source)
        if not path.exists():
            skipped.append({"source": source, "reason": "file not present"})
            continue
        body = json.loads(path.read_text())
        task = body.get("task", "self-graded")
        for arm in body.get("arms", []):
            trace = arm.get("attacker_trace") or []
            name = f"{path.stem}::{arm['challenger']}"
            if not trace:
                skipped.append(
                    {"source": name, "reason": "no attacker trace recorded"}
                )
                continue
            if not any("solves_the_task" in t for t in trace):
                # The scripted Challenger is a fixed repertoire with no model in
                # the loop. It states no belief about whether it solved anything,
                # so it has no calibration -- which is different from being
                # perfectly calibrated, and must not be pooled in as if it were.
                skipped.append(
                    {
                        "source": name,
                        "reason": (
                            "the trace carries no `solves_the_task` field: this "
                            "challenger emits no self-report, so there is no "
                            "forecast to score. Not the same as being well "
                            "calibrated, and deliberately not pooled in."
                        ),
                    }
                )
                continue
            print(f"replaying {name} ({len(trace)} turns) ...", flush=True)
            rows = score(task, trace)
            if not rows:
                skipped.append(
                    {
                        "source": name,
                        "reason": (
                            "every turn in the trace was malformed, a reset, or "
                            "otherwise produced no replayable action prefix"
                        ),
                    }
                )
                continue
            pairs = [
                Pair(
                    label=f"{name}#turn{r['turn']}",
                    forecast=_confidence(r["claim_solves_the_task"]),
                    outcome=float(r["true_completion"]),
                )
                for r in rows
            ]
            all_pairs.extend(pairs)
            per_arm[name] = {
                "task": f"harbor/{task}",
                "n_turns_in_trace": len(trace),
                "n_scored": len(rows),
                "turns": rows,
                "calibration": report(pairs, args.bins, args.threshold),
                "replay_fidelity": {
                    "turns_where_replay_reproduced_the_recorded_score": sum(
                        1 for r in rows if r["reported_matches_replay"]
                    ),
                    "of": sum(1 for r in rows if r["reported_matches_replay"] is not None),
                    "why_this_matters": (
                        "the outcome half of every pair comes from a replay, so if "
                        "the replay does not reproduce the score the run recorded, "
                        "it is scoring a different workspace and the pairs are not "
                        "about the run they claim to be about"
                    ),
                },
            }

    if not all_pairs:
        print(
            "FAILED: no (claim, outcome) pairs could be built. Needs Docker and at "
            "least one recorded attacker trace.",
            file=sys.stderr,
        )
        return 1

    body = {
        "spec": "criteria.md -- Calibration: mean Brier (not sum), ECE, reliability "
                "diagram, Brier decomposition; plus a false-success rate",
        "forecast": (
            "the attacker's own `solves_the_task` probability, per turn. It was a "
            "boolean until the calibration file itself reported that two distinct "
            "forecast values cannot support a reliability diagram; traces recorded "
            "before that carry bools and are read at the endpoints, so a mixed "
            "corpus is scored honestly rather than silently rebinned."
        ),
        "outcome": (
            "adapter.true_completion of the replayed action prefix -- a deterministic "
            "verifier the attacker never had access to"
        ),
        "no_model_scored_anything": (
            "the traces are on disk and the replay is a program; no model was called "
            "to produce any number in this file"
        ),
        "assay_revision": git_revision(),
        "pooled": report(all_pairs, args.bins, args.threshold),
        "per_arm": per_arm,
        "skipped": skipped,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2))

    pooled = body["pooled"]
    print(f"\npooled over {pooled['n_pairs']} (claim, outcome) pairs")
    print(f"  mean Brier            : {pooled['mean_brier']:.4f}")
    print(f"  (summed, not to use)  : {pooled['summed_brier_do_not_use']:.4f}")
    print(f"  ECE                   : {pooled['ece']:.4f}")
    d = pooled["brier_decomposition"]
    print(f"  reliability           : {d['reliability']:.4f}")
    print(f"  resolution            : {d['resolution']:.4f}")
    print(f"  uncertainty           : {d['uncertainty']:.4f}")
    print(f"  identity holds        : {pooled['decomposition_identity_holds']}")
    r = pooled["outcome_rates"]
    fs = r["false_success_rate"]
    ff = r["false_failure_rate"]
    print(f"  false-success rate    : {fs if fs is None else f'{fs:.4f}'} "
          f"({r['false_success_count']} of {r['n_claimed_solved']} claimed solved)")
    print(f"  false-failure rate    : {ff if ff is None else f'{ff:.4f}'} "
          f"({r['false_failure_count']} of {r['n_claimed_not_solved']} claimed not solved)")
    if "instrument_limit" in pooled:
        print(f"  LIMIT: {pooled['instrument_limit']}")
    print("\nper arm:")
    for name, blk in per_arm.items():
        c = blk["calibration"]
        rr = c["outcome_rates"]
        print(f"  {name:56} n={c['n_pairs']:3} brier={c['mean_brier']:.4f} "
              f"ece={c['ece']:.4f} false_succ={rr['false_success_count']}/"
              f"{rr['n_claimed_solved']} false_fail={rr['false_failure_count']}/"
              f"{rr['n_claimed_not_solved']}")
        f = blk["replay_fidelity"]
        print(f"    replay reproduced the recorded score on "
              f"{f['turns_where_replay_reproduced_the_recorded_score']} of {f['of']} turns")
    for s in skipped:
        print(f"  SKIPPED {s['source']}: {s['reason']}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
