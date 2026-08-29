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


def test_the_corpus_split_is_published_on_provenance():
    """Split on who wrote the environment, not on the id prefix.

    Splitting on the `fixture/` prefix produced a README sentence claiming
    Assay loses on "the twelve environments this repo did not write" -- it
    wrote ten of them.
    """
    d = _load("corpus_splits.json")
    splits = d["splits"]
    assert {"external-envs", "self-authored", "third-party-format",
            "in-process-fixtures", "no-harbor"} <= set(splits)
    assert "provenance" in d, "the split is only trustworthy if provenance ships with it"

    research = splits["third-party-format"]["profiles"]["research-run"]
    assert research["assay"]["expected_loss"] > research["flag_everything"]["expected_loss"], (
        "Assay now beats the floor on third-party-format environments -- good, "
        "but the README says it loses there and must be updated with this."
    )
    assert splits["in-process-fixtures"]["profiles"]["research-run"]["assay"]["expected_loss"] == 0.0


def test_the_readme_does_not_claim_a_third_party_corpus_it_does_not_have():
    """Only 2 of 24 environments are genuinely external."""
    d = _load("corpus_splits.json")
    assert d["splits"]["external-envs"]["n_environments"] == 2
    assert "the twelve environments this repo did not write" not in README


def test_the_readme_does_not_advertise_a_signed_card():
    """It is an unkeyed digest unless ASSAY_CARD_KEY is set."""
    assert "signed Environment Card" not in README


def test_the_quickstart_command_produces_the_advertised_corpus():
    """--extra adapters alone omits openenv and gives 22 environments, not 24."""
    for line in README.splitlines():
        if "scripts/full_run.py" in line and "uv run" in line:
            assert "--extra openenv" in line, line


def test_the_published_example_card_matches_the_current_renderer():
    """`results/example-card.md` is the sample deliverable a judge reads.

    It is a committed artifact of a live renderer, so a field rename leaves it
    stale and nothing notices -- which is exactly what happened when
    `signature` became `content_digest`. This renders a card now and asserts
    the published one uses the same vocabulary.
    """
    from assay import audit
    from assay.card import to_markdown
    from assay.fixtures import build

    published = (ROOT / "results" / "example-card.md").read_text()
    fresh = to_markdown(audit(build("gold_broken"), {"solve_rates": {}}))

    for label in ("| Content digest |", "Produced by Assay. Unkeyed content digest"):
        assert label in fresh, f"renderer no longer emits {label!r}; update this test"
        assert label in published, (
            f"results/example-card.md is stale: the renderer emits {label!r} and the "
            "published card does not. Regenerate it with "
            "`uv run --extra adapters assay audit inspect/effort-scorer "
            "--card results/example-card.md`."
        )
    assert "| Signature |" not in published
