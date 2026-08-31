"""The ScienceAgentBench adapter, and the honesty properties it exists for.

The load-bearing property is not that the adapter audits SAB well -- it cannot,
and that is the finding. It is that a metadata-only SAB produces twelve
NOT_APPLICABLE reasons and a verdict of UNVERIFIED, rather than a clean bill of
health, because "Assay ran and found nothing" and "Assay could not run" are the
two claims this project most needs to keep apart.

No ScienceAgentBench content appears in this file. The eval script written
below is a fixture: it is the SHAPE of a SAB eval script, not any of theirs.
"""

from __future__ import annotations

import pytest

# The adapter reads SAB's splits through pandas and huggingface_hub, both in
# `--extra sab`. Without them this module raised ModuleNotFoundError on a
# `uv sync --extra dev` clone instead of skipping, so the first command in the
# README reported a failure that is really a missing optional dependency.
pytest.importorskip("pandas", reason="needs --extra sab")
pytest.importorskip("huggingface_hub", reason="needs --extra sab")

from assay.adapter import NotSupported
from assay.adapters.scienceagentbench import (
    SPLITS,
    SabTask,
    ScienceAgentBenchAdapter,
)
from assay.runner import audit
from assay.types import ProbeStatus

CSV_TASK = SabTask(
    instance_id=7,
    task_inst='Fit a curve and save the coefficients to "pred_results/fit.csv".',
    output_fname="pred_results/fit.csv",
    eval_script_name="fit_eval.py",
    gold_program_name="fit.py",
    domain="Chemistry",
)

PNG_TASK = SabTask(
    instance_id=8,
    task_inst="Plot the spectrum.",
    output_fname="pred_results/spectrum.png",
    eval_script_name="spectrum_eval.py",
    gold_program_name="spectrum.py",
    domain="Physics",
)


def test_task_id_is_the_bare_int_benchguard_keys_on():
    # BenchGuard's gold standard keys tasks by "9", not "task_009".
    assert CSV_TASK.task_id == "7"


@pytest.mark.parametrize(
    ("output_fname", "judged"),
    [
        ("pred_results/x.png", True),
        ("pred_results/x.TIF", True),
        ("pred_results/x.csv", False),
        ("pred_results/x.json", False),
        ("pred_results/x.npy", False),
    ],
)
def test_image_outputs_are_flagged_as_llm_judged(output_fname, judged):
    """SAB judges visualization outputs with GPT-4o; those tasks are excluded."""
    task = SabTask(
        instance_id=1,
        task_inst="",
        output_fname=output_fname,
        eval_script_name="e.py",
    )
    assert task.llm_judged is judged


def test_metadata_only_declares_no_capabilities():
    adapter = ScienceAgentBenchAdapter([CSV_TASK, PNG_TASK])
    assert adapter.manifest().capabilities == frozenset()


def test_metadata_only_is_unverified_not_clean():
    """The whole point: no findings must not read as a clean bill of health."""
    report = audit(ScienceAgentBenchAdapter([CSV_TASK, PNG_TASK]))

    assert report.findings == []
    assert report.verdict == "UNVERIFIED"
    assert report.coverage["PASS"] == 0
    assert report.coverage["DEFECT"] == 0
    assert report.coverage["ERROR"] == 0
    assert report.coverage["NOT_APPLICABLE"] == len(report.results)


def test_every_probe_that_cannot_run_says_why():
    report = audit(ScienceAgentBenchAdapter([CSV_TASK]))
    for result in report.results:
        assert result.status is ProbeStatus.NOT_APPLICABLE
        assert result.reason, f"{result.probe} gave no reason"


def test_spec_probe_names_the_gated_archive():
    """A reader must be able to tell WHY family 6 could not run, and what fixes it."""
    report = audit(ScienceAgentBenchAdapter([CSV_TASK]))
    spec = next(r for r in report.results if r.family == "spec_verifier_match")
    assert "password-protected archive" in spec.reason
    assert "docs/SCIENCEAGENTBENCH.md" in spec.reason


