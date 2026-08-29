"""Independent verification of what the wild sweep found on published evals.

A finding against a real benchmark is the most valuable output this project
produces and a false one is the most damaging, so no finding is reported on the
strength of Assay having flagged it. Each is re-established here from the
suite's own code -- `inspect_evals`' sample builder and `inspect_ai`'s own
scorer -- without Assay in the loop, the same way
`tests/test_corpus_ground_truth.py` establishes the planted ones.

These tests are offline. Importing an `inspect_evals` module is network-free;
only *calling* a task factory materialises its dataset. So the records below are
hand-written and pushed through the eval's own `record_to_sample`, which fixes
the target vocabulary from the eval's code rather than from a memory of it.
The full-dataset numbers quoted in `docs/changelog/30-wild-sweep.md` need the
Hub and are reproduced by `scripts/wild_sweep.py`, not here.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect as pyinspect

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals", reason="the sweep dependency group is not installed")

from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import (  # noqa: E402
    CORRECT,
    INCORRECT,
    NOANSWER,
    Target,
    includes,
    pattern,
)
from inspect_ai.solver import TaskState  # noqa: E402

# An `inspect_evals` package `__init__` re-exports its task function under the
# package's own name, which shadows the submodule on attribute access.
paws_module = importlib.import_module("inspect_evals.paws.paws")  # noqa: E402
boolq_module = importlib.import_module("inspect_evals.boolq.boolq")  # noqa: E402


def score(scorer_fn, completion: str, target: str):
    state = TaskState(
        model="assay/probe",
        sample_id="p1",
        epoch=1,
        input="Sentence1: ...\nSentence2: ...",
        messages=[],
        output=ModelOutput.from_content(model="assay/probe", content=completion),
    )
    return asyncio.run(scorer_fn(state, Target(target))).value


def paws_targets() -> set[str]:
    """The eval's whole target vocabulary, taken from its own sample builder."""
    return {
        str(paws_module.record_to_sample({"sentence1": "a", "sentence2": "b", "label": label, "id": label}).target)
        for label in (0, 1)
    }


class TestPawsSubstringScorer:
    """`paws` scores with `includes()` against the targets "Yes" and "No".

    `includes()` is a case-insensitive *substring* test, so the eval cannot
    distinguish a completion that answers from one that merely contains the
    label's letters. This is the WebArena substring-match failure the README
    cites, live in a published eval.
    """

    def test_the_eval_really_wires_includes_as_its_scorer(self):
        source = pyinspect.getsource(paws_module)
        assert "scorer=includes()" in source, (
            "this finding is about includes(); if paws changed its scorer the "
            "finding needs re-establishing, not re-asserting"
        )

    def test_the_target_vocabulary_is_two_short_words(self):
        assert paws_targets() == {"Yes", "No"}

    @pytest.mark.parametrize(
        "completion",
        [
            "I cannot determine the answer.",
            "I don't know",
            "Not sure",
            "None of the above",
            "no idea",
            "There is not enough information.",
        ],
    )
    def test_a_refusal_is_marked_correct_whenever_the_target_is_no(self, completion):
        """Every one of these contains the substring "no" -- in "cannot", "know",
        "not", "none". None of them answers the question."""
        assert score(includes(), completion, "No") == CORRECT

    def test_the_same_refusal_is_marked_wrong_when_the_target_is_yes(self):
        """The looseness is one-sided, so it does not cancel out: it makes the
        No class systematically easier for any model that hedges."""
        assert score(includes(), "I cannot determine the answer.", "Yes") == INCORRECT

    def test_a_single_constant_string_satisfies_both_targets(self):
        """The strongest form. One fixed completion, chosen without reading the
        input, is scored correct against every target the eval has."""
        for target in paws_targets():
            assert score(includes(), "yesno", target) == CORRECT

    @pytest.mark.parametrize("completion", ["Yes or No", "Yes. No.", "yesno"])
    def test_several_natural_constant_strings_do_the_same(self, completion):
        for target in paws_targets():
            assert score(includes(), completion, target) == CORRECT

    def test_an_ordinary_wrong_answer_is_still_caught(self):
        """Not everything passes -- the scorer is loose, not broken. Recording
        this because 'the eval cannot fail' would be a stronger claim than the
        evidence supports."""
        assert score(includes(), "Yes", "No") == INCORRECT
        assert score(includes(), "No", "Yes") == INCORRECT


