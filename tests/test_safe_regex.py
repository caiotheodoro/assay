"""A timeout asserted is not a timeout. These exhibit the hang."""

from __future__ import annotations

import time

import pytest

from assay.safe_regex import PatternInvalid, PatternTooSlow, search


def test_it_matches_the_way_re_does():
    assert search(r"(Yes|No).?\Z", "No.") is True
    assert search(r"(Yes|No).?\Z", "I cannot determine the answer.") is False


def test_the_catastrophic_pattern_is_bounded_not_endured():
    """`(a+)+$` against 31 characters takes ~100s in-process. Here it must fail
    fast instead."""
    started = time.time()
    with pytest.raises(PatternTooSlow):
        search("(a+)+$", "a" * 30 + "!", timeout=1.0)
    assert time.time() - started < 10, "the budget was not enforced"


def test_an_uncompilable_pattern_is_a_different_error():
    """Distinguishable on purpose: one is the submitter's typo, the other is a
    denial of service."""
    with pytest.raises(PatternInvalid):
        search("(unclosed", "text")


def test_a_slow_pattern_is_reported_rather_than_treated_as_no_match():
    """Returning False would let a hostile pattern silently mark every item
    wrong, which is a defect wearing a verifier's clothes."""
    with pytest.raises(PatternTooSlow):
        search("(x+x+)+y", "x" * 40, timeout=1.0)