def test_verifier_asserts_refuses_without_the_archive():
    adapter = ScienceAgentBenchAdapter([CSV_TASK])
    with pytest.raises(NotSupported, match="password-protected archive"):
        adapter.verifier_asserts("7")


def test_execution_surface_refuses_in_both_modes(tmp_path):
    """No benchmark_root, and a populated one, both refuse to execute."""
    (tmp_path / "eval_programs").mkdir()
    for adapter in (
        ScienceAgentBenchAdapter([CSV_TASK]),
        ScienceAgentBenchAdapter([CSV_TASK], benchmark_root=tmp_path),
    ):
        with pytest.raises(NotSupported):
            adapter.reset("7")
        with pytest.raises(NotSupported):
            adapter.verify(None)
        # Supplying eval scripts must never silently unlock execution probes.
        assert adapter.manifest().capabilities == frozenset()


def test_eval_programs_unlock_only_the_static_read(tmp_path):
    """With an eval script on disk, family 6 reads what the scorer checks."""
    programs = tmp_path / "eval_programs"
    programs.mkdir()
    # A fixture in the shape of a SAB eval script. Not any of theirs.
    (programs / "fit_eval.py").write_text(
        "def eval():\n"
        "    import json\n"
        "    got = json.load(open('pred_results/fit.csv'))\n"
        "    assert got['n_coefficients'] == 3\n"
        "    if got['rmse'] > 0.05:\n"
        "        return 0, 'rmse too high'\n"
        "    return 1, 'ok'\n"
    )
    adapter = ScienceAgentBenchAdapter([CSV_TASK], benchmark_root=tmp_path)

    claims = adapter.verifier_asserts("7")

    assert "got['n_coefficients'] == 3" in claims
    assert "got['rmse'] > 0.05" in claims


def test_verifier_asserts_reports_a_missing_script_rather_than_empty(tmp_path):
    """An absent eval script must not read as 'this verifier checks nothing'."""
    (tmp_path / "eval_programs").mkdir()
    adapter = ScienceAgentBenchAdapter([CSV_TASK], benchmark_root=tmp_path)
    with pytest.raises(NotSupported, match="not found"):
        adapter.verifier_asserts("7")


def test_verifier_asserts_reports_an_unparsable_script(tmp_path):
    programs = tmp_path / "eval_programs"
    programs.mkdir()
    (programs / "fit_eval.py").write_text("def eval( :\n")
    adapter = ScienceAgentBenchAdapter([CSV_TASK], benchmark_root=tmp_path)
    with pytest.raises(NotSupported, match="does not parse"):
        adapter.verifier_asserts("7")


def test_unknown_task_is_refused_not_guessed():
    adapter = ScienceAgentBenchAdapter([CSV_TASK])
    with pytest.raises(NotSupported, match="unknown task_id"):
        adapter.verifier_asserts("999")


def test_manifest_carries_the_judge_flag_for_downstream_exclusion():
    adapter = ScienceAgentBenchAdapter([CSV_TASK, PNG_TASK])
    flags = {t.task_id: t.metadata["llm_judged"] for t in adapter.manifest().tasks}
    assert flags == {"7": False, "8": True}


def test_ecosystem_is_the_one_publish_refuses_to_redistribute():
    """publish.py keys its redistribution refusal on this exact string."""
    from assay.publish import THEIRS

    assert ScienceAgentBenchAdapter([CSV_TASK]).manifest().ecosystem in THEIRS


def test_both_published_splits_are_addressable():
    assert set(SPLITS) == {"original", "verified"}


def test_unknown_split_is_rejected():
    from assay.adapters.scienceagentbench import load_tasks_from_hub

    with pytest.raises(ValueError, match="unknown split"):
        load_tasks_from_hub(split="nope")
