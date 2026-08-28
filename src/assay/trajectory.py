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
