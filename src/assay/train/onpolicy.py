"""Sampler-vs-trainer KL, and the fields a GRPO run has to log to have one.

`environments.md:140` makes `sampler_trainer_kl` a mandatory field of the health
block a GRPO-shaped run emits, and `environments.md:80` says what it is for:

    | KL ~= 0, reward stable   | true on-policy (batch-invariant stack)  |
    | KL ~ 1e-3 with IW        | corrected off-policy, OK                |
    | KL spike + reward crash  | missing IW / nondeterministic batching |

Two real runs happened without it. It cannot be recovered from what they logged
-- `results/assay-challenger-r{1,2}/rewards.jsonl` carries rewards, completions
and parse flags and no logprobs, no token ids and no prompt text, TRL ran with
`report_to: "none"` so there are no trainer logs either, and both spot instances
are gone along with their per-step checkpoints. `scripts/env_health_report.py`
reports the field as null with that reason attached rather than omitting it.

It is tempting to answer "zero by construction": those runs used TRL's colocated
path, so the sampler and the trainer are the same weights in the same process.
That answer is not admissible and this module exists partly to say why. The
runs loaded the base model in 4-bit NF4 and generated with a KV cache, then
computed trainer logprobs in a separate batched forward pass. Quantised matmuls
and cached versus uncached attention do not agree bit-for-bit, and batch size
changes the numerics -- which is precisely the failure mode the field is there
to detect. "Should be zero" and "measured zero" are different claims, and this
project's own standard is that the second one requires having measured it.

So what is here is the instrument, not a number: the estimators, and the
explicit list of what a future run must record to use them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

#: What a run must log, per rollout, for `sampler_trainer_kl` to be computable
#: afterwards. Written as data so `scripts/env_health_report.py` can check an
#: existing log against it and name the missing fields instead of guessing.
REQUIRED_FIELDS: dict[str, str] = {
    "sampler_logprobs": (
        "per-token logprob of each sampled completion token under the policy that "
        "GENERATED it, captured at generation time. TRL exposes these from the "
        "generation call; vLLM returns them in `logprobs`."
    ),
    "trainer_logprobs": (
        "per-token logprob of the SAME tokens under the policy the optimiser steps, "
        "from the training forward pass, in the same batch shape the step used"
    ),
    "completion_token_ids": (
        "the token ids the two arrays are aligned to. Without them a length "
        "mismatch is silent and the KL is computed over misaligned positions"
    ),
    "step": "the optimiser step, so KL can be plotted on the same axis as reward",
    "group_index": (
        "which rollout group the row belongs to, so per-group KL can be read next "
        "to that group's advantage spread"
    ),
}


class NotComputable(ValueError):
    """The inputs cannot support a KL estimate. Raised rather than returning a
    zero, because a zero here reads as "true on-policy" -- the healthiest
    possible verdict -- and that is the worst thing an absent measurement could
    be mistaken for."""


@dataclass(frozen=True)
class KLEstimate:
    """Both estimators, plus the token count they rest on.

    Two are reported because they disagree in a way that is informative. `k1` is
    the plain Monte-Carlo estimate and can come out negative on a short sequence
    even though a KL cannot be; `k3` is Schulman's low-variance unbiased
    estimator and is non-negative by construction. A run where k1 is negative
    and k3 is near zero is a sample-size artefact. A run where both are large is
    a real divergence.
    """

    k1: float
    k3: float
    n_tokens: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "k1": round(self.k1, 8),
            "k3": round(self.k3, 8),
            "n_tokens": self.n_tokens,
            "estimators": (
                "k1 = mean(log p_sampler - log p_trainer); "
                "k3 = mean(r - 1 - log r) with log r = log p_trainer - log p_sampler"
            ),
        }


def sampler_trainer_kl(
    sampler_logprobs: Sequence[float], trainer_logprobs: Sequence[float]
) -> KLEstimate:
    """KL(sampler || trainer) over the tokens that were actually sampled.

    The only estimate available from a single rollout: the tokens are drawn from
    the sampler, so their mean log-ratio is a one-sample estimate of the KL in
    that direction. It is not symmetric and the direction matters -- what the
    field is watching for is the trainer assigning low probability to what the
    sampler emitted, which is the case importance weighting has to correct.
    """
    if len(sampler_logprobs) != len(trainer_logprobs):
        raise NotComputable(
            f"length mismatch: {len(sampler_logprobs)} sampler logprobs vs "
            f"{len(trainer_logprobs)} trainer logprobs. Aligning them by "
            "truncation would compute a KL over the wrong positions."
        )
    if not sampler_logprobs:
        raise NotComputable("no tokens; an empty completion has no KL")

    k1_terms, k3_terms = [], []
    for s, t in zip(sampler_logprobs, trainer_logprobs):
        if not (math.isfinite(s) and math.isfinite(t)):
            raise NotComputable(
                "non-finite logprob in the input; a masked or padded position "
                "reached the estimator"
            )
        log_r = t - s  # log(p_trainer / p_sampler)
        k1_terms.append(-log_r)
        k3_terms.append(math.exp(log_r) - 1.0 - log_r)
    n = len(k1_terms)
    return KLEstimate(sum(k1_terms) / n, sum(k3_terms) / n, n)


def run_kl(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate KL over a run's rollout log, or say exactly why it cannot.

    Returns the same shape either way. A caller that has to branch on whether a
    measurement exists will eventually forget to, so the absence is a value with
    a reason in it, not a `None` and a comment.
    """
    missing = sorted(
        name
        for name in ("sampler_logprobs", "trainer_logprobs")
        if not any(name in row for row in rows)
    )
    if missing:
        return {
            "value": None,
            "unavailable": (
                f"the rollout log records no {' and no '.join(missing)}, so the "
                "quantity cannot be reconstructed from it"
            ),
            "required_to_fix": {k: REQUIRED_FIELDS[k] for k in REQUIRED_FIELDS},
        }

    estimates, failures = [], []
    for i, row in enumerate(rows):
        try:
            estimates.append(
                sampler_trainer_kl(row["sampler_logprobs"], row["trainer_logprobs"])
            )
        except NotComputable as exc:
            failures.append({"row": i, "reason": str(exc)})
    if not estimates:
        return {
            "value": None,
            "unavailable": "every row failed the estimator",
            "failures": failures,
        }
    total = sum(e.n_tokens for e in estimates)
    return {
        "value": round(sum(e.k3 * e.n_tokens for e in estimates) / total, 8),
        "k1_token_weighted": round(
            sum(e.k1 * e.n_tokens for e in estimates) / total, 8
        ),
        "n_rows": len(estimates),
        "n_tokens": total,
        "n_rows_failed": len(failures),
        "failures": failures[:20],
        "reading": (
            "~0 with stable reward: true on-policy. ~1e-3 with importance "
            "weighting: corrected off-policy, fine. A spike alongside a reward "
            "crash: missing IW or nondeterministic batching."
        ),
    }
