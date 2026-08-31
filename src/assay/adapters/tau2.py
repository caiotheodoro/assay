"""Adapter for tau2-bench (sierra-research), retail and airline domains.

This is the first adapter in the repository pointed at an environment whose
defects were catalogued by somebody else. Every earlier number Assay reports
was measured against defects this repo planted, which is a closed loop: the
same author picked the defect and the probe that finds it. `tau2-bench-verified`
breaks the loop -- an independent team read all 164 tasks, judged 62 of them
wrong, and published the corrected task files.

The adapter drives the *real* tau2 environment and calls tau2's *own*
deterministic evaluators. It does not reimplement them. Two consequences worth
stating up front:

  - `scripts/tau2_fetch.py` must have run. The tau2 package is not on PyPI, and
    its own `pyproject.toml` requires Python 3.13 while this repo supports
    3.11+, so it is fetched as source into a gitignored cache rather than
    declared as a dependency.
  - tau2's third evaluator, `NLAssertionsEvaluator`, is an LLM judge. It is not
    used, and `verify` says so in its profile rather than quietly scoring
    without it. All 50 airline tasks and 8 retail tasks carry NL assertions
    that therefore go unchecked, which is reported as coverage, not as a pass.
"""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path
from typing import Any, Sequence

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
from ..tau2_truth import (
    BASE_REPO,
    BASE_REV,
    Tau2DataMissing,
    domain_data_dir,
    load_tasks,
    tau2_source_root,
    tasks_path,
)
from . import tau2_policy

DOMAINS = ("retail", "airline")

#: tau2 marks each tool READ or WRITE. A gold sequence routinely contains
#: *failing* reads on purpose -- the simulated user offers the wrong email and
#: the agent looks again -- so a read that errors is not evidence of anything.
#: A write that errors is: it means the graded answer cannot be executed.
_WRITE = "write"


def _ensure_source() -> Path:
    root = tau2_source_root() / "src"
    if not (root / "tau2").is_dir():
        raise Tau2DataMissing(
            f"{root / 'tau2'} is absent. tau2-bench is not redistributed here; fetch "
            "the pinned snapshot first:\n"
            "    uv run --extra tau2 python scripts/tau2_fetch.py"
        )
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


@functools.lru_cache(maxsize=None)
def _tau2_modules() -> dict[str, Any]:
    """Import tau2 once, and turn a missing dependency into a stated reason."""
    _ensure_source()
    try:
        from loguru import logger

        # tau2 logs the full JSON of every reservation it touches at DEBUG.
        # Disabled by name rather than by removing handlers, so a caller's own
        # logging is untouched and re-enabling it is one call away.
        logger.disable("tau2")

        from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage
        from tau2.data_model.tasks import Task as Tau2Task
        from tau2.domains.airline.environment import get_environment as airline_env
        from tau2.domains.retail.environment import get_environment as retail_env
        from tau2.evaluator.evaluator_action import ActionEvaluator
        from tau2.evaluator.evaluator_env import EnvironmentEvaluator
    except ImportError as exc:  # pragma: no cover - depends on the local env
        raise Tau2DataMissing(
            f"tau2 is present but not importable ({exc}). Install its runtime "
            "dependencies:\n    uv sync --extra tau2"
        ) from exc
    return {
        "AssistantMessage": AssistantMessage,
        "ToolCall": ToolCall,
        "ToolMessage": ToolMessage,
        "Task": Tau2Task,
        "environment": {"retail": retail_env, "airline": airline_env},
        "ActionEvaluator": ActionEvaluator,
        "EnvironmentEvaluator": EnvironmentEvaluator,
    }


@functools.lru_cache(maxsize=None)
def _db(domain: str) -> dict:
    return json.loads((domain_data_dir(domain) / "db.json").read_text())


@functools.lru_cache(maxsize=None)
def _write_tools(domain: str) -> frozenset[str]:
    """tau2's own READ/WRITE marking, read off a throwaway environment."""
    env = _tau2_modules()["environment"][domain]()
    return frozenset(
        name
        for name in env.tools.tools
        if env.tools.tool_type(name).value.lower() == _WRITE
    )


