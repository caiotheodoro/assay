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


# --- The third state: checked-and-clean is not could-not-check ----------------


def _classes():
    from assay.types import DefectClass

    return DefectClass


def test_a_declined_probe_is_not_scored_as_a_failure_to_detect():
    """Assay's only published miss was a check that could not run.

    `inspect_evals/boolq` plants SHORTCUT_LEAK and ships no train split, so
    `partial_input_baseline` returns NOT_APPLICABLE with that reason. `Outcome`
    carried only `planted` and `detected`, so the class landed in `missed` and
    every run ever published reported recall 0.9815 for a defect the tool had
    explicitly declined to rule on.
    """
    from assay.metrics import ArmResult, Outcome

    D = _classes()
    declined = Outcome(
        "inspect_evals/boolq",
        planted=frozenset({D.SHORTCUT_LEAK}),
        detected=frozenset(),
        inconclusive=frozenset({D.SHORTCUT_LEAK}),
    )
    assert declined.missed == frozenset()
    assert declined.unchecked == frozenset({D.SHORTCUT_LEAK})

    arm = ArmResult("assay", [declined])
    assert arm.n_missed == 0
    assert arm.n_unchecked == 1


def test_declining_to_answer_never_lowers_an_arms_expected_loss():
    """The one incentive a tool like this must not have.

    If an unchecked defect were cheaper than a missed one, any probe could cut
    its arm's reported loss by returning NOT_APPLICABLE. The loss is identical;
    only the account of why changes.
    """
    from assay.metrics import ArmResult, Outcome

    D = _classes()
    profile = load("research-run")
    planted = frozenset({D.SHORTCUT_LEAK})

    as_miss = ArmResult("m", [Outcome("e", planted, frozenset())])
    as_unchecked = ArmResult(
        "u", [Outcome("e", planted, frozenset(), inconclusive=planted)]
    )
    assert as_miss.expected_loss(profile) == as_unchecked.expected_loss(profile)
    assert as_miss.error_count == as_unchecked.error_count


def test_recall_keeps_the_full_denominator_and_reports_the_other_beside_it():
    """Both numbers, never whichever one is kinder."""
    from assay.metrics import ArmResult, Outcome

    D = _classes()
    arm = ArmResult(
        "assay",
        [
            Outcome("found", frozenset({D.GOLD_FAILS}), frozenset({D.GOLD_FAILS})),
            Outcome(
                "declined",
                frozenset({D.SHORTCUT_LEAK}),
                frozenset(),
                inconclusive=frozenset({D.SHORTCUT_LEAK}),
            ),
        ],
    )
    assert arm.recall == 0.5, "the headline denominator must stay the full planted set"
    assert arm.recall_on_checkable == 1.0
    row = arm.profile_row(load("research-run"))
    assert "recall" in row and "recall_on_checkable" in row and "n_unchecked" in row


def test_every_probe_declares_what_it_would_have_found():
    """`detects` is what makes NOT_APPLICABLE legible one layer up."""
    from assay.probes import all_probes

    undeclared = [p.name for p in all_probes() if not p.detects]
    assert not undeclared, f"probes that declare no defect classes: {undeclared}"


def test_the_declared_classes_match_the_ones_each_probe_module_actually_raises():
    """A probe that starts reporting a new class must say so here too."""
    import ast
    import pathlib

    from assay.probes import all_probes

    declared = {d.value for p in all_probes() for d in p.detects}
    root = pathlib.Path(__file__).resolve().parents[1] / "src/assay/probes"
    raised = set()
    for path in root.glob("*.py"):
        if path.name in {"__init__.py", "base.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "DefectClass"
            ):
                raised.add(node.attr)
    assert raised <= declared, (
        "probe modules name defect classes no probe declares in `detects`: "
        f"{sorted(raised - declared)}"
    )


def test_an_error_is_not_laundered_into_could_not_determine():
    """A crashed probe is a bug in Assay and must keep costing like one."""
    from assay.runner import AuditReport
    from assay.types import ProbeResult, ProbeStatus

    report = AuditReport(env_id="e", ecosystem="x", env_version="1")
    report.results = [
        ProbeResult(
            family="shortcut_leakage",
            probe="partial_input_baseline",
            status=ProbeStatus.ERROR,
            reason="boom",
        )
    ]
    assert report.unchecked == set(), "ERROR must not read as a reasoned decline"
