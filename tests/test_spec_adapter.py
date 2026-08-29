"""The declarative adapter behind the Space.

The load-bearing property is not that it audits a good spec correctly. It is
that a *thin* spec produces a card full of NOT_APPLICABLE reasons rather than a
clean bill of health, because the Space's whole failure mode is a stranger
submitting three lines, seeing "no findings", and concluding their eval is fine.
"""

from __future__ import annotations

import pytest

from assay.adapters.spec import EnvSpec, SpecError, build
from assay.runner import audit
from assay.types import Capability, DefectClass, ProbeStatus

# A minimal but complete Yes/No eval. Written here from scratch: it is the
# SHAPE of a two-label classification eval, not any third party's content.
FULL = {
    "env_id": "example/yes-no",
    "verifier": "exact",
    "tasks": [
        {
            "task_id": "q1",
            "instruction": "Answer Yes or No: is 2 greater than 1?",
            "target": "Yes",
            "gold": "Yes",
            "known_wrong": "No",
            "asserts": ["the answer equals Yes"],
        },
        {
            "task_id": "q2",
            "instruction": "Answer Yes or No: is 1 greater than 2?",
            "target": "No",
            "gold": "No",
            "known_wrong": "Yes",
            "asserts": ["the answer equals No"],
        },
        {
            "task_id": "q3",
            "instruction": "Answer Yes or No: is 3 greater than 2?",
            "target": "Yes",
            "gold": "Yes",
            "known_wrong": "No",
            "asserts": ["the answer equals Yes"],
        },
    ],
    "train": [{"item_id": "tr1", "text": "is 5 greater than 4", "label": "Yes"}],
    "eval": [{"item_id": "ev1", "text": "is 4 greater than 5", "label": "No"}],
}

THIN = {
    "env_id": "example/thin",
    "tasks": [{"task_id": "only", "instruction": "do the thing", "target": "done"}],
}


# -- parsing ---------------------------------------------------------------


def test_a_spec_without_env_id_is_refused():
    with pytest.raises(SpecError, match="env_id is required"):
        EnvSpec.parse({"tasks": [{"target": "x"}]})


def test_a_task_without_a_target_is_refused_and_the_error_says_why():
    """`target` is separate from the verifier on purpose, and the error has to
    teach that, because a submitter who conflates them gets a vacuous audit."""
    with pytest.raises(SpecError, match="what the verifier accepts"):
        EnvSpec.parse({"env_id": "x", "tasks": [{"task_id": "a"}]})


def test_an_unknown_matcher_is_refused_rather_than_defaulted():
    with pytest.raises(SpecError, match="verifier must be one of"):
        EnvSpec.parse({"env_id": "x", "verifier": "vibes", "tasks": [{"target": "y"}]})


def test_malformed_json_reports_the_json_error_not_a_traceback():
    with pytest.raises(SpecError, match="not valid JSON"):
        EnvSpec.parse("{not json")


def test_duplicate_task_ids_are_refused():
    with pytest.raises(SpecError, match="unique"):
        EnvSpec.parse(
            {"env_id": "x", "tasks": [{"task_id": "a", "target": "1"},
                                      {"task_id": "a", "target": "2"}]}
        )


def test_oversized_submissions_are_refused_with_the_cap_named():
    raw = {"env_id": "x", "tasks": [{"task_id": f"t{i}", "target": "y"} for i in range(201)]}
    with pytest.raises(SpecError, match="the cap is 200"):
        EnvSpec.parse(raw)


# -- capabilities ----------------------------------------------------------


def test_capabilities_are_derived_from_content_not_claimed_by_the_submitter():
    """A spec cannot talk a probe into running by asserting a capability: the
    key is not even read."""
    raw = dict(THIN, capabilities=["GOLD_TRAJECTORY", "SPLITS"])
    caps = build(raw).manifest().capabilities
    assert Capability.GOLD_TRAJECTORY not in caps
    assert Capability.SPLITS not in caps


def test_a_complete_spec_earns_the_capabilities_it_actually_supports():
    caps = build(FULL).manifest().capabilities
    for cap in (
        Capability.GOLD_TRAJECTORY,
        Capability.KNOWN_WRONG,
        Capability.GRADED_POLICIES,
        Capability.INVERTIBLE_SPEC,
        Capability.SPLITS,
        Capability.SEPARABLE_VERIFIER,
        Capability.TRUE_COMPLETION,
    ):
        assert cap in caps, cap


def test_an_always_pass_verifier_has_no_rule_to_invert():
    caps = build(dict(FULL, verifier="always_pass")).manifest().capabilities
    assert Capability.INVERTIBLE_SPEC not in caps


# -- the point of the whole thing -----------------------------------------


def test_a_thin_spec_is_unverified_not_valid():
    """The card must not read as a pass. This is the Space's entire risk."""
    report = audit(build(THIN))
    assert report.verdict == "UNVERIFIED"
    assert report.exit_code != 0
    assert not report.findings


def test_every_probe_that_could_not_run_carries_a_reason():
    report = audit(build(THIN))
    skipped = report.by_status(ProbeStatus.NOT_APPLICABLE)
    assert skipped, "a one-task spec with no splits must skip something"
    for result in skipped:
        assert result.reason


def test_no_probe_errors_on_a_thin_spec():
    """NOT_APPLICABLE is a finding about the environment; ERROR is a bug in us."""
    report = audit(build(THIN))
    assert report.by_status(ProbeStatus.ERROR) == []


# -- it finds real defects -------------------------------------------------


def test_a_substring_verifier_against_two_labels_is_caught():
    """The shape of the `paws` finding, written from scratch: a submission
    naming both labels satisfies a substring matcher on either target while
    answering neither task."""
    adapter = build(dict(FULL, verifier="includes", trivial_answers=["YesNo"]))
    report = audit(adapter)
    assert DefectClass.TRIVIAL_FLOOR_BREACH in report.detected
    assert report.verdict in ("DEFECTIVE", "INVALID")


def test_an_always_pass_verifier_is_flagged_as_unfalsifiable():
    report = audit(build(dict(FULL, verifier="always_pass")))
    assert DefectClass.NOOP_PASSES in report.detected


def test_a_leaked_eval_item_is_caught():
    leaked = dict(
        FULL,
        train=[{"item_id": "tr1", "text": "is 4 greater than 5", "label": "No"}],
        eval=[{"item_id": "ev1", "text": "is 4 greater than 5", "label": "No"}],
    )
    report = audit(build(leaked))
    assert DefectClass.CONTAMINATION_EXACT in report.detected


def test_a_healthy_spec_produces_no_findings():
    report = audit(build(FULL))
    assert report.findings == [], [f.summary() for f in report.findings]


# -- the honest-solve invariant -------------------------------------------


def test_true_completion_is_stricter_than_a_loose_verifier():
    """Otherwise the exploit gap is identically zero and the hackability probe
    measures nothing."""
    from assay.adapter import run_policy
    from assay.types import Action

    adapter = build(dict(FULL, verifier="includes"))
    transcript = run_policy(adapter, "q1", [Action("submit", {"answer": "YesNo"})])
    assert adapter.verify(transcript).passed is True
    assert adapter.true_completion(transcript) == 0.0


def test_the_ecosystem_is_spec_so_publishing_refuses_to_classify_it():
    """A submitted environment is neither ours nor a known third party's. The
    redistribution guard must refuse rather than guess -- see test_publish."""
    from assay.publish import OURS, THEIRS

    assert build(THIN).manifest().ecosystem not in OURS | THEIRS
