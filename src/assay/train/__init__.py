"""Training the adversarial Challenger.

This package is the HARNESS side of the split that `assay.challenger.grpo`
enforces. It holds the independent verifier, replays proposed policies, and
turns the exploit gap into a scalar reward. The attacker never imports from
here, and nothing here is needed to run Assay: the trained Challenger is an
optional artifact, the scripted one is the floor, and the reproduction guide
never needs a GPU.

Every heavy dependency (torch, trl, peft) is imported inside a function, so
`import assay.train` costs nothing on a machine that only ever audits.
"""

from .reward import (  # noqa: F401
    PARSE_PENALTY,
    RewardBreakdown,
    exploit_gap_reward_func,
    make_reward_func,
    policy_reward,
)

__all__ = [
    "PARSE_PENALTY",
    "RewardBreakdown",
    "exploit_gap_reward_func",
    "make_reward_func",
    "policy_reward",
]
