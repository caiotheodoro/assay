"""Lock the corrections a red-team pass had to find by hand.

Each test here failed silently for weeks. They are not testing behaviour --
they are testing that a number this repository publishes is still sourced from
the artifact it claims to come from, which is the failure mode this whole
project exists to catch and did not catch in itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()


def _load(name: str) -> dict:
    path = ROOT / "results" / name
    if not path.exists():
        pytest.skip(f"{name} not generated")
    return json.loads(path.read_text())


def test_tau2_recall_is_reported_against_a_floor():
    """The trivial-floor rule applies to the auditor, not only to environments."""
    d = _load("tau2_recall.json")
    assert "trivial_floor" in d, "no floor reported for the external measurement"
    for row in ("combined", "combined_excluding_advisory_probe"):
        sig = d[row]["significance"]
        assert "p_one_sided" in sig and "base_rate" in sig


def test_the_headline_tau2_row_is_still_indistinguishable_from_random():
    """If this ever fails, the README's framing must change with it.

    Not a claim that 0.339 is bad -- a claim that the README currently says it
    is chance, and must not go on saying so if the measurement improves.
    """
    d = _load("tau2_recall.json")
    assert d["combined"]["significance"]["beats_random_at_0.05"] is False
    assert d["combined_excluding_advisory_probe"]["significance"]["beats_random_at_0.05"] is True
    assert "The 0.339 row is chance" in README


def test_the_corpus_split_is_published():
    """Half the corpus is our own fixtures; pooling hid that Assay loses on the rest."""
    d = _load("corpus_splits.json")
    splits = d["splits"]
    assert {"no-fixture", "fixture-only", "no-harbor"} <= set(splits)

    research = splits["no-fixture"]["profiles"]["research-run"]
    assert research["assay"]["expected_loss"] > research["flag_everything"]["expected_loss"], (
        "Assay now beats the floor on non-fixture environments -- good, but the "
        "README says it loses there and must be updated with this."
    )
    assert splits["fixture-only"]["profiles"]["research-run"]["assay"]["expected_loss"] == 0.0


def test_the_readme_does_not_advertise_a_signed_card():
    """It is an unkeyed digest unless ASSAY_CARD_KEY is set."""
    assert "signed Environment Card" not in README


def test_the_quickstart_command_produces_the_advertised_corpus():
    """--extra adapters alone omits openenv and gives 22 environments, not 24."""
    for line in README.splitlines():
        if "scripts/full_run.py" in line and "uv run" in line:
            assert "--extra openenv" in line, line
