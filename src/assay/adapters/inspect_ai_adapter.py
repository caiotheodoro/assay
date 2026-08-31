"""Adapter for inspect_ai (UK AISI).

Chosen as the first real ecosystem because its tasks are plain importable
Python: `Sample`, `Solver`, `Scorer` are objects, so an auditor can enumerate
the dataset and call the scorer directly without spinning up a container or
spending a single token. That is the cheapest adapter to write, and the
cheapness is load-bearing -- the wild sweep scores 246 published tasks, which a
container per scorer call would price out of existence.

It is **not** the safest to run, and this docstring used to say it was. Calling
`scorer(state, target)` executes somebody else's Python in the auditor's own
interpreter. Nothing that protects the Harbor path applies: no `--cap-drop
ALL`, no `--network none`, no read-only root, no wall-clock cap. A scorer that
opens a socket or reads `~/.ssh` is doing something this adapter cannot see or
stop.

That is a deliberate trade and it is now an approved one. Scoring asks
`current_approver()` once per adapter with an `InProcessRequest` that names the
scorers, says why they are not in a container, and states the exposure; the
answer is recorded and reaches the Environment Card. Refused, nothing is
scored. See `docs/changelog/98-approval-gate.md` for why the choice was to gate
in-process scoring rather than to sandbox it.

The load-bearing property: `scorer(state, target)` takes the target as an
argument. Pass a different one and you have an inverted-spec probe. An
ecosystem that hard-codes the target inside the scoring call cannot be audited
this way, which is exactly why the adapter protocol insists on separability.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from ..adapter import BaseAdapter, NotSupported
from ..sandbox import (
    ApprovalDenied,
    Approver,
    InProcessRequest,
    approver_record,
    current_approver,
    describe,
    summarise,
)
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

#: inspect_ai's categorical score values.
_VALUE_REWARD = {"C": 1.0, "I": 0.0, "P": 0.5, "N": 0.0}

ANSWER_TOOL = "submit"


def _reward(value: Any) -> float:
    """inspect_ai scores may be categorical, numeric, boolean, or a dict."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _VALUE_REWARD.get(value.upper(), 0.0)
    if isinstance(value, dict) and value:
        return sum(_reward(v) for v in value.values()) / len(value)
    return 0.0


def _normalise(text: str | None) -> str:
    return (text or "").strip().lower()


