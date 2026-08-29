"""Scoring an auditor.

The objective is expected loss, not detection accuracy. A missed contamination
defect burns a training run; a false alarm burns an engineer an hour. Reporting
accuracy silently assumes those cost the same -- which is the flat-cost profile,
and it is a special case, not the general one.

Normalisation follows the same shape used for any cost-asymmetric system:

    normalized_loss = (L_system - L_oracle) / (L_trivial - L_oracle)

0 is the oracle, 1 is the best trivial detector, above 1 is actively harmful.
The auditor is held to the same trivial-floor rule it applies to environments:
if it cannot beat the best policy that ignores its input, it has not earned its
existence.

`criteria.md:52` names five trivial policies and all five are implemented here,
under a mapping from its single-label vocabulary into this multilabel one that
is written out above `base_rates` rather than left to be inferred.
"""

from __future__ import annotations

import random
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


def trivial_arms(
    ground_truth: dict[str, frozenset[DefectClass]], *, seed: int = 11
) -> dict[str, ArmResult]:
    """The floor any real auditor must clear.

    All four non-oracle policies from `criteria.md:52`, under the mapping
    documented at the bottom of this module. `oracle` is excluded on purpose: it
    is the numerator's zero point, and putting a zero-loss policy in the set the
    denominator minimises over would make every normalised loss infinite.

    `stratified_random` is a seeded realisation. The seed is fixed here so the
    floor is a property of the corpus rather than of when it was run; its
    closed-form expectation is `expected_stratified_loss`.
    """
    everything = frozenset(DefectClass)
    arms = {
        "flag_nothing": ArmResult("flag_nothing"),
        "flag_everything": ArmResult("flag_everything"),
    }
    for env_id, planted in ground_truth.items():
        arms["flag_nothing"].outcomes.append(Outcome(env_id, planted, frozenset()))
        arms["flag_everything"].outcomes.append(Outcome(env_id, planted, everything))
    if ground_truth:
        arms["always_modal_defect"] = always_modal_defect_arm(ground_truth)
        arms["stratified_random"] = stratified_random_arm(ground_truth, seed=seed)
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


# -- the five trivial policies criteria.md names --------------------------------
#
# `criteria.md:52` lists five: always-match, always-exception, always-escalate,
# stratified-random, oracle. That list is written for a per-item classifier that
# emits MATCH / EXCEPTION / ESCALATE. An auditor emits a SET of defect classes
# per environment, so the five have to be mapped, and the mapping is stated here
# rather than left for a reader to reconstruct:
#
#   always-match      -> flag_nothing        predict the modal label ("healthy")
#                                            for every environment
#   always-exception  -> always_modal_defect predict the single most frequently
#                                            planted defect class, everywhere
#   always-escalate   -> flag_everything     send every defect class of every
#                                            environment to a human. Zero misses,
#                                            unbounded review cost -- the policy
#                                            any deferral system must beat on
#                                            TOTAL loss
#   stratified-random -> stratified_random   flag each class independently at its
#                                            base rate across the corpus
#   oracle            -> oracle              the planted set exactly; loss 0
#
# `flag_nothing` and `flag_everything` keep their existing names because every
# published number and every results file already uses them; renaming them to
# match the source vocabulary would break the record for a cosmetic gain.


def base_rates(
    ground_truth: dict[str, frozenset[DefectClass]],
) -> dict[DefectClass, float]:
    """P(class d is planted) over the corpus, per defect class.

    This is the corpus's OWN prior, not a held-out one. Assay has no train/eval
    split of its corpus, so the stratified-random policy is handed the exact
    distribution it is being scored against. That makes the floor harder than a
    policy fit on a training split would be, which is the conservative direction
    for any claim of the form "Assay beats the floor".
    """
    n = len(ground_truth)
    if not n:
        return {d: 0.0 for d in DefectClass}
    counts = {d: 0 for d in DefectClass}
    for planted in ground_truth.values():
        for d in planted:
            counts[d] += 1
    return {d: counts[d] / n for d in DefectClass}


