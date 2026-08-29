"""Run several Challengers and keep every attempt.

A better attacker is not a superset of a worse one. Pointing the prompted
Challenger at `harbor/vacuous-tests` -- a verifier that exits 0 unconditionally
-- LOST a defect the scripted repertoire had been catching, because the model
never happened to try submitting nothing at all. It wrote a plausible answer,
was told 1.0, and moved on.

So Challengers compose rather than replace. The cheap fixed repertoire runs
first and costs nothing; the model runs after and looks for what a fixed list
cannot anticipate. The probe scores every attempt from both and takes the best
gap, which is the only combination rule that cannot lose coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..adapter import EnvAdapter
from .base import Attempt, Challenger


@dataclass
class CompositeChallenger:
    members: list[Challenger]
    name: str = field(default="", init=False)

    def __post_init__(self) -> None:
        if not self.members:
            raise ValueError("a composite Challenger needs at least one member")
        self.name = "+".join(m.name for m in self.members)

    def attack(self, adapter: EnvAdapter, task_id: str) -> list[Attempt]:
        attempts: list[Attempt] = []
        for member in self.members:
            for attempt in member.attack(adapter, task_id):
                # Namespace the labels so a finding names the attacker that
                # produced it. "which challenger found this" is the whole point
                # of running more than one.
                attempts.append(
                    Attempt(
                        label=f"{member.name}/{attempt.label}",
                        transcript=attempt.transcript,
                        log=attempt.log,
                    )
                )
        return attempts
