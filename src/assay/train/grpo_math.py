"""Group-relative advantages and the DAPO decoupled clip.

Reused, not rewritten, from a sibling project:
`plumb/curriculum/src/plumb_curriculum/grpo.py`. See docs/LINEAGE.md. TRL's
GRPOTrainer implements this internally; the copy is here because it is
torch-free, so the advantage arithmetic this project's reward feeds into can be
asserted on a laptop with no GPU and no trainer -- and because the offline
analysis of a run's reward log wants the same numbers the trainer saw.

GRPO (DeepSeekMath) normalises advantages within one prompt's rollout group.
The clip is DAPO-style and decoupled: the ratio is bounded to
[1 - eps_low, 1 + eps_high] with eps_high > eps_low, so low-probability tokens
are not driven to zero. Dr.GRPO drops per-token length normalisation -- the
policies here are short, fixed-shape JSON, so length plays no role.
"""

from __future__ import annotations

import math


def group_advantages(rewards: list[float], eps: float = 1e-4) -> list[float]:
    """(r - mean) / (std + eps) within one prompt's rollout group.

    A group whose rewards are all equal yields all-zero advantages and hence no
    gradient. That is not a bug to paper over: it is the honest statement that
    an environment nobody in the group could hack teaches nothing this step.
    """
    n = len(rewards)
    if n == 0:
        return []
    mean = sum(rewards) / n
    var = sum((r - mean) ** 2 for r in rewards) / n
    std = math.sqrt(var + eps)
    return [(r - mean) / std for r in rewards]


def decoupled_clip(ratio: float, eps_low: float = 0.2, eps_high: float = 1.0) -> float:
    """DAPO decoupled clip: clamp the ratio to [1-eps_low, 1+eps_high]."""
    return min(max(ratio, 1.0 - eps_low), 1.0 + eps_high)


def grpo_loss(
    new_logps: list[list[float]],
    old_logps: list[list[float]],
    advantages: list[float],
    eps_low: float = 0.2,
    eps_high: float = 1.0,
) -> float:
    """Mean negative decoupled-clip surrogate over all sampled tokens."""
    total = 0.0
    count = 0
    for nl, ol, adv in zip(new_logps, old_logps, advantages):
        for n, o in zip(nl, ol):
            ratio = math.exp(n - o)
            total += decoupled_clip(ratio, eps_low, eps_high) * adv
            count += 1
    return -total / count if count else 0.0


def ratio_bounds(eps_low: float = 0.2, eps_high: float = 1.0) -> tuple[float, float]:
    return (1.0 - eps_low, 1.0 + eps_high)


def group_is_degenerate(rewards: list[float], tol: float = 1e-9) -> bool:
    """True when every rollout in the group scored the same, so GRPO gets no
    signal from it. Counted per step and reported: a run whose groups are
    mostly degenerate did not fail to converge, it was never trained."""
    return not rewards or (max(rewards) - min(rewards)) <= tol
