"""The five trivial policies `criteria.md:52` requires.

Two of them -- stratified-random and always-exception -- were missing, and the
floor they define is the denominator of every normalised number this project
publishes. These tests pin the arithmetic, not the conclusion: the conclusion
(that neither new policy becomes the floor on this corpus) is a fact about the
corpus and belongs in `results/baselines.json`, where it can change when the
corpus does.
"""

from __future__ import annotations

import pytest

from assay.costs import all_profiles, load
from assay.metrics import (
    ArmResult,
    Outcome,
    always_modal_defect_arm,
    base_rates,
    expected_stratified_loss,
    modal_defect,
    oracle_arm,
    stratified_random_arm,
    stratified_random_setwise_arm,
    trivial_arms,
)
from assay.types import DefectClass

TRUTH = {
    "env-a": frozenset({DefectClass.INVERT_PASSES, DefectClass.NOOP_PASSES}),
    "env-b": frozenset({DefectClass.INVERT_PASSES}),
    "env-c": frozenset(),
    "env-d": frozenset({DefectClass.REWARD_HACKABLE}),
}


def test_base_rates_are_per_class_fractions_of_environments():
    rates = base_rates(TRUTH)
    assert rates[DefectClass.INVERT_PASSES] == 0.5  # 2 of 4
    assert rates[DefectClass.NOOP_PASSES] == 0.25
    assert rates[DefectClass.REWARD_HACKABLE] == 0.25
    assert rates[DefectClass.GOLD_FAILS] == 0.0
    assert set(rates) == set(DefectClass), "every class gets a rate, including zero ones"


def test_base_rates_of_an_empty_corpus_are_zero_not_a_crash():
    assert set(base_rates({}).values()) == {0.0}


def test_modal_defect_is_the_most_planted_class():
    assert modal_defect(TRUTH) is DefectClass.INVERT_PASSES


def test_modal_defect_breaks_ties_on_enum_order_not_dict_order():
    """A policy whose output depends on iteration order is not a policy."""
    tied = {
        "a": frozenset({DefectClass.GOLD_FAILS}),
        "b": frozenset({DefectClass.NOOP_PASSES}),
    }
    reversed_insert = {
        "b": frozenset({DefectClass.NOOP_PASSES}),
        "a": frozenset({DefectClass.GOLD_FAILS}),
    }
    assert modal_defect(tied) is modal_defect(reversed_insert)
    assert modal_defect(tied) is DefectClass.GOLD_FAILS  # earlier in the enum


def test_always_modal_defect_predicts_the_same_set_everywhere():
    arm = always_modal_defect_arm(TRUTH)
    predicted = {frozenset(o.detected) for o in arm.outcomes}
    assert predicted == {frozenset({DefectClass.INVERT_PASSES})}
    assert len(arm.outcomes) == len(TRUTH)


def test_stratified_random_is_reproducible_from_its_seed():
    a = stratified_random_arm(TRUTH, seed=3)
    b = stratified_random_arm(TRUTH, seed=3)
    assert [o.detected for o in a.outcomes] == [o.detected for o in b.outcomes]
    c = stratified_random_arm(TRUTH, seed=4)
    assert [o.detected for o in a.outcomes] != [o.detected for o in c.outcomes]


def test_stratified_random_never_flags_a_class_with_zero_base_rate():
    """`rng.random() < 0.0` is false for every draw, so an unplanted class must
    never appear. If it did, the policy would be inventing a prior it was not
    given."""
    unseen = {d for d, p in base_rates(TRUTH).items() if p == 0.0}
    for seed in range(50):
        for outcome in stratified_random_arm(TRUTH, seed=seed).outcomes:
            assert not (outcome.detected & unseen)


@pytest.mark.parametrize("profile_name", sorted(all_profiles()))
def test_closed_form_matches_the_monte_carlo_mean(profile_name):
    """The analytic expectation is the thing reported next to the seeded draw,
    so it has to be the same quantity a large sample converges to."""
    profile = load(profile_name)
    closed = expected_stratified_loss(TRUTH, profile)
    sampled = [
        stratified_random_arm(TRUTH, seed=s).expected_loss(profile) for s in range(4000)
    ]
    mean = sum(sampled) / len(sampled)
    assert closed == pytest.approx(mean, rel=0.05)


def test_oracle_loss_is_zero_on_every_profile():
    arm = oracle_arm(TRUTH)
    assert arm.n_missed == 0 and arm.n_spurious == 0
    for profile in all_profiles().values():
        assert arm.expected_loss(profile) == 0.0


def test_oracle_is_not_one_of_the_trivial_arms():
    """It is the numerator's zero point. In the denominator it would make every
    normalised loss infinite, and `normalized_loss` raises rather than divide by
    zero -- so this is the guard that keeps that path unreachable."""
    assert "oracle" not in trivial_arms(TRUTH)


def test_trivial_arms_carries_all_four_non_oracle_policies():
    assert set(trivial_arms(TRUTH)) == {
        "flag_nothing",
        "flag_everything",
        "always_modal_defect",
        "stratified_random",
    }


def test_trivial_arms_of_an_empty_corpus_does_not_invent_rows():
    arms = trivial_arms({})
    assert all(not a.outcomes for a in arms.values())


def test_setwise_stratified_random_only_predicts_sets_the_corpus_contains():
    """The point of the set-wise variant is that it preserves co-occurrence.
    A prediction that is not one of the observed label sets would break that."""
    observed = {frozenset(v) for v in TRUTH.values()}
    for seed in range(30):
        for outcome in stratified_random_setwise_arm(TRUTH, seed).outcomes:
            assert frozenset(outcome.detected) in observed


def test_per_class_stratified_random_can_emit_a_set_the_corpus_never_shows():
    """The flip side, stated as a test so the difference between the two
    readings is exercised rather than only described in a docstring."""
    observed = {frozenset(v) for v in TRUTH.values()}
    emitted = {
        frozenset(o.detected)
        for seed in range(200)
        for o in stratified_random_arm(TRUTH, seed=seed).outcomes
    }
    assert emitted - observed, "per-class independence must be able to break co-occurrence"
