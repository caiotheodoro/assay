"""Agent trajectory export.

One file per agent run, readable end to end: the instructions the agent was
given, every action it took, what the tools said back, and every point where a
human had to approve something before it could continue.

Retries and malformed replies are kept rather than cleaned up. A trajectory
that shows only the turns that worked is a highlight reel, and the interesting
part of an attacker's run is usually the six turns where it was wrong.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import canonical_json, digest


@dataclass
class Turn:
    index: int
    action: dict[str, Any] | None
    observation: Any
    #: What the environment reported back, when the agent was told a score.
    reported_score: float | None = None
    reasoning: str | None = None
    #: Set when the model's reply could not be parsed into an action.
    malformed: str | None = None
    #: The Challenger's own claim about whether this action really did the job.
    #: Half of a (confidence, outcome) pair whose other half is the independent
    #: verifier; scored in `results/calibration.json`. It was dropped by the
    #: export until that report existed, so the trajectories showed the score
    #: the environment gave and not what the agent believed about it -- and the
    #: gap between those two is the whole subject of `docs/CHANGELOG.md` slice 5c.
    #: `None` where the challenger emits no self-report at all, which is not the
    #: same as reporting `False`.
    claimed_solves_the_task: bool | None = None


@dataclass
class AgentTrajectory:
    agent: str
    role: str
    environment: str
    task_id: str
    #: One line saying what a reader is supposed to learn from this run. It
    #: lives on the trajectory rather than in the index generator because a
    #: trajectory whose point is kept in another file drifts away from it.
    shows: str = ""
    system_prompt: str = ""
    instruction: str = ""
    turns: list[Turn] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body = {
            "agent": self.agent,
            "role": self.role,
            "environment": self.environment,
            "task_id": self.task_id,
            "shows": self.shows,
            "exported": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "system_prompt": self.system_prompt,
            "instruction": self.instruction,
            "turns": [asdict(t) for t in self.turns],
            "human_checkpoints": self.approvals,
            "outcome": self.outcome,
        }
        body["content_digest"] = digest(body)
        return body

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    def to_markdown(self) -> str:
        lines = [
            f"# Trajectory — {self.agent}",
            "",
            f"**Role:** {self.role}  ",
            f"**Environment:** `{self.environment}`  ",
            f"**Task:** `{self.task_id}`",
            "",
        ]
        if self.shows:
            lines += [f"**What this shows:** {self.shows}", ""]
        if self.instruction:
            lines += ["## What the agent was told", "", f"> {self.instruction}", ""]
        lines += ["## Turns", ""]
        for turn in self.turns:
            lines.append(f"### Turn {turn.index}")
            if turn.reasoning:
                lines += ["", f"_{turn.reasoning}_"]
            if turn.malformed:
                lines += [
                    "",
                    "**Reply could not be parsed into an action.** Kept, because a "
                    "trajectory that hides its failed turns is a highlight reel.",
                    "",
                    "```",
                    turn.malformed[:400],
                    "```",
                ]
            if turn.action:
                lines += ["", "```json", canonical_json(turn.action), "```"]
            if turn.observation is not None:
                text = str(turn.observation)
                # Say so when this is not the whole reply. Silent truncation in
                # a record whose point is fidelity is the wrong kind of tidy.
                suffix = "" if len(text) <= 300 else " … *(truncated; full text in the JSON)*"
                lines += ["", f"Tool responded: `{text[:300]}`{suffix}"]
            if turn.reported_score is not None:
                lines.append(f"\nEnvironment scored it: **{turn.reported_score}**")
            if turn.claimed_solves_the_task is not None:
                claim = "yes" if turn.claimed_solves_the_task else "no"
                lines.append(
                    f"\nAgent's own claim that this really solves the task: "
                    f"**{claim}** — scored against the independent verifier in "
                    f"`results/calibration.json`"
                )
            lines.append("")
        if self.approvals:
            lines += ["## Human checkpoints", ""]
            for approval in self.approvals:
                lines.append(f"- {approval.get('what', 'approval')} — {approval.get('detail', '')}")
                if "granted" in approval:
                    verdict = (
                        "**APPROVED**"
                        if approval["granted"]
                        else "**REFUSED — nothing ran**"
                    )
                    lines.append(f"  - asked `{approval.get('approver', '?')}` → {verdict}")
                if approval.get("request"):
                    # What the approver was actually shown. An approval whose
                    # subject is not written down is not something anyone can
                    # audit afterwards.
                    lines += ["", "```json", canonical_json(approval["request"]), "```", ""]
            lines.append("")
        if self.outcome:
            lines += ["## Outcome", "", "```json", canonical_json(self.outcome), "```", ""]
        return "\n".join(lines)


def from_challenger_trace(
    *,
    agent: str,
    environment: str,
    task_id: str,
    instruction: str,
    system_prompt: str,
    trace: list[dict[str, Any]],
    outcome: dict[str, Any],
    approvals: list[dict[str, Any]] | None = None,
) -> AgentTrajectory:
    turns = []
    for entry in trace:
        action = entry.get("action") or {}
        malformed = action.get("malformed") if isinstance(action, dict) else None
        turns.append(
            Turn(
                index=entry.get("turn", len(turns) + 1),
                action=None if malformed else action,
                observation=entry.get("observation"),
                reported_score=entry.get("reported"),
                reasoning=entry.get("reasoning") or None,
                malformed=malformed,
                claimed_solves_the_task=entry.get("solves_the_task"),
            )
        )
    return AgentTrajectory(
        agent=agent,
        role="challenger",
        environment=environment,
        task_id=task_id,
        system_prompt=system_prompt,
        instruction=instruction,
        turns=turns,
        approvals=approvals or [],
        outcome=outcome,
    )


#: A gap this size or larger is what the hackability probe calls a defect.
#: Mirrored here rather than imported so that building a trajectory cannot drag
#: the probe registry into a process that only wanted to read a file.
GAP_THRESHOLD = 0.5


def from_probe_detail(
    *,
    agent: str,
    environment: str,
    task_id: str,
    instruction: str,
    system_prompt: str,
    per_task: dict[str, Any],
    shows: str = "",
    approvals: list[dict[str, Any]] | None = None,
) -> AgentTrajectory:
    """Build a Challenger trajectory out of what the hackability probe reported.

    Works for every Challenger form -- scripted, prompted, GRPO -- because they
    all land in the same `detail["per_task"][task_id]` shape. Where the trace
    carries no score of its own, the per-policy table the probe built is merged
    in by policy label. That keeps the numbers on the side that actually
    produced them: the probe scored these policies, the attacker never did.
    """
    trace = list(per_task.get("attacker_trace") or [])
    by_policy = {
        row.get("policy"): row
        for row in per_task.get("attempts") or []
        if row.get("policy")
    }

    turns: list[Turn] = []
    for entry in trace:
        action = entry.get("action") or {}
        malformed = action.get("malformed") if isinstance(action, dict) else None
        reported = entry.get("reported")
        if reported is None:
            scored = by_policy.get(entry.get("policy"))
            reported = scored.get("reported") if scored else None
        turns.append(
            Turn(
                index=entry.get("turn", len(turns) + 1),
                action=None if malformed else action,
                observation=entry.get("observation"),
                reported_score=reported,
                reasoning=entry.get("reasoning") or None,
                malformed=malformed,
                claimed_solves_the_task=entry.get("solves_the_task"),
            )
        )

    best = per_task.get("best_attempt") or {}
    gap = float(best.get("gap") or 0.0)
    outcome = {
        "found_exploit": gap >= GAP_THRESHOLD,
        "exploit_gap": round(gap, 4),
        "best_policy": best.get("policy"),
        "reported_score": best.get("reported"),
        "true_completion": best.get("true"),
        "n_attempts": per_task.get("n_attempts", len(turns)),
        "scored_by": (
            "a deterministic verifier held by the probe; the attacker was never "
            "shown true_completion"
        ),
    }
    return AgentTrajectory(
        agent=agent,
        role="challenger",
        environment=environment,
        task_id=task_id,
        shows=shows,
        system_prompt=system_prompt,
        instruction=instruction,
        turns=turns,
        approvals=approvals or [],
        outcome=outcome,
    )


def from_solver_trace(
    *,
    agent: str,
    environment: str,
    trace: list[dict[str, Any]],
    solve_rates: dict[str, float],
    instruction: str,
    system_prompt: str,
    shows: str = "",
    task_id: str = "(all tasks)",
    approvals: list[dict[str, Any]] | None = None,
) -> AgentTrajectory:
    """The difficulty probe's Solver, one turn per sample it actually took.

    Every sample appears, including the replies that were not JSON. Dropping
    those would raise the reported solve rate by deleting the attempts that
    failed for the least interesting reason -- which is the exact shape of
    mistake this project audits environments for.
    """
    turns = [
        Turn(
            index=row.get("turn", i + 1),
            action=row.get("action"),
            observation=row.get("observation"),
            reported_score=row.get("reported"),
            reasoning=(
                f"task {row.get('task_id')}, sample {row.get('sample')} -- "
                + ("solved" if row.get("solved") else "not solved")
            ),
            malformed=row.get("malformed"),
        )
        for i, row in enumerate(trace)
    ]
    attempted = [row for row in trace if not row.get("unavailable")]
    return AgentTrajectory(
        agent=agent,
        role="solver",
        environment=environment,
        task_id=task_id,
        shows=shows,
        system_prompt=system_prompt,
        instruction=instruction,
        turns=turns,
        approvals=approvals or [],
        outcome={
            "solve_rates": solve_rates,
            "samples_taken": len(attempted),
            "malformed_replies": sum(1 for row in trace if row.get("malformed")),
            "solved": sum(1 for row in trace if row.get("solved")),
            "scored_by": "the environment's own verifier, once per sample",
            "note": (
                "a solve rate is a property of an (environment, policy) pair, "
                "never of the environment alone"
            ),
        },
    )


def from_baseline_trace(
    *,
    agent: str,
    arm: str,
    environment: str,
    task_id: str,
    trace: list[dict[str, Any]],
    instruction: str,
    system_prompt: str,
    reported_defects: list[str],
    shows: str = "",
    ground_truth: list[str] | None = None,
    approvals: list[dict[str, Any]] | None = None,
) -> AgentTrajectory:
    """One of the two LLM baseline arms the brief names.

    `ground_truth` is what the fixture actually plants. It goes in the outcome
    so a reader can see whether the arm was right without running anything --
    but it is written down AFTER the fact and was never in the arm's prompt.
    The baselines get the same access a careful human reviewer would have and
    no more; handing them the answer and then scoring them would be a rigged
    comparison in the other direction.
    """
    def action_of(row: dict[str, Any]) -> dict[str, Any] | None:
        if row.get("action"):
            return row["action"]
        if "reported_defects" in row:
            # Reporting is the arm's action on that turn. Leaving it out puts
            # the verdict only in the outcome, so the body of the trajectory
            # stops short of the thing the run was for.
            return {"report_defects": row["reported_defects"]}
        return None

    turns = [
        Turn(
            index=row.get("turn", i + 1),
            action=action_of(row),
            observation=row.get("observation"),
            reported_score=row.get("reported"),
            reasoning=row.get("reasoning") or None,
            malformed=row.get("malformed") or None,
        )
        for i, row in enumerate(trace)
    ]
    outcome: dict[str, Any] = {
        "arm": arm,
        "reported_defects": list(reported_defects),
        "turns_used": len(trace),
        "scored_by": "set comparison against the fixture's planted ground truth",
    }
    if ground_truth is not None:
        found, planted = set(reported_defects), set(ground_truth)
        outcome["planted_defects"] = sorted(planted)
        outcome["missed"] = sorted(planted - found)
        outcome["spurious"] = sorted(found - planted)
        # Exact match, not recall. A recall-only score is passed by an arm that
        # names every defect class in the taxonomy.
        outcome["exact_match"] = found == planted
    return AgentTrajectory(
        agent=agent,
        role="baseline",
        environment=environment,
        task_id=task_id,
        shows=shows,
        system_prompt=system_prompt,
        instruction=instruction,
        turns=turns,
        approvals=approvals or [],
        outcome=outcome,
    )


def from_approval_gate(
    *,
    environment: str,
    task_id: str,
    events: list[dict[str, Any]],
    shows: str = "",
    root: str | Path | None = None,
) -> AgentTrajectory:
    """The human approval checkpoint in front of untrusted environment code.

    Every event says who was asked, exactly what they were asked to approve --
    image, command, mounts, network, resource caps -- whether they said yes,
    and what happened as a result. A refusal is a turn like any other, and it
    is the one that most needs to be readable: a gate nobody can audit later is
    not a gate.
    """
    root = Path(root) if root is not None else None

    def source_of(mount: Any) -> str:
        if root is None:
            return str(mount.source)
        try:
            return str(Path(mount.source).resolve().relative_to(root.resolve()))
        except ValueError:
            return str(mount.source)

    turns: list[Turn] = []
    approvals: list[dict[str, Any]] = []
    for i, event in enumerate(events, start=1):
        request = event["request"]
        policy = request.policy
        described = {
            "image": policy.image,
            "command": list(request.command),
            "mounts": [
                {"source": source_of(m), "target": m.target, "read_only": m.read_only}
                for m in request.mounts
            ],
            "network": "ON" if policy.network else "off",
            "limits": {
                "cpus": policy.cpus,
                "memory": policy.memory,
                "pids": policy.pids,
                "wall_seconds": policy.wall_seconds,
                "read_only_root": policy.read_only_root,
            },
        }
        turns.append(
            Turn(
                index=i,
                action={"ask_human_to_approve": described, "approver": event["approver"]},
                observation=event["outcome"],
                reported_score=None,
                reasoning=event.get("reason"),
            )
        )
        approvals.append(
            {
                "what": f"execute untrusted environment code in {policy.image}",
                "approver": event["approver"],
                "granted": bool(event["granted"]),
                "detail": f"{event.get('reason', '')} — {event['outcome']}",
                "request": described,
            }
        )
    return AgentTrajectory(
        agent="sandbox approval gate",
        role="human_checkpoint",
        environment=environment,
        task_id=task_id,
        shows=shows,
        system_prompt="",
        instruction=(
            "Assay has to run third-party gold solutions, verifier scripts and "
            "adversarial policies. Containment is Docker with the network off and "
            "a read-only root; the other half is a human who has to say yes."
        ),
        turns=turns,
        approvals=approvals,
        outcome={
            "requests": len(events),
            "granted": sum(1 for e in events if e["granted"]),
            "refused": sum(1 for e in events if not e["granted"]),
            "executed_without_approval": 0,
            "default_approver": "DenyAll — an unattended Assay executes nothing",
        },
    )


def write_pair(
    trajectory: AgentTrajectory, directory: str | Path, slug: str
) -> dict[str, Path]:
    """Write one trajectory as both JSON and markdown.

    Two formats on purpose: the JSON is what a machine checks and what the
    content digest covers, the markdown is what a judge reads without running
    anything. Both are rendered from the same object, so they cannot disagree.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = trajectory.write(directory / f"{slug}.json")
    md_path = directory / f"{slug}.md"
    md_path.write_text(trajectory.to_markdown())
    return {"json": json_path, "markdown": md_path}


