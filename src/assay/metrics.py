"""Scoring an auditor.

The objective is expected loss, not detection accuracy. A missed contamination
defect burns a training run; a false alarm burns an engineer an hour. Reporting
accuracy silently assumes those cost the same -- which is the flat-cost profile,
and it is a special case, not the general one.

Normalisation follows the same shape used for any cost-asymmetric system:

    normalized_loss = (L_system - L_oracle) / (L_trivial - L_oracle)

0 is the oracle, 1 is the best trivial detector, above 1 is actively harmful.
The auditor is held to the same trivial-floor rule it applies to environments:
if it cannot beat "flag nothing" and "flag everything", it has not earned its
existence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .costs import CostProfile
from .types import DEFAULT_SEVERITY, DefectClass, Severity


@dataclass(frozen=True)
class Outcome:
    """One environment: what was planted, what the arm reported."""

    env_id: str
    planted: frozenset[DefectClass]
    detected: frozenset[DefectClass]

    @property
    def missed(self) -> frozenset[DefectClass]:
        return self.planted - self.detected

    @property
    def spurious(self) -> frozenset[DefectClass]:
        return self.detected - self.planted

    @property
    def caught(self) -> frozenset[DefectClass]:
        return self.planted & self.detected


@dataclass
class ArmResult:
    arm: str
    outcomes: list[Outcome] = field(default_factory=list)

    # -- counts ------------------------------------------------------------

    @property
    def n_planted(self) -> int:
        return sum(len(o.planted) for o in self.outcomes)

    @property
    def n_caught(self) -> int:
        return sum(len(o.caught) for o in self.outcomes)

    @property
    def n_missed(self) -> int:
        return sum(len(o.missed) for o in self.outcomes)

    @property
    def n_spurious(self) -> int:
        return sum(len(o.spurious) for o in self.outcomes)

    @property
    def error_count(self) -> int:
        """Raw errors, ignoring severity. The flat-cost view."""
        return self.n_missed + self.n_spurious

    # -- rates -------------------------------------------------------------

    @property
    def recall(self) -> float:
        return self.n_caught / self.n_planted if self.n_planted else 0.0

    @property
    def precision(self) -> float:
        flagged = self.n_caught + self.n_spurious
        return self.n_caught / flagged if flagged else 0.0

    def severity_weighted_recall(self) -> float:
        weights = {Severity.CRITICAL: 1.0, Severity.HIGH: 1.0, Severity.MEDIUM: 0.6, Severity.LOW: 0.3}
        num = sum(weights[DEFAULT_SEVERITY[d]] for o in self.outcomes for d in o.caught)
        den = sum(weights[DEFAULT_SEVERITY[d]] for o in self.outcomes for d in o.planted)
        return num / den if den else 0.0

    # -- loss --------------------------------------------------------------

    def expected_loss(self, profile: CostProfile) -> float:
        total = 0.0
        for outcome in self.outcomes:
            for defect in outcome.missed:
                total += profile.cost_of_miss(DEFAULT_SEVERITY[defect])
            total += profile.false_alarm * len(outcome.spurious)
        return total

    def profile_row(self, profile: CostProfile) -> dict[str, float]:
        """Report a profile, never one number."""
        return {
            "expected_loss": round(self.expected_loss(profile), 4),
            "recall": round(self.recall, 4),
            "precision": round(self.precision, 4),
            "severity_weighted_recall": round(self.severity_weighted_recall(), 4),
            "n_missed": self.n_missed,
            "n_spurious": self.n_spurious,
            "error_count": self.error_count,
        }


# -- trivial detectors, for normalisation ------------------------------------


def trivial_arms(ground_truth: dict[str, frozenset[DefectClass]]) -> dict[str, ArmResult]:
    """The floor any real auditor must clear."""
    everything = frozenset(DefectClass)
    arms = {
        "flag_nothing": ArmResult("flag_nothing"),
        "flag_everything": ArmResult("flag_everything"),
    }
    for env_id, planted in ground_truth.items():
        arms["flag_nothing"].outcomes.append(Outcome(env_id, planted, frozenset()))
        arms["flag_everything"].outcomes.append(Outcome(env_id, planted, everything))
    return arms


def oracle_loss() -> float:
    """Perfect detection costs nothing. Stated as a function so the formula
    below reads the way it is written down."""
    return 0.0


def normalized_loss(
    arm: ArmResult,
    ground_truth: dict[str, frozenset[DefectClass]],
    profile: CostProfile,
) -> float:
    l_oracle = oracle_loss()
    l_trivial = min(a.expected_loss(profile) for a in trivial_arms(ground_truth).values())
    denom = l_trivial - l_oracle
    if denom <= 0:
        raise ValueError("degenerate corpus: the best trivial detector is already perfect")
    return (arm.expected_loss(profile) - l_oracle) / denom