class InspectAdapter(BaseAdapter):
    """Audit one inspect_ai Task.

    `train_dataset` is optional and only supplied when the suite genuinely
    ships a separate split. Without it the contamination and shortcut probes
    report NOT_APPLICABLE rather than comparing a split against itself, which
    would manufacture a clean result out of nothing.
    """

    def __init__(
        self,
        task: Any,
        *,
        env_id: str | None = None,
        train_dataset: Any | None = None,
        pass_threshold: float = 1.0,
        approver: Approver | None = None,
    ) -> None:
        #: Who says yes to running this task's scorer in the auditor's own
        #: process. `None` means resolve it at the moment of asking, which is
        #: how the CLI's `--yes` and `ASSAY_APPROVE_ALL` reach here.
        self._approver = approver
        #: None until asked. Asked once per adapter, not once per sample: a
        #: 25-item probe battery that prompted per call would be answered by
        #: holding down a key.
        self._scoring_approved: bool | None = None
        self._approvals: list[dict[str, Any]] = []
        self._task = task
        self._samples = list(task.dataset)
        self._by_id = {str(s.id or i): s for i, s in enumerate(self._samples)}
        self._train = list(train_dataset) if train_dataset is not None else None
        self._env_id = env_id or getattr(task, "name", None) or "inspect_ai/task"
        self._pass_threshold = pass_threshold
        self._current: str | None = None

        scorers = task.scorer if isinstance(task.scorer, list) else [task.scorer]
        self._scorers = [s for s in scorers if s is not None]

    # -- helpers -----------------------------------------------------------

    def _sample(self, task_id: str):
        try:
            return self._by_id[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown sample id: {task_id}") from exc

    def items(self) -> list[Item]:
        """Every datum this suite ships, with no split declared.

        Distinct from `train_items` / `eval_items`, which stay unsupported and
        should: this suite ships no separate train split, and inventing one
        silently would let family 4 and family 5 report on a division the
        environment never made.

        What it *can* honestly say is what data exists. Anything that wants to
        cross-fit on it has to declare that it synthesized the split -- see
        `assay.auditor`, which does exactly that and says so on the card.
        """
        return [
            Item(
                item_id=str(sample.id or index),
                text=str(sample.input),
                label=self._target_text(sample),
            )
            for index, sample in enumerate(self._samples)
        ]

    @staticmethod
    def _target_text(sample) -> str:
        target = sample.target
        return target[0] if isinstance(target, list) and target else str(target)

    @staticmethod
    def _answer(transcript: Transcript) -> str:
        for action in reversed(transcript.actions):
            if action.tool == ANSWER_TOOL:
                return str(action.args.get("answer", ""))
        return ""

    # -- the in-process approval gate --------------------------------------

    def approval_log(self) -> list[dict[str, Any]]:
        return list(self._approvals)

    def scoring_request(self) -> InProcessRequest:
        """Exactly what the approver is asked to allow, spelled out."""
        return InProcessRequest(
            what=(
                f"call the scorer(s) of inspect_ai task {self._env_id!r} inside the "
                "Assay process"
            ),
            why_not_sandboxed=(
                "an inspect_ai scorer is a live Python closure over the task object, "
                "not a script; running it in a container would mean rebuilding "
                "inspect_ai's runtime inside the image and re-entering the task "
                "there. Assay calls it here instead, and asks first"
            ),
            callables=[getattr(fn, "__qualname__", repr(fn)) for fn in self._scorers],
        )

    def authorise_scoring(self) -> None:
        """Ask before third-party scorer code runs in this interpreter.

        Asked once and remembered, including when the answer was no: a refused
        gate that re-asks on the next of 25 samples is a gate that wears the
        person down until they say yes.
        """
        if self._scoring_approved:
            return
        request = self.scoring_request()
        if self._scoring_approved is None:
            approver = self._approver or current_approver()
            granted = bool(approver(request))
            self._approvals.append(
                {
                    **approver_record(approver),
                    "granted": granted,
                    "contained": False,
                    "what": summarise(request),
                    "detail": describe(request),
                }
            )
            self._scoring_approved = granted
        if not self._scoring_approved:
            raise ApprovalDenied(
                f"running {self._env_id}'s scorer in the Assay process was not "
                "approved; nothing was scored. This code is not contained -- pass "
                "`--yes` or set ASSAY_APPROVE_ALL if you accept that"
            )

    def _score_with(self, sample, answer: str, target_text: str) -> Score:
        self.authorise_scoring()

        from inspect_ai.model import ModelOutput
        from inspect_ai.scorer import Target
        from inspect_ai.solver import TaskState

        state = TaskState(
            model="assay/probe",
            sample_id=sample.id,
            epoch=1,
            input=sample.input,
            messages=[],
            choices=sample.choices,
            output=ModelOutput.from_content(model="assay/probe", content=answer),
        )
        target = Target(target_text)

        async def run_all():
            return [await fn(state, target) for fn in self._scorers]

        scores = asyncio.run(run_all())
        rewards = [_reward(s.value) for s in scores]
        reward = sum(rewards) / len(rewards) if rewards else 0.0
        return Score(
            passed=reward >= self._pass_threshold,
            reward=reward,
            profile={
                "answer": answer,
                "target": target_text,
                "per_scorer": [
                    {"scorer": getattr(fn, "__qualname__", "scorer"), "value": s.value}
                    for fn, s in zip(self._scorers, scores)
                ],
            },
        )

    # -- manifest ----------------------------------------------------------

    def manifest(self) -> Manifest:
        caps = {
            Capability.SEPARABLE_VERIFIER,
            Capability.GOLD_TRAJECTORY,
            Capability.INVERTIBLE_SPEC,
            Capability.KNOWN_WRONG,
            Capability.TRUE_COMPLETION,
            Capability.TRIVIAL_POLICIES,
            Capability.SEEDED_RESET,
            # Declared late: `reset` and `step` were always real here, but
            # LIVE_STEPPING gated nothing, so nobody noticed it was missing.
            # Wiring the capability to the probes that drive episodes is what
            # surfaced the under-declaration.
            Capability.LIVE_STEPPING,
        }
        # Separating a strong from a weak policy needs a plausible wrong answer,
        # which needs at least two distinct targets to draw from.
        if len({self._target_text(s) for s in self._samples}) > 1:
            caps.add(Capability.GRADED_POLICIES)
        # Declared only when every scorer's source is actually obtainable. A
        # scorer defined in a REPL, a C extension, or behind a decorator that
        # discards `__wrapped__` has no source to read, and claiming the
        # capability anyway would put the refusal at the probe instead of in the
        # manifest where a caller can see it before running anything.
        if self._scorer_sources() is not None:
            caps.add(Capability.VERIFIER_SOURCE)
        if self._train:
            caps.add(Capability.SPLITS)
            if any(self._parts(s) for s in self._train):
                caps.add(Capability.ITEM_PARTS)

        return Manifest(
            env_id=self._env_id,
            ecosystem="inspect_ai",
            version=str(getattr(self._task, "version", "unknown")),
            source="inspect_ai.Task",
            capabilities=frozenset(caps),
            tasks=[
                Task(
                    task_id=tid,
                    instruction=str(sample.input),
                    metadata=dict(sample.metadata or {}),
                )
                for tid, sample in self._by_id.items()
            ],
        )

    def describe(self) -> str:
        import inspect as pyinspect

        parts = [super().describe(), "", "scorers:"]
        for fn in self._scorers:
            name = getattr(fn, "__qualname__", repr(fn))
            try:
                source = pyinspect.getsource(fn)
            except (OSError, TypeError):
                source = "(source unavailable)"
            parts.append(f"# {name}\n{source.strip()}")
        parts.append("")
        parts.append("samples:")
        for tid, sample in self._by_id.items():
            parts.append(f"  - {tid}: input={sample.input!r} target={sample.target!r}")
        return "\n".join(parts)

    # -- episode -----------------------------------------------------------

    def reset(self, task_id: str, seed: int = 0) -> Observation:
        sample = self._sample(task_id)
        self._current = task_id
        return Observation(ok=True, data={"input": sample.input, "choices": sample.choices})

    def step(self, action: Action) -> StepResult:
        if action.tool != ANSWER_TOOL:
            return StepResult(
                Observation(ok=False, code="UNKNOWN_TOOL", message=action.tool), done=False
            )
        return StepResult(Observation(ok=True, data={"submitted": True}), done=True)

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        sample = self._sample(transcript.task_id)
        target_text = str(spec) if spec is not None else self._target_text(sample)
        return self._score_with(sample, self._answer(transcript), target_text)

    def true_completion(self, transcript: Transcript) -> float:
        """Independent of the suite's own scorer: exact match on the declared
        target. The gap between this and `verify` is what the Challenger hunts."""
        sample = self._sample(transcript.task_id)
        return 1.0 if _normalise(self._answer(transcript)) == _normalise(
            self._target_text(sample)
        ) else 0.0

    # -- policies ----------------------------------------------------------

    def gold_actions(self, task_id: str) -> list[Action]:
        return [Action(ANSWER_TOOL, {"answer": self._target_text(self._sample(task_id))})]

    def invert_spec(self, task_id: str) -> Any:
        """A target this sample's gold answer must NOT satisfy."""
        own = self._target_text(self._sample(task_id))
        for sample in self._samples:
            other = self._target_text(sample)
            if _normalise(other) != _normalise(own):
                return other
        return own + "_definitely_not_this"

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        return [Action(ANSWER_TOOL, {"answer": str(self.invert_spec(task_id))})]

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        targets = [self._target_text(s) for s in self._samples]
        majority = Counter(targets).most_common(1)[0][0] if targets else ""
        return {
            "always_abstain": [],
            "always_escalate": [Action(ANSWER_TOOL, {"answer": "I cannot determine the answer."})],
            "majority_class": [Action(ANSWER_TOOL, {"answer": majority})],
        }

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        """Best first. The weak policy answers with another sample's target --
        plausible, wrong, and generic enough to work on any suite."""
        return {
            "strong": self.gold_actions(task_id),
            "weak": [Action(ANSWER_TOOL, {"answer": str(self.invert_spec(task_id))})],
        }

    # -- splits ------------------------------------------------------------

    @staticmethod
    def _parts(sample) -> dict[str, str]:
        meta = sample.metadata or {}
        return {k: str(v) for k, v in meta.items() if isinstance(v, (str, int, float, bool))}

    def _items(self, samples, split: str) -> list[Item]:
        return [
            Item(
                item_id=f"{split}-{s.id or i}",
                text=str(s.input),
                label=self._target_text(s),
                parts=self._parts(s),
            )
            for i, s in enumerate(samples)
        ]

    def train_items(self) -> list[Item]:
        if not self._train:
            raise NotSupported("suite ships no separate train split to compare against")
        return self._items(self._train, "train")

    def eval_items(self) -> list[Item]:
        if not self._train:
            raise NotSupported("suite ships no separate train split to compare against")
        return self._items(self._samples, "eval")

    def verifier_source(self, task_id: str) -> str:
        """Every scorer's own source, concatenated, for family 11 to parse.

        Per-suite rather than per-task: an inspect_ai `Task` has one scorer list
        for the whole dataset, so every sample returns the same text and the
        probe deduplicates on it.

        Refuses the whole thing if any one scorer's source cannot be read.
        Handing back the readable half would let a verifier pass a static scan
        by having its dangerous part live somewhere `getsource` cannot reach,
        which is the one shape this check must not be able to miss.
        """
        sources = self._scorer_sources()
        if sources is None:
            raise NotSupported(
                "at least one scorer's source could not be read, so the verifier "
                "cannot be analysed in full; a partial scan would report a clean "
                "result over source nobody saw"
            )
        return "\n\n".join(sources)

    def _scorer_sources(self) -> list[str] | None:
        """Dedented source for each scorer, or None if any is unavailable.

        Each block is prefixed with the scorer's qualified name as a comment, so
        a finding's line number points somewhere a reader can find. Line numbers
        are within this text, not within the original file.
        """
        import inspect as pyinspect
        import textwrap

        if not self._scorers:
            return None
        out = []
        for fn in self._scorers:
            try:
                source = pyinspect.getsource(fn)
            except (OSError, TypeError):
                return None
            name = getattr(fn, "__qualname__", "scorer")
            out.append(f"# scorer: {name}\n{textwrap.dedent(source)}")
        return out

    def verifier_asserts(self, task_id: str) -> list[str]:
        """Only when the suite states them. A generic 'output matches target'
        shares no vocabulary with the question, so feeding it to the lexical
        spec-match check would manufacture findings rather than find them."""
        meta = self._sample(task_id).metadata or {}
        asserts = meta.get("assay_asserts") or meta.get("requirements")
        if not asserts:
            raise NotSupported(
                "scorer assertions are not machine-readable; inspect_ai scorers are "
                "opaque functions unless the suite declares requirements in metadata"
            )
        return [str(a) for a in asserts]
