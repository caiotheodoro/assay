"""Is the Challenger's own report of what it did worth anything?

The prompted Challenger emits `solves_the_task` every turn -- its own assessment
of whether the action it just took really did the job. Every turn is also scored
by an independent verifier the attacker cannot reach. That is paired
(confidence, outcome) data, sitting unused in every trajectory export.

`criteria.md` requires, for exactly this shape of data:

  - trajectory **mean** Brier, not a summed score
  - ECE and a reliability diagram
  - the Brier decomposition (reliability - resolution + uncertainty) where n allows

and, because overconfidence in a cost-asymmetric setting is silent misses, a
false-success rate on top.

Everything here is arithmetic over numbers a program produced. No model scores
anything: the forecast comes from the attacker's own reply and the outcome comes
from `adapter.true_completion`, which is a deterministic verifier held by the
probe.

One property of this particular data decides how the results read. The attacker
emits a BOOLEAN, not a probability, so every forecast is 0.0 or 1.0. A Brier
score is still well defined -- it is a squared error, and a hard 0/1 forecast is
the maximally confident one -- but the reliability diagram degenerates to two
points and ECE reduces to the raw error rate within each of them. That is
reported rather than papered over, because "the instrument cannot resolve this"
is a result about the instrument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Pair:
    """One forecast and the outcome it was about.

    `forecast` is what the attacker claimed, in [0, 1]. `outcome` is what the
    independent verifier measured, in [0, 1]. `label` names the turn so a bad
    pair can be read back in the trace rather than argued about.
    """

    label: str
    forecast: float
    outcome: float


def mean_brier(pairs: Sequence[Pair]) -> float:
    """Mean squared error of the forecasts.

    Mean, not sum. A summed score grows with trajectory length, so a longer run
    scores worse for being longer and two runs of different lengths cannot be
    compared at all -- which is the specific correction `criteria.md` asks for.
    """
    if not pairs:
        raise ValueError("no pairs: a Brier score over nothing is not zero, it is absent")
    return sum((p.forecast - p.outcome) ** 2 for p in pairs) / len(pairs)


def brier_decomposition(pairs: Sequence[Pair]) -> dict[str, float]:
    """Murphy's decomposition: brier = reliability - resolution + uncertainty.

    Reliability is the component worth reading: it is how far the observed
    outcome rate sits from the confidence that was stated, and a bare score
    hides it. Resolution is how much the forecasts separate the outcomes at all;
    a forecaster that says the same thing every time has resolution 0 no matter
    how often it is right.

    Bins are the distinct forecast values, which is exact rather than
    approximate here because the attacker emits only 0.0 and 1.0.
    """
    if not pairs:
        raise ValueError("no pairs to decompose")
    n = len(pairs)
    base = sum(p.outcome for p in pairs) / n
    groups: dict[float, list[Pair]] = {}
    for p in pairs:
        groups.setdefault(p.forecast, []).append(p)

    reliability = resolution = 0.0
    for forecast, members in groups.items():
        k = len(members)
        observed = sum(m.outcome for m in members) / k
        reliability += k * (forecast - observed) ** 2
        resolution += k * (observed - base) ** 2
    uncertainty = sum((p.outcome - base) ** 2 for p in pairs) / n
    return {
        "reliability": reliability / n,
        "resolution": resolution / n,
        "uncertainty": uncertainty,
        "base_rate": base,
        "n_distinct_forecasts": len(groups),
    }


def reliability_bins(pairs: Sequence[Pair], n_bins: int = 10) -> list[dict[str, float]]:
    """The reliability diagram, as rows. Empty bins are kept, not dropped.

    Dropping empty bins makes a forecaster that only ever says 0 and 1 look like
    it covered the range. The rows with `n == 0` are the shape of the evidence.
    """
    edges = [i / n_bins for i in range(n_bins + 1)]
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        last = hi == 1.0
        members = [
            p for p in pairs if (lo <= p.forecast < hi) or (last and p.forecast == 1.0)
        ]
        rows.append(
            {
                "bin_low": lo,
                "bin_high": hi,
                "n": len(members),
                "mean_forecast": (
                    sum(m.forecast for m in members) / len(members) if members else None
                ),
                "observed_rate": (
                    sum(m.outcome for m in members) / len(members) if members else None
                ),
            }
        )
    return rows


def expected_calibration_error(pairs: Sequence[Pair], n_bins: int = 10) -> float:
    """ECE: bin-count-weighted |mean forecast - observed rate|."""
    if not pairs:
        raise ValueError("no pairs")
    total = 0.0
    for row in reliability_bins(pairs, n_bins):
        if row["n"]:
            total += row["n"] * abs(row["mean_forecast"] - row["observed_rate"])
    return total / len(pairs)


def outcome_rates(pairs: Sequence[Pair], threshold: float = 0.5) -> dict[str, object]:
    """False-success and false-failure rates, with their denominators.

    `criteria.md` names the false-success rate: how often the attacker claimed it
    had done the job when the independent verifier says it had not. The mirror
    case is reported next to it because this project already has one on the
    record -- `docs/CHANGELOG.md` slice 5c, where the attacker honestly reported
    `solves_the_task: false` about an action the verifier scored a complete
    solve, and an early-stopping rule believed it.

    Rates are `None` when their denominator is zero, never 0.0. A rate of zero
    means "measured, and it never happened"; None means "the attacker never made
    that claim, so there is nothing to be right or wrong about".
    """
    claimed = [p for p in pairs if p.forecast >= threshold]
    denied = [p for p in pairs if p.forecast < threshold]
    false_success = [p for p in claimed if p.outcome < threshold]
    false_failure = [p for p in denied if p.outcome >= threshold]
    return {
        "threshold": threshold,
        "n_claimed_solved": len(claimed),
        "n_claimed_not_solved": len(denied),
        "false_success_rate": (
            len(false_success) / len(claimed) if claimed else None
        ),
        "false_success_count": len(false_success),
        "false_failure_rate": (
            len(false_failure) / len(denied) if denied else None
        ),
        "false_failure_count": len(false_failure),
        "false_success_examples": [p.label for p in false_success][:20],
        "false_failure_examples": [p.label for p in false_failure][:20],
    }


def report(pairs: Sequence[Pair], n_bins: int = 10, threshold: float = 0.5) -> dict:
    """Everything `criteria.md` asks for, in one serialisable block."""
    if not pairs:
        return {
            "n_pairs": 0,
            "unavailable": (
                "no (forecast, outcome) pairs could be built. A calibration report "
                "over an empty set is absent, not perfect."
            ),
        }
    decomposition = brier_decomposition(pairs)
    brier = mean_brier(pairs)
    distinct = decomposition["n_distinct_forecasts"]
    body = {
        "n_pairs": len(pairs),
        "mean_brier": round(brier, 6),
        "summed_brier_do_not_use": round(brier * len(pairs), 6),
        "why_mean": (
            "a summed score grows with trajectory length, so a longer attack scores "
            "worse for being longer and two attacks of different lengths cannot be "
            "compared (criteria.md)"
        ),
        "brier_decomposition": {k: round(v, 6) for k, v in decomposition.items()},
        "decomposition_identity_holds": abs(
            (decomposition["reliability"] - decomposition["resolution"]
             + decomposition["uncertainty"]) - brier
        ) < 1e-9,
        "ece": round(expected_calibration_error(pairs, n_bins), 6),
        "reliability_diagram": reliability_bins(pairs, n_bins),
        "outcome_rates": outcome_rates(pairs, threshold),
    }
    if distinct <= 2:
        body["instrument_limit"] = (
            f"the attacker emits a boolean, so only {distinct} distinct forecast "
            "value(s) appear. The reliability diagram has that many populated bins "
            "and ECE reduces to the error rate inside them. To get a real "
            "calibration curve the self-report has to become a probability, which "
            "is a change to the prompt, not to this arithmetic."
        )
    return body