class TestWhatAssayItselfFound:
    """The probe battery found the weaker half of this and missed the stronger.

    Recorded as a test so the gap cannot quietly close in the write-up. The
    scripted Challenger's repertoire is the adapter's trivial policies; a
    constant string that names *every* label is not among them, so the 100%
    exploit was found by hand during triage, not by the tool.
    """

    def test_the_escalate_policy_is_the_exploit_the_tool_had_available(self):
        from assay.adapters.inspect_ai_adapter import ANSWER_TOOL
        from assay.sweep import RAW, WildInspectAdapter

        from inspect_ai import Task
        from inspect_ai.dataset import MemoryDataset, Sample
        from inspect_ai.solver import generate

        dataset = MemoryDataset(
            [
                Sample(input="Sentence1: a\nSentence2: b", target="No", id="n1"),
                Sample(input="Sentence1: c\nSentence2: d", target="Yes", id="y1"),
            ]
        )
        adapter = WildInspectAdapter(
            Task(dataset=dataset, scorer=includes(), solver=generate()),
            protocol=RAW,
            env_id="paws-shape",
        )
        escalate = adapter.trivial_policies("n1")["always_escalate"]
        assert escalate[0].args["answer"] == "I cannot determine the answer."

        from assay.adapter import run_policy

        on_no = adapter.verify(run_policy(adapter, "n1", escalate))
        on_yes = adapter.verify(run_policy(adapter, "y1", escalate))
        assert on_no.reward == 1.0, "credited on the No half"
        assert on_yes.reward == 0.0, "not on the Yes half"

    def test_the_constant_string_exploit_was_not_in_the_challenger_repertoire(self):
        """The honest half of the result: the tool did not propose this."""
        from inspect_ai import Task
        from inspect_ai.dataset import MemoryDataset, Sample
        from inspect_ai.solver import generate

        from assay.challenger import ScriptedChallenger
        from assay.sweep import RAW, WildInspectAdapter

        dataset = MemoryDataset(
            [
                Sample(input="Sentence1: a\nSentence2: b", target="No", id="n1"),
                Sample(input="Sentence1: c\nSentence2: d", target="Yes", id="y1"),
            ]
        )
        adapter = WildInspectAdapter(
            Task(dataset=dataset, scorer=includes(), solver=generate()),
            protocol=RAW,
            env_id="paws-shape",
        )
        proposed = {
            str(a.args.get("answer", ""))
            for attempt in ScriptedChallenger().attack(adapter, "y1")
            for a in attempt.transcript.actions
        }
        assert "yesno" not in proposed
        assert not any("yes" in p.lower() and "no" in p.lower() for p in proposed), (
            "no scripted policy names both labels at once, which is why the 100% "
            "exploit had to come from hand triage"
        )


class TestBoolqAnchoredPattern:
    r"""The same two-label hazard, mitigated better, still leaking.

    `boolq` scores with `pattern(r"(Yes|No).?\Z")` rather than `includes()`.
    Anchoring at the end of the completion is a real mitigation: it returns
    NOANSWER for most refusals instead of crediting them, and there is no
    constant string that satisfies both targets. It is recorded here as the
    contrast that makes the `paws` finding legible -- and then as a narrower
    leak of its own, because `.?` admits exactly one trailing character and
    "know" is "no" plus one.
    """

    def test_the_eval_really_wires_this_pattern(self):
        source = pyinspect.getsource(boolq_module)
        assert 'pattern(r"(Yes|No).?\\Z")' in source

    def test_the_target_vocabulary_is_the_same_two_short_words(self):
        assert {
            str(boolq_module.record_to_sample(
                {"answer": answer, "passage": "p", "question": "q"}
            ).target)
            for answer in (True, False)
        } == {"Yes", "No"}

    def test_anchoring_defuses_the_constant_string_exploit(self):
        """What `paws` would have needed. No single completion is correct for
        both targets, so the 100% exploit does not carry over."""
        for constant in ("yesno", "Yes or No", "Yes. No."):
            values = {
                score(pattern(r"(Yes|No).?\Z"), constant, target)
                for target in ("Yes", "No")
            }
            assert CORRECT in values and INCORRECT in values

    @pytest.mark.parametrize(
        "completion", ["I cannot determine the answer.", "Unknown", "I cannot say"]
    )
    def test_most_refusals_are_correctly_left_unscored(self, completion):
        assert score(pattern(r"(Yes|No).?\Z"), completion, "No") == NOANSWER

    @pytest.mark.parametrize("completion", ["I don't know", "I do not know"])
    def test_but_a_bare_i_dont_know_is_credited_as_no(self, completion):
        """`.?` admits one trailing character, and "know" is "no" plus "w".
        A model that answers with the most common bare non-answer there is gets
        marked correct on every No-targeted item."""
        assert score(pattern(r"(Yes|No).?\Z"), completion, "No") == CORRECT

    def test_the_leak_closes_with_any_trailing_punctuation(self):
        """The scope of the leak, stated exactly rather than overclaimed: two
        trailing characters do not match, so "I don't know." is unscored."""
        assert score(pattern(r"(Yes|No).?\Z"), "I don't know.", "No") == NOANSWER

    def test_the_scripted_challenger_would_not_have_proposed_it(self):
        """Assay reported `boolq` clean, and this is why: the trivial policy
        vocabulary is a fixed set of strings, and whether a substring leak is
        found depends on which string it happens to hold. The repertoire's
        refusal is "I cannot determine the answer.", which ends in "answer."."""
        assert score(pattern(r"(Yes|No).?\Z"), "I cannot determine the answer.", "No") == NOANSWER
