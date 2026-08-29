"""The parts of the BenchGuard scoring run that decide what a number means.

Two of them are load-bearing and neither is obvious:

* ``gold_still_present`` -- recall against a gold set silently assumes the
  defect is still in the text being read. For ScienceAgentBench that is false
  on the split SAB tells you to use, so the pipeline measures it per task
  instead of assuming.
* ``redact_gold_text`` -- BenchGuard's gold wording quotes ScienceAgentBench
  instructions, and `scienceagentbench` is in publish.py's THEIRS. Verdicts
  ship; their content does not.

No ScienceAgentBench or BenchGuard content appears here. The gold entries below
are fixtures in the shape of theirs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from assay.adapters.scienceagentbench import SabTask

_SPEC = importlib.util.spec_from_file_location(
    "sab_benchguard_recall",
    Path(__file__).resolve().parents[1] / "scripts" / "sab_benchguard_recall.py",
)
sab_scoring = importlib.util.module_from_spec(_SPEC)
sys.modules["sab_benchguard_recall"] = sab_scoring
_SPEC.loader.exec_module(sab_scoring)


def task(instance_id: int, instruction: str, output_fname: str = "out/x.csv") -> SabTask:
    return SabTask(
        instance_id=instance_id,
        task_inst=instruction,
        output_fname=output_fname,
        eval_script_name="e.py",
    )


GOLD = {
    "tasks": {
        "1": {
            "original_question": "Compute the mean and save it.",
            "updated_question": "Compute the median and save it.",
            "issues": [{"id": "1_issue_1", "description": "mean should be median"}],
        },
        "2": {
            "original_question": "Sort ascending.",
            "updated_question": "Sort descending.",
            "issues": [{"id": "2_issue_1", "description": "wrong sort order"}],
        },
        "3": {
            "original_question": "Round to 2dp.",
            "updated_question": "Round to 3dp.",
            "issues": [{"id": "3_issue_1", "description": "wrong precision"}],
        },
    }
}


def test_defect_present_when_the_split_still_has_the_old_wording():
    out = sab_scoring.gold_still_present([task(1, "Compute the mean and save it.")], GOLD)
    assert out["per_task"]["1"] == "defect_present"


def test_already_fixed_when_the_split_carries_the_correction():
    """The case that makes a recall number meaningless if it goes unnoticed."""
    out = sab_scoring.gold_still_present([task(2, "Sort descending.")], GOLD)
    assert out["per_task"]["2"] == "already_fixed_upstream"


def test_whitespace_is_not_treated_as_a_difference():
    out = sab_scoring.gold_still_present(
        [task(1, "Compute   the mean\n  and save it.")], GOLD
    )
    assert out["per_task"]["1"] == "defect_present"


def test_third_wording_is_flagged_rather_than_bucketed():
    out = sab_scoring.gold_still_present([task(3, "Round to 4dp.")], GOLD)
    assert out["per_task"]["3"] == "differs_from_both"


def test_task_missing_from_the_split_is_reported_not_skipped():
    out = sab_scoring.gold_still_present([], GOLD)
    assert set(out["per_task"].values()) == {"absent_from_split"}
    assert out["counts"]["absent_from_split"] == 3


def test_counts_cover_every_gold_task():
    out = sab_scoring.gold_still_present(
        [task(1, "Compute the mean and save it."), task(2, "Sort descending.")], GOLD
    )
    assert sum(out["counts"].values()) == len(GOLD["tasks"])


# -- the rejected heuristic ------------------------------------------------


@pytest.mark.parametrize(
    ("instruction", "output_fname", "fires"),
    [
        ('Save it to "out/x.csv".', "out/x.csv", False),
        ("Save it to `out/x.csv`.", "out/x.csv", False),
        ("Save the results.", "out/x.csv", True),
        ('Read "in/y.csv" and save the results.', "out/x.csv", True),
    ],
)
def test_r1_fires_only_when_the_instruction_never_names_the_output(
    instruction, output_fname, fires
):
    assert sab_scoring.output_path_unstated(task(1, instruction, output_fname)) is fires


def test_r1_records_are_labelled_as_not_part_of_assay():
    """It must be impossible to read this arm as a shipped Assay capability."""
    _, detail = sab_scoring.rejected_r1_records([task(1, "Save the results.")])
    assert detail["status"] == "REJECTED - not part of Assay"
    assert "trivial-floor" in detail["why_rejected"]


def test_r1_emits_a_record_for_every_task_even_when_silent():
    """Their converter aborts unless every gold task has an audit record."""
    records, _ = sab_scoring.rejected_r1_records(
        [task(1, 'Save it to "out/x.csv".'), task(2, "Save the results.")]
    )
    assert set(records) == {"1", "2"}
    assert records["1"]["findings"] == []
    assert len(records["2"]["findings"]) == 1


# -- redistribution --------------------------------------------------------


def test_redaction_drops_gold_wording_but_keeps_the_verdict():
    report = {
        "recall": {"aligned": {"count": 0, "total": 12, "rate": 0.0}},
        "per_issue_detail": [
            {
                "issue_id": "1_issue_1",
                "task_id": "1",
                "description": "Changed 'the mean' to 'the median'.",
                "best_verdict": "MISSED",
            }
        ],
    }

    out = sab_scoring.redact_gold_text(report)
    issue = out["per_issue_detail"][0]

    assert "description" not in issue
    assert issue["best_verdict"] == "MISSED"
    assert issue["issue_id"] == "1_issue_1"
    # A digest, so a reader can confirm they hold the same gold file.
    assert len(issue["description_sha256"]) == 64
    assert out["recall"]["aligned"]["total"] == 12
    assert "_redaction" in out


def test_redaction_does_not_mutate_the_caller_s_report():
    report = {"per_issue_detail": [{"issue_id": "x", "description": "secret"}]}
    sab_scoring.redact_gold_text(report)
    assert report["per_issue_detail"][0]["description"] == "secret"
