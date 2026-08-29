"""Publishing must refuse to carry other people's benchmarks.

Auditing someone's environment does not make it ours to republish, and the
check is code rather than a note in a README because a published artifact is
not something you fix afterwards.
"""

from __future__ import annotations

import pytest

from assay.publish import (
    OURS,
    THEIRS,
    Payload,
    RedistributionRefused,
    build,
    verify_no_redistribution,
    write,
)


def _row(env_id, ecosystem, content_included):
    return {
        "env_id": env_id,
        "ecosystem": ecosystem,
        "verdict": "VALID",
        "detected": [],
        "coverage": {},
        "content_included": content_included,
    }


def test_our_own_environments_may_ship_in_full():
    payload = Payload(rows=[_row("fixture/healthy", "fixture", True)])
    verify_no_redistribution(payload)  # does not raise


def test_third_party_content_is_refused():
    payload = Payload(rows=[_row("inspect_ai/paws", "inspect_ai", True)])
    with pytest.raises(RedistributionRefused, match="content marked for inclusion"):
        verify_no_redistribution(payload)


def test_a_verdict_about_third_party_software_may_ship():
    """The line is between a claim and a copy. 'paws scores a constant string at
    100%' carries no benchmark content to redistribute."""
    payload = Payload(rows=[_row("inspect_ai/paws", "inspect_ai", False)])
    verify_no_redistribution(payload)


def test_an_unclassified_ecosystem_is_refused_rather_than_guessed():
    payload = Payload(rows=[_row("newthing/x", "newthing", False)])
    with pytest.raises(RedistributionRefused, match="not classified"):
        verify_no_redistribution(payload)


def test_a_card_for_someone_elses_environment_is_refused():
    payload = Payload(
        rows=[_row("openenv/echo", "openenv", False)],
        cards={"openenv/echo": "# Environment Card"},
    )
    with pytest.raises(RedistributionRefused, match="card for an ecosystem"):
        verify_no_redistribution(payload)


def test_ours_and_theirs_do_not_overlap():
    assert not (OURS & THEIRS)


def test_a_real_build_classifies_every_environment(tmp_path):
    payload = build()
    assert payload.rows
    for row in payload.rows:
        assert row["ecosystem"] in OURS | THEIRS, row["env_id"]
        if row["ecosystem"] in THEIRS:
            assert row["content_included"] is False
            assert row["planted_defects"] is None
            assert "not redistributed" in row["note"]
    out = write(payload, tmp_path / "artifact")
    assert (out / "corpus.jsonl").exists()
    assert (out / "manifest.json").exists()
    for card in (out / "cards").glob("*.md"):
        assert not card.name.startswith(("inspect_ai", "openenv"))
