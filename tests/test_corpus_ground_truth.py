"""Independent verification of the corpus ground truth.

Correcting a label because the tool disagreed with it is circular. These tests
establish each planted defect directly from the scorer's own behaviour --
calling inspect_ai's scorer, not Assay -- so the label stands on its own and
Assay can be scored against it honestly.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from assay.adapters.inspect_ai_adapter import _reward  # noqa: E402


def _run(scorer_fn, answer: str, target: str):
    state = TaskState(
        model="assay/probe",
        sample_id="q1",
        epoch=1,
        input="What is the capital of France?",
        messages=[],
        output=ModelOutput.from_content(model="assay/probe", content=answer),
    )
    return asyncio.run(scorer_fn(state, Target(target)))


@scorer(metrics=[accuracy()])
def constant_partial():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=0.5, answer=state.output.completion)

    return score


@scorer(metrics=[accuracy()])
def any_nonempty():
    async def score(state: TaskState, target: Target) -> Score:
        answer = (state.output.completion or "").strip()
        return Score(value=CORRECT if answer else INCORRECT, answer=answer)

    return score


PASS_THRESHOLD = 1.0


class TestConstantScorer:
    """A scorer returning 0.5 for everyone has four defects, not one."""

    def test_gold_answer_does_not_pass(self):
        r = _reward(_run(constant_partial(), "Paris", "Paris").value)
        assert r < PASS_THRESHOLD, "GOLD_FAILS is real: the correct answer never passes"

    def test_a_wrong_answer_scores_the_same_as_the_right_one(self):
        right = _reward(_run(constant_partial(), "Paris", "Paris").value)
        wrong = _reward(_run(constant_partial(), "Berlin", "Paris").value)
        assert right == wrong, "SEPARABILITY_LOSS is real"

    def test_a_wrong_answer_is_paid_while_completing_nothing(self):
        wrong = _reward(_run(constant_partial(), "Berlin", "Paris").value)
        true_completion = 0.0  # "Berlin" is not "Paris" by any independent reading
        assert wrong - true_completion >= 0.5, "REWARD_HACKABLE is real"

    def test_an_input_ignoring_answer_ties_the_best_real_one(self):
        trivial = _reward(_run(constant_partial(), "I cannot determine the answer.", "Paris").value)
        best_real = _reward(_run(constant_partial(), "Paris", "Paris").value)
        assert trivial >= best_real, "TRIVIAL_FLOOR_BREACH is real"


class TestEffortScorer:
    """Accepting any non-empty answer also destroys separability."""

    def test_strong_and_weak_answers_are_indistinguishable(self):
        strong = _reward(_run(any_nonempty(), "Paris", "Paris").value)
        weak = _reward(_run(any_nonempty(), "Mercury", "Paris").value)
        assert strong == weak, "SEPARABILITY_LOSS is real"

    def test_a_wrong_answer_is_marked_correct(self):
        assert _run(any_nonempty(), "Mercury", "Paris").value == CORRECT
