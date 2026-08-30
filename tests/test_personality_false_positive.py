"""Assay reports a CRITICAL defect on a correctly-designed eval.

`inspect_evals/personality_BFI` is the Big Five Inventory. Its scorer,
`any_choice()`, checks `letter in target.text` and says in its own docstring
that it "checks for response format rather than factual correctness" -- correct
design, because a personality inventory has no right answer. The trait score
comes from `answer_mapping` metadata, not from the scorer.

Assay's verifier-integrity family assumes a verifier separates correct from
incorrect. On this eval that assumption is false, and the battery returns
verdict INVALID with `INVERT_PASSES`, the class reserved for "the verifier
cannot fail".

This test pins the *upstream* half of that claim, with Assay out of the loop:
the scorer really does accept any well-formed letter regardless of target, so
the finding is mechanically true and semantically wrong. If upstream ever
tightens the scorer, this fails and the coverage document needs revisiting.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals", reason="the sweep dependency group is not installed")

from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

personality = importlib.import_module("inspect_evals.personality.personality")


def _score(completion: str, target: str) -> str:
    state = TaskState(
        model="assay/probe",
        sample_id="p1",
        epoch=1,
        input="I see myself as someone who is talkative.",
        messages=[],
        output=ModelOutput.from_content(model="assay/probe", content=completion),
    )
    return asyncio.run(personality.any_choice()(state, Target(target))).value


def test_the_scorer_declares_it_checks_format_not_correctness():
    """The design is stated upstream; this is not an undocumented flaw."""
    doc = personality.any_choice.__doc__ or ""
    assert "format rather than factual correctness" in doc


@pytest.mark.parametrize("letter", ["A", "B", "C", "D", "E"])
def test_every_offered_letter_is_accepted(letter):
    """No answer is wrong, which is correct for an inventory."""
    assert _score(f"ANSWER: {letter}", "ABCDE") == CORRECT


def test_appending_to_the_target_does_not_invalidate_gold():
    """Why `inverted_fails` fires: substring matching survives negation.

    `invert_spec` builds a target the gold answer must NOT satisfy by appending
    a suffix. Under a substring test the original letters are all still there.
    """
    assert _score("ANSWER: A", "ABCDE_definitely_not_this") == CORRECT


def test_a_malformed_answer_is_still_rejected():
    """The scorer is not vacuous -- it does the job it claims."""
    for bad in ("I refuse", "ANSWER: ", "ANSWER: Z"):
        assert _score(bad, "ABCDE") == INCORRECT


def test_personality_is_not_in_the_scored_corpus():
    """An environment the tool is wrong about must not measure the tool."""
    from assay.corpus import scored_ground_truth

    assert not [e for e in scored_ground_truth() if "personality" in e]
