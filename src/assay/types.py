"""Core vocabulary shared by adapters, probes, and the Environment Card.

Nothing here knows about a specific ecosystem. Adapters translate their world
into these types; probes only ever see these types.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# --------------------------------------------------------------------------
# Severity and defects
# --------------------------------------------------------------------------


class Severity(str, Enum):
    """How bad it is if this defect ships undetected.

    CRITICAL is reserved for defects that make every number the environment
    produces meaningless (the eval cannot fail; the eval set is contaminated).
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DefectClass(str, Enum):
    """The taxonomy. Each belongs to exactly one probe family."""

    # family 1 - verifier integrity
    GOLD_FAILS = "GOLD_FAILS"
    NOOP_PASSES = "NOOP_PASSES"
    INVERT_PASSES = "INVERT_PASSES"
    KNOWN_WRONG_PASSES = "KNOWN_WRONG_PASSES"
    # family 2 - trivial floor
    TRIVIAL_FLOOR_BREACH = "TRIVIAL_FLOOR_BREACH"
    # family 3 - separability
    SEPARABILITY_LOSS = "SEPARABILITY_LOSS"
    # family 4 - contamination
    CONTAMINATION_EXACT = "CONTAMINATION_EXACT"
    CONTAMINATION_NEARDUP = "CONTAMINATION_NEARDUP"
    # family 5 - shortcut leakage
    SHORTCUT_LEAK = "SHORTCUT_LEAK"
    # family 6 - spec/verifier mismatch
    SPEC_VERIFIER_MISMATCH = "SPEC_VERIFIER_MISMATCH"
    # family 7 - determinism
    NONDETERMINISM = "NONDETERMINISM"
    # family 8 - difficulty band
    DIFFICULTY_SATURATED = "DIFFICULTY_SATURATED"
    DIFFICULTY_IMPOSSIBLE = "DIFFICULTY_IMPOSSIBLE"
    # family 9 - reward hackability
    REWARD_HACKABLE = "REWARD_HACKABLE"


#: Default severity per defect class. Costs live in cost profiles, not here --
#: severity is the environment-independent judgement, cost is the caller's.
DEFAULT_SEVERITY: dict[DefectClass, Severity] = {
    DefectClass.GOLD_FAILS: Severity.HIGH,
    DefectClass.NOOP_PASSES: Severity.HIGH,
    DefectClass.INVERT_PASSES: Severity.CRITICAL,
    DefectClass.KNOWN_WRONG_PASSES: Severity.HIGH,
    DefectClass.TRIVIAL_FLOOR_BREACH: Severity.HIGH,
    DefectClass.SEPARABILITY_LOSS: Severity.MEDIUM,
    DefectClass.CONTAMINATION_EXACT: Severity.CRITICAL,
    DefectClass.CONTAMINATION_NEARDUP: Severity.HIGH,
    DefectClass.SHORTCUT_LEAK: Severity.HIGH,
    DefectClass.SPEC_VERIFIER_MISMATCH: Severity.HIGH,
    DefectClass.NONDETERMINISM: Severity.MEDIUM,
    DefectClass.DIFFICULTY_SATURATED: Severity.MEDIUM,
    DefectClass.DIFFICULTY_IMPOSSIBLE: Severity.MEDIUM,
    DefectClass.REWARD_HACKABLE: Severity.CRITICAL,
}


# --------------------------------------------------------------------------
# Episode protocol
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    """One move. `tool` is a name the environment understands."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    ok: bool
    data: Any = None
    code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class StepResult:
    observation: Observation
    done: bool
    #: Environments that only score terminally leave this None.
    reward: float | None = None


@dataclass
class Transcript:
    """What a policy did, in a form `verify` can score without a live episode."""

    task_id: str
    seed: int
    actions: list[Action] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    final_state: Any = None

    def record(self, action: Action, result: StepResult) -> None:
        self.actions.append(action)
        self.observations.append(result.observation)


@dataclass(frozen=True)
class Score:
    """A verifier's judgement of a transcript."""

    passed: bool
    reward: float
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Task:
    task_id: str
    #: Human-facing instruction. Family 6 compares this against what the
    #: verifier actually asserts.
    instruction: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Item:
    """One datum in a train or eval split. Family 4 works on these."""

    item_id: str
    text: str
    label: Any = None
    #: Fields a partial-input baseline is allowed to see (family 5).
    parts: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------


