from .base import Attempt, Challenger, action_template, action_vocabulary  # noqa: F401
from .scripted import ScriptedChallenger  # noqa: F401

__all__ = [
    "Attempt",
    "Challenger",
    "ScriptedChallenger",
    "PromptedChallenger",
    "action_template",
    "action_vocabulary",
]


def __getattr__(name: str):
    if name == "PromptedChallenger":
        from .prompted import PromptedChallenger

        return PromptedChallenger
    raise AttributeError(name)
