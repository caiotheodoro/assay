"""Verdicts must fail closed, and the card must be tamper-evident."""

from __future__ import annotations

import json

from assay import audit
from assay.fixtures import build
from assay.types import CARD_KEY_ENV, ProbeStatus, digest, verify


#: In-band solve rates, so the difficulty probe can actually run.
IN_BAND = {"solve_rates": {"t1": 0.4, "t2": 0.5, "t3": 0.6}}


def test_healthy_with_full_coverage_is_valid_and_exits_zero():
    report = audit(build("healthy"), IN_BAND)
    assert report.verdict == "VALID", [f.summary() for f in report.findings]
    assert report.exit_code == 0


def test_unrunnable_probe_blocks_a_clean_verdict():
    """No defects found is not the same as no defects. An environment we could
    not fully probe is UNVERIFIED, and still exits nonzero."""
    report = audit(build("healthy"))
    assert report.verdict == "UNVERIFIED"
    assert report.exit_code == 1


def test_critical_defect_makes_the_environment_invalid():
    report = audit(build("unfalsifiable"))
    assert report.verdict == "INVALID"
    assert report.exit_code == 1


def test_medium_only_defect_is_defective_not_invalid():
    report = audit(build("rationale_ignored"))
    assert report.verdict == "DEFECTIVE"
    assert report.exit_code == 1


def test_content_digest_covers_the_body():
    body = audit(build("healthy"), IN_BAND).to_dict()
    assert body.pop("content_digest") == digest(body)


def test_unkeyed_card_carries_no_hmac(monkeypatch):
    """An unsigned card must not look signed."""
    monkeypatch.delenv(CARD_KEY_ENV, raising=False)
    assert "hmac_sha256" not in audit(build("healthy"), IN_BAND).to_dict()


def test_hmac_detects_the_forgery_a_digest_cannot(monkeypatch):
    """The red-team forged a card by re-digesting it. A key stops that."""
    monkeypatch.setenv(CARD_KEY_ENV, "test-key")
    body = audit(build("gold_broken"), IN_BAND).to_dict()
    sig = body.pop("hmac_sha256")
    body.pop("content_digest")
    assert verify(body, sig)

    body["verdict"] = "VALID"
    body["probe_results"] = []
    assert not verify(body, sig), "forged body verified against the original signature"
    # ...while the unkeyed digest certifies the forgery: recompute and it is
    # self-consistent, which is exactly the three-line forgery the red-team ran.
    forged = dict(body, content_digest=digest(body))
    assert forged.pop("content_digest") == digest(body)


def test_report_is_json_serialisable():
    payload = json.loads(audit(build("weak_oracle")).to_json())
    assert payload["verdict"] in {"INVALID", "DEFECTIVE", "UNVERIFIED", "INCONCLUSIVE"}
    assert payload["probes"]
