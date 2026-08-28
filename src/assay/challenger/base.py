"""What a Challenger is.

A Challenger proposes policies that might score well without doing the job. It
never sees ground truth -- `true_completion` is held by the probe, not passed
to the attacker. That separation is the whole reason the exploit gap means
anything: an attacker told the answer is not finding an exploit, it is being
handed one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..adapter import EnvAdapter, run_policy
from ..types import Action, Transcript


@dataclass
class Attempt:
    label: str
    transcript: Transcript
    #: What the attacker saw and did, for the trajectory export.
    log: list[dict[str, Any]] = field(default_factory=list)


class Challenger(Protocol):
    name: str

    def attack(self, adapter: EnvAdapter, task_id: str) -> list[Attempt]: ...


def action_template(adapter: EnvAdapter, task_id: str) -> tuple[str, list[str]] | None:
    """Infer the action vocabulary from the policies the adapter already
    defines, so a Challenger works on any ecosystem without a bespoke schema."""
    try:
        policies = adapter.trivial_policies(task_id)
    except Exception:  # noqa: BLE001
        return None
    for actions in policies.values():
        if actions:
            first = actions[0]
            return first.tool, sorted(first.args.keys())
    return None
