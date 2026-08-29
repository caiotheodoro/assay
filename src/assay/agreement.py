"""Inter-rater agreement on the hand-labelled corpus.

Every headline number this project publishes rests on one author reading source
code and writing down what was planted. `eval-methodology.md:64` says to measure
inter-rater agreement with Cohen's kappa before trusting human labels, and
`docs/CHANGELOG.md` already admits hand-labelled ground truth is error-prone --
which is, word for word, the problem this tool exists to solve. Auditing
everyone else's labels and none of your own is the failure mode.

The unit of agreement is one (environment, defect class) CELL, not one
environment. Two raters who both say `harbor/self-graded` is defective but
disagree about which family agree on nothing that matters, and an
environment-level score would count that as a hit.

Kappa rather than raw agreement because the cells are extremely imbalanced:
with 14 classes and 24 environments, most cells are "not planted" under both
raters and percent-agreement is ~90% before anyone has read anything. Kappa
corrects for exactly that, and it is why the number to report is the corrected
one even though it looks much worse.

The known cost of the correction is stated with the result rather than
discovered by a reader: on a rare class, kappa is unstable and a single flipped
cell moves it a long way, so per-class kappa is published next to its prevalence
and its cell count and not on its own.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Sequence

from .types import DefectClass

Labelling = dict[str, frozenset[DefectClass]]


@dataclass(frozen=True)
class Cell:
    env_id: str
    defect: DefectClass
    a: bool
    b: bool


def cells(a: Labelling, b: Labelling, classes: Iterable[DefectClass] | None = None) -> list[Cell]:
    """The full (environment x class) grid both raters implicitly filled in.

    Every class is a cell, including ones neither rater used. Restricting the
    grid to classes somebody mentioned would silently drop the true negatives
    that kappa's chance correction is computed from, and inflate it.
    """
    classes = list(classes or DefectClass)
    shared = sorted(set(a) & set(b))
    return [
        Cell(env, d, d in a[env], d in b[env]) for env in shared for d in classes
    ]


def confusion(grid: Sequence[Cell]) -> dict[str, int]:
    return {
        "both_yes": sum(1 for c in grid if c.a and c.b),
        "both_no": sum(1 for c in grid if not c.a and not c.b),
        "a_only": sum(1 for c in grid if c.a and not c.b),
        "b_only": sum(1 for c in grid if not c.a and c.b),
        "n": len(grid),
    }


def cohen_kappa(grid: Sequence[Cell]) -> float | None:
    """Chance-corrected agreement on binary cells.

    `None` when chance agreement is exactly 1 -- both raters marked every cell
    the same way, so there is no variation for kappa to be defined over.
    Returning 1.0 there would report perfect agreement on a comparison that
    carries no information, which is the opposite of what happened.
    """
    n = len(grid)
    if not n:
        return None
    observed = sum(1 for c in grid if c.a == c.b) / n
    pa = sum(1 for c in grid if c.a) / n
    pb = sum(1 for c in grid if c.b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def percent_agreement(grid: Sequence[Cell]) -> float | None:
    if not grid:
        return None
    return sum(1 for c in grid if c.a == c.b) / len(grid)


def per_class(grid: Sequence[Cell]) -> dict[str, dict]:
    """Kappa per defect class, each with the numbers needed to discount it."""
    out: dict[str, dict] = {}
    for defect in DefectClass:
        subset = [c for c in grid if c.defect is defect]
        if not subset:
            continue
        conf = confusion(subset)
        n = len(subset)
        out[defect.value] = {
            **conf,
            "prevalence_rater_a": round(sum(1 for c in subset if c.a) / n, 4),
            "prevalence_rater_b": round(sum(1 for c in subset if c.b) / n, 4),
            "percent_agreement": round(percent_agreement(subset), 4),
            "kappa": _round(cohen_kappa(subset)),
            "kappa_undefined_reason": (
                None
                if cohen_kappa(subset) is not None
                else "no variation: both raters gave every environment the same verdict "
                "on this class, so kappa has nothing to correct"
            ),
        }
    return out


def per_environment(a: Labelling, b: Labelling) -> list[dict]:
    """Where the two raters actually differ, environment by environment."""
    rows = []
    for env in sorted(set(a) & set(b)):
        sa, sb = set(a[env]), set(b[env])
        union = sa | sb
        rows.append(
            {
                "env_id": env,
                "rater_a": sorted(d.value for d in sa),
                "rater_b": sorted(d.value for d in sb),
                "a_only": sorted(d.value for d in sa - sb),
                "b_only": sorted(d.value for d in sb - sa),
                "exact_set_match": sa == sb,
                "jaccard": round(len(sa & sb) / len(union), 4) if union else 1.0,
            }
        )
    return rows


def bootstrap_kappa(
    a: Labelling, b: Labelling, resamples: int = 10000, seed: int = 11
) -> dict:
    """95% CI on kappa, resampling ENVIRONMENTS.

    Same resampling unit as `scripts/intervals.py`, for the same reason: the 14
    cells of one environment are not 14 independent judgements. A rater who
    misreads one verifier gets a whole row wrong at once, so resampling cells
    would report an interval far tighter than the data supports.
    """
    envs = sorted(set(a) & set(b))
    if not envs:
        return {"point": None, "ci95": [None, None], "reason": "no shared environments"}
    if resamples <= 0:
        return {
            "point": _round(cohen_kappa(cells(a, b))),
            "ci95": [None, None],
            "reason": "not bootstrapped: resamples=0 was requested for this comparison",
        }
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        picked = [envs[rng.randrange(len(envs))] for _ in envs]
        sub_a = {f"{env}#{i}": a[env] for i, env in enumerate(picked)}
        sub_b = {f"{env}#{i}": b[env] for i, env in enumerate(picked)}
        k = cohen_kappa(cells(sub_a, sub_b))
        if k is not None:
            draws.append(k)
    if not draws:
        return {"point": None, "ci95": [None, None], "reason": "kappa undefined on every resample"}
    draws.sort()

    def pct(q):
        idx = (len(draws) - 1) * q
        lo, hi = int(idx), min(int(idx) + 1, len(draws) - 1)
        return draws[lo] + (draws[hi] - draws[lo]) * (idx - lo)

    return {
        "point": _round(cohen_kappa(cells(a, b))),
        "ci95": [round(pct(0.025), 4), round(pct(0.975), 4)],
        "resamples": resamples,
        "seed": seed,
        "resampling_unit": "environment",
        "n_undefined_resamples": resamples - len(draws),
    }


def interpret(kappa: float | None) -> str:
    """Landis & Koch's bands, named so a number is not left to read itself."""
    if kappa is None:
        return "undefined"
    if kappa < 0:
        return "worse than chance"
    if kappa < 0.21:
        return "slight"
    if kappa < 0.41:
        return "fair"
    if kappa < 0.61:
        return "moderate"
    if kappa < 0.81:
        return "substantial"
    return "almost perfect"


