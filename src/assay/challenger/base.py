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


def action_vocabulary(adapter: EnvAdapter, task_id: str) -> list[tuple[str, list[str]]]:
    """Infer the action vocabulary from policies the adapter already defines,
    so a Challenger works on any ecosystem without a bespoke schema.

    Ordered richest-first, by argument count. A no-argument tool is usually the
    least useful thing to hand an attacker as its example -- an environment
    whose first trivial policy is `noop` would otherwise teach the attacker
    that doing nothing is the whole vocabulary.
    """
    try:
        policies = adapter.trivial_policies(task_id)
    except Exception:  # noqa: BLE001 - absence is not a failure
        return []
    seen: dict[str, set[str]] = {}
    for actions in policies.values():
        for action in actions:
            seen.setdefault(action.tool, set()).update(action.args.keys())
    return sorted(
        ((tool, sorted(args)) for tool, args in seen.items()),
        key=lambda pair: (-len(pair[1]), pair[0]),
    )


def action_template(adapter: EnvAdapter, task_id: str) -> tuple[str, list[str]] | None:
    vocabulary = action_vocabulary(adapter, task_id)
    return vocabulary[0] if vocabulary else None
