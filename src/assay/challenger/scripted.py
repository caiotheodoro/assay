"""The scripted Challenger: a fixed repertoire, no model.

Deliberately dumb. It is the floor a prompted or trained Challenger has to
beat, and because it needs no model it keeps the reproduction path free of
GPUs, API keys, and network.
"""

from __future__ import annotations

from ..adapter import EnvAdapter, run_policy
from .base import Attempt


class ScriptedChallenger:
    name = "scripted"

    def attack(self, adapter: EnvAdapter, task_id: str) -> list[Attempt]:
        candidates: list[tuple[str, list]] = [("empty", [])]
        try:
            candidates += [
                (f"trivial:{label}", actions)
                for label, actions in adapter.trivial_policies(task_id).items()
            ]
        except Exception:  # noqa: BLE001 - absence of trivial policies is not a failure
            pass
        return [
            Attempt(label=label, transcript=run_policy(adapter, task_id, actions))
            for label, actions in candidates
        ]
