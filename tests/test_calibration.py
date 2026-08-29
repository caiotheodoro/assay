"""Calibration arithmetic on the Challenger's self-reports.

`criteria.md` asks for mean Brier rather than summed, ECE with a reliability
diagram, the Murphy decomposition where n allows, and a false-success rate.
These tests pin the arithmetic. The measured values live in
`results/calibration.json`, because they are facts about runs and will move
when the runs do.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assay.calibration import (
    Pair,
    brier_decomposition,
    expected_calibration_error,
    mean_brier,
    outcome_rates,
    reliability_bins,
    report,
)

REPO = Path(__file__).resolve().parents[1]


def p(forecast, outcome, label="t"):
    return Pair(label, forecast, outcome)


def test_perfect_confident_forecasts_score_zero():
    assert mean_brier([p(1.0, 1.0), p(0.0, 0.0)]) == 0.0


def test_confidently_wrong_forecasts_score_one():
    assert mean_brier([p(1.0, 0.0), p(0.0, 1.0)]) == 1.0


def test_brier_is_a_mean_not_a_sum():
    """The correction criteria.md asks for. A longer trajectory of identical
    quality must score the same, or length becomes a penalty and two runs of
    different lengths cannot be compared."""
    short = [p(1.0, 0.0)] * 2
    long = [p(1.0, 0.0)] * 20
    assert mean_brier(short) == mean_brier(long) == 1.0


def test_brier_over_no_pairs_raises_rather_than_returning_zero():
    """Zero is the best possible score. An absent measurement must not read as
    a perfect one."""
    with pytest.raises(ValueError):
        mean_brier([])


def test_decomposition_identity_holds():
    """brier == reliability - resolution + uncertainty. If it does not, one of
    the three is being computed against a different base rate and the
    'reliability' number -- the one worth reading -- is meaningless."""
    pairs = [p(1.0, 1.0), p(1.0, 0.0), p(0.0, 0.0), p(0.0, 1.0), p(1.0, 1.0)]
    d = brier_decomposition(pairs)
    assert d["reliability"] - d["resolution"] + d["uncertainty"] == pytest.approx(
        mean_brier(pairs)
    )


def test_a_forecaster_that_always_says_the_same_thing_has_zero_resolution():
    pairs = [p(0.0, 1.0), p(0.0, 0.0), p(0.0, 0.0)]
    assert brier_decomposition(pairs)["resolution"] == pytest.approx(0.0)


def test_reliability_is_zero_when_stated_confidence_matches_observed_rate():
    """Four identical 0.5 forecasts on two hits and two misses: perfectly
    reliable, and useless, which is what resolution is for."""
    pairs = [p(0.5, 1.0), p(0.5, 1.0), p(0.5, 0.0), p(0.5, 0.0)]
    d = brier_decomposition(pairs)
    assert d["reliability"] == pytest.approx(0.0)
    assert d["resolution"] == pytest.approx(0.0)


def test_reliability_diagram_keeps_empty_bins():
    """Dropping them makes a boolean forecaster look like it covered the range."""
    rows = reliability_bins([p(0.0, 0.0), p(1.0, 1.0)], n_bins=10)
    assert len(rows) == 10
    assert sum(1 for r in rows if r["n"] == 0) == 8
    assert rows[0]["n"] == 1 and rows[-1]["n"] == 1


def test_forecast_of_exactly_one_lands_in_the_top_bin_not_outside():
    rows = reliability_bins([p(1.0, 1.0)], n_bins=5)
    assert rows[-1]["n"] == 1
    assert sum(r["n"] for r in rows) == 1


def test_ece_is_zero_for_a_perfectly_calibrated_forecaster():
    assert expected_calibration_error([p(1.0, 1.0), p(0.0, 0.0)]) == pytest.approx(0.0)


def test_ece_weights_bins_by_how_much_evidence_is_in_them():
    """One badly-calibrated forecast among many good ones must not dominate."""
    pairs = [p(0.0, 0.0)] * 99 + [p(1.0, 0.0)]
    assert expected_calibration_error(pairs) == pytest.approx(0.01)


def test_false_success_is_claimed_solved_but_verifier_says_not():
    rates = outcome_rates([p(1.0, 0.0), p(1.0, 1.0), p(0.0, 0.0)])
    assert rates["false_success_count"] == 1
    assert rates["false_success_rate"] == pytest.approx(0.5)


def test_false_failure_is_the_slice_5c_shape():
    """The attacker honestly reports `solves_the_task: false` about something
    the independent verifier scores a complete solve. Narrated by hand in
    docs/CHANGELOG.md slice 5c; this is the rate."""
    rates = outcome_rates([p(0.0, 1.0), p(0.0, 0.0)])
    assert rates["false_failure_count"] == 1
    assert rates["false_failure_rate"] == pytest.approx(0.5)


def test_a_rate_with_no_denominator_is_none_not_zero():
    """`0.0` means 'measured, never happened'. `None` means 'the attacker never
    made that claim'. Collapsing them would report a clean false-success rate
    for an attacker that never once claimed success."""
    rates = outcome_rates([p(0.0, 0.0), p(0.0, 0.0)])
    assert rates["false_success_rate"] is None
    assert rates["false_failure_rate"] == 0.0


def test_report_names_the_instrument_limit_for_boolean_forecasts():
    body = report([p(0.0, 0.0), p(1.0, 1.0), p(0.0, 1.0)])
    assert "instrument_limit" in body
    assert body["brier_decomposition"]["n_distinct_forecasts"] == 2


def test_report_over_no_pairs_says_absent_rather_than_perfect():
    body = report([])
    assert body["n_pairs"] == 0
    assert "unavailable" in body
    assert "mean_brier" not in body


def test_report_carries_the_summed_score_only_as_a_warning():
    body = report([p(1.0, 0.0), p(1.0, 0.0)])
    assert body["mean_brier"] == 1.0
    assert body["summed_brier_do_not_use"] == 2.0
    assert body["decomposition_identity_holds"]


def test_the_published_calibration_file_is_internally_consistent():
    """Guards the published numbers against a decomposition that silently stops
    adding up, which is how a 'reliability' figure goes quietly wrong."""
    path = REPO / "results" / "calibration.json"
    if not path.exists():
        pytest.skip("results/calibration.json not generated on this machine")
    body = json.loads(path.read_text())
    for block in [body["pooled"]] + [
        arm["calibration"] for arm in body["per_arm"].values()
    ]:
        assert block["decomposition_identity_holds"], block
        d = block["brier_decomposition"]
        assert d["reliability"] >= 0.0
        assert d["resolution"] >= 0.0
        assert 0.0 <= block["mean_brier"] <= 1.0


def test_the_replay_reproduced_every_recorded_score():
    """The outcome half of every pair comes from a replay. If the replay does
    not reproduce the score the original run recorded, it is scoring a different
    workspace and the pairs are not about the runs they claim to be."""
    path = REPO / "results" / "calibration.json"
    if not path.exists():
        pytest.skip("results/calibration.json not generated on this machine")
    body = json.loads(path.read_text())
    for name, arm in body["per_arm"].items():
        fidelity = arm["replay_fidelity"]
        assert (
            fidelity["turns_where_replay_reproduced_the_recorded_score"]
            == fidelity["of"]
        ), name
