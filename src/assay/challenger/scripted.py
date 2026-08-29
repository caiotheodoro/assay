"""The scripted Challenger: a fixed repertoire, no model.

Deliberately dumb. It is the floor a prompted or trained Challenger has to
beat, and because it needs no model it keeps the reproduction path free of
GPUs, API keys, and network.

It still keeps a log. `attacker_trace` was empty for this arm in every result
file the project has published, which means the one arm whose *miss* carries
the whole agentic argument was the one with no record of what it actually
tried. An arm with no trajectory is an arm a reader has to take on trust.
"""

from __future__ import annotations

import json
from typing import Any

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

        attempts: list[Attempt] = []
        history: list[dict[str, Any]] = []
        for turn, (label, actions) in enumerate(candidates, start=1):
            transcript = run_policy(adapter, task_id, actions)
            history.append(
                {
                    "turn": turn,
                    "policy": label,
                    "reasoning": (
                        f"fixed repertoire entry {label!r}; no model in the loop, so "
                        "nothing here is chosen in response to what came back"
                    ),
                    "action": {
                        "policy": label,
                        "actions": [
                            {"tool": a.tool, "args": a.args} for a in transcript.actions
                        ],
                    },
                    "observation": json.dumps(
                        [o.data for o in transcript.observations], default=str
                    )[:400],
                }
            )
            # Each attempt carries the history up to and including itself, so
            # the last one holds the whole run -- the shape the probe reads.
            # No score is recorded here on purpose: the probe scores these, the
            # attacker never saw a number, and writing one in would put
            # knowledge into the record that the attacker did not have.
            attempts.append(Attempt(label=label, transcript=transcript, log=list(history)))
        return attempts
