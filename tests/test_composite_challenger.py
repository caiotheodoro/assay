"""A member that cannot speak must not delete another member's findings.

`CompositeChallenger` exists because the prompted Challenger, run alone, lost
`harbor/vacuous-tests` -- a defect the fixed repertoire catches for free. Its
docstring promised the combination "cannot lose coverage". It could: the
promise covered the success path, and `PromptedChallenger` raises
`LLMUnavailable` when it produces no attempt at all. With no handler here, that
exception unwound past every scripted attempt already made, the probe recorded
`n_attempts: 0`, and the same environment was lost again.
"""

from __future__ import annotations

import pytest

from assay.adapter import run_policy
from assay.challenger import CompositeChallenger, ScriptedChallenger
from assay.challenger.base import Attempt
from assay.fixtures import build
from assay.llm import LLMUnavailable
from assay.types import Action


class _Mute:
    """A member whose backend is unreachable before it manages anything."""

    name = "mute"

    def attack(self, adapter, task_id):
        raise LLMUnavailable("backend unreachable")


class _Works:
    name = "works"

    def attack(self, adapter, task_id):
        t = run_policy(adapter, task_id, [Action("submit", {"answer": "x"})])
        return [Attempt(label="one", transcript=t)]


def _adapter():
    return build("weak_oracle")


def test_a_mute_member_does_not_discard_a_working_member():
    adapter = _adapter()
    task = adapter.manifest().tasks[0].task_id

    scripted_only = ScriptedChallenger().attack(adapter, task)
    assert scripted_only, "fixture must give the scripted repertoire something to do"

    composed = CompositeChallenger([ScriptedChallenger(), _Mute()]).attack(adapter, task)
    assert len(composed) == len(scripted_only), (
        "the mute member deleted the scripted member's attempts, which is the "
        "regression this composite was written to prevent"
    )


def test_the_unavailability_is_recorded_not_swallowed():
    adapter = _adapter()
    task = adapter.manifest().tasks[0].task_id
    composed = CompositeChallenger([ScriptedChallenger(), _Mute()]).attack(adapter, task)
    note = composed[-1].log[-1]
    assert "unavailable" in note, "a short run must say so in the record"
    assert any("mute" in u for u in note["unavailable"])


def test_every_member_mute_still_raises():
    """When nothing ran, 'could not act' is the truth and must reach the probe."""
    adapter = _adapter()
    task = adapter.manifest().tasks[0].task_id
    with pytest.raises(LLMUnavailable):
        CompositeChallenger([_Mute(), _Mute()]).attack(adapter, task)


def test_order_is_preserved_and_labels_name_the_member():
    adapter = _adapter()
    task = adapter.manifest().tasks[0].task_id
    composed = CompositeChallenger([_Works(), _Mute(), _Works()]).attack(adapter, task)
    assert [a.label for a in composed] == ["works/one", "works/one"]
