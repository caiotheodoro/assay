"""Inter-rater agreement arithmetic, and the blinding that makes it mean anything.

The measured kappa lives in `results/label_agreement.json` -- it is a fact about
two labellings and moves when either does. What is pinned here is the maths, and
the one property the whole exercise rests on: a second labelling that was shown
the answer key is worse than none, so the redaction is tested, not trusted.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from assay.agreement import (
    cells,
    cohen_kappa,
    compare,
    confusion,
    interpret,
    per_class,
    per_environment,
    percent_agreement,
)
from assay.types import DefectClass

REPO = Path(__file__).resolve().parents[1]

D = DefectClass


def _load_second_labelling_module():
    spec = importlib.util.spec_from_file_location(
        "second_labelling", REPO / "scripts" / "second_labelling.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identical_labellings_give_kappa_one():
    a = {"e1": frozenset({D.GOLD_FAILS}), "e2": frozenset()}
    assert cohen_kappa(cells(a, dict(a))) == pytest.approx(1.0)


def test_kappa_is_none_when_there_is_no_variation_to_correct():
    """Both raters said 'no defect' in every cell. Percent agreement is 1.0 and
    means nothing; reporting kappa = 1.0 there would claim perfect agreement on
    a comparison carrying no information."""
    a = {"e1": frozenset(), "e2": frozenset()}
    grid = cells(a, dict(a))
    assert percent_agreement(grid) == 1.0
    assert cohen_kappa(grid) is None


def test_kappa_is_far_below_percent_agreement_on_a_sparse_grid():
    """The reason kappa is the number to report. One class right, one wrong, out
    of 14 classes: percent agreement is high before anyone has read anything."""
    a = {"e1": frozenset({D.GOLD_FAILS})}
    b = {"e1": frozenset({D.NOOP_PASSES})}
    grid = cells(a, b)
    assert percent_agreement(grid) > 0.85
    assert cohen_kappa(grid) < 0.0


def test_kappa_can_go_negative_when_raters_are_worse_than_chance():
    a = {"e1": frozenset({D.GOLD_FAILS}), "e2": frozenset()}
    b = {"e1": frozenset(), "e2": frozenset({D.GOLD_FAILS})}
    assert cohen_kappa(cells(a, b)) < 0
    assert interpret(cohen_kappa(cells(a, b))) == "worse than chance"


def test_the_unit_is_a_cell_not_an_environment():
    """Two raters who both call an environment defective but name different
    families agree on nothing that matters."""
    a = {"e1": frozenset({D.GOLD_FAILS})}
    b = {"e1": frozenset({D.REWARD_HACKABLE})}
    conf = confusion(cells(a, b))
    assert conf["both_yes"] == 0
    assert conf["a_only"] == 1 and conf["b_only"] == 1
    assert conf["n"] == len(DefectClass)


def test_the_grid_includes_classes_neither_rater_used():
    """Dropping them would remove the true negatives kappa's chance correction
    is computed from, and inflate it."""
    a = {"e1": frozenset({D.GOLD_FAILS})}
    grid = cells(a, dict(a))
    assert len(grid) == len(DefectClass)
    assert {c.defect for c in grid} == set(DefectClass)


def test_per_environment_reports_which_side_each_disagreement_came_from():
    a = {"e1": frozenset({D.GOLD_FAILS, D.NOOP_PASSES})}
    b = {"e1": frozenset({D.NOOP_PASSES, D.REWARD_HACKABLE})}
    row = per_environment(a, b)[0]
    assert row["a_only"] == ["GOLD_FAILS"]
    assert row["b_only"] == ["REWARD_HACKABLE"]
    assert not row["exact_set_match"]
    assert row["jaccard"] == pytest.approx(1 / 3, abs=1e-4)


def test_per_class_carries_the_numbers_needed_to_discount_a_rare_class():
    """One rater used the class once, the other never. Percent agreement is
    2/3 and kappa is exactly 0 -- they agree at chance. Both numbers are
    published because either alone is misleading at this prevalence."""
    a = {"e1": frozenset({D.SHORTCUT_LEAK}), "e2": frozenset(), "e3": frozenset()}
    b = {"e1": frozenset(), "e2": frozenset(), "e3": frozenset()}
    row = per_class(cells(a, b))["SHORTCUT_LEAK"]
    assert row["prevalence_rater_a"] == pytest.approx(1 / 3, abs=1e-4)
    assert row["prevalence_rater_b"] == 0.0
    assert row["n"] == 3
    assert row["percent_agreement"] == pytest.approx(2 / 3, abs=1e-4)
    assert row["kappa"] == 0.0


def test_per_class_kappa_is_undefined_when_neither_rater_used_the_class():
    """Distinct from kappa == 0. Zero means 'they agreed at chance'; undefined
    means 'there was nothing to agree about', and a reader must be able to tell
    those apart on a corpus where most classes are rare."""
    a = {"e1": frozenset({D.SHORTCUT_LEAK}), "e2": frozenset()}
    row = per_class(cells(a, dict(a)))["GOLD_FAILS"]
    assert row["kappa"] is None
    assert "no variation" in row["kappa_undefined_reason"]


def test_reported_kappa_never_serialises_as_negative_zero():
    a = {"e1": frozenset({D.SHORTCUT_LEAK}), "e2": frozenset(), "e3": frozenset()}
    b = {"e1": frozenset(), "e2": frozenset(), "e3": frozenset()}
    value = per_class(cells(a, b))["SHORTCUT_LEAK"]["kappa"]
    assert str(value) == "0.0", "-0.0 reads as slightly worse than chance"


def test_compare_lists_environments_only_one_rater_covered():
    """A rater that failed on an environment must not silently shrink the
    comparison -- that is how a corpus quietly gets easier."""
    a = {"e1": frozenset(), "e2": frozenset()}
    b = {"e1": frozenset()}
    block = compare(a, b, resamples=0)
    assert block["environments_only_one_rater_covered"] == ["e2"]
    assert block["n_environments"] == 1


def test_bootstrap_resamples_environments_not_cells():
    """The 14 cells of one environment are not 14 independent judgements: a
    rater who misreads one verifier gets the whole row wrong at once."""
    a = {f"e{i}": frozenset({D.GOLD_FAILS}) if i % 2 else frozenset() for i in range(12)}
    b = {f"e{i}": frozenset({D.GOLD_FAILS}) if i % 3 else frozenset() for i in range(12)}
    block = compare(a, b, resamples=500, seed=11)
    bs = block["bootstrap"]
    assert bs["resampling_unit"] == "environment"
    assert bs["ci95"][0] <= bs["point"] <= bs["ci95"][1]


def test_bootstrap_is_reproducible_from_its_seed():
    a = {f"e{i}": frozenset({D.GOLD_FAILS}) if i % 2 else frozenset() for i in range(10)}
    b = {f"e{i}": frozenset({D.NOOP_PASSES}) if i % 3 else frozenset() for i in range(10)}
    first = compare(a, b, resamples=300, seed=7)["bootstrap"]
    second = compare(a, b, resamples=300, seed=7)["bootstrap"]
    assert first["ci95"] == second["ci95"]


# -- the blinding -----------------------------------------------------------


def test_redaction_strips_every_defect_class_name_from_the_real_bundles():
    """The property the whole exercise rests on. A 'blinded' second labelling
    that saw the answer key produces a kappa that looks like evidence and is
    not."""
    module = _load_second_labelling_module()
    from assay.corpus import ground_truth

    for env_id in sorted(ground_truth()):
        bundle, _files = module.bundle_for(env_id)
        leaked = [d.value for d in DefectClass if d.value in bundle]
        assert not leaked, f"{env_id} bundle leaks {leaked}"


def test_assert_blind_refuses_a_leaking_bundle():
    module = _load_second_labelling_module()
    with pytest.raises(SystemExit, match="REFUSING"):
        module.assert_blind("this text mentions REWARD_HACKABLE", "env")


def test_redaction_removes_catalogue_lines_not_just_class_names():
    module = _load_second_labelling_module()
    redacted = module.redact("CATALOG = {\n  'x': 1,\n}\nkeep = 2\n")
    assert "CATALOG" not in redacted
    assert "keep = 2" in redacted


def test_the_taxonomy_defines_every_class_the_rater_may_use():
    """A rater given an undefined label has to guess what it means, and its
    disagreement then measures the prompt rather than the corpus."""
    module = _load_second_labelling_module()
    assert set(module.DEFINITIONS) == set(DefectClass)
    assert all(text.strip() for text in module.DEFINITIONS.values())


def test_parse_rejects_a_reply_that_names_a_class_outside_the_taxonomy():
    module = _load_second_labelling_module()
    defects, _reasoning, note = module.parse('{"defects": ["GOLD_FAILS", "MADE_UP"]}')
    assert defects == frozenset({D.GOLD_FAILS})
    assert "MADE_UP" in note


def test_parse_reports_an_unparseable_reply_rather_than_an_empty_labelling():
    """An empty defect set is a real answer -- the corpus has healthy
    environments. A failed parse must not become one."""
    module = _load_second_labelling_module()
    defects, _reasoning, note = module.parse("I could not decide.")
    assert defects == frozenset()
    assert note and "unparseable" in note


def test_majority_pooling_is_not_biased_by_the_number_of_runs():
    """Union gets more defect-happy with k and intersection more conservative;
    neither converges on what the rater believes."""
    spec = importlib.util.spec_from_file_location(
        "label_agreement", REPO / "scripts" / "label_agreement.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runs = [
        {"e1": ["GOLD_FAILS"]},
        {"e1": ["GOLD_FAILS"]},
        {"e1": ["NOOP_PASSES"]},
    ]
    assert module.majority(runs)["e1"] == frozenset({D.GOLD_FAILS})
    assert module.majority(runs[:1] + runs[2:])["e1"] == frozenset()
