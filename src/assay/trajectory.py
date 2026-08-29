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
        body["signature"] = digest(body)
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
                lines += ["", f"Tool responded: `{text[:300]}`"]
            if turn.reported_score is not None:
                lines.append(f"\nEnvironment scored it: **{turn.reported_score}**")
            lines.append("")
        if self.approvals:
            lines += ["## Human checkpoints", ""]
            for approval in self.approvals:
                lines.append(f"- {approval.get('what', 'approval')} — {approval.get('detail', '')}")
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
    turns = [
        Turn(
            index=row.get("turn", i + 1),
            action=row.get("action"),
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
