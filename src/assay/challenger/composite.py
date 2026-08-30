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

That guarantee held for the success path and not for the failure path, and the
failure path is where it mattered. `PromptedChallenger` raises `LLMUnavailable`
when it cannot produce a single attempt; this class had no handler, so the
exception unwound past every attempt the scripted member had *already made*.
`RewardHackability` caught it, recorded `n_attempts: 0`, and returned
NOT_APPLICABLE -- so four scripted policies with `gap=1.0` on
`harbor/vacuous-tests` became "the Challenger could not act", and the same
environment this module was written to stop losing was lost again through a
different door. Measured 4 times out of 4 before it was found.

A member that cannot speak is now recorded and stepped over. The composite only
re-raises when *no* member produced anything, which is the one case where
"could not act" is the truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..adapter import EnvAdapter
from ..llm import LLMUnavailable
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
        unavailable: list[str] = []
        for member in self.members:
            try:
                produced = member.attack(adapter, task_id)
            except LLMUnavailable as exc:
                # One member's backend being unreachable must not delete
                # another member's findings. Recorded, not swallowed: the
                # reason travels into the last attempt's log so the card can
                # say the composite ran short.
                unavailable.append(f"{member.name}: {exc}")
                continue
            for attempt in produced:
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
        if unavailable:
            if not attempts:
                # Nothing ran at all. "Could not act" is now the honest report,
                # and the probe turns this into NOT_APPLICABLE with the reason.
                raise LLMUnavailable("; ".join(unavailable))
            attempts[-1].log.append(
                {
                    "composite": "a member could not act; its attempts are absent "
                    "from this run and the others are not",
                    "unavailable": unavailable,
                }
            )
        return attempts