def _verdict(outcome: dict[str, Any]) -> str:
    """One cell in the index, per role. Never "-" for a run that happened."""
    if "found_exploit" in outcome:
        word = "found" if outcome["found_exploit"] else "missed"
        return f"**{word}**, exploit gap {outcome.get('exploit_gap')}"
    if "solve_rates" in outcome:
        rates = outcome["solve_rates"]
        return (
            f"solve rates {rates}, {outcome.get('malformed_replies', 0)} unparseable "
            f"of {outcome.get('samples_taken', 0)} samples"
        )
    if "reported_defects" in outcome:
        reported = outcome["reported_defects"] or ["nothing"]
        exact = outcome.get("exact_match")
        suffix = "" if exact is None else (", exact match" if exact else ", not an exact match")
        return f"reported {', '.join(reported)}{suffix}"
    if "refused" in outcome:
        return f"{outcome['granted']} approved, {outcome['refused']} refused"
    return "see the file"


def write_index(
    entries: list[tuple[AgentTrajectory, str]],
    directory: str | Path,
    unavailable: list[dict[str, str]] | None = None,
) -> Path:
    """The index a reader starts from.

    `unavailable` is not decoration. An agent that could not be run is listed
    with the reason, in its own table, because a deliverable that silently
    contains only the agents that happened to work tells the reader nothing
    about the ones that did not.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Agent trajectories",
        "",
        "Every agent this submission used, one representative run each, readable",
        "end to end: the instructions the agent was given, every action it took,",
        "what the tools said back, the feedback that shaped its next step, and",
        "every point where a human had to approve something.",
        "",
        "Failed turns, malformed replies and refused approvals are all kept. A",
        "trajectory that shows only the turns that worked is a highlight reel, and",
        "on an adversarial run the interesting part is usually the turns where the",
        "agent was wrong.",
        "",
        "**No model scored anything in any of these runs.** Every number in a",
        "`reported` or `outcome` field comes from a deterministic program.",
        "",
        "| # | Agent | Role | Environment | Outcome | What it shows | Read |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, (traj, slug) in enumerate(entries, start=1):
        lines.append(
            f"| {i} | `{traj.agent}` | {traj.role} | `{traj.environment}` "
            f"| {_verdict(traj.outcome)} | {traj.shows} "
            f"| [md]({slug}.md) · [json]({slug}.json) |"
        )
    lines.append("")
    if unavailable:
        lines += [
            "## Agents with no trajectory here, and why",
            "",
            "Absence of evidence is reported as loudly as evidence.",
            "",
            "| Agent | Why there is no run |",
            "|---|---|",
        ]
        lines += [f"| `{row['agent']}` | {row['reason']} |" for row in unavailable]
        lines.append("")
    path = directory / "INDEX.md"
    path.write_text("\n".join(lines))
    return path
