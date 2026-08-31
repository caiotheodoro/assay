"""An environment described as data, not as code.

The Space needs a way for a stranger to submit an environment and get a card
back. Executing a stranger's Python on a public host is not a way; a
declarative spec is. The submitter writes down the tasks, the targets and the
rule the verifier applies, and this module turns that into an `EnvAdapter` the
probe battery can drive.

Two things make the spec worth auditing rather than a toy:

`target` and the verifier are separate. The target is what the task actually
asks for; the verifier is the rule the environment happens to apply. Every
interesting eval defect lives in the gap between those two -- a substring
verifier against the target `No` credits `"I don't know"` -- and a format that
collapsed them into one field could not express a single one of them.

Capabilities are derived from what the spec contains, never asserted by the
submitter. A spec with no train split does not get `SPLITS`, the contamination
probe reports NOT_APPLICABLE with that reason, and the card says so. A
submitter cannot talk a probe into passing by claiming a capability, and cannot
hide one by omitting a field -- omission is reported just as loudly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .. import safe_regex
from ..adapter import BaseAdapter, NotSupported
from ..types import (
    Action,
    Capability,
    Item,
    Manifest,
    Observation,
    Score,
    StepResult,
    Task,
    Transcript,
)


class SpecError(ValueError):
    """The submitted spec is not usable. Says which field and why."""


#: How the environment decides a submission passed. `exact` is the only one
#: that cannot be loose; the rest are here because real evals use them and this
#: tool exists to show what they cost.
MATCHERS = ("exact", "exact_ci", "includes", "regex", "always_pass", "always_fail")

#: Matchers that ask whether the target *occurs in* the answer rather than
#: whether it equals it. Every one of these is satisfied by a constant
#: string naming all the targets at once.
_SUBSTRING_MATCHERS = ("includes",)

MAX_TASKS = 200
MAX_ITEMS = 2000
MAX_TEXT = 20_000

SUBMIT = "submit"


def _matches(kind: str, answer: str, target: str) -> bool:
    if kind == "always_pass":
        return True
    if kind == "always_fail":
        return False
    if kind == "exact":
        return answer == target
    if kind == "exact_ci":
        return answer.strip().casefold() == target.strip().casefold()
    if kind == "includes":
        return target.casefold() in answer.casefold()
    if kind == "regex":
        # Never `re.search` here. The pattern arrives from whoever submitted the
        # spec, Python's engine backtracks, and `(a+)+$` against 31 characters
        # takes about 100 seconds -- a denial of service on a public Space with
        # a payload of a dozen bytes. Catching re.error does not help: that
        # fires when a pattern fails to COMPILE, and one that compiles cleanly
        # and runs forever is not an error.
        try:
            return safe_regex.search(target, answer)
        except safe_regex.PatternInvalid as exc:
            raise SpecError(
                f"verifier.kind=regex but target {target!r} is not a regex: {exc}"
            ) from exc
    raise SpecError(f"verifier.kind must be one of {MATCHERS}, got {kind!r}")


@dataclass(frozen=True)
class SpecTask:
    task_id: str
    instruction: str
    target: str
    gold: str | None = None
    known_wrong: str | None = None
    asserts: tuple[str, ...] = ()


@dataclass
class EnvSpec:
    """The parsed, validated submission. Construction is the whole validation."""

    env_id: str
    verifier: str
    tasks: tuple[SpecTask, ...]
    train: tuple[Item, ...] = ()
    eval: tuple[Item, ...] = ()
    trivial_answers: tuple[str, ...] = ()
    version: str = "submitted"

    @staticmethod
    def _items(raw: Any, where: str) -> tuple[Item, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise SpecError(f"{where} must be a list of items")
        if len(raw) > MAX_ITEMS:
            raise SpecError(f"{where} has {len(raw)} items; the cap is {MAX_ITEMS}")
        out = []
        for i, row in enumerate(raw):
            if not isinstance(row, dict):
                raise SpecError(f"{where}[{i}] must be an object")
            text = str(row.get("text", ""))
            if len(text) > MAX_TEXT:
                raise SpecError(f"{where}[{i}].text is {len(text)} chars; the cap is {MAX_TEXT}")
            parts = row.get("parts") or {}
            if not isinstance(parts, dict):
                raise SpecError(f"{where}[{i}].parts must be an object")
            out.append(
                Item(
                    item_id=str(row.get("item_id", f"{where}-{i}")),
                    text=text,
                    label=row.get("label"),
                    parts={str(k): str(v) for k, v in parts.items()},
                )
            )
        return tuple(out)

    @classmethod
    def parse(cls, raw: str | dict[str, Any]) -> EnvSpec:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SpecError(f"not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise SpecError("the spec must be a JSON object")

        env_id = str(raw.get("env_id") or "").strip()
        if not env_id:
            raise SpecError("env_id is required; it is what the card is about")

        verifier = raw.get("verifier")
        if isinstance(verifier, dict):
            verifier = verifier.get("kind")
        verifier = str(verifier or "exact")
        if verifier not in MATCHERS:
            raise SpecError(f"verifier must be one of {MATCHERS}, got {verifier!r}")

        raw_tasks = raw.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise SpecError("tasks must be a non-empty list")
        if len(raw_tasks) > MAX_TASKS:
            raise SpecError(f"{len(raw_tasks)} tasks submitted; the cap is {MAX_TASKS}")

        tasks = []
        for i, row in enumerate(raw_tasks):
            if not isinstance(row, dict):
                raise SpecError(f"tasks[{i}] must be an object")
            target = row.get("target")
            if target is None:
                raise SpecError(
                    f"tasks[{i}].target is required. It is what the task asks for, as "
                    "distinct from what the verifier accepts -- the gap between those "
                    "two is what most of these probes measure."
                )
            asserts = row.get("asserts") or []
            if not isinstance(asserts, list):
                raise SpecError(f"tasks[{i}].asserts must be a list of strings")
            tasks.append(
                SpecTask(
                    task_id=str(row.get("task_id", f"t{i + 1}")),
                    instruction=str(row.get("instruction", "")),
                    target=str(target),
                    gold=None if row.get("gold") is None else str(row["gold"]),
                    known_wrong=(
                        None if row.get("known_wrong") is None else str(row["known_wrong"])
                    ),
                    asserts=tuple(str(a) for a in asserts),
                )
            )

        seen = [t.task_id for t in tasks]
        if len(set(seen)) != len(seen):
            raise SpecError("task_id values must be unique")

        trivial = raw.get("trivial_answers") or []
        if not isinstance(trivial, list):
            raise SpecError("trivial_answers must be a list of strings")

        return cls(
            env_id=env_id,
            verifier=verifier,
            tasks=tuple(tasks),
            train=cls._items(raw.get("train"), "train"),
            eval=cls._items(raw.get("eval"), "eval"),
            trivial_answers=tuple(str(a) for a in trivial),
            version=str(raw.get("version", "submitted")),
        )


@dataclass
class SpecAdapter(BaseAdapter):
    """Drives a submitted `EnvSpec` through the probe protocol."""

    spec: EnvSpec
    _task_id: str | None = field(default=None, init=False)
    _seed: int = field(default=0, init=False)
    _answer: str | None = field(default=None, init=False)

    # -- capabilities ------------------------------------------------------

    def _capabilities(self) -> frozenset[Capability]:
        spec = self.spec
        caps = {
            Capability.LIVE_STEPPING,
            Capability.SEEDED_RESET,
            Capability.SEPARABLE_VERIFIER,
            Capability.TRUE_COMPLETION,
            Capability.TRIVIAL_POLICIES,
        }
        if all(t.gold is not None for t in spec.tasks):
            caps.add(Capability.GOLD_TRAJECTORY)
        if all(t.known_wrong is not None for t in spec.tasks):
            caps.add(Capability.KNOWN_WRONG)
        if Capability.GOLD_TRAJECTORY in caps and Capability.KNOWN_WRONG in caps:
            caps.add(Capability.GRADED_POLICIES)
        # An always-pass or always-fail verifier consults no target, so there is
        # no rule to negate and "must not match" is not expressible.
        if spec.verifier not in ("always_pass", "always_fail"):
            caps.add(Capability.INVERTIBLE_SPEC)
        if spec.train and spec.eval:
            caps.add(Capability.SPLITS)
        if spec.eval and any(i.parts for i in spec.eval):
            caps.add(Capability.ITEM_PARTS)
        return frozenset(caps)

    def manifest(self) -> Manifest:
        return Manifest(
            env_id=self.spec.env_id,
            ecosystem="spec",
            tasks=[
                Task(
                    task_id=t.task_id,
                    instruction=t.instruction,
                    metadata={"verifier": self.spec.verifier},
                )
                for t in self.spec.tasks
            ],
            capabilities=self._capabilities(),
            version=self.spec.version,
            source="submitted environment spec",
        )

    # -- episode -----------------------------------------------------------

    def _task(self, task_id: str) -> SpecTask:
        for t in self.spec.tasks:
            if t.task_id == task_id:
                return t
        raise SpecError(f"unknown task_id {task_id!r}")

    def reset(self, task_id: str, seed: int = 0) -> Observation:
        task = self._task(task_id)
        self._task_id, self._seed, self._answer = task_id, seed, None
        return Observation(ok=True, data={"instruction": task.instruction})

    def step(self, action: Action) -> StepResult:
        if action.tool != SUBMIT:
            return StepResult(
                observation=Observation(
                    ok=False, code="unknown_tool", message=f"only {SUBMIT!r} is available"
                ),
                done=False,
            )
        self._answer = str(action.args.get("answer", ""))
        return StepResult(observation=Observation(ok=True, data={"received": True}), done=True)

    # -- verification ------------------------------------------------------

    @staticmethod
    def _submitted(transcript: Transcript) -> str | None:
        for action in reversed(transcript.actions):
            if action.tool == SUBMIT:
                return str(action.args.get("answer", ""))
        return None

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        """The environment's own opinion, applying the declared matcher.

        `spec` is the inverted-spec override: `{"negate": True}` asks whether
        the verifier still passes when its rule is flipped, which is how family
        1 catches a verifier that cannot fail.
        """
        task = self._task(transcript.task_id)
        answer = self._submitted(transcript)
        negate = bool(spec.get("negate")) if isinstance(spec, dict) else False
        target = (
            str(spec["target"])
            if isinstance(spec, dict) and spec.get("target") is not None
            else task.target
        )
        passed = _matches(self.spec.verifier, answer if answer is not None else "", target)
        if negate:
            passed = not passed
        return Score(
            passed=passed,
            reward=1.0 if passed else 0.0,
            profile={"matcher": self.spec.verifier, "target": target, "answer": answer},
        )

    def invert_spec(self, task_id: str) -> Any:
        if self.spec.verifier in ("always_pass", "always_fail"):
            raise NotSupported("an always-pass/always-fail verifier consults no rule to invert")
        return {"negate": True}

    def true_completion(self, transcript: Transcript) -> float:
        """Exact match against what the task asked for.

        Deliberately stricter than `verify`. The Challenger is paid the
        difference, so a loose verifier is exactly what it is hunting.
        """
        task = self._task(transcript.task_id)
        answer = self._submitted(transcript)
        if answer is None:
            return 0.0
        return 1.0 if answer.strip().casefold() == task.target.strip().casefold() else 0.0

    # -- optional capabilities --------------------------------------------

    def gold_actions(self, task_id: str) -> list[Action]:
        task = self._task(task_id)
        if task.gold is None:
            raise NotSupported(f"tasks[{task_id}] declares no gold answer")
        return [Action(SUBMIT, {"answer": task.gold})]

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        task = self._task(task_id)
        if task.known_wrong is None:
            raise NotSupported(f"tasks[{task_id}] declares no known-wrong answer")
        return [Action(SUBMIT, {"answer": task.known_wrong})]

    def train_items(self) -> list[Item]:
        if not self.spec.train:
            raise NotSupported("the spec declares no train split")
        return list(self.spec.train)

    def eval_items(self) -> list[Item]:
        if not self.spec.eval:
            raise NotSupported("the spec declares no eval split")
        return list(self.spec.eval)

    def verifier_asserts(self, task_id: str) -> list[str]:
        task = self._task(task_id)
        if not task.asserts:
            raise NotSupported(
                f"tasks[{task_id}] lists no verifier asserts, so there is nothing to "
                "trace back against the instruction"
            )
        return list(task.asserts)

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        """Policies that ignore the task. The modal target is the majority-class
        baseline; the submitter may add more, and the empty answer is always
        included because "say nothing" is the cheapest policy there is."""
        answers: dict[str, str] = {"empty": ""}
        targets = [t.target for t in self.spec.tasks]
        if targets:
            answers["majority_class"] = max(set(targets), key=targets.count)

        # Under a substring matcher, one constant string containing every
        # declared target answers every task. This is not a heuristic and it is
        # not a guess about the data: `includes` asks whether the target occurs
        # in the answer, so an answer that contains all of them satisfies all of
        # them. It is the `paws` defect this project leads with -- `includes()`
        # against `Yes` and `No`, and the constant `"yesno"` scoring 8000/8000 --
        # and until now Assay could find it in a published eval and not in a
        # spec a reader submitted, which is the one thing this adapter is for.
        #
        # Declared as a policy rather than a new probe so the existing
        # reward-hackability machinery decides whether it actually pays. The
        # adapter proposes; the verifier scores.
        distinct = sorted({t for t in targets if t})
        if self.spec.verifier in _SUBSTRING_MATCHERS and len(distinct) > 1:
            answers["every_target_at_once"] = " ".join(distinct)

        for i, answer in enumerate(self.spec.trivial_answers):
            answers[f"submitted_{i + 1}"] = answer
        return {name: [Action(SUBMIT, {"answer": a})] for name, a in answers.items()}

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        task = self._task(task_id)
        if task.gold is None or task.known_wrong is None:
            raise NotSupported(
                f"tasks[{task_id}] needs both gold and known_wrong to define policies "
                "of known-differing quality"
            )
        return {
            "gold": [Action(SUBMIT, {"answer": task.gold})],
            "known_wrong": [Action(SUBMIT, {"answer": task.known_wrong})],
        }


def build(raw: str | dict[str, Any]) -> SpecAdapter:
    return SpecAdapter(spec=EnvSpec.parse(raw))
