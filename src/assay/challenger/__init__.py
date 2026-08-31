from .base import (  # noqa: F401
    Attempt,
    Challenger,
    ChallengerExhausted,
    action_template,
    action_vocabulary,
    vocabulary_or_reason,
)
from .composite import CompositeChallenger  # noqa: F401
from .scripted import ScriptedChallenger  # noqa: F401

__all__ = [
    "Attempt",
    "Challenger",
    "ChallengerExhausted",
    "ScriptedChallenger",
    "CompositeChallenger",
    "PromptedChallenger",
    "PolicySynthesisChallenger",
    "GRPOChallenger",
    "action_template",
    "action_vocabulary",
    "vocabulary_or_reason",
]


def __getattr__(name: str):
    if name == "PromptedChallenger":
        from .prompted import PromptedChallenger

        return PromptedChallenger
    if name == "PolicySynthesisChallenger":
        from .synthesis import PolicySynthesisChallenger

        return PolicySynthesisChallenger
    if name == "GRPOChallenger":
        from .grpo import GRPOChallenger

        return GRPOChallenger
    raise AttributeError(name)
