"""Ecosystems register themselves, and a missing runtime is never silent."""

from __future__ import annotations

from assay.corpus import availability, entries, ground_truth, providers, unavailable


def test_ecosystems_are_discovered_not_hardcoded():
    """Adding an ecosystem means adding a `_<name>_corpus.py`, never editing a
    shared registration function -- which is the file three workstreams would
    otherwise collide on."""
    found = set(providers())
    assert {"fixture", "inspect_ai", "harbor"} <= found


def test_fixtures_need_no_runtime():
    usable, reason = availability()["fixture"]
    assert usable, reason


def test_an_unavailable_ecosystem_reports_a_reason():
    """A corpus that shrank because Docker was not running would make every arm
    look better than it is."""
    for name, (usable, reason) in availability().items():
        assert reason, name
        if not usable:
            assert name in unavailable()
            assert len(reason) > 10, "a reason must say something useful"


def test_only_and_skip_select_ecosystems():
    just_fixtures = entries(only=["fixture"])
    assert just_fixtures
    assert all(env_id.startswith("fixture/") for env_id, _, _ in just_fixtures)
    assert not any(
        env_id.startswith("fixture/") for env_id, _, _ in entries(skip=["fixture"])
    )


def test_ground_truth_covers_every_entry():
    corpus = entries()
    truth = ground_truth()
    assert set(truth) == {env_id for env_id, _, _ in corpus}


def test_env_ids_are_unique():
    ids = [env_id for env_id, _, _ in entries()]
    assert len(ids) == len(set(ids)), "a duplicate id would silently overwrite a result row"


def test_every_environment_declares_provenance():
    """An undeclared environment must fail, not default to clean.

    `frozenset()` is ambiguous: it is what a verified-clean environment carries
    and what an environment nobody looked at carries. Under `research-run` a
    clean environment is worth 14 free points against `flag_everything`, so a
    corpus can be grown into a better headline without anyone lying. The
    registry defaults to UNAUDITED and this test refuses it.
    """
    from assay.corpus import UNDECLARED, provenance

    declared = provenance()
    undeclared = sorted(e for e, p in declared.items() if p == UNDECLARED)
    assert not undeclared, (
        "these environments register no provenance, so their empty defect set "
        f"cannot be distinguished from 'not audited': {undeclared}"
    )


def test_an_empty_defect_set_is_never_silently_clean():
    """Every environment with no planted defects must say why it has none."""
    from assay.corpus import LabelSource, ground_truth, provenance

    truth, declared = ground_truth(), provenance()
    for env_id, defects in sorted(truth.items()):
        if defects:
            continue
        p = declared[env_id]
        assert p.label_source is not LabelSource.UNAUDITED, (
            f"{env_id} has no planted defects and no label source: it would "
            "score as a clean environment on the strength of nobody checking"
        )
        assert p.note, f"{env_id} claims no defects without saying on what basis"