class Capability(str, Enum):
    """What an environment exposes.

    A probe whose prerequisites are absent reports NOT_APPLICABLE with a
    reason. It never guesses, and it never silently skips.
    """

    GOLD_TRAJECTORY = "GOLD_TRAJECTORY"
    INVERTIBLE_SPEC = "INVERTIBLE_SPEC"
    KNOWN_WRONG = "KNOWN_WRONG"
    SEPARABLE_VERIFIER = "SEPARABLE_VERIFIER"
    LIVE_STEPPING = "LIVE_STEPPING"
    SPLITS = "SPLITS"
    ITEM_PARTS = "ITEM_PARTS"
    SEEDED_RESET = "SEEDED_RESET"
    TRUE_COMPLETION = "TRUE_COMPLETION"
    TRIVIAL_POLICIES = "TRIVIAL_POLICIES"
    GRADED_POLICIES = "GRADED_POLICIES"


@dataclass(frozen=True)
class Manifest:
    env_id: str
    ecosystem: str
    tasks: list[Task]
    capabilities: frozenset[Capability]
    version: str = "unknown"
    source: str = ""

    def has(self, cap: Capability) -> bool:
        return cap in self.capabilities


# --------------------------------------------------------------------------
# Probe results
# --------------------------------------------------------------------------


class ProbeStatus(str, Enum):
    PASS = "PASS"
    #: A defect was found. The probe worked; the environment did not.
    DEFECT = "DEFECT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


@dataclass
class Finding:
    defect: DefectClass
    severity: Severity
    task_id: str | None
    #: Everything a reader needs to check the claim themselves.
    evidence: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        where = f" on {self.task_id}" if self.task_id else ""
        return f"[{self.severity.value}] {self.defect.value}{where}"


@dataclass
class ProbeResult:
    family: str
    probe: str
    status: ProbeStatus
    findings: list[Finding] = field(default_factory=list)
    #: Why NOT_APPLICABLE, or why ERROR. Required for both.
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status in (ProbeStatus.NOT_APPLICABLE, ProbeStatus.ERROR):
            if not self.reason:
                raise ValueError(f"{self.probe}: {self.status.value} requires a reason")
        if self.status is ProbeStatus.DEFECT and not self.findings:
            raise ValueError(f"{self.probe}: DEFECT requires at least one finding")
        if self.status is ProbeStatus.PASS and self.findings:
            raise ValueError(f"{self.probe}: PASS cannot carry findings")


# --------------------------------------------------------------------------
# Canonical hashing -- used for content digests and determinism comparison
#
# A digest is not a signature. `digest` is unkeyed SHA-256: it detects
# accidental edits and identifies content, and it stops nobody who wants to
# change a card, because they can recompute it. `sign` below is the keyed
# version, and it is the only thing here that survives a motivated forger.
# --------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Sorted keys, no incidental whitespace, stable across runs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    """Unkeyed content digest. Detects corruption, not forgery."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


CARD_KEY_ENV = "ASSAY_CARD_KEY"


def sign(value: Any, key: bytes | None = None) -> str | None:
    """Keyed HMAC-SHA256 over the canonical body, or None if no key is set.

    Returns None rather than falling back to an unkeyed hash. A caller that
    cannot tell a signed card from an unsigned one is the failure this
    function exists to prevent, so the absence of a key is reported as an
    absent signature and never as a weaker one.
    """
    if key is None:
        env = os.environ.get(CARD_KEY_ENV)
        if not env:
            return None
        key = env.encode("utf-8")
    return hmac.new(key, canonical_json(value).encode("utf-8"), hashlib.sha256).hexdigest()


def verify(value: Any, signature: str | None, key: bytes | None = None) -> bool:
    """Constant-time check of a keyed signature over `value`."""
    expected = sign(value, key)
    if expected is None or signature is None:
        return False
    return hmac.compare_digest(expected, signature)