def _instruction(task: dict) -> str:
    """What a solver is told, concatenated in the order the user sees it."""
    instructions = (task.get("user_scenario") or {}).get("instructions") or {}
    parts = [
        instructions.get("reason_for_call"),
        instructions.get("known_info"),
        instructions.get("unknown_info"),
        instructions.get("task_instructions"),
        (task.get("description") or {}).get("purpose"),
    ]
    return " ".join(p for p in parts if p)


def _gold(task: dict) -> list[dict]:
    """The gold action sequence, minus the calls the simulated user makes.

    A user-requestor action is not something the agent under test is graded on
    performing, so replaying it as if it were the agent's would measure a
    different policy than the one tau2 scores.
    """
    criteria = task.get("evaluation_criteria") or {}
    return [a for a in criteria.get("actions") or [] if a.get("requestor") != "user"]


class Tau2Adapter(BaseAdapter):
    """One tau2 domain, at one of the two pinned task-set revisions.

    `task_set="base"` is the pre-fix task set -- the one the recall measurement
    probes. `task_set="verified"` is the corrected one, used only to check that
    a probe which fires on a defective task stops firing once the defect is
    fixed. Nothing in the audit path reads the verified set.
    """

    def __init__(
        self,
        domain: str = "retail",
        task_set: str = "base",
        task_ids: Sequence[str] | None = None,
    ) -> None:
        if domain not in DOMAINS:
            raise ValueError(f"unknown tau2 domain {domain!r}; expected one of {DOMAINS}")
        self.domain = domain
        self.task_set = task_set
        self._tasks = {t["id"]: t for t in load_tasks(domain, task_set)}
        if task_ids is not None:
            # Only for tests and for narrowing a rerun to one task. The recall
            # measurement always audits the whole set: a recall figure computed
            # over a subset someone chose is not a recall figure.
            missing = [t for t in task_ids if t not in self._tasks]
            if missing:
                raise KeyError(f"{domain}/{task_set}: no such tasks {missing}")
            self._tasks = {t: self._tasks[t] for t in task_ids}
        self._env = None
        self._task_id: str | None = None
        self._n_steps = 0

    # -- manifest ---------------------------------------------------------

    def manifest(self) -> Manifest:
        tasks = [
            Task(
                task_id=tid,
                instruction=_instruction(task),
                metadata={
                    "n_gold_actions": len(_gold(task)),
                    "n_nl_assertions": len(
                        (task.get("evaluation_criteria") or {}).get("nl_assertions") or []
                    ),
                    "n_communicate_info": len(
                        (task.get("evaluation_criteria") or {}).get("communicate_info")
                        or []
                    ),
                },
            )
            for tid, task in self._tasks.items()
        ]
        capabilities = {
            Capability.GOLD_TRAJECTORY,
            Capability.SEPARABLE_VERIFIER,
            Capability.LIVE_STEPPING,
            Capability.SEEDED_RESET,
            Capability.KNOWN_WRONG,
        }
        return Manifest(
            env_id=f"tau2/{self.domain}",
            ecosystem="tau2",
            tasks=tasks,
            capabilities=frozenset(capabilities),
            version=f"{BASE_REV[:10]}/{self.task_set}",
            source=f"https://github.com/{BASE_REPO}/tree/{BASE_REV}",
        )

    # -- episode ----------------------------------------------------------

    def reset(self, task_id: str, seed: int = 0) -> Observation:
        if task_id not in self._tasks:
            raise KeyError(f"{self.domain}: no task {task_id!r}")
        mods = _tau2_modules()
        self._env = mods["environment"][self.domain]()
        self._task_id = task_id
        self._n_steps = 0
        task = self._tasks[task_id]
        initial = task.get("initial_state") or {}
        for action in initial.get("initialization_actions") or []:
            self._env.use_tool(action["name"], **(action.get("arguments") or {}))
        return Observation(ok=True, data={"task_id": task_id, "domain": self.domain})

    def step(self, action: Action) -> StepResult:
        """One tool call, through tau2's own `get_response`.

        Not `use_tool`: `get_response` is what tau2 itself calls during a run,
        and it serialises the result exactly the way `Environment.set_state`
        later expects to see it replayed. Going around it produced transcripts
        that tau2's own environment evaluator then refused to accept.
        """
        if self._env is None:
            raise RuntimeError("reset() before step()")
        mods = _tau2_modules()
        call = mods["ToolCall"](
            id=f"c{self._n_steps}", name=action.tool, arguments=dict(action.args)
        )
        self._n_steps += 1
        message = self._env.get_response(call)
        return StepResult(
            observation=Observation(
                ok=not message.error,
                data=message.content,
                code="ToolError" if message.error else None,
                message=message.content if message.error else None,
            ),
            done=False,
        )

    # -- verifier ---------------------------------------------------------

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        """tau2's own action and DB evaluators, plus executability.

        Three conjuncts, and the profile names each one so a failure says which:

          executable   no WRITE action in the transcript was refused
          action       tau2's ActionEvaluator finds every gold action
          db           tau2's EnvironmentEvaluator finds a matching end state

        `spec` is unused: tau2 tasks carry no `env_assertions` (checked -- all
        164 have none), so there is no success spec to substitute and the
        inverted-spec probe correctly reports NOT_APPLICABLE instead.
        """
        mods = _tau2_modules()
        task = self._tasks[transcript.task_id]
        tau2_task = mods["Task"].model_validate(task)
        trajectory = self._trajectory(transcript, mods)

        writes = _write_tools(self.domain)
        refused, read_refused = [], []
        for action, observation in zip(transcript.actions, transcript.observations):
            if observation.ok:
                continue
            record = {"tool": action.tool, "error": observation.message}
            (refused if action.tool in writes else read_refused).append(record)

        action_reward = mods["ActionEvaluator"].calculate_reward(
            task=tau2_task, full_trajectory=trajectory
        ).reward
        env_reward = mods["EnvironmentEvaluator"].calculate_reward(
            environment_constructor=mods["environment"][self.domain],
            task=tau2_task,
            full_trajectory=trajectory,
        ).reward

        executable = 0.0 if refused else 1.0
        reward = min(executable, action_reward, env_reward)
        return Score(
            passed=reward >= 1.0,
            reward=reward,
            profile={
                "executable": executable,
                "action_reward": action_reward,
                "db_reward": env_reward,
                "refused_writes": refused,
                "refused_reads": read_refused,
                "nl_assertions_checked": False,
                "nl_assertions_note": (
                    "tau2 scores nl_assertions with an LLM judge. Assay scores nothing "
                    "with a judge, so this conjunct is absent, not passed."
                ),
            },
        )

    def _trajectory(self, transcript: Transcript, mods: dict) -> list[Any]:
        """Rebuild the message history tau2's evaluators expect.

        One assistant message per tool call, each immediately followed by the
        tool message it produced -- `Environment.set_state` replays the calls
        and compares each response against the recorded one, so the recorded
        observation has to be the real serialised response and not a summary
        of it.
        """
        out: list[Any] = []
        for i, (action, observation) in enumerate(
            zip(transcript.actions, transcript.observations)
        ):
            call = mods["ToolCall"](
                id=f"c{i}", name=action.tool, arguments=dict(action.args)
            )
            out.append(mods["AssistantMessage"](role="assistant", tool_calls=[call]))
            out.append(
                mods["ToolMessage"](
                    id=call.id,
                    role="tool",
                    content=observation.data,
                    error=not observation.ok,
                )
            )
        return out

    # -- capabilities -----------------------------------------------------

    def gold_actions(self, task_id: str) -> list[Action]:
        return [
            Action(tool=a["name"], args=dict(a.get("arguments") or {}))
            for a in _gold(self._tasks[task_id])
        ]

    def policy_violations(self, task_id: str) -> list[tau2_policy.Violation]:
        """Which sentences of `policy.md` the task's own gold answer breaks."""
        task = self._tasks[task_id]
        return tau2_policy.violations(
            self.domain, task, _gold(task), _db(self.domain)
        )

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        """The gold sequence, but only where the policy oracle says it is wrong.

        This is the mapping the tau2 defect taxonomy invites: a task whose
        *expected* actions violate the domain policy is a known-wrong policy
        that the verifier is guaranteed to accept, because it is the answer key.

        **The guard this docstring used to claim is false, and the correction
        belongs here rather than in a changelog.** It said: returning `[]` for a
        task with no violation leaves the probe to score an empty transcript,
        "which fails on every task that has a gold action -- so a clean task
        cannot produce a finding here by accident". The premise is right and the
        conclusion does not follow, because 9 of the 164 tasks have **no** gold
        action once `_gold()` drops the user-requestor entries: retail/{24,57}
        and airline/{0,10,26,28,31,34,46}. On those, `verify` scores an empty
        transcript at 1.0 -- `reward = min(executable, action_reward,
        db_reward)` over an empty requirement -- and `known_wrong_fails` reports
        `KNOWN_WRONG_PASSES` on a task with no policy violation at all. Measured:
        that accounts for **2 of retail's 6 and 6 of airline's 13**
        `known_wrong_fails` findings in `results/tau2_recall.json`, and it is the
        whole of that probe's false-positive column on both domains.

        Left in place rather than patched, deliberately. The fix is a probe
        contract change -- the family has to be able to say "this task has no
        known-wrong policy to try" and be skipped, rather than being handed an
        empty list that means something else -- and doing it here would move a
        published recall measurement inside a change whose subject is the corpus
        label. It is written down instead, and
        `tau2_truth.EXCLUDED_DEFECT_CLASSES[NOOP_PASSES]` is the same nine tasks
        seen from the other side.
        """
        if not self.policy_violations(task_id):
            return []
        return self.gold_actions(task_id)

    def verifier_asserts(self, task_id: str) -> list[str]:
        """The scorer's own natural-language claims.

        Gold actions are deliberately excluded. Their arguments are opaque
        identifiers -- `#W2378156`, `8069050545` -- that no task instruction
        ever contains, so feeding them to a lexical traceability test would
        mark all 164 tasks as mismatched and mean nothing. What is left is
        `nl_assertions` and `communicate_info`: claims written in the same
        register as the instruction, where a word that appears in one and not
        the other is a real signal.

        Returning `[]` rather than refusing, for a task that has neither, is
        deliberate: `NotSupported` is raised to the probe harness and would
        turn the whole family NOT_APPLICABLE over the first such task, taking
        the 46 retail tasks that *do* state claims down with it. The empty case
        stays visible in the probe's `per_task` detail as `n_asserts: 0`.
        """
        criteria = self._tasks[task_id].get("evaluation_criteria") or {}
        claims = list(criteria.get("nl_assertions") or [])
        claims += [str(c) for c in criteria.get("communicate_info") or []]
        return claims

    # -- refusals, each with a reason ------------------------------------

    def invert_spec(self, task_id: str) -> Any:
        raise NotSupported(
            "tau2 tasks carry no env_assertions -- all 164 in retail and airline have "
            "none -- so the success spec is a gold action list and a DB hash. Neither "
            "has a meaningful negation to substitute."
        )

    def train_items(self) -> list[Item]:
        raise NotSupported("tau2 ships a single evaluation split; there is no train set")

    def eval_items(self) -> list[Item]:
        raise NotSupported(
            "tau2 tasks are interactive episodes, not labelled items; there is nothing "
            "for a partial-input baseline to hold out"
        )

    def true_completion(self, transcript: Transcript) -> float:
        raise NotSupported(
            "tau2 exposes no ground-truth completion signal independent of its own "
            "scorer, so the exploit gap cannot be measured without an LLM judge"
        )

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        raise NotSupported(
            "a degenerate tau2 policy is a conversational refusal, which only the "
            "LLM-judged nl_assertions can score"
        )

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        raise NotSupported(
            "tau2 ships no quality-graded reference policies, and constructing them "
            "would mean inventing the grades this probe is supposed to check"
        )

    def close(self) -> None:
        self._env = None


def available() -> bool:
    """Whether the pinned snapshot has been fetched."""
    return tasks_path("retail", "base").exists() and (
        tau2_source_root() / "src" / "tau2"
    ).is_dir()
