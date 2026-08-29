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


# -- probe bodies: which probes ran, and why the rest did not ---------------
#
# The card's "what could not be checked" section is the part that stops an
# empty card reading as a clean bill of health, so it has to travel for THIRD
# PARTY environments too. That makes the payload carry probe bodies, and the
# guard has to cover them as tightly as it covers cards.


def _probe_body(env_id, ecosystem, **over):
    body = {
        "env_id": env_id,
        "ecosystem": ecosystem,
        "verdict": "UNVERIFIED",
        "coverage": {"PASS": 1, "DEFECT": 0, "NOT_APPLICABLE": 1, "ERROR": 0},
        "content_included": ecosystem in OURS,
        "probes": [
            {
                "family": "contamination",
                "probe": "train_eval_leak",
                "status": "NOT_APPLICABLE",
                "reason": "environment does not expose: SPLITS",
                "n_findings": 0,
                "detail": {},
            }
        ],
    }
    body.update(over)
    return body


def test_a_third_party_probe_body_may_ship_when_it_carries_no_findings():
    """"This probe could not run, because the environment exposes no train
    split" is a fact ABOUT the environment, not a copy of it."""
    payload = Payload(
        rows=[_row("inspect_ai/paws", "inspect_ai", False)],
        probes={"inspect_ai/paws": _probe_body("inspect_ai/paws", "inspect_ai")},
    )
    verify_no_redistribution(payload)  # does not raise


def test_a_third_party_probe_body_carrying_findings_is_refused():
    """Findings quote task ids and item text. That is a copy."""
    body = _probe_body("inspect_ai/paws", "inspect_ai")
    body["probes"][0]["findings"] = [{"defect": "REWARD_HACKABLE", "task_id": "7531"}]
    payload = Payload(
        rows=[_row("inspect_ai/paws", "inspect_ai", False)],
        probes={"inspect_ai/paws": body},
    )
    with pytest.raises(RedistributionRefused, match="carries findings"):
        verify_no_redistribution(payload)


def test_a_third_party_probe_body_marked_for_inclusion_is_refused():
    payload = Payload(
        rows=[_row("openenv/echo", "openenv", False)],
        probes={"openenv/echo": _probe_body("openenv/echo", "openenv", content_included=True)},
    )
    with pytest.raises(RedistributionRefused, match="probe body marked for inclusion"):
        verify_no_redistribution(payload)


def test_an_unlisted_detail_key_is_refused_rather_than_published_by_default():
    """A probe added later must not silently start shipping someone's data
    because it happened to put it in `detail`."""
    body = _probe_body("inspect_ai/paws", "inspect_ai")
    body["probes"][0]["detail"] = {"n_eval": 25, "sample_texts": ["..."]}
    payload = Payload(
        rows=[_row("inspect_ai/paws", "inspect_ai", False)],
        probes={"inspect_ai/paws": body},
    )
    with pytest.raises(RedistributionRefused, match="sample_texts"):
        verify_no_redistribution(payload)


def test_a_real_build_publishes_skip_reasons_for_third_party_environments():
    """The point of carrying them at all: a reader can see what was NOT checked
    on someone else's environment without receiving any of it."""
    payload = build()
    third_party = [r["env_id"] for r in payload.rows if r["ecosystem"] in THEIRS]
    assert third_party, "the corpus should contain third-party environments"
    for env_id in third_party:
        body = payload.probes[env_id]
        assert body["content_included"] is False
        assert body["probes"], env_id
        for probe in body["probes"]:
            assert "findings" not in probe
            if probe["status"] in ("NOT_APPLICABLE", "ERROR"):
                assert probe["reason"], f"{env_id}/{probe['probe']}"
