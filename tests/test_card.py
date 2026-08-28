"""The card must not let an unverified environment read as a clean one."""

from __future__ import annotations

from assay import audit
from assay.card import to_html, to_markdown
from assay.fixtures import build
from assay.types import digest

IN_BAND = {"solve_rates": {"t1": 0.4, "t2": 0.5, "t3": 0.6}}


def test_an_unverified_card_says_so_where_a_reader_will_see_it():
    card = to_markdown(audit(build("healthy")))
    assert "UNVERIFIED" in card
    assert "not a clean bill of health" in card
    assert "## What could not be checked" in card
    assert "difficulty_band" in card


def test_a_fully_probed_clean_environment_says_every_probe_ran():
    card = to_markdown(audit(build("healthy"), IN_BAND))
    assert "VALID" in card
    assert "Nothing. Every probe ran." in card


def test_findings_are_ordered_by_severity():
    card = to_markdown(audit(build("solved_at_reset")))
    assert card.index("### CRITICAL") < card.index("### HIGH")


def test_every_finding_carries_its_evidence():
    card = to_markdown(audit(build("paraphrased_splits")))
    assert "estimated_jaccard" in card
    assert "threshold" in card


def test_an_unsigned_card_blocks_nothing_and_says_so():
    card = to_markdown(audit(build("weak_oracle")))
    assert "_Unsigned._" in card
    assert "blocks nothing until a human reviews it" in card


def test_a_signed_card_names_the_reviewer():
    card = to_markdown(audit(build("weak_oracle")), signed_by="a reviewer")
    assert "signed by **a reviewer**" in card
    assert "_Unsigned._" not in card


def test_the_signature_in_the_card_matches_the_report():
    report = audit(build("healthy"), IN_BAND)
    body = report.to_dict()
    signature = body.pop("signature")
    assert signature == digest(body)
    assert signature in to_markdown(report)


def test_html_is_self_contained_and_theme_aware():
    html = to_html(audit(build("weak_oracle")))
    assert "prefers-color-scheme" in html
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html
