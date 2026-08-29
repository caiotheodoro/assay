"""The sampler/trainer KL estimator, and what it does when it has nothing.

`environments.md:140` makes this a mandatory field. Neither GPU run logged what
it needs, so the estimator ships without a number attached to it. The one thing
that must not happen is an absent measurement coming back as 0.0 -- "KL ~= 0" is
the healthiest verdict the field has, so a silent zero would read as a clean
bill of health for a check that never ran.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from assay.train.onpolicy import (
    REQUIRED_FIELDS,
    KLEstimate,
    NotComputable,
    run_kl,
    sampler_trainer_kl,
)

REPO = Path(__file__).resolve().parents[1]


def test_identical_logprobs_give_exactly_zero_kl():
    est = sampler_trainer_kl([-0.5, -1.25, -0.01], [-0.5, -1.25, -0.01])
    assert est.k1 == 0.0
    assert est.k3 == 0.0
    assert est.n_tokens == 3


def test_k3_is_non_negative_even_where_k1_is_not():
    """The reason two estimators are reported. k1 is a plain Monte-Carlo mean
    and can go negative on a short sequence; a KL cannot."""
    sampler = [-2.0, -2.0, -2.0]
    trainer = [-1.0, -1.0, -1.0]  # trainer likes these tokens MORE
    est = sampler_trainer_kl(sampler, trainer)
    assert est.k1 < 0
    assert est.k3 > 0


def test_k1_matches_the_mean_log_ratio_by_hand():
    sampler = [-1.0, -2.0]
    trainer = [-1.5, -2.5]
    est = sampler_trainer_kl(sampler, trainer)
    assert est.k1 == pytest.approx(((-1.0) - (-1.5) + (-2.0) - (-2.5)) / 2)


def test_k3_matches_schulmans_formula_by_hand():
    sampler, trainer = [-1.0], [-1.5]
    log_r = -1.5 - (-1.0)
    est = sampler_trainer_kl(sampler, trainer)
    assert est.k3 == pytest.approx(math.exp(log_r) - 1.0 - log_r)


def test_kl_grows_as_the_two_policies_diverge():
    base = [-1.0] * 8
    near = sampler_trainer_kl(base, [-1.05] * 8)
    far = sampler_trainer_kl(base, [-3.0] * 8)
    assert far.k3 > near.k3


def test_length_mismatch_raises_rather_than_truncating():
    with pytest.raises(NotComputable, match="length mismatch"):
        sampler_trainer_kl([-1.0, -2.0], [-1.0])


def test_empty_input_raises_rather_than_returning_zero():
    with pytest.raises(NotComputable):
        sampler_trainer_kl([], [])


def test_non_finite_logprob_raises():
    with pytest.raises(NotComputable, match="non-finite"):
        sampler_trainer_kl([-1.0, float("-inf")], [-1.0, -1.0])


def test_absent_logprobs_return_a_reason_not_a_zero():
    """The whole point. A caller reading `.get("value")` must get None, and the
    reason must be in the same object so it cannot be dropped on the way out."""
    result = run_kl([{"reward": 1.0}, {"reward": 0.0}])
    assert result["value"] is None
    assert "no sampler_logprobs" in result["unavailable"]
    assert set(result["required_to_fix"]) == set(REQUIRED_FIELDS)


def test_run_kl_token_weights_rather_than_averaging_rows():
    """A 100-token rollout and a 1-token rollout are not equal evidence."""
    rows = [
        {"sampler_logprobs": [-1.0] * 100, "trainer_logprobs": [-1.0] * 100},
        {"sampler_logprobs": [-1.0], "trainer_logprobs": [-5.0]},
    ]
    result = run_kl(rows)
    assert result["n_tokens"] == 101
    naive_row_mean = sampler_trainer_kl([-1.0], [-5.0]).k3 / 2
    assert result["value"] < naive_row_mean


@pytest.mark.parametrize("run", ["assay-challenger-r1", "assay-challenger-r2"])
def test_the_real_run_logs_genuinely_lack_the_field(run):
    """Pins the claim in docs/changelog/62-rigour.md that this gap is
    uncloseable. If someone later adds logprob capture and re-runs, this fails
    and the write-up has to be corrected rather than left stale."""
    path = REPO / "results" / run / "rewards.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert rows
    assert not any("sampler_logprobs" in r or "trainer_logprobs" in r for r in rows)
    assert run_kl(rows)["value"] is None


def test_estimate_serialises_with_its_definition_attached():
    payload = KLEstimate(0.1, 0.2, 5).as_dict()
    assert payload["n_tokens"] == 5
    assert "log p_sampler - log p_trainer" in payload["estimators"]
