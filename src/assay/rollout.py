"""Estimating how hard an environment's tasks actually are.

The difficulty-band probe needs a solve rate, and a solve rate needs a policy
that genuinely tries. Scripted policies cannot supply one: they either know the
answer or ignore the question, so they measure 1.0 or 0.0 and nothing between.

So this runs a real solver -- a small local model, several samples per task --
and reports the fraction the environment's own verifier accepts. Local by
default, because a difficulty estimate that needs an API key is a difficulty
estimate the reproduction guide cannot promise.

The number is noisy at small sample counts and the probe treats it that way:
it flags only the ends of the range, saturated and impossible, where a handful
of samples is enough to be sure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .adapter import EnvAdapter, run_policy
from .challenger.base import action_vocabulary
from .challenger.prompted import _extract_json
from .llm import LLMClient, LLMUnavailable, default_client

SYSTEM = """You are solving a task inside an evaluation environment.

Do the task as well as you can. Reply with ONE action as a JSON object and
nothing else:
{"tool": "<tool>", "args": {...}}
No markdown fences. No prose outside the JSON."""


@dataclass
class SolveRateSampler:
    client: LLMClient | None = None
    samples: int = 5

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = default_client()

    @property
    def name(self) -> str:
        return f"solver[{self.client.name}]"

    def _prompt(self, instruction: str, vocabulary: list[tuple[str, list[str]]]) -> str:
        tools = "\n".join(f"  {tool}({', '.join(args)})" for tool, args in vocabulary)
        return (
            f"Task:\n  {instruction or '(no instruction provided)'}\n\n"
            f"Tools available to you:\n{tools}\n\nWhat is your action?"
        )

    def solve_rates(self, adapter: EnvAdapter) -> dict[str, float]:
        rates: dict[str, float] = {}
        for task in adapter.manifest().tasks:
            vocabulary = action_vocabulary(adapter, task.task_id)
            if not vocabulary:
                continue
            default_tool = vocabulary[0][0]
            solved = 0
            attempted = 0
            for _ in range(self.samples):
                try:
                    raw = self.client.complete(
                        SYSTEM, self._prompt(task.instruction, vocabulary)
                    )
                except LLMUnavailable:
                    break
                parsed = _extract_json(raw)
                attempted += 1
                if not parsed or "args" not in parsed:
                    continue  # a malformed reply is a failed attempt, not a skipped one
                from .types import Action

                action = Action(str(parsed.get("tool") or default_tool), dict(parsed["args"]))
                transcript = run_policy(adapter, task.task_id, [action])
                if adapter.verify(transcript).passed:
                    solved += 1
            if attempted:
                rates[task.task_id] = solved / attempted
        return rates
