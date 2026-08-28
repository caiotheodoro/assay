"""The two LLM baselines the hackathon brief names.

  direct_prompt   one prompt, everything a reviewer could read, one answer
  agent_with_tools  the same, plus turns in which it may actually run things

Both are given the exact defect taxonomy Assay reports against, and the same
source access -- manifest, instructions, verifier code. Handing a baseline less
than a person would have and then reporting that it found nothing is not a fair
comparison, it is a rigged one.

What they are NOT given is the planted ground truth, and neither is Assay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..adapter import EnvAdapter
from ..challenger.base import action_vocabulary
from ..challenger.prompted import _extract_json
from ..llm import LLMClient, LLMUnavailable
from ..types import Action, DefectClass, Transcript

TAXONOMY = "\n".join(f"  {d.value}" for d in DefectClass)

SYSTEM = f"""You audit evaluation environments for validity defects.

You are asked whether an environment measures what it claims. Report only
defects you have positive reason to believe are present. Guessing costs you --
a false alarm is a real cost, not a free lottery ticket.

The defect classes are exactly these:
{TAXONOMY}

Reply with ONE JSON object and nothing else:
{{"defects": ["CLASS", ...], "reasoning": "<two sentences at most>"}}
An empty list is a valid and often correct answer. No markdown fences."""

AGENT_SYSTEM = SYSTEM + """

Before answering you may take up to N turns to run things in the environment.
On each of those turns reply instead with:
{"tool": "<tool>", "args": {...}, "reasoning": "<one sentence>"}
When you are ready to report, reply with the defects object above."""


def _parse_defects(raw: str) -> set[DefectClass]:
    parsed = _extract_json(raw)
    if not parsed or "defects" not in parsed:
        return set()
    out = set()
    for name in parsed["defects"] or []:
        try:
            out.add(DefectClass(str(name).strip().upper()))
        except ValueError:
            continue  # a hallucinated class is not a detection
    return out


@dataclass
class DirectPromptArm:
    """One prompt with basic instructions -- the brief's first suggestion."""

    client: LLMClient
    arm: str = "direct_prompt"

    def run(self, adapter: EnvAdapter) -> tuple[frozenset[DefectClass], list[str]]:
        prompt = (
            f"{adapter.describe()}\n\n"
            "Which validity defects, if any, does this environment have?"
        )
        try:
            raw = self.client.complete(SYSTEM, prompt)
        except LLMUnavailable as exc:
            return frozenset(), [f"model unavailable: {exc}"]
        return frozenset(_parse_defects(raw)), [raw[:400]]


@dataclass
class ToolAgentArm:
    """One general-purpose agent with basic tools -- the brief's second."""

    client: LLMClient
    turns: int = 6
    arm: str = "agent_with_tools"

    def run(self, adapter: EnvAdapter) -> tuple[frozenset[DefectClass], list[str]]:
        manifest = adapter.manifest()
        if not manifest.tasks:
            return frozenset(), ["environment declares no tasks"]
        task_id = manifest.tasks[0].task_id
        vocabulary = action_vocabulary(adapter, task_id)
        tools = "\n".join(f"  {t}({', '.join(a)})" for t, a in vocabulary) or "  (none)"

        log: list[str] = []
        history: list[str] = []
        system = AGENT_SYSTEM.replace("up to N turns", f"up to {self.turns} turns")

        for turn in range(1, self.turns + 1):
            prompt = (
                f"{adapter.describe()}\n\nTools available:\n{tools}\n\n"
                + ("\n".join(history) if history else "You have not run anything yet.")
                + f"\n\nTurn {turn} of {self.turns}. Act, or report your defects."
            )
            try:
                raw = self.client.complete(system, prompt)
            except LLMUnavailable as exc:
                log.append(f"model unavailable: {exc}")
                break
            log.append(raw[:300])
            parsed = _extract_json(raw)
            if not parsed:
                history.append(f"turn {turn}: reply was not JSON; ignored")
                continue
            if "defects" in parsed:
                return frozenset(_parse_defects(raw)), log
            if "args" not in parsed or not vocabulary:
                history.append(f"turn {turn}: reply was neither an action nor a report")
                continue
            action = Action(str(parsed.get("tool") or vocabulary[0][0]), dict(parsed["args"]))
            adapter.reset(task_id, seed=0)
            transcript = Transcript(task_id=task_id, seed=0)
            result = adapter.step(action)
            transcript.record(action, result)
            score = adapter.verify(transcript)
            history.append(
                f"turn {turn}: {json.dumps({'tool': action.tool, 'args': action.args})[:200]}"
                f"\n  output: {json.dumps(result.observation.data)[:250]}"
                f"\n  environment scored it: {score.reward}"
            )

        # Out of turns without a report. That is a null result, not a clean one.
        log.append("agent used every turn without reporting; recorded as no defects found")
        return frozenset(), log
