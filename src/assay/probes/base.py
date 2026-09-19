"""Probe base class and registry."""

from __future__ import annotations

from typing import Any, Callable, ClassVar

from ..adapter import EnvAdapter, NotSupported
from ..types import (
    Capability,
    DEFAULT_SEVERITY,
    DefectClass,
    Finding,
    ProbeResult,
    ProbeStatus,
)


class Probe:
    """One check. Subclasses implement `check`; the harness handles the rest.

    A probe never raises to its caller. Missing prerequisites become
    NOT_APPLICABLE with a reason; unexpected failures become ERROR with a
    reason. Both are visible in the card -- a probe that quietly did not run
    is the failure mode this whole tool exists to prevent.
    """

    family: ClassVar[str] = "unnamed"
    name: ClassVar[str] = "unnamed"
    #: Capabilities without which this probe cannot run at all.
    requires: ClassVar[tuple[Capability, ...]] = ()
    #: The defect classes this probe is the one that finds.
    #:
    #: Without this a NOT_APPLICABLE result is indistinguishable from a clean
    #: PASS one layer up: both contribute nothing to `report.detected`, so the
    #: corpus scorer charged `inspect_evals/boolq` a full miss for SHORTCUT_LEAK
    #: on a probe that had declined for want of a train split. Declaring what a
    #: probe would have looked for is what lets a caller tell "checked, clean"
    #: from "could not check".
    detects: ClassVar[tuple[DefectClass, ...]] = ()

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]) -> ProbeResult:
        raise NotImplementedError

    # -- harness -----------------------------------------------------------

    def run(self, adapter: EnvAdapter, ctx: dict[str, Any] | None = None) -> ProbeResult:
        ctx = ctx or {}
        manifest = adapter.manifest()
        missing = [c for c in self.requires if not manifest.has(c)]
        if missing:
            return self.na(
                "environment does not expose: "
                + ", ".join(c.value for c in missing)
            )
        try:
            return self.check(adapter, ctx)
        except NotSupported as exc:
            return self.na(str(exc))
        except Exception as exc:  # noqa: BLE001 - a probe crash is a reportable outcome
            return ProbeResult(
                family=self.family,
                probe=self.name,
                status=ProbeStatus.ERROR,
                reason=f"{type(exc).__name__}: {exc}",
            )

    # -- result constructors ----------------------------------------------

    def na(self, reason: str, **detail: Any) -> ProbeResult:
        """Could not check, and why.

        `detail` is accepted because a probe that ran and then found it could
        not conclude has a record worth keeping -- what it attempted, on which
        tasks, and how far it got. Dropping it left the card saying only
        "NOT_APPLICABLE" for a probe that had done real work, which is thinner
        than the evidence deserves.
        """
        return ProbeResult(
            family=self.family,
            probe=self.name,
            status=ProbeStatus.NOT_APPLICABLE,
            reason=reason,
            detail=detail,
        )

    def ok(self, **detail: Any) -> ProbeResult:
        return ProbeResult(
            family=self.family, probe=self.name, status=ProbeStatus.PASS, detail=detail
        )

    def defect(
        self,
        cls: DefectClass,
        task_id: str | None = None,
        severity=None,
        **evidence: Any,
    ) -> ProbeResult:
        finding = Finding(
            defect=cls,
            severity=severity or DEFAULT_SEVERITY[cls],
            task_id=task_id,
            evidence=evidence,
        )
        return ProbeResult(
            family=self.family, probe=self.name, status=ProbeStatus.DEFECT, findings=[finding]
        )

    def defects(self, findings: list[Finding], **detail: Any) -> ProbeResult:
        if not findings:
            return self.ok(**detail)
        return ProbeResult(
            family=self.family,
            probe=self.name,
            status=ProbeStatus.DEFECT,
            findings=findings,
            detail=detail,
        )


#: Families for which no `assay.fixtures` variant plants a defect, and why.
#:
#: Two callers assert that every registered family fires somewhere -- the
#: `assay selftest` command and `tests/test_probes_fire.py` -- and both walked
#: `assay.fixtures` with `difficulty_band` spelled out inline as a literal. The
#: list is here instead so there is one copy with a reason attached to each
#: entry.
#:
#: A family listed here is NOT excused from firing. Every one of them *runs* on
#: the fixtures and passes; what is missing is a fixture that plants the defect,
#: and `CATALOG` is the scored fixture corpus -- adding a variant to it changes
#: a published number. So the planted instances live beside the probes' own
#: tests, and each entry below names where.
FAMILIES_NOT_PLANTED_IN_FIXTURES: dict[str, str] = {
    "difficulty_band": (
        "a solve rate is a property of an (environment, policy) pair supplied in "
        "ctx, not of the fixture; fires in tests/test_probes_fire.py"
    ),
    "sandbox_permissions": (
        "`TOY_POSTURE` is deliberately a minimal deployment, so the probe runs and "
        "passes; the over-permissioned postures are in "
        "tests/test_dead_zone_probes.py"
    ),
    "evaluator_code_execution": (
        "the fixture hands over its real verifier's source and that source has no "
        "execution sink. Planting one would mean putting a live `eval` in a corpus "
        "environment every other probe also drives, to make one probe fire; the "
        "planted verifiers are in tests/test_dead_zone_probes.py"
    ),
}


REGISTRY: list[type[Probe]] = []


def register(cls: type[Probe]) -> type[Probe]:
    REGISTRY.append(cls)
    return cls


def all_probes() -> list[Probe]:
    return [cls() for cls in REGISTRY]


def families() -> list[str]:
    seen: list[str] = []
    for cls in REGISTRY:
        if cls.family not in seen:
            seen.append(cls.family)
    return seen