def modal_defect(ground_truth: dict[str, frozenset[DefectClass]]) -> DefectClass:
    """The most frequently planted class. Ties break on the enum's own order so
    the policy is a function of the corpus and not of dict iteration."""
    rates = base_rates(ground_truth)
    order = list(DefectClass)
    return max(order, key=lambda d: (rates[d], -order.index(d)))


def stratified_random_arm(
    ground_truth: dict[str, frozenset[DefectClass]], seed: int = 11
) -> ArmResult:
    """One seeded realisation: flag class d with probability base_rate(d).

    A realisation, not an expectation, because `ArmResult` carries concrete
    outcomes and the bootstrap in `scripts/intervals.py` resamples them. The
    closed-form expectation is `expected_stratified_loss`, and both are
    published so the draw cannot be read as cherry-picked.
    """
    rng = random.Random(seed)
    rates = base_rates(ground_truth)
    arm = ArmResult("stratified_random")
    for env_id in sorted(ground_truth):
        detected = frozenset(d for d in DefectClass if rng.random() < rates[d])
        arm.outcomes.append(Outcome(env_id, ground_truth[env_id], detected))
    return arm


def expected_stratified_loss(
    ground_truth: dict[str, frozenset[DefectClass]], profile: CostProfile
) -> float:
    """Exact E[loss] of stratified-random, in closed form.

    Every (environment, class) decision is an independent Bernoulli, so the
    expectation is a sum and needs no sampling:

        E[L] = sum_e [ sum_{d in P_e} (1-p_d)*miss(sev d)
                     + sum_{d not in P_e} p_d * false_alarm ]

    Reported next to the seeded draw so a reader can see how far one draw sits
    from the policy's actual mean, rather than trusting a single sample of a
    stochastic baseline -- the same pass@1-for-pass^k substitution this project
    already calls out in its own Challenger write-up.
    """
    rates = base_rates(ground_truth)
    total = 0.0
    for planted in ground_truth.values():
        for d in DefectClass:
            if d in planted:
                total += (1.0 - rates[d]) * profile.cost_of_miss(DEFAULT_SEVERITY[d])
            else:
                total += rates[d] * profile.false_alarm
    return total


def always_modal_defect_arm(
    ground_truth: dict[str, frozenset[DefectClass]],
) -> ArmResult:
    """criteria.md's `always-exception`: predict the modal defect, everywhere."""
    modal = frozenset({modal_defect(ground_truth)})
    return ArmResult(
        "always_modal_defect",
        [Outcome(env, planted, modal) for env, planted in sorted(ground_truth.items())],
    )


def oracle_arm(ground_truth: dict[str, frozenset[DefectClass]]) -> ArmResult:
    """The achievable minimum. Kept out of `trivial_arms` on purpose: it is the
    zero point of the normalisation, not a candidate for its denominator."""
    return ArmResult(
        "oracle",
        [Outcome(env, planted, planted) for env, planted in sorted(ground_truth.items())],
    )


def stratified_random_setwise_arm(
    ground_truth: dict[str, frozenset[DefectClass]], seed: int = 11
) -> ArmResult:
    """The other reading of "sample from the label prior", published alongside.

    `criteria.md` writes its trivial-policy list for a single-label classifier,
    where "the label prior" is unambiguous. An auditor emits a SET, so the
    phrase has two defensible readings and picking one silently would be a
    choice disguised as a definition:

      per-class  (`stratified_random_arm`) -- flag each class independently at
                 its own base rate. Destroys the corpus's co-occurrence
                 structure: it will happily emit INVERT_PASSES without
                 KNOWN_WRONG_PASSES, which no real environment in the corpus
                 does.
      set-wise   (this one) -- draw one environment's whole planted set from
                 the corpus and predict it. Keeps co-occurrence, so it is the
                 stronger-looking policy a priori.

    Both are reported in `results/baselines.json`. Only the per-class one is an
    arm in `trivial_arms`, because it is the literal reading and it has a closed
    form; this one is the robustness check on that choice.
    """
    rng = random.Random(seed)
    pool = [ground_truth[env] for env in sorted(ground_truth)]
    return ArmResult(
        "stratified_random_setwise",
        [
            Outcome(env, ground_truth[env], rng.choice(pool))
            for env in sorted(ground_truth)
        ],
    )