def _round(value: float | None) -> float | None:
    # `+ 0.0` normalises -0.0, which is a true zero that reads in JSON as though
    # the raters did slightly worse than chance.
    return None if value is None else round(value, 4) + 0.0


def compare(a: Labelling, b: Labelling, *, resamples: int = 10000, seed: int = 11) -> dict:
    """The whole agreement report for one pair of labellings."""
    grid = cells(a, b)
    kappa = cohen_kappa(grid)
    envs = sorted(set(a) & set(b))
    rows = per_environment(a, b)
    return {
        "n_environments": len(envs),
        "n_cells": len(grid),
        "unit": "one (environment, defect class) cell",
        "confusion": confusion(grid),
        "percent_agreement": _round(percent_agreement(grid)),
        "why_percent_agreement_is_not_the_number": (
            "most cells are 'not planted' under both raters, so percent agreement "
            "is high before anyone has read anything. Kappa corrects for that."
        ),
        "cohen_kappa": _round(kappa),
        "interpretation": interpret(kappa),
        "bootstrap": bootstrap_kappa(a, b, resamples, seed),
        "n_environments_exact_set_match": sum(1 for r in rows if r["exact_set_match"]),
        "mean_jaccard": round(sum(r["jaccard"] for r in rows) / len(rows), 4) if rows else None,
        "per_class": per_class(grid),
        "per_environment": rows,
        "disagreements": [r for r in rows if not r["exact_set_match"]],
        "environments_only_one_rater_covered": sorted(set(a) ^ set(b)),
    }
