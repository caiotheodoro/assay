"""Run every probe against one environment and collect the result.

The runner is deliberately dumb: it applies every registered probe and records
what happened, including what could not run and why. Deciding which probes are
worth running, and reading the results, is the Auditor agent's job -- keeping
that judgement out of here is what makes the numbers reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .adapter import EnvAdapter
from .probes import all_probes
from .types import (
    DefectClass,
    Finding,
    ProbeResult,
    ProbeStatus,
    Severity,
    canonical_json,
    digest,
    sign,
)


@dataclass
class AuditReport:
    env_id: str
    ecosystem: str
    env_version: str
    results: list[ProbeResult] = field(default_factory=list)
    #: Judgements the Auditor applied, if one ran. Empty for every
    #: deterministic audit, and omitted from the card body when empty so
    #: that adding this field did not move a single existing digest.
    auditor_overrides: list[dict[str, Any]] = field(default_factory=list)

    # -- views -------------------------------------------------------------

    @property
    def findings(self) -> list[Finding]:
        return [f for r in self.results for f in r.findings]

    @property
    def detected(self) -> set[DefectClass]:
        return {f.defect for f in self.findings}

    def by_status(self, status: ProbeStatus) -> list[ProbeResult]:
        return [r for r in self.results if r.status is status]

    @property
    def coverage(self) -> dict[str, int]:
        return {
            s.value: len(self.by_status(s))
            for s in (
                ProbeStatus.PASS,
                ProbeStatus.DEFECT,
                ProbeStatus.NOT_APPLICABLE,
                ProbeStatus.ERROR,
            )
        }

    @property
    def verdict(self) -> str:
        """Fail closed. An environment that could not be probed is not 'clean'."""
        if self.by_status(ProbeStatus.ERROR):
            return "INCONCLUSIVE"
        severities = {f.severity for f in self.findings}
        if Severity.CRITICAL in severities:
            return "INVALID"
        if severities:
            return "DEFECTIVE"
        if self.by_status(ProbeStatus.NOT_APPLICABLE):
            return "UNVERIFIED"
        return "VALID"

    @property
    def exit_code(self) -> int:
        return 0 if self.verdict == "VALID" else 1

    def to_dict(self) -> dict[str, Any]:
        body = {
            "env_id": self.env_id,
            "ecosystem": self.ecosystem,
            "env_version": self.env_version,
            "verdict": self.verdict,
            "coverage": self.coverage,
            "probes": [
                {
                    "family": r.family,
                    "probe": r.probe,
                    "status": r.status.value,
                    "reason": r.reason,
                    "findings": [
                        {
                            "defect": f.defect.value,
                            "severity": f.severity.value,
                            "task_id": f.task_id,
                            "evidence": f.evidence,
                        }
                        for f in r.findings
                    ],
                    "detail": r.detail,
                }
                for r in self.results
            ],
        }
        if self.auditor_overrides:
            body["auditor_overrides"] = self.auditor_overrides
        # A content digest identifies this card and catches corruption. It is
        # not tamper-evidence: anyone editing the body can recompute it. When
        # ASSAY_CARD_KEY is set the card also carries a keyed HMAC, which is.
        # Both attest the same bare body, so either can be checked alone.
        sig = sign(body)
        body["content_digest"] = digest(body)
        if sig is not None:
            body["hmac_sha256"] = sig
        return body

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def audit(adapter: EnvAdapter, ctx: dict[str, Any] | None = None) -> AuditReport:
    manifest = adapter.manifest()
    report = AuditReport(
        env_id=manifest.env_id, ecosystem=manifest.ecosystem, env_version=manifest.version
    )
    for probe in all_probes():
        report.results.append(probe.run(adapter, ctx))
    return report
