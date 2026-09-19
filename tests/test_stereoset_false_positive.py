"""Assay reports GOLD_FAILS on an eval whose reference answers are fine.

`inspect_evals/stereoset` measures bias; it does not grade correctness. Two of
its three options are accepted -- `multiple_choice_scorer` builds
`target_letters` from the samples labelled "stereotype" and "anti-stereotype"
and marks either CORRECT -- while `stereoset_scorer` returns a *signed
measurement* over the same choice: `{stereotype: 1, anti-stereotype: -1,
unrelated: 0}`.

Assay reads the mean of an environment's scorers as a reward and asks whether
the reference answer passes. Here an accepted answer scores `(1.0 + -1)/2 = 0.0`
whenever the model picks the anti-stereotype option, so the battery concludes
the gold answer fails and reports `GOLD_FAILS` on a correctly-designed eval.

This pins the *upstream* half, with Assay out of the loop: both accepted letters
really do pass the accept scorer, and one of them really does return -1 from the
measurement scorer. If upstream ever changes either, this fails and
`docs/COVERAGE.md` and the corpus entry need revisiting.

Sibling of `tests/test_personality_false_positive.py`. That one is a format-only
scorer producing INVERT_PASSES; this one is a bias metric producing GOLD_FAILS.
Two environments the tool is wrong about, wrong two different ways.
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals", reason="the sweep dependency group is not installed")

stereoset = importlib.import_module("inspect_evals.stereoset.stereoset")


def test_the_measurement_scorer_maps_an_accepted_answer_to_minus_one():
    """The whole false positive in one constant.

    A grade cannot be negative. This is not a grade.
    """
    source = importlib.import_module("inspect_evals.stereoset.stereoset").__file__
    text = open(source).read()
    assert '"stereotype": 1' in text and '"anti-stereotype": -1' in text, (
        "stereoset_scorer no longer maps anti-stereotype to -1; the GOLD_FAILS "
        "finding this corpus entry records may no longer be reproducible"
    )


def test_two_options_are_accepted_as_correct_not_one():
    """`target_letters` is built from both labels, so there is no single answer."""
    source = open(importlib.import_module("inspect_evals.stereoset.stereoset").__file__).read()
    assert 'if label in ["stereotype", "anti-stereotype"]' in source, (
        "the eval no longer accepts both the stereotype and anti-stereotype "
        "options; if it now has one correct answer, this environment does not "
        "belong in the no-correct-answer set"
    )


def test_stereoset_is_in_the_scored_corpus_and_plants_nothing():
    """Registered because Assay is wrong about it, and scored as such."""
    from assay.corpus import ground_truth, provenance

    truth, declared = ground_truth(), provenance()
    assert "inspect_evals/stereoset" in truth, (
        "stereoset must be registered; docs/PRE-REGISTRATION-STEREOSET.md "
        "predicts the arithmetic that rests on it"
    )
    assert truth["inspect_evals/stereoset"] == frozenset(), (
        "it must plant nothing -- every finding here is a false positive, and "
        "planting anything would make it measure a detection instead"
    )
    p = declared["inspect_evals/stereoset"]
    assert str(p.env_author).endswith("EXTERNAL"), (
        "the value of this environment is that we did not write it"
    )


def test_the_battery_still_reports_the_false_positive_this_entry_records():
    """If Assay stops being wrong here, the corpus entry's note is stale."""
    from assay._inspect_evals_corpus import _build
    from assay.runner import audit
    from assay.types import DefectClass

    adapter = _build("stereoset")
    try:
        report = audit(adapter, None)
    finally:
        close = getattr(adapter, "close", None)
        if close:
            try:
                close()
            except Exception:
                pass
    assert DefectClass.GOLD_FAILS in report.detected, (
        f"expected the GOLD_FAILS false positive, got "
        f"{sorted(d.value for d in report.detected)}. If the battery no longer "
        "fires here, this environment stops measuring what it was added to "
        "measure and the corpus note must change."
    )
