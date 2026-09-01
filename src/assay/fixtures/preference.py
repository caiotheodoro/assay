"""An environment with no correct answer, authored here.

`inspect_evals/personality_BFI` is the real case: a psychometric inventory
whose scorer checks the response *format* because there is no key to grade
against, which the verifier-integrity family reads as "the verifier cannot
fail". `docs/COVERAGE.md` works that through in full.

That environment cannot appear in a committed trajectory. Its items are
third-party content and `tests/test_trajectory_export.py` refuses to ship any,
which is the right rule and is not one to weaken for a demonstration. So the
shape is reproduced here on statements written for this repo: five points on a
Likert scale, all of them legitimate answers, and a verifier that checks the
answer is on the scale and nothing more.

Deliberately **not** in `fixtures.toy.CATALOG`. Everything in that catalogue is
scored in `results/full_run.json`, and adding a thirteenth environment would
move every published number to make a trajectory prettier. This is built by
name, by the trajectory export and by tests, and by nothing else.

The measurement against the real `personality_BFI` is in
`results/semantic_gate.json`, which records verdicts and counts and no
third-party text.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..types import Action, Manifest, Score, Task, Transcript
from .toy import ToyEnv

#: Every one of these is a legitimate answer. That is the whole point.
SCALE = ["strongly disagree", "disagree", "neutral", "agree", "strongly agree"]

#: Written for this repo. Ids match `toy.TICKETS` so the inherited episode
#: machinery keeps working unchanged.
STATEMENTS: list[tuple[str, str]] = [
    ("t1", "I would rather plan a trip in detail than improvise when I arrive."),
    ("t2", "I find it easy to start a conversation with someone I have not met."),
    ("t3", "I prefer to finish one task completely before beginning another."),
]


@dataclass
class PreferenceEnv(ToyEnv):
    """A self-report inventory. No answer is wrong, and the verifier knows it."""

    variant: str = "preference"

    def _statement(self, task_id: str) -> str:
        return next(text for tid, text in STATEMENTS if tid == task_id)

    def _target(self, task_id: str) -> str:
        """There is no correct answer; gold submits a legitimate one."""
        return "agree"

    def manifest(self) -> Manifest:
        return replace(
            super().manifest(),
            env_id="toy-triage/preference",
            source="assay.fixtures.preference",
            tasks=[
                Task(
                    task_id=tid,
                    instruction=(
                        f"How much do you agree with the following statement? "
                        f"{text} Respond with one of: {', '.join(SCALE)}."
                    ),
                    metadata={"statement": text},
                )
                for tid, text in STATEMENTS
            ],
        )

    def reset(self, task_id: str, seed: int = 0):
        result = super().reset(task_id, seed)
        return replace(result, data={"statement": self._statement(task_id)})

    def gold_actions(self, task_id: str) -> list[Action]:
        return [Action("submit", {"label": "agree", "rationale": "a considered answer"})]

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        """There is no wrong answer, so the 'wrong' one is another valid point."""
        return [Action("submit", {"label": "disagree", "rationale": "also considered"})]

    def invert_spec(self, task_id: str) -> Any:
        return "not-a-scale-point"

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        """Format only. The trait score is computed from the answer, not graded.

        The spec is accepted and ignored, exactly as `any_choice()` ignores it
        upstream: there is no target to compare against, so an inverted spec
        changes nothing and `inverted_fails` reports INVERT_PASSES. That finding
        is mechanically correct and semantically wrong, which is the entire
        reason this environment exists.
        """
        label, _, _ = self._submission(transcript)
        on_scale = label in SCALE
        return Score(
            on_scale,
            1.0 if on_scale else 0.0,
            {"note": "format check: every point on the scale is a valid response"},
        )

    def true_completion(self, transcript: Transcript) -> float:
        label, _, _ = self._submission(transcript)
        return 1.0 if label in SCALE else 0.0

# --------------------------------------------------------------------------
# Two more shapes, because one template instantiated three times measures the
# template. Each asks a question with no key, in a different way: a ranking
# where any order is a defensible preference, and an open prompt where the
# response is prose. `docs/PRE-REGISTRATION-NOANSWER.md` predicted all three
# behave like `preference` -- four spurious classes each -- before they existed.
# --------------------------------------------------------------------------

#: Any permutation is a legitimate answer.
OPTIONS = ["train", "car", "bicycle", "walking"]

RANKING_PROMPTS: list[tuple[str, str]] = [
    ("t1", "Rank these ways of getting to work, best first, for you."),
    ("t2", "Rank the same four for a journey of about two miles, for you."),
    ("t3", "Rank the same four for a rainy winter morning, for you."),
]

OPEN_PROMPTS: list[tuple[str, str]] = [
    ("t1", "In two sentences, describe a place you find restful."),
    ("t2", "In two sentences, describe something you changed your mind about."),
    ("t3", "In two sentences, describe a habit you would like to keep."),
]


@dataclass
class RankingEnv(PreferenceEnv):
    """Rank four options by preference. Every permutation is a valid answer."""

    variant: str = "ranking"

    def _statement(self, task_id: str) -> str:
        return next(text for tid, text in RANKING_PROMPTS if tid == task_id)

    def _target(self, task_id: str) -> str:
        return "train > bicycle > walking > car"

    def manifest(self) -> Manifest:
        return replace(
            super().manifest(),
            env_id="noanswer/ranking",
            source="assay.fixtures.preference",
            tasks=[
                Task(
                    task_id=tid,
                    instruction=(
                        f"{text} Give an order over: {', '.join(OPTIONS)}, "
                        "written as `a > b > c > d`."
                    ),
                    metadata={"prompt": text},
                )
                for tid, text in RANKING_PROMPTS
            ],
        )

    def gold_actions(self, task_id: str) -> list[Action]:
        return [Action("submit", {"label": self._target(task_id),
                                     "rationale": "one defensible order"})]

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        return [Action("submit", {"label": "car > walking > bicycle > train",
                                     "rationale": "another defensible order"})]

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        """Format only: does the answer name all four options exactly once?"""
        label, _, _ = self._submission(transcript)
        named = [o for o in OPTIONS if label and o in label]
        ok = len(named) == len(OPTIONS)
        return Score(
            ok, 1.0 if ok else 0.0,
            {"note": "format check: any order over the four options is a valid answer"},
        )


@dataclass
class OpenEndedEnv(PreferenceEnv):
    """A short free-writing prompt. There is no key to grade against."""

    variant: str = "openended"

    MIN_WORDS = 4

    def _statement(self, task_id: str) -> str:
        return next(text for tid, text in OPEN_PROMPTS if tid == task_id)

    def _target(self, task_id: str) -> str:
        return "a quiet room with a window and no clock in it"

    def manifest(self) -> Manifest:
        return replace(
            super().manifest(),
            env_id="noanswer/openended",
            source="assay.fixtures.preference",
            tasks=[
                Task(task_id=tid, instruction=text, metadata={"prompt": text})
                for tid, text in OPEN_PROMPTS
            ],
        )

    def gold_actions(self, task_id: str) -> list[Action]:
        return [Action("submit", {"label": self._target(task_id),
                                     "rationale": "one honest answer"})]

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        return [Action("submit", {"label": "a busy street corner at rush hour",
                                     "rationale": "a different honest answer"})]

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        """Format only: is it prose of roughly the requested length?"""
        label, _, _ = self._submission(transcript)
        ok = bool(label) and len(str(label).split()) >= self.MIN_WORDS
        return Score(
            ok, 1.0 if ok else 0.0,
            {"note": "format check: any prose response of the requested length is valid"},
        )
