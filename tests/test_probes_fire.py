"""The self-check that matters: every planted defect must be detected, and a
healthy environment must produce none.

If this test can pass with a probe that never fires, the probe is decoration.
"""

from __future__ import annotations

import pytest

from assay import audit
from assay.fixtures import CATALOG, build
from assay.probes import families
from assay.types import DefectClass, ProbeStatus


@pytest.mark.parametrize("variant", sorted(CATALOG))
def test_detection_matches_ground_truth_exactly(variant):
    """Exact match, not 'at least'. Recall alone cannot separate detection from
    guessing -- a probe that flags everything would pass a recall-only test."""
    report = audit(build(variant))
    planted = CATALOG[variant]
    detected = report.detected
    assert detected == planted, (
        f"{variant}: planted {sorted(d.value for d in planted)}, "
        f"detected {sorted(d.value for d in detected)} "
        f"(missed {sorted(d.value for d in planted - detected)}, "
        f"spurious {sorted(d.value for d in detected - planted)})"
    )


def test_healthy_environment_is_clean():
    report = audit(build("healthy"))
    assert not report.findings, [f.summary() for f in report.findings]


def test_no_probe_errors_on_any_fixture():
    for variant in CATALOG:
        report = audit(build(variant))
        errors = report.by_status(ProbeStatus.ERROR)
        assert not errors, f"{variant}: {[(e.probe, e.reason) for e in errors]}"


def test_every_family_fires_on_at_least_one_fixture():
    fired: set[str] = set()
    for variant in CATALOG:
        for result in audit(build(variant)).results:
            if result.status is ProbeStatus.DEFECT:
                fired.add(result.family)
    expected = set(families()) - {"difficulty_band"}  # needs a rollout sampler
    assert expected <= fired, f"never fired: {sorted(expected - fired)}"


def test_difficulty_band_fires_with_solve_rates():
    env = build("healthy")
    ctx = {"solve_rates": {"t1": 0.98, "t2": 0.45, "t3": 0.02}}
    report = audit(env, ctx)
    assert DefectClass.DIFFICULTY_SATURATED in report.detected
    assert DefectClass.DIFFICULTY_IMPOSSIBLE in report.detected


def test_difficulty_findings_name_the_policy_that_produced_the_rate():
    """A solve rate belongs to an (environment, policy) pair. A card that
    reports the number without the policy is reporting half a fact."""
    ctx = {"solve_rates": {"t1": 0.02}, "solve_rate_source": "ollama:qwen3:1.7b"}
    report = audit(build("healthy"), ctx)
    finding = [f for f in report.findings if f.defect is DefectClass.DIFFICULTY_IMPOSSIBLE][0]
    assert finding.evidence["measured_with"] == "ollama:qwen3:1.7b"


def test_difficulty_band_is_not_applicable_without_rates():
    report = audit(build("healthy"))
    band = [r for r in report.results if r.family == "difficulty_band"][0]
    assert band.status is ProbeStatus.NOT_APPLICABLE
    assert band.reason
