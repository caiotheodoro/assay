"""`solves_the_task` is a probability, and used to be a boolean.

`results/calibration.json` reported `instrument_limit`: the attacker emitted a
bool, so only two distinct forecast values ever appeared and the reliability
diagram had two bins. ECE over two bins is not much of a measurement. The
attacker now emits a probability -- but every trajectory committed before that
still carries a bool, so both have to read correctly or the calibration corpus
splits in half.
"""

from __future__ import annotations

import pytest

from assay.challenger.prompted import SOLVED_AT, _confidence


@pytest.mark.parametrize(
    "raw, expected",
    [
        (True, 1.0),
        (False, 0.0),
        (0.0, 0.0),
        (1.0, 1.0),
        (0.5, 0.5),
        (0.73, 0.73),
        (1, 1.0),
        (0, 0.0),
    ],
)
def test_bools_and_floats_both_read(raw, expected):
    assert _confidence(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "yes", "", {}, []])
def test_anything_unreadable_is_no_claim(raw):
    """A missing or malformed forecast must not read as 'I solved it'."""
    assert _confidence(raw) == 0.0


@pytest.mark.parametrize("raw, expected", [(-3.0, 0.0), (7.5, 1.0)])
def test_out_of_range_is_clamped(raw, expected):
    assert _confidence(raw) == expected


def test_a_low_probability_is_not_a_claim_of_success():
    """The regression this threshold exists to prevent.

    A float is truthy at 0.1, so a consumer written against the old boolean
    would read "10% sure" as "this genuinely solves the task" and drop the
    score from the exploit tally.
    """
    assert _confidence(0.1) < SOLVED_AT
    assert _confidence(0.9) >= SOLVED_AT
    assert bool(0.1) is True, "the truthiness trap this guards against"
