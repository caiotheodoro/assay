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


class ChallengerExhausted(RuntimeError):
    """The attacker ran and produced nothing usable.

    Sibling of `LLMUnavailable`, and deliberately not the same thing. That one
    means the backend never spoke; this one means it spoke and every word was
    unusable -- eight replies that were not JSON, eight that were the same
    policy, a vocabulary with no actions in it. Both are "no attempt was
    scored", and neither is "no exploit exists", which is what an empty list
    silently claimed.

    `history` carries what was thrown away. Every exhaustion route used to
    discard the attacker's transcript on the way out, so the card recorded a
    reason with nothing behind it and there was no way to tell an attacker that
    emitted prose from one that emitted the same policy eight times.
    """

    def __init__(self, reason: str, history: list[dict[str, Any]] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.history: list[dict[str, Any]] = list(history or [])


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
    return vocabulary_or_reason(adapter, task_id)[0]


def vocabulary_or_reason(
    adapter: EnvAdapter, task_id: str
) -> tuple[list[tuple[str, list[str]]], str]:
    """The vocabulary, and -- when it is empty -- why.

    `action_vocabulary` returns `[]` for "this adapter names no actions" and
    for "asking it raised", and a challenger that gets `[]` used to return `[]`
    in turn, which the probe scored as a clean PASS with no attempts. The
    reason existed at the point the exception was caught and was dropped one
    frame later. Callers that must not fail silently take this pair instead;
    the five that only want a prompt keep the simple signature.
    """
    try:
        policies = adapter.trivial_policies(task_id)
    except Exception as exc:  # noqa: BLE001 - absence is not a failure, but it is a reason
        return [], f"asking {type(adapter).__name__} for trivial policies raised: {exc}"
    seen: dict[str, set[str]] = {}
    for actions in policies.values():
        for action in actions:
            seen.setdefault(action.tool, set()).update(action.args.keys())
    vocabulary = sorted(
        ((tool, sorted(args)) for tool, args in seen.items()),
        key=lambda pair: (-len(pair[1]), pair[0]),
    )
    if vocabulary:
        return vocabulary, ""
    return [], (
        "the adapter defines no trivial policies, so there is no action "
        "vocabulary to hand an attacker; a challenger cannot propose actions "
        "it has no way to name"
    )


def action_template(adapter: EnvAdapter, task_id: str) -> tuple[str, list[str]] | None:
    vocabulary = action_vocabulary(adapter, task_id)
    return vocabulary[0] if vocabulary else None
