"""The flat-cost theorem test.

Under equal costs, ranking systems by expected loss MUST equal ranking them by
raw error count. If it does not, the loss function silently reorders systems
relative to a naive count, and every severity-weighted number the harness
produces is void.

This is a test, not a report. It never appears in a card as a result.
"""

from __future__ import annotations

import pytest

from assay.costs import load
from assay.metrics import ArmResult, Outcome, normalized_loss, trivial_arms
from assay.types import DefectClass

GROUND_TRUTH = {
    "env-a": frozenset({DefectClass.INVERT_PASSES, DefectClass.NOOP_PASSES}),
    "env-b": frozenset({DefectClass.SEPARABILITY_LOSS}),
    "env-c": frozenset(),
}


def _arm(name: str, detections: dict[str, frozenset]) -> ArmResult:
    return ArmResult(
        name,
        [Outcome(env, planted, detections.get(env, frozenset()))
         for env, planted in GROUND_TRUTH.items()],
    )


PERFECT = _arm("perfect", dict(GROUND_TRUTH))
ONE_MISS = _arm(
    "one_miss",
    {"env-a": frozenset({DefectClass.INVERT_PASSES}), "env-b": GROUND_TRUTH["env-b"]},
)
NOISY = _arm(
    "noisy",
    {
        "env-a": GROUND_TRUTH["env-a"],
        "env-b": GROUND_TRUTH["env-b"],
        "env-c": frozenset({DefectClass.NONDETERMINISM, DefectClass.GOLD_FAILS}),
    },
)

ARMS = [PERFECT, ONE_MISS, NOISY]


def test_flat_cost_loss_ranking_equals_error_count_ranking():
    flat = load("flat")
    by_loss = sorted(ARMS, key=lambda a: (a.expected_loss(flat), a.arm))
    by_errors = sorted(ARMS, key=lambda a: (a.error_count, a.arm))
    assert [a.arm for a in by_loss] == [a.arm for a in by_errors]


@pytest.mark.parametrize("profile_name", ["research-run", "production-training", "benchmark-publication"])
def test_severity_weighted_profiles_can_reorder_and_that_is_the_point(profile_name):
    """A weighted profile is allowed to rank a single CRITICAL miss worse than
    two MEDIUM false alarms. If it could not, weighting would be decoration."""
    profile = load(profile_name)
    assert ONE_MISS.expected_loss(profile) > NOISY.expected_loss(profile)
    # ...while the raw error count says they are equal.
    assert ONE_MISS.error_count < NOISY.error_count


def test_perfect_detection_normalises_to_zero():
    assert normalized_loss(PERFECT, GROUND_TRUTH, load("research-run")) == 0.0


def test_a_trivial_detector_normalises_to_at_least_one():
    profile = load("research-run")
    for arm in trivial_arms(GROUND_TRUTH).values():
        assert normalized_loss(arm, GROUND_TRUTH, profile) >= 1.0


def test_every_shipped_profile_loads():
    from assay.costs import all_profiles

    profiles = all_profiles()
    assert "flat" in profiles
    for name, p in profiles.items():
        assert p.description, name
        assert p.false_alarm > 0, name
