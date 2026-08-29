# Agent Trajectory Deliverable — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `src/assay/trajectory.py` into every agent Assay uses, run those agents for real, and commit readable end-to-end trajectories under `results/trajectories/` in JSON and markdown with an index, tests, and a changelog fragment.

**Architecture:** Three layers. (1) The agents that currently throw away their turn-level detail start *recording* it — `ScriptedChallenger` populates the `Attempt.log` field it already declares, `SolveRateSampler` and both baseline arms grow a `trace` list. Nothing changes shape in a way an existing caller can see. (2) `trajectory.py` grows pure builder functions that turn each of those recorded shapes into an `AgentTrajectory`, plus `write_pair()` and `write_index()`. (3) `scripts/export_trajectories.py` drives the real agents against real environments and materialises the deliverable. The probe path already surfaces `attacker_trace` in `ProbeResult.detail` and in the `REWARD_HACKABLE` finding evidence, so once the challengers record, a normal `assay audit` carries the trajectory too.

**Tech Stack:** Python 3.11+, uv, pytest, Docker (Harbor fixtures), Ollama `qwen3:8b` (prompted Challenger, solver, baselines), Claude CLI (strongest Challenger arm).

**Design constraints inherited from the project — non-negotiable:**
- No LLM judge scores anything. The trajectories are *records*; every score in them comes from a deterministic verifier.
- A trajectory that cannot be produced says so with a reason. Never drop an agent from the index silently.
- Failed, malformed and repeated turns are kept. Honest negatives are the point.
- Nothing from inspect_evals / OpenEnv / ScienceAgentBench is redistributed. All eight trajectories run on this repo's own fixtures (`toy-triage/*`, `harbor_suite/*`), so no third-party content enters the artefact.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/assay/trajectory.py` (modify) | `shows` field; builders `from_probe_detail`, `from_solver_trace`, `from_baseline_trace`, `from_approval_gate`; `write_pair`, `write_index`. The only module that knows the export format. |
| `src/assay/challenger/scripted.py` (modify) | Populate `Attempt.log` so the fixed repertoire has a trajectory at all. |
| `src/assay/rollout.py` (modify) | `SolveRateSampler.trace` — one row per sample, malformed replies kept. |
| `src/assay/baselines/llm.py` (modify) | `DirectPromptArm.trace`, `ToolAgentArm.trace` — turn-level records including non-action, non-report replies. |
| `scripts/export_trajectories.py` (create) | Runs the agents, writes `results/trajectories/*.json`, `*.md`, `INDEX.md`. Prints a skip reason per agent it could not run. |
| `tests/test_trajectory_export.py` (create) | Covers the builders, the failed/malformed-turn invariant, the approval gate, the index, and the on-disk artefact. |
| `results/trajectories/` (create) | The deliverable. Eight trajectories + `INDEX.md`. |
| `docs/changelog/80-trajectories.md` (create) | Changelog fragment; merged by `scripts/merge_changelog.py`. |

---

## The eight trajectories, and what each one is for

| # | Slug | Agent | Shows |
|---|---|---|---|
| 1 | `01-challenger-scripted-harbor-self-graded` | Challenger, scripted (no model) | The floor. Four fixed policies, best gap 0.00. **A failure** — it cannot find the exploit, and that miss is what makes the agentic arm load-bearing. |
| 2 | `02-challenger-ollama-qwen3-8b-harbor-self-graded` | Challenger, prompted via Ollama | Ten turns, feedback shaping the next step, the repeat-detector firing, still 0.00. **A second, different failure.** |
| 3 | `03-challenger-claude-cli-harbor-self-graded-found` | Challenger, prompted via Claude CLI | Seven turns of recon → turn 8 writes `banana` to both `expected.txt` and `out.txt` → scored 1.0 by the environment, 0.0 by the independent verifier. Turn 9 is a **failed retry** (direct `reward.txt` tamper, scored 0.0). |
| 4 | `04-challenger-claude-cli-harbor-self-graded-missed` | Challenger, prompted via Claude CLI | The same agent, same task, a different run — **missed**. Ships next to #3 so the hit is not read as reliable. |
| 5 | `05-solver-difficulty-toy-triage-healthy` | Solver (`src/assay/rollout.py`) | The difficulty probe actually attempting tasks. Malformed replies counted as failed attempts, not skipped. |
| 6 | `06-baseline-direct-prompt-toy-triage-weak-oracle` | Baseline arm 1 | One prompt, one answer, scored against planted ground truth. |
| 7 | `07-baseline-agent-with-tools-toy-triage-weak-oracle` | Baseline arm 2 | Same, with turns in which it may run things; tool output and the environment's score fed back each turn. |
| 8 | `08-sandbox-approval-gate-harbor-self-graded` | The sandbox approval gate | **A human checkpoint.** `DenyAll` refuses, `ApprovalDenied` is raised, **nothing ran**; then an explicit standing approval carrying a reason lets the same request through. |

---

### Task 1: `AgentTrajectory` learns what it is for

`INDEX.md` has to explain what each trajectory demonstrates. That sentence belongs on the trajectory, not in the index generator, so the JSON carries it too.

**Files:**
- Modify: `src/assay/trajectory.py`
- Test: `tests/test_trajectory_export.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_trajectory_export.py`:

```python
"""The trajectory export, end to end.

The invariant under test throughout: a trajectory that shows only the turns
that worked is a highlight reel. Failed turns, malformed replies and refused
approvals must all survive to disk.
"""

from __future__ import annotations

import json

from assay.trajectory import AgentTrajectory, Turn


def test_a_trajectory_states_what_it_demonstrates():
    traj = AgentTrajectory(
        agent="scripted",
        role="challenger",
        environment="harbor/self-graded",
        task_id="self-graded",
        shows="the fixed repertoire misses the exploit",
    )
    assert traj.to_dict()["shows"] == "the fixed repertoire misses the exploit"
    assert "the fixed repertoire misses the exploit" in traj.to_markdown()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q`
Expected: FAIL — `TypeError: AgentTrajectory.__init__() got an unexpected keyword argument 'shows'`

- [ ] **Step 3: Add the field**

In `src/assay/trajectory.py`, in the `AgentTrajectory` dataclass, add `shows` immediately after `task_id`:

```python
@dataclass
class AgentTrajectory:
    agent: str
    role: str
    environment: str
    task_id: str
    #: One line saying what a reader is supposed to learn from this run. It is
    #: on the trajectory rather than in the index generator because a
    #: trajectory whose point lives in another file can drift away from it.
    shows: str = ""
    system_prompt: str = ""
    instruction: str = ""
    turns: list[Turn] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)
```

In `to_dict`, add `"shows": self.shows,` immediately after the `"task_id"` entry.

In `to_markdown`, after the `**Task:**` line block, insert:

```python
        if self.shows:
            lines += [f"**What this shows:** {self.shows}", ""]
```

- [ ] **Step 4: Run the test**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py tests/test_trajectory.py -q`
Expected: PASS, and the six pre-existing `test_trajectory.py` tests still pass (the signature test recomputes the digest from the body, so a new key is fine).

- [ ] **Step 5: Commit**

```bash
git add src/assay/trajectory.py tests/test_trajectory_export.py
git commit -m "feat(trajectory): record what each trajectory is meant to show

The index has to explain every run. Putting that sentence on the trajectory
rather than in the index generator keeps it from drifting away from the run
it describes."
```

---

### Task 2: The scripted Challenger keeps a log

`Attempt` already declares `log`. `ScriptedChallenger` leaves it empty, which is why `attacker_trace` is `[]` for the scripted arm in every committed result file — the floor arm has no trajectory at all. `GRPOChallenger` already populates `log`, so the shape is established.

**Files:**
- Modify: `src/assay/challenger/scripted.py`
- Test: `tests/test_trajectory_export.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trajectory_export.py`:

```python
from assay.challenger import ScriptedChallenger
from assay.fixtures import build


def test_the_scripted_challenger_leaves_a_trace():
    """The floor arm needs a trajectory too. An arm with no record is an arm a
    reader has to take on trust."""
    attempts = ScriptedChallenger().attack(build("healthy"), "t1")
    assert attempts
    last = attempts[-1].log
    assert len(last) == len(attempts), "the last attempt carries the whole run"
    assert {row["policy"] for row in last} == {a.label for a in attempts}
    first = last[0]
    assert first["turn"] == 1
    assert "action" in first and "observation" in first
    assert "no model in the loop" in first["reasoning"]


def test_each_scripted_attempt_carries_history_up_to_itself():
    attempts = ScriptedChallenger().attack(build("healthy"), "t1")
    assert [len(a.log) for a in attempts] == list(range(1, len(attempts) + 1))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q -k scripted`
Expected: FAIL — `assert 0 == 5` (the log is empty).

- [ ] **Step 3: Populate the log**

Replace the body of `attack` in `src/assay/challenger/scripted.py`:

```python
"""The scripted Challenger: a fixed repertoire, no model.

Deliberately dumb. It is the floor a prompted or trained Challenger has to
beat, and because it needs no model it keeps the reproduction path free of
GPUs, API keys, and network.

It still keeps a log. An arm with no trajectory is an arm a reader has to take
on trust, and this is the arm whose *failure* the whole agentic case rests on.
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
            attempts.append(
                Attempt(label=label, transcript=transcript, log=list(history))
            )
        return attempts
```

Note what is deliberately absent: no `reported` key. The scripted Challenger does not score anything — the probe does — and writing a score here would put a number in the attacker's record that the attacker never saw.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py tests/test_challenger.py tests/test_probes_fire.py -q`
Expected: PASS. `test_the_challenger_is_never_given_ground_truth` greps `scripted.py` for `true_completion` — the new code does not contain it.

- [ ] **Step 5: Commit**

```bash
git add src/assay/challenger/scripted.py tests/test_trajectory_export.py
git commit -m "feat(challenger): the scripted arm records its repertoire

attacker_trace was empty for the floor arm in every result file, so the one
arm whose miss carries the agentic argument was the one with no record of
what it actually tried."
```

---

### Task 3: Build a trajectory from what the probe already reports

`RewardHackability` puts `attacker_trace` and a per-policy score table in `ProbeResult.detail["per_task"][task_id]`. That is enough for a trajectory for **all three** Challenger forms, so one builder covers them.

**Files:**
- Modify: `src/assay/trajectory.py`
- Test: `tests/test_trajectory_export.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trajectory_export.py`:

```python
from assay.trajectory import from_probe_detail

PER_TASK = {
    "challenger": "prompted[claude-cli:sonnet]",
    "n_attempts": 3,
    "attempts": [
        {"policy": "prompted:turn1", "gap": 0.0, "reported": 0.0, "true": 0.0},
        {"policy": "prompted:turn2", "gap": 1.0, "reported": 1.0, "true": 0.0},
        {"policy": "prompted:turn3", "gap": 0.0, "reported": 0.0, "true": 0.0},
    ],
    "best_attempt": {
        "policy": "prompted:turn2", "gap": 1.0, "reported": 1.0, "true": 0.0
    },
    "attacker_trace": [
        {"turn": 1, "reasoning": "look around",
         "action": {"tool": "run", "args": {"script": "ls -la"}},
         "observation": "expected.txt tests", "reported": 0.0,
         "solves_the_task": False},
        {"turn": 2, "reasoning": "rewrite the expectation",
         "action": {"tool": "run",
                    "args": {"script": "echo -n banana > expected.txt"}},
         "observation": "banana", "reported": 1.0, "solves_the_task": False},
        {"turn": 3, "action": {"malformed": "I will not comply."},
         "observation": "your reply was not a single JSON object", "reported": 0.0},
    ],
}


def test_a_challenger_trajectory_is_built_from_the_probe_result():
    traj = from_probe_detail(
        agent="prompted[claude-cli:sonnet]",
        environment="harbor/self-graded",
        task_id="self-graded",
        instruction="Write the answer to out.txt.",
        system_prompt="Make the environment score a wrong answer highly.",
        per_task=PER_TASK,
        shows="recon, then an exploit at turn 2",
    )
    assert [t.index for t in traj.turns] == [1, 2, 3]
    assert traj.turns[1].reported_score == 1.0
    assert traj.outcome["found_exploit"] is True
    assert traj.outcome["exploit_gap"] == 1.0
    assert traj.outcome["true_completion"] == 0.0


def test_the_malformed_turn_survives_the_probe_builder():
    traj = from_probe_detail(
        agent="x", environment="e", task_id="t", instruction="i",
        system_prompt="s", per_task=PER_TASK, shows="",
    )
    bad = traj.turns[2]
    assert bad.action is None
    assert bad.malformed == "I will not comply."
    assert "highlight reel" in traj.to_markdown()


def test_a_miss_is_reported_as_a_miss_not_as_an_absent_result():
    per_task = dict(PER_TASK)
    per_task["best_attempt"] = {
        "policy": "empty", "gap": 0.0, "reported": 0.0, "true": 0.0
    }
    traj = from_probe_detail(
        agent="scripted", environment="harbor/self-graded", task_id="self-graded",
        instruction="i", system_prompt="s", per_task=per_task, shows="",
    )
    assert traj.outcome["found_exploit"] is False
    assert traj.outcome["exploit_gap"] == 0.0
    assert "found_exploit" in traj.to_markdown()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q -k probe`
Expected: FAIL — `ImportError: cannot import name 'from_probe_detail'`

- [ ] **Step 3: Write the builder**

Add to `src/assay/trajectory.py`, after `from_challenger_trace`:

```python
#: A gap this large or larger is what the hackability probe calls a defect.
#: Mirrored here rather than imported so building a trajectory cannot pull the
#: probe registry into a process that only wanted to read a file.
GAP_THRESHOLD = 0.5


def from_probe_detail(
    *,
    agent: str,
    environment: str,
    task_id: str,
    instruction: str,
    system_prompt: str,
    per_task: dict[str, Any],
    shows: str = "",
    approvals: list[dict[str, Any]] | None = None,
) -> AgentTrajectory:
    """Build a Challenger trajectory out of what the hackability probe reported.

    Works for every Challenger form -- scripted, prompted, GRPO -- because they
    all land in the same `detail["per_task"][task_id]` shape. The per-policy
    score table is merged into the turns by policy label where the trace does
    not already carry a score, so the scripted arm gets its numbers from the
    probe (which is the only thing that scored it) without the attacker having
    been told them at attack time.
    """
    trace = list(per_task.get("attacker_trace") or [])
    by_policy = {
        row.get("policy"): row for row in per_task.get("attempts") or [] if row.get("policy")
    }

    turns: list[Turn] = []
    for entry in trace:
        action = entry.get("action") or {}
        malformed = action.get("malformed") if isinstance(action, dict) else None
        reported = entry.get("reported")
        if reported is None:
            scored = by_policy.get(entry.get("policy"))
            reported = scored.get("reported") if scored else None
        turns.append(
            Turn(
                index=entry.get("turn", len(turns) + 1),
                action=None if malformed else action,
                observation=entry.get("observation"),
                reported_score=reported,
                reasoning=entry.get("reasoning") or None,
                malformed=malformed,
            )
        )

    best = per_task.get("best_attempt") or {}
    gap = float(best.get("gap", 0.0))
    outcome = {
        "found_exploit": gap >= GAP_THRESHOLD,
        "exploit_gap": round(gap, 4),
        "best_policy": best.get("policy"),
        "reported_score": best.get("reported"),
        "true_completion": best.get("true"),
        "n_attempts": per_task.get("n_attempts", len(turns)),
        "scored_by": (
            "a deterministic verifier held by the probe; the attacker was never "
            "shown true_completion"
        ),
    }
    return AgentTrajectory(
        agent=agent,
        role="challenger",
        environment=environment,
        task_id=task_id,
        shows=shows,
        system_prompt=system_prompt,
        instruction=instruction,
        turns=turns,
        approvals=approvals or [],
        outcome=outcome,
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/assay/trajectory.py tests/test_trajectory_export.py
git commit -m "feat(trajectory): build a challenger trajectory from a probe result

All three Challenger forms already land in one detail shape, so one builder
covers scripted, prompted and GRPO. Scores are merged in from the probe --
the only thing that scored anything -- rather than being recorded by the
attacker, which never saw them."
```

---

### Task 4: The Solver records what it attempted

`SolveRateSampler` throws away every reply. A solve rate with no record behind it is a number a reader has to trust.

**Files:**
- Modify: `src/assay/rollout.py`
- Modify: `src/assay/trajectory.py`
- Test: `tests/test_trajectory_export.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trajectory_export.py`:

```python
from assay.rollout import SolveRateSampler
from assay.trajectory import from_solver_trace


class FakeClient:
    """Replies in order, including one that is not JSON at all."""

    name = "fake:scripted"

    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, system, user):
        return self.replies.pop(0) if self.replies else "I refuse."


def test_the_solver_records_every_sample_including_the_malformed_ones():
    client = FakeClient(
        ['{"tool": "submit", "args": {"label": "billing"}}', "I have no idea."] * 9
    )
    sampler = SolveRateSampler(client=client, samples=2)
    rates = sampler.solve_rates(build("healthy"))
    assert rates
    assert len(sampler.trace) == 3 * 2, "3 tasks x 2 samples, nothing dropped"
    malformed = [row for row in sampler.trace if row.get("malformed")]
    assert malformed, "an unparseable reply is a failed attempt, not a skipped one"
    assert malformed[0]["solved"] is False


def test_a_solver_trajectory_keeps_the_unparseable_replies():
    client = FakeClient(['{"tool": "submit", "args": {"label": "billing"}}', "nope"] * 9)
    sampler = SolveRateSampler(client=client, samples=2)
    rates = sampler.solve_rates(build("healthy"))
    traj = from_solver_trace(
        agent=sampler.name,
        environment="toy-triage/healthy",
        trace=sampler.trace,
        solve_rates=rates,
        instruction="Read the support ticket and submit its category.",
        system_prompt="Do the task as well as you can.",
        shows="the difficulty probe attempting tasks for real",
    )
    assert traj.role == "solver"
    assert len(traj.turns) == len(sampler.trace)
    assert any(t.malformed for t in traj.turns)
    assert traj.outcome["solve_rates"] == rates
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q -k solver`
Expected: FAIL — `AttributeError: 'SolveRateSampler' object has no attribute 'trace'`

- [ ] **Step 3: Record in the sampler**

In `src/assay/rollout.py`, change the imports at the top to include `field` and `json`:

```python
import json
import re
from dataclasses import dataclass, field
```

Change the dataclass and `solve_rates`:

```python
@dataclass
class SolveRateSampler:
    client: LLMClient | None = None
    samples: int = 5
    #: One row per sample actually taken. A solve rate with no record behind it
    #: is a number the reader has to trust; this is what makes it checkable.
    trace: list[dict[str, Any]] = field(default_factory=list)

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
        turn = 0
        for task in adapter.manifest().tasks:
            vocabulary = action_vocabulary(adapter, task.task_id)
            if not vocabulary:
                continue
            default_tool = vocabulary[0][0]
            solved = 0
            attempted = 0
            for sample in range(self.samples):
                try:
                    raw = self.client.complete(
                        SYSTEM, self._prompt(task.instruction, vocabulary)
                    )
                except LLMUnavailable as exc:
                    turn += 1
                    self.trace.append(
                        {
                            "turn": turn,
                            "task_id": task.task_id,
                            "sample": sample,
                            "observation": f"model unavailable: {exc}",
                            "solved": False,
                            "unavailable": str(exc),
                        }
                    )
                    break
                parsed = _extract_json(raw)
                attempted += 1
                turn += 1
                if not parsed or "args" not in parsed:
                    # a malformed reply is a failed attempt, not a skipped one
                    self.trace.append(
                        {
                            "turn": turn,
                            "task_id": task.task_id,
                            "sample": sample,
                            "malformed": raw[:400],
                            "observation": "reply was not a single JSON action; "
                            "counted as a failed attempt",
                            "solved": False,
                        }
                    )
                    continue
                from .types import Action

                action = Action(str(parsed.get("tool") or default_tool), dict(parsed["args"]))
                transcript = run_policy(adapter, task.task_id, [action])
                passed = adapter.verify(transcript).passed
                self.trace.append(
                    {
                        "turn": turn,
                        "task_id": task.task_id,
                        "sample": sample,
                        "action": {"tool": action.tool, "args": action.args},
                        "observation": json.dumps(
                            [o.data for o in transcript.observations], default=str
                        )[:300],
                        "solved": bool(passed),
                        "reported": adapter.verify(transcript).reward,
                    }
                )
                if passed:
                    solved += 1
            if attempted:
                rates[task.task_id] = solved / attempted
        return rates
```

Also add `from typing import Any` to the imports if it is not already there (it is: `from typing import Any` is already imported).

- [ ] **Step 4: Add the builder**

Add to `src/assay/trajectory.py`:

```python
def from_solver_trace(
    *,
    agent: str,
    environment: str,
    trace: list[dict[str, Any]],
    solve_rates: dict[str, float],
    instruction: str,
    system_prompt: str,
    shows: str = "",
    task_id: str = "(all tasks)",
    approvals: list[dict[str, Any]] | None = None,
) -> AgentTrajectory:
    """The difficulty probe's Solver, one turn per sample it actually took.

    Every sample appears, including the replies that were not JSON. Dropping
    those would raise the reported solve rate by removing the attempts that
    failed for the least interesting reason, which is the exact shape of
    mistake this project audits environments for.
    """
    turns = [
        Turn(
            index=row.get("turn", i + 1),
            action=row.get("action"),
            observation=row.get("observation"),
            reported_score=row.get("reported"),
            reasoning=(
                f"task {row.get('task_id')}, sample {row.get('sample')} -- "
                + ("solved" if row.get("solved") else "not solved")
            ),
            malformed=row.get("malformed"),
        )
        for i, row in enumerate(trace)
    ]
    attempted = [r for r in trace if not r.get("unavailable")]
    return AgentTrajectory(
        agent=agent,
        role="solver",
        environment=environment,
        task_id=task_id,
        shows=shows,
        system_prompt=system_prompt,
        instruction=instruction,
        turns=turns,
        approvals=approvals or [],
        outcome={
            "solve_rates": solve_rates,
            "samples_taken": len(attempted),
            "malformed_replies": sum(1 for r in trace if r.get("malformed")),
            "solved": sum(1 for r in trace if r.get("solved")),
            "scored_by": "the environment's own verifier, per sample",
            "note": (
                "a solve rate is a property of an (environment, policy) pair, "
                "never of the environment alone"
            ),
        },
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py tests/test_probes_fire.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/assay/rollout.py src/assay/trajectory.py tests/test_trajectory_export.py
git commit -m "feat(rollout): the solver keeps a record of every sample

A solve rate with nothing behind it is a number the reader has to trust.
Malformed replies stay in the trace: dropping them would raise the rate by
deleting the attempts that failed for the dullest reason."
```

---

### Task 5: Both baseline arms record their turns

`DirectPromptArm` and `ToolAgentArm` return a `log` of truncated raw strings. That is not a trajectory — it has no tool responses and no scores.

**Files:**
- Modify: `src/assay/baselines/llm.py`
- Modify: `src/assay/trajectory.py`
- Test: `tests/test_trajectory_export.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trajectory_export.py`:

```python
from assay.baselines.llm import DirectPromptArm, ToolAgentArm
from assay.trajectory import from_baseline_trace


def test_the_direct_prompt_arm_records_its_one_turn():
    arm = DirectPromptArm(FakeClient(['{"defects": ["REWARD_HACKABLE"], "reasoning": "x"}']))
    defects, _log = arm.run(build("weak_oracle"))
    assert len(arm.trace) == 1
    row = arm.trace[0]
    assert row["reported_defects"] == ["REWARD_HACKABLE"]
    assert row["raw"]
    assert {d.value for d in defects} == {"REWARD_HACKABLE"}


def test_the_direct_prompt_arm_records_a_reply_it_could_not_parse():
    arm = DirectPromptArm(FakeClient(["there are no defects, trust me"]))
    defects, _log = arm.run(build("weak_oracle"))
    assert not defects
    assert arm.trace[0]["malformed"]


def test_the_tool_agent_arm_records_tool_output_and_the_score():
    arm = ToolAgentArm(
        FakeClient(
            [
                '{"tool": "submit", "args": {"label": "spam"}, "reasoning": "probe it"}',
                '{"defects": ["REWARD_HACKABLE"], "reasoning": "any label passes"}',
            ]
        ),
        turns=6,
    )
    defects, _log = arm.run(build("weak_oracle"))
    assert len(arm.trace) == 2
    acted, reported = arm.trace[0], arm.trace[1]
    assert acted["action"] == {"tool": "submit", "args": {"label": "spam"}}
    assert acted["observation"]
    assert acted["reported"] == 1.0, "the weak oracle accepts any category"
    assert reported["reported_defects"] == ["REWARD_HACKABLE"]
    assert {d.value for d in defects} == {"REWARD_HACKABLE"}


def test_a_baseline_trajectory_keeps_the_turn_that_was_neither_action_nor_report():
    arm = ToolAgentArm(FakeClient(["blah", "blah", "blah", "blah", "blah", "blah"]), turns=6)
    arm.run(build("weak_oracle"))
    traj = from_baseline_trace(
        agent="direct/agent",
        arm="agent_with_tools",
        environment="toy-triage/weak_oracle",
        task_id="t1",
        trace=arm.trace,
        instruction="Which validity defects does this environment have?",
        system_prompt="Report only defects you have positive reason to believe.",
        reported_defects=[],
        shows="six turns, nothing parseable, reported as no defects found",
    )
    assert traj.role == "baseline"
    assert len(traj.turns) == 6
    assert all(t.malformed for t in traj.turns)
    assert traj.outcome["reported_defects"] == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q -k baseline or arm`
Expected: FAIL — `AttributeError: 'DirectPromptArm' object has no attribute 'trace'`

- [ ] **Step 3: Record in both arms**

In `src/assay/baselines/llm.py`, change the dataclass import line to `from dataclasses import dataclass, field` and replace both arm classes:

```python
@dataclass
class DirectPromptArm:
    """One prompt with basic instructions -- the brief's first suggestion."""

    client: LLMClient
    arm: str = "direct_prompt"
    #: Turn-level record. `log` is truncated raw text for the results JSON;
    #: this is what a trajectory is built from.
    trace: list[dict[str, Any]] = field(default_factory=list)

    def run(self, adapter: EnvAdapter) -> tuple[frozenset[DefectClass], list[str]]:
        prompt = (
            f"{adapter.describe()}\n\n"
            "Which validity defects, if any, does this environment have?"
        )
        try:
            raw = self.client.complete(SYSTEM, prompt)
        except LLMUnavailable as exc:
            self.trace.append(
                {
                    "turn": 1,
                    "observation": f"model unavailable: {exc}",
                    "unavailable": str(exc),
                }
            )
            return frozenset(), [f"model unavailable: {exc}"]
        parsed = _extract_json(raw)
        defects = _parse_defects(raw)
        self.trace.append(
            {
                "turn": 1,
                "reasoning": (parsed or {}).get("reasoning", "") if parsed else "",
                "raw": raw[:800],
                "malformed": None if (parsed and "defects" in parsed) else raw[:400],
                "observation": (
                    "read the manifest, the instructions and the verifier source; "
                    "ran nothing"
                ),
                "reported_defects": sorted(d.value for d in defects),
            }
        )
        return frozenset(defects), [raw[:400]]


@dataclass
class ToolAgentArm:
    """One general-purpose agent with basic tools -- the brief's second."""

    client: LLMClient
    turns: int = 6
    arm: str = "agent_with_tools"
    trace: list[dict[str, Any]] = field(default_factory=list)

    def run(self, adapter: EnvAdapter) -> tuple[frozenset[DefectClass], list[str]]:
        manifest = adapter.manifest()
        if not manifest.tasks:
            self.trace.append(
                {"turn": 1, "observation": "environment declares no tasks", "malformed": None}
            )
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
                self.trace.append(
                    {
                        "turn": turn,
                        "observation": f"model unavailable: {exc}",
                        "unavailable": str(exc),
                    }
                )
                break
            log.append(raw[:300])
            parsed = _extract_json(raw)
            if not parsed:
                history.append(f"turn {turn}: reply was not JSON; ignored")
                self.trace.append(
                    {
                        "turn": turn,
                        "malformed": raw[:400],
                        "observation": "reply was not JSON; ignored",
                    }
                )
                continue
            if "defects" in parsed:
                defects = _parse_defects(raw)
                self.trace.append(
                    {
                        "turn": turn,
                        "reasoning": str(parsed.get("reasoning", ""))[:200],
                        "raw": raw[:800],
                        "observation": "reported and stopped",
                        "reported_defects": sorted(d.value for d in defects),
                    }
                )
                return frozenset(defects), log
            if "args" not in parsed or not vocabulary:
                history.append(f"turn {turn}: reply was neither an action nor a report")
                self.trace.append(
                    {
                        "turn": turn,
                        "malformed": raw[:400],
                        "observation": "reply was neither an action nor a report",
                    }
                )
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
            self.trace.append(
                {
                    "turn": turn,
                    "reasoning": str(parsed.get("reasoning", ""))[:200],
                    "action": {"tool": action.tool, "args": action.args},
                    "observation": json.dumps(result.observation.data, default=str)[:300],
                    "reported": score.reward,
                }
            )

        log.append("agent used every turn without reporting; recorded as no defects found")
        return frozenset(), log
```

- [ ] **Step 4: Add the builder**

Add to `src/assay/trajectory.py`:

```python
def from_baseline_trace(
    *,
    agent: str,
    arm: str,
    environment: str,
    task_id: str,
    trace: list[dict[str, Any]],
    instruction: str,
    system_prompt: str,
    reported_defects: list[str],
    shows: str = "",
    ground_truth: list[str] | None = None,
    approvals: list[dict[str, Any]] | None = None,
) -> AgentTrajectory:
    """One of the two LLM baseline arms.

    `ground_truth` is what the fixture actually plants. It goes in the outcome
    so a reader can see whether the arm was right without running anything --
    but it is recorded AFTER the fact and was never in the arm's prompt. The
    baselines get the same access a careful human reviewer would have, and no
    more; handing them the answer and then reporting a score would be a rigged
    comparison in the other direction.
    """
    turns = [
        Turn(
            index=row.get("turn", i + 1),
            action=row.get("action"),
            observation=row.get("observation"),
            reported_score=row.get("reported"),
            reasoning=row.get("reasoning") or None,
            malformed=row.get("malformed") or None,
        )
        for i, row in enumerate(trace)
    ]
    outcome: dict[str, Any] = {
        "arm": arm,
        "reported_defects": list(reported_defects),
        "turns_used": len(trace),
        "scored_by": "set comparison against the fixture's planted ground truth",
    }
    if ground_truth is not None:
        found, planted = set(reported_defects), set(ground_truth)
        outcome["planted_defects"] = sorted(planted)
        outcome["missed"] = sorted(planted - found)
        outcome["spurious"] = sorted(found - planted)
        outcome["exact_match"] = found == planted
    return AgentTrajectory(
        agent=agent,
        role="baseline",
        environment=environment,
        task_id=task_id,
        shows=shows,
        system_prompt=system_prompt,
        instruction=instruction,
        turns=turns,
        approvals=approvals or [],
        outcome=outcome,
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/assay/baselines/llm.py src/assay/trajectory.py tests/test_trajectory_export.py
git commit -m "feat(baselines): both arms record turns, tool output and scores

The arms returned truncated raw strings, which is not enough to read a run
end to end -- no tool responses, no scores, and the turns that were neither
an action nor a report vanished entirely."
```

---

### Task 6: The approval gate is a trajectory too

The sandbox refuses to execute untrusted environment code without a human. That refusal is the most consequential turn in the whole system, and it currently leaves no record a judge can read.

**Files:**
- Modify: `src/assay/trajectory.py`
- Test: `tests/test_trajectory_export.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trajectory_export.py`:

```python
import pytest

from assay.sandbox import (
    ApprovalDenied,
    AutoApprove,
    DenyAll,
    DockerSandbox,
    ExecRequest,
    Mount,
    SandboxPolicy,
    SandboxUnavailable,
)
from assay.trajectory import from_approval_gate

POLICY = SandboxPolicy(image="alpine:3.20", network=False)
REQUEST = ExecRequest(policy=POLICY, command=["sh", "-c", "cat expected.txt"])


def test_the_default_approver_refuses_and_nothing_runs():
    sandbox = DockerSandbox()  # DenyAll by default
    with pytest.raises((ApprovalDenied, SandboxUnavailable)) as exc:
        sandbox.run(REQUEST)
    if isinstance(exc.value, ApprovalDenied):
        assert "nothing ran" in str(exc.value)
    assert sandbox.approvals == []


def test_an_approval_gate_trajectory_records_the_refusal():
    traj = from_approval_gate(
        environment="harbor/self-graded",
        task_id="self-graded",
        events=[
            {
                "approver": "DenyAll",
                "request": REQUEST,
                "granted": False,
                "reason": "unattended run; the default approver executes nothing",
                "outcome": "ApprovalDenied raised; nothing ran",
            },
            {
                "approver": "AutoApprove",
                "request": REQUEST,
                "granted": True,
                "reason": "standing approval recorded for the test suite",
                "outcome": "container started, command executed",
            },
        ],
        shows="nothing executes untrusted environment code without a human",
    )
    assert traj.role == "human_checkpoint"
    assert len(traj.approvals) == 2
    assert traj.approvals[0]["granted"] is False
    markdown = traj.to_markdown()
    assert "Human checkpoints" in markdown
    assert "nothing ran" in markdown
    assert "network" in markdown, "a reader must see what containment was applied"
    assert traj.outcome["executed_without_approval"] == 0


def test_the_approval_trajectory_is_signed_like_any_other(tmp_path):
    traj = from_approval_gate(
        environment="harbor/self-graded", task_id="self-graded",
        events=[{"approver": "DenyAll", "request": REQUEST, "granted": False,
                 "reason": "r", "outcome": "nothing ran"}],
        shows="",
    )
    payload = json.loads(traj.write(tmp_path / "gate.json").read_text())
    assert payload["human_checkpoints"][0]["approver"] == "DenyAll"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q -k approval`
Expected: FAIL — `ImportError: cannot import name 'from_approval_gate'`

- [ ] **Step 3: Write the builder**

Add to `src/assay/trajectory.py`:

```python
def from_approval_gate(
    *,
    environment: str,
    task_id: str,
    events: list[dict[str, Any]],
    shows: str = "",
) -> AgentTrajectory:
    """The human approval checkpoint in front of untrusted environment code.

    Every event says who was asked, exactly what they were asked to approve --
    image, command, mounts, network, resource caps -- whether they said yes,
    and what happened as a result. A refusal is a turn like any other, and it
    is the one that most needs to be readable: a gate nobody can audit is not
    a gate.
    """
    turns: list[Turn] = []
    approvals: list[dict[str, Any]] = []
    for i, event in enumerate(events, start=1):
        request = event["request"]
        policy = request.policy
        described = {
            "image": policy.image,
            "command": list(request.command),
            "mounts": [
                {"source": str(m.source), "target": m.target, "read_only": m.read_only}
                for m in request.mounts
            ],
            "network": "ON" if policy.network else "off",
            "limits": {
                "cpus": policy.cpus,
                "memory": policy.memory,
                "pids": policy.pids,
                "wall_seconds": policy.wall_seconds,
                "read_only_root": policy.read_only_root,
            },
        }
        granted = bool(event["granted"])
        turns.append(
            Turn(
                index=i,
                action={"ask_human_to_approve": described, "approver": event["approver"]},
                observation=event["outcome"],
                reported_score=None,
                reasoning=event.get("reason"),
            )
        )
        approvals.append(
            {
                "what": f"execute untrusted environment code in {policy.image}",
                "approver": event["approver"],
                "granted": granted,
                "detail": f"{event.get('reason', '')} -- {event['outcome']}",
                "request": described,
            }
        )
    return AgentTrajectory(
        agent="sandbox approval gate",
        role="human_checkpoint",
        environment=environment,
        task_id=task_id,
        shows=shows,
        system_prompt="",
        instruction=(
            "Assay must run third-party gold solutions, verifier scripts and "
            "adversarial policies. Containment is Docker with the network off and "
            "a read-only root; the second half is a human who has to say yes."
        ),
        turns=turns,
        approvals=approvals,
        outcome={
            "requests": len(events),
            "granted": sum(1 for e in events if e["granted"]),
            "refused": sum(1 for e in events if not e["granted"]),
            "executed_without_approval": 0,
            "default_approver": "DenyAll -- an unattended Assay executes nothing",
        },
    )
```

- [ ] **Step 4: Make the markdown show the request**

The test asserts `"network" in markdown`. `to_markdown` renders `approval.get('what')` and `approval.get('detail')` only. Extend the human-checkpoints block in `to_markdown`:

```python
        if self.approvals:
            lines += ["## Human checkpoints", ""]
            for approval in self.approvals:
                verdict = (
                    "**APPROVED**" if approval.get("granted") else "**REFUSED — nothing ran**"
                )
                lines.append(f"- {approval.get('what', 'approval')} — {approval.get('detail', '')}")
                if "granted" in approval:
                    lines.append(f"  - asked: `{approval.get('approver', '?')}` → {verdict}")
                if approval.get("request"):
                    lines += ["", "```json", canonical_json(approval["request"]), "```", ""]
            lines.append("")
```

Existing callers pass approvals without `granted` or `request` (see `tests/test_trajectory.py`), and both are guarded, so that test keeps passing.

- [ ] **Step 5: Run the tests**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py tests/test_trajectory.py tests/test_sandbox.py -q`
Expected: PASS. `test_the_default_approver_refuses_and_nothing_runs` accepts `SandboxUnavailable` so it does not fail on a machine without Docker — but it must still assert `sandbox.approvals == []` either way.

- [ ] **Step 6: Commit**

```bash
git add src/assay/trajectory.py tests/test_trajectory_export.py
git commit -m "feat(trajectory): render the sandbox approval gate as a trajectory

The refusal is the most consequential turn in the system and it left no
record anyone could read. A gate nobody can audit is not a gate."
```

---

### Task 7: Write the pair, and the index

**Files:**
- Modify: `src/assay/trajectory.py`
- Test: `tests/test_trajectory_export.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trajectory_export.py`:

```python
from assay.trajectory import write_index, write_pair


def _sample(slug_agent: str, shows: str) -> AgentTrajectory:
    return AgentTrajectory(
        agent=slug_agent,
        role="challenger",
        environment="harbor/self-graded",
        task_id="self-graded",
        shows=shows,
        turns=[Turn(index=1, action={"tool": "run"}, observation="ok", reported_score=0.0)],
        outcome={"found_exploit": False},
    )


def test_write_pair_emits_json_and_markdown_that_agree(tmp_path):
    traj = _sample("scripted", "the floor arm misses")
    paths = write_pair(traj, tmp_path, "01-scripted")
    assert paths["json"].name == "01-scripted.json"
    assert paths["markdown"].name == "01-scripted.md"
    payload = json.loads(paths["json"].read_text())
    assert payload["agent"] == "scripted"
    assert traj.shows in paths["markdown"].read_text()


def test_the_index_lists_every_trajectory_and_what_it_shows(tmp_path):
    entries = [
        (_sample("scripted", "the floor arm misses"), "01-scripted"),
        (_sample("prompted", "the model finds it"), "02-prompted"),
    ]
    for traj, slug in entries:
        write_pair(traj, tmp_path, slug)
    path = write_index(entries, tmp_path, unavailable=[
        {"agent": "grpo-trained", "reason": "needs a GPU; the trained adapter is optional"}
    ])
    text = path.read_text()
    for _traj, slug in entries:
        assert f"{slug}.md" in text
        assert f"{slug}.json" in text
    assert "the floor arm misses" in text
    assert "the model finds it" in text
    assert "grpo-trained" in text, "an agent with no trajectory is named, not omitted"
    assert "needs a GPU" in text


def test_the_index_names_agents_that_could_not_be_run_at_all(tmp_path):
    path = write_index([], tmp_path, unavailable=[
        {"agent": "prompted[ollama:qwen3:8b]", "reason": "ollama daemon unreachable"}
    ])
    assert "ollama daemon unreachable" in path.read_text()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q -k index or pair`
Expected: FAIL — `ImportError: cannot import name 'write_pair'`

- [ ] **Step 3: Write both functions**

Add to `src/assay/trajectory.py`:

```python
def write_pair(
    trajectory: AgentTrajectory, directory: str | Path, slug: str
) -> dict[str, Path]:
    """Write one trajectory as both JSON and markdown.

    Two formats on purpose: the JSON is what a machine checks and what the
    signature covers; the markdown is what a judge reads without running
    anything. They are generated from the same object, so they cannot disagree.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = trajectory.write(directory / f"{slug}.json")
    md_path = directory / f"{slug}.md"
    md_path.write_text(trajectory.to_markdown())
    return {"json": json_path, "markdown": md_path}


def write_index(
    entries: list[tuple[AgentTrajectory, str]],
    directory: str | Path,
    unavailable: list[dict[str, str]] | None = None,
) -> Path:
    """The index a reader starts from.

    `unavailable` is not decoration. An agent that could not be run is listed
    with the reason it could not, in the same table, because a deliverable that
    silently contains only the agents that happened to work tells the reader
    nothing about the ones that did not.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Agent trajectories",
        "",
        "Every agent this submission used, one representative run each, readable "
        "end to end: the instructions the agent was given, every action it took, "
        "what the tools said back, the feedback that shaped the next step, and "
        "every point where a human had to approve something.",
        "",
        "Failed turns, malformed replies and refused approvals are kept. A "
        "trajectory that shows only the turns that worked is a highlight reel, "
        "and on an adversarial run the interesting part is usually the turns "
        "where the agent was wrong.",
        "",
        "No model scored anything in any of these runs. Every number in the "
        "`reported` and `outcome` fields comes from a deterministic verifier.",
        "",
        "| # | Agent | Role | Environment | Outcome | What it shows | Read |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, (traj, slug) in enumerate(entries, start=1):
        outcome = traj.outcome
        if "found_exploit" in outcome:
            verdict = (
                f"**found**, gap {outcome.get('exploit_gap')}"
                if outcome["found_exploit"]
                else f"**missed**, gap {outcome.get('exploit_gap')}"
            )
        elif "solve_rates" in outcome:
            verdict = f"solve rates {outcome['solve_rates']}"
        elif "reported_defects" in outcome:
            verdict = f"reported {outcome['reported_defects'] or 'nothing'}"
        elif "refused" in outcome:
            verdict = f"{outcome['granted']} approved, {outcome['refused']} refused"
        else:
            verdict = "-"
        lines.append(
            f"| {i} | `{traj.agent}` | {traj.role} | `{traj.environment}` | {verdict} "
            f"| {traj.shows} | [md]({slug}.md) · [json]({slug}.json) |"
        )
    lines.append("")
    if unavailable:
        lines += [
            "## Agents with no trajectory here, and why",
            "",
            "Absence of evidence is reported as loudly as evidence.",
            "",
            "| Agent | Why there is no run |",
            "|---|---|",
        ]
        lines += [f"| `{row['agent']}` | {row['reason']} |" for row in unavailable]
        lines.append("")
    path = directory / "INDEX.md"
    path.write_text("\n".join(lines))
    return path
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra adapters pytest tests/test_trajectory_export.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/assay/trajectory.py tests/test_trajectory_export.py
git commit -m "feat(trajectory): write the json/markdown pair and the index

The index names agents that could not be run, with the reason, in the same
table as the ones that could. A deliverable containing only the agents that
happened to work says nothing about the ones that did not."
```

---

### Task 8: The export script

**Files:**
- Create: `scripts/export_trajectories.py`

- [ ] **Step 1: Write the script**

Create `scripts/export_trajectories.py`:

```python
"""Run every agent Assay uses and write its trajectory into the repo.

The deliverable is `results/trajectories/`: one JSON and one markdown per run,
plus an INDEX.md. A judge should be able to read all of it without running
anything, which is why the artefacts are committed rather than generated on
demand.

Agents that cannot run here -- no Ollama, no Docker, no Claude CLI -- are
listed in the index with the reason. An agent missing from the deliverable is
a result about this machine, not about the method.

Two Challenger runs against `harbor/self-graded` are replayed from committed
result files rather than re-run: `results/challenger_ablation.json` (the run
where the Claude CLI arm found the exploit at turn 8) and
`results/challenger_ablation_claude.json` (the run where the same arm, same
task, missed). Both are real recorded runs. Shipping only the first would
report a nondeterministic agent as a reliable one.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.adapters import HarborAdapter  # noqa: E402
from assay.baselines.llm import DirectPromptArm, ToolAgentArm  # noqa: E402
from assay.challenger import ScriptedChallenger  # noqa: E402
from assay.challenger.prompted import SYSTEM as CHALLENGER_SYSTEM  # noqa: E402
from assay.challenger.prompted import PromptedChallenger  # noqa: E402
from assay.baselines.llm import AGENT_SYSTEM, SYSTEM as BASELINE_SYSTEM  # noqa: E402
from assay.fixtures import CATALOG, build  # noqa: E402
from assay.llm import ClaudeCLIClient, OllamaClient  # noqa: E402
from assay.rollout import SYSTEM as SOLVER_SYSTEM  # noqa: E402
from assay.rollout import SolveRateSampler  # noqa: E402
from assay.sandbox import (  # noqa: E402
    ApprovalDenied,
    AutoApprove,
    DenyAll,
    DockerSandbox,
    ExecRequest,
    Mount,
    SandboxPolicy,
    SandboxUnavailable,
    docker_available,
)
from assay.trajectory import (  # noqa: E402
    from_approval_gate,
    from_baseline_trace,
    from_probe_detail,
    from_solver_trace,
    write_index,
    write_pair,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "src" / "assay" / "fixtures" / "harbor_suite"
OUT = ROOT / "results" / "trajectories"
HARBOR_TASK = "self-graded"


def harbor(task: str) -> HarborAdapter:
    root = Path(tempfile.mkdtemp(prefix="assay-traj-"))
    shutil.copytree(SUITE / task, root / task)
    return HarborAdapter(
        root, sandbox=DockerSandbox(AutoApprove("trajectory export")), env_id=f"harbor/{task}"
    )


def harbor_instruction(task: str) -> str:
    return (SUITE / task / "instruction.md").read_text().strip()


def challenger_run(challenger, agent: str, shows: str):
    """Audit harbor/self-graded with one Challenger and build its trajectory."""
    with harbor(HARBOR_TASK) as adapter:
        report = audit(adapter, {"challenger": challenger})
    probe = [r for r in report.results if r.family == "reward_hackability"][0]
    if probe.status.value in ("NOT_APPLICABLE", "ERROR"):
        return None, f"{probe.status.value}: {probe.reason}"
    per_task = next(iter(probe.detail.get("per_task", {}).values()), {})
    return (
        from_probe_detail(
            agent=agent,
            environment=f"harbor/{HARBOR_TASK}",
            task_id=HARBOR_TASK,
            instruction=harbor_instruction(HARBOR_TASK),
            system_prompt=CHALLENGER_SYSTEM.strip(),
            per_task=per_task,
            shows=shows,
            approvals=[
                {
                    "what": "execute untrusted environment code in the Harbor image",
                    "approver": "AutoApprove",
                    "granted": True,
                    "detail": "standing approval recorded for this export run -- "
                    "see 08 for the gate itself",
                }
            ],
        ),
        None,
    )


def archived_claude(path: Path, agent: str, shows: str):
    """Replay a committed ablation result as a trajectory."""
    if not path.exists():
        return None, f"{path.relative_to(ROOT)} is not in this checkout"
    payload = json.loads(path.read_text())
    arm = next(
        (a for a in payload["arms"] if a["challenger"] == "prompted:claude-cli"), None
    )
    if arm is None:
        return None, f"no claude-cli arm in {path.name}"
    best = {
        "policy": (arm.get("exploit") or {}).get("policy", "n/a"),
        "gap": arm.get("best_exploit_gap", 0.0),
        "reported": (arm.get("exploit") or {}).get("reported"),
        "true": (arm.get("exploit") or {}).get("true_completion"),
    }
    per_task = {
        "attacker_trace": arm.get("attacker_trace", []),
        "attempts": [],
        "n_attempts": arm.get("attempts", 0),
        "best_attempt": best,
    }
    return (
        from_probe_detail(
            agent=agent,
            environment=f"harbor/{HARBOR_TASK}",
            task_id=HARBOR_TASK,
            instruction=harbor_instruction(HARBOR_TASK),
            system_prompt=CHALLENGER_SYSTEM.strip(),
            per_task=per_task,
            shows=shows,
            approvals=[
                {
                    "what": "execute untrusted environment code in the Harbor image",
                    "approver": "AutoApprove",
                    "granted": True,
                    "detail": f"recorded run, replayed from {path.name}",
                }
            ],
        ),
        None,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b", help="ollama model for the live arms")
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--samples", type=int, default=4, help="solver samples per task")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    out = Path(args.out)
    entries: list[tuple] = []
    unavailable: list[dict[str, str]] = []

    def emit(slug, traj, reason, agent):
        if traj is None:
            print(f"SKIP {slug}: {reason}", flush=True)
            unavailable.append({"agent": agent, "reason": reason})
            return
        write_pair(traj, out, slug)
        print(f"wrote {slug}", flush=True)
        entries.append((traj, slug))

    # 1 -- scripted Challenger, the floor
    if docker_available():
        traj, reason = challenger_run(
            ScriptedChallenger(),
            "scripted",
            "the fixed repertoire, no model: four policies, none of which reads a "
            "file or writes to expected.txt, so the exploit is out of reach. A "
            "miss -- and the miss is what makes the agentic arm load-bearing.",
        )
        emit("01-challenger-scripted-harbor-self-graded", traj, reason, "scripted")
    else:
        emit("01-challenger-scripted-harbor-self-graded", None,
             "docker is not installed or the daemon is not running", "scripted")

    # 2 -- prompted Challenger via Ollama
    ollama = OllamaClient(args.model)
    ok, reason = ollama.availability()
    if ok and docker_available():
        traj, why = challenger_run(
            PromptedChallenger(client=ollama, turns=args.turns),
            f"prompted[{ollama.name}]",
            f"a local {args.model} in a feedback loop for {args.turns} turns. It "
            "gets tool output and a score back every turn, repeats itself, is told "
            "so by the harness, and still never reads the verifier. A second, "
            "different failure.",
        )
        emit(f"02-challenger-ollama-{args.model.replace(':', '-')}-harbor-self-graded",
             traj, why, f"prompted[{ollama.name}]")
    else:
        emit(f"02-challenger-ollama-{args.model.replace(':', '-')}-harbor-self-graded",
             None, reason if not ok else "docker daemon not running",
             f"prompted[ollama:{args.model}]")

    # 3, 4 -- the Claude CLI arm, both a hit and a miss, from committed runs
    emit(
        "03-challenger-claude-cli-harbor-self-graded-found",
        *archived_claude(
            ROOT / "results" / "challenger_ablation.json",
            "prompted[claude-cli:sonnet]",
            "seven turns of reconnaissance -- hunting the verifier, listing "
            "/logs, checking permissions, trying to write reward.txt directly -- "
            "then turn 8 writes 'banana' to both expected.txt and out.txt and is "
            "scored 1.0 by the environment and 0.0 by the independent verifier. "
            "Turn 9 is a failed retry: tampering with reward.txt directly scores 0.0.",
        )[::1],
        "prompted[claude-cli:sonnet]",
    )
    emit(
        "04-challenger-claude-cli-harbor-self-graded-missed",
        *archived_claude(
            ROOT / "results" / "challenger_ablation_claude.json",
            "prompted[claude-cli:sonnet]",
            "the same agent, the same task, a different run -- and it misses. "
            "Shipped next to 03 so the hit is not read as a reliable capability.",
        )[::1],
        "prompted[claude-cli:sonnet]",
    )

    # 5 -- the Solver behind the difficulty probe
    if ok:
        env = build("healthy")
        sampler = SolveRateSampler(client=ollama, samples=args.samples)
        rates = sampler.solve_rates(env)
        traj = from_solver_trace(
            agent=sampler.name,
            environment="toy-triage/healthy",
            trace=sampler.trace,
            solve_rates=rates,
            instruction=env.manifest().tasks[0].instruction,
            system_prompt=SOLVER_SYSTEM.strip(),
            shows="the difficulty probe estimating a solve rate by actually "
            "attempting the tasks. Every sample is here, including the replies "
            "that were not JSON -- those are failed attempts, not skipped ones.",
        )
        emit("05-solver-difficulty-toy-triage-healthy", traj, None, sampler.name)
    else:
        emit("05-solver-difficulty-toy-triage-healthy", None, reason,
             f"solver[ollama:{args.model}]")

    # 6, 7 -- the two LLM baseline arms
    planted = sorted(d.value for d in CATALOG["weak_oracle"])
    if ok:
        for slug, arm, shows in (
            (
                "06-baseline-direct-prompt-toy-triage-weak-oracle",
                DirectPromptArm(ollama),
                "one prompt, everything a careful reviewer could read, one answer. "
                "It is given the exact defect taxonomy and the same source access "
                "Assay has, and never the planted ground truth.",
            ),
            (
                "07-baseline-agent-with-tools-toy-triage-weak-oracle",
                ToolAgentArm(ollama, turns=6),
                "the same, plus turns in which it may actually run things. Each "
                "turn it sees the tool output and the score the environment gave, "
                "and that feedback is what it has to reason from.",
            ),
        ):
            env = build("weak_oracle")
            defects, _log = arm.run(env)
            traj = from_baseline_trace(
                agent=f"{arm.arm}[{ollama.name}]",
                arm=arm.arm,
                environment="toy-triage/weak_oracle",
                task_id=env.manifest().tasks[0].task_id,
                trace=arm.trace,
                instruction="Which validity defects, if any, does this environment have?",
                system_prompt=(BASELINE_SYSTEM if arm.arm == "direct_prompt" else AGENT_SYSTEM).strip(),
                reported_defects=sorted(d.value for d in defects),
                ground_truth=planted,
                shows=shows,
            )
            emit(slug, traj, None, f"{arm.arm}[{ollama.name}]")
    else:
        emit("06-baseline-direct-prompt-toy-triage-weak-oracle", None, reason,
             f"direct_prompt[ollama:{args.model}]")
        emit("07-baseline-agent-with-tools-toy-triage-weak-oracle", None, reason,
             f"agent_with_tools[ollama:{args.model}]")

    # 8 -- the human approval gate
    policy = SandboxPolicy(image="alpine:3.20", network=False)
    request = ExecRequest(
        policy=policy,
        command=["sh", "-c", "cat expected.txt"],
        mounts=[Mount(source=SUITE / HARBOR_TASK, target="/work", read_only=True)],
    )
    events = []
    denying = DockerSandbox(DenyAll())
    try:
        denying.run(request)
        refusal = "the request was executed -- this should not happen"
    except ApprovalDenied as exc:
        refusal = f"ApprovalDenied: {exc}"
    except SandboxUnavailable as exc:
        refusal = f"never reached the approver: {exc}"
    events.append(
        {
            "approver": "DenyAll",
            "request": request,
            "granted": False,
            "reason": "the default approver. An unattended Assay executes nothing.",
            "outcome": f"{refusal} -- approvals recorded: {len(denying.approvals)}",
        }
    )
    approving = DockerSandbox(AutoApprove("standing approval for the trajectory export"))
    if docker_available():
        result = approving.run(request)
        outcome = (
            f"approved and executed: exit {result.exit_code}, "
            f"stdout {result.stdout.strip()[:80]!r}"
        )
    else:
        outcome = "approved, but docker is not running, so nothing executed"
    events.append(
        {
            "approver": "AutoApprove('standing approval for the trajectory export')",
            "request": request,
            "granted": True,
            "reason": "explicit standing approval, carrying a reason. An approval "
            "nobody can account for later is the same as no approval.",
            "outcome": outcome,
        }
    )
    emit(
        "08-sandbox-approval-gate-harbor-self-graded",
        from_approval_gate(
            environment=f"harbor/{HARBOR_TASK}",
            task_id=HARBOR_TASK,
            events=events,
            shows="the human checkpoint in front of untrusted environment code. "
            "The default approver refuses and nothing runs; an explicit standing "
            "approval carrying a reason lets the identical request through.",
        ),
        None,
        "sandbox approval gate",
    )

    unavailable.append(
        {
            "agent": "grpo-trained Challenger",
            "reason": "needs a GPU and a trained LoRA adapter. Both GRPO runs failed "
            "to learn (99.7% and 95.7% of rollout groups had zero reward spread) and "
            "the numbers are in docs/changelog/40-grpo-challenger.md. It is an "
            "optional artifact; nothing in Assay requires it.",
        }
    )

    index = write_index(entries, out, unavailable=unavailable)
    print(f"\nwrote {index} -- {len(entries)} trajectories, {len(unavailable)} not run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Check the module-level constants the script imports actually exist**

Run:
```bash
uv run --extra adapters python -c "
from assay.rollout import SYSTEM
from assay.baselines.llm import SYSTEM, AGENT_SYSTEM
from assay.challenger.prompted import SYSTEM
print('ok')
"
```
Expected: `ok`. If any name differs, fix the import in the script to the real name rather than renaming the module constant.

- [ ] **Step 3: Fix the `emit(*archived_claude(...))` call shape**

`archived_claude` returns `(traj, reason)` and `emit` takes `(slug, traj, reason, agent)`. The `[::1]` in the draft above is a no-op placeholder that reads badly; replace both call sites with an explicit unpack:

```python
    traj, why = archived_claude(
        ROOT / "results" / "challenger_ablation.json",
        "prompted[claude-cli:sonnet]",
        "seven turns of reconnaissance -- hunting the verifier, listing /logs, "
        "checking permissions, trying to write reward.txt directly -- then turn 8 "
        "writes 'banana' to both expected.txt and out.txt and is scored 1.0 by the "
        "environment and 0.0 by the independent verifier. Turn 9 is a failed retry: "
        "tampering with reward.txt directly scores 0.0.",
    )
    emit("03-challenger-claude-cli-harbor-self-graded-found", traj, why,
         "prompted[claude-cli:sonnet]")

    traj, why = archived_claude(
        ROOT / "results" / "challenger_ablation_claude.json",
        "prompted[claude-cli:sonnet]",
        "the same agent, the same task, a different run -- and it misses. Shipped "
        "next to 03 so the hit is not read as a reliable capability.",
    )
    emit("04-challenger-claude-cli-harbor-self-graded-missed", traj, why,
         "prompted[claude-cli:sonnet]")
```

- [ ] **Step 4: Run it**

Run:
```bash
uv run --extra adapters --extra sweep --extra openenv python scripts/export_trajectories.py --model qwen3:8b --turns 10 --samples 4
```
Expected: eight `wrote NN-...` lines, or a `SKIP` line naming the missing runtime. Anything skipped must appear in `results/trajectories/INDEX.md` with its reason.

- [ ] **Step 5: Read the output as a judge would**

Run: `cat results/trajectories/INDEX.md` and open two of the markdown files. Check by eye:
- trajectory 01 outcome says **missed**, gap 0.0
- trajectory 03 turn 8 shows the `banana` command, `Environment scored it: 1.0`, and turn 9 shows the failed `reward.txt` tamper at 0.0
- trajectory 08 renders both the refusal and the approval, with the image, command, mounts, network and limits visible

- [ ] **Step 6: Commit**

```bash
git add scripts/export_trajectories.py results/trajectories
git commit -m "feat(trajectories): export one run per agent as the deliverable

Eight runs across every agent the submission uses, JSON and markdown, with an
index. Two Challenger misses and one refused approval are in there on purpose."
```

---

### Task 9: A test that the committed artefact is real

The deliverable is committed files. A test that only exercises the builders would pass while the directory on disk was stale or empty.

**Files:**
- Modify: `tests/test_trajectory_export.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_trajectory_export.py`:

```python
from pathlib import Path

TRAJECTORIES = Path(__file__).resolve().parents[1] / "results" / "trajectories"


def test_the_committed_deliverable_covers_every_agent_the_submission_used():
    """Not a smoke test. The brief asks for a trajectory per agent, so the
    absence of one is a deliverable defect, not a missing nice-to-have."""
    index = TRAJECTORIES / "INDEX.md"
    assert index.exists(), "run scripts/export_trajectories.py"
    text = index.read_text()
    for role in ("challenger", "solver", "baseline", "human_checkpoint"):
        assert role in text, f"no {role} trajectory in the index"


def test_every_indexed_trajectory_has_both_files_on_disk():
    text = (TRAJECTORIES / "INDEX.md").read_text()
    slugs = sorted(
        p.stem for p in TRAJECTORIES.glob("*.json")
    )
    assert slugs, "no trajectories exported"
    for slug in slugs:
        assert (TRAJECTORIES / f"{slug}.md").exists(), f"{slug} has no markdown"
        assert f"{slug}.md" in text, f"{slug} is not in the index"


def test_the_committed_trajectories_are_signed_and_intact():
    from assay.types import digest

    for path in TRAJECTORIES.glob("*.json"):
        payload = json.loads(path.read_text())
        signature = payload.pop("signature")
        # `exported` is part of the signed body, so this checks the file has
        # not been hand-edited since it was written.
        assert signature == digest(payload), f"{path.name} has been modified"


def test_at_least_one_committed_trajectory_is_a_failure():
    """An index of successes is a highlight reel."""
    misses = []
    for path in TRAJECTORIES.glob("*.json"):
        outcome = json.loads(path.read_text())["outcome"]
        if outcome.get("found_exploit") is False or outcome.get("refused"):
            misses.append(path.name)
    assert misses, "no failed run in the deliverable"


def test_a_human_approval_checkpoint_is_in_the_deliverable():
    gates = [
        json.loads(p.read_text())
        for p in TRAJECTORIES.glob("*.json")
        if json.loads(p.read_text())["role"] == "human_checkpoint"
    ]
    assert gates, "no human checkpoint trajectory"
    gate = gates[0]
    assert gate["outcome"]["executed_without_approval"] == 0
    assert any(not a["granted"] for a in gate["human_checkpoints"]), (
        "a gate that only ever says yes demonstrates nothing"
    )


def test_no_third_party_environment_content_is_redistributed():
    """inspect_evals, OpenEnv and ScienceAgentBench content may not ship. The
    trajectories run on this repo's own fixtures only."""
    for path in TRAJECTORIES.glob("*.json"):
        env = json.loads(path.read_text())["environment"]
        assert env.startswith(("harbor/", "toy-triage/", "fixture/")), env
```

- [ ] **Step 2: Run the whole suite**

Run: `uv run --extra adapters --extra sweep --extra openenv pytest -q`
Expected: the pre-existing 270 pass, plus the new ones. If anything in the 270 broke, fix the cause — do not adjust the assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/test_trajectory_export.py
git commit -m "test: the committed trajectories must be signed, complete and honest

Asserts the deliverable on disk, not just the builders: every indexed run has
both files, every signature still verifies, at least one run is a failure, and
the approval gate refuses at least once."
```

---

### Task 10: Changelog fragment

**Files:**
- Create: `docs/changelog/80-trajectories.md`
- Modify: `docs/CHANGELOG.md` (generated — never hand-edited)

- [ ] **Step 1: Write the fragment**

Create `docs/changelog/80-trajectories.md` with rows in the house shape
`| Stage | What was tried and why | Evidence | Decision / learning |`.
It must record at minimum:
- that `trajectory.py` existed and was wired to nothing, and what wiring it meant per agent
- that `ScriptedChallenger` left `attacker_trace` empty, so the arm whose *miss* carries the agentic argument was the one with no record
- the two Claude CLI runs on the identical task, one found and one missed, and why both ship
- that the approval gate is exported as a trajectory including the refusal
- the exact reproduction command

- [ ] **Step 2: Merge**

Run: `uv run --extra adapters python scripts/merge_changelog.py`
Expected: `docs/CHANGELOG.md` regenerated with a `<!-- from 80-trajectories.md -->` block.

- [ ] **Step 3: Verify nothing else in the changelog moved**

Run: `git diff --stat docs/CHANGELOG.md`
Expected: additions only.

- [ ] **Step 4: Commit**

```bash
git add docs/changelog/80-trajectories.md docs/CHANGELOG.md
git commit -m "docs: record the trajectory deliverable in the changelog"
```

---

### Task 11: Point the reader at it

A deliverable nobody is told about is a deliverable nobody reads.

**Files:**
- Modify: `README.md`
- Modify: `docs/REPRODUCTION.md`

- [ ] **Step 1: Add a README section**

After the "Does an agent find what a script cannot?" section in `README.md`, add:

```markdown
## What every agent actually did

[`results/trajectories/`](results/trajectories/INDEX.md) — one representative run
per agent this submission used, readable end to end without running anything:
the instructions it was given, every action, what the tools said back, the
feedback that shaped the next step, and every human approval.

Failed turns and malformed replies are kept. Two of the eight runs are Challenger
**misses**, one is the same Claude CLI arm missing on the task it cracks in
another run, and one is the sandbox approval gate refusing — `DenyAll` is the
default, and nothing executes untrusted environment code without a human.

```bash
uv run --extra adapters python scripts/export_trajectories.py
```
```

- [ ] **Step 2: Add a REPRODUCTION section**

After "The Challenger ablation" in `docs/REPRODUCTION.md`:

```markdown
## The agent trajectories

```bash
uv run --extra adapters python scripts/export_trajectories.py --model qwen3:8b
```

Writes `results/trajectories/`. The Ollama-backed arms skip with a reason if
the daemon is not running, and the Harbor arms skip without Docker; both are
listed in `INDEX.md` rather than dropped. The two Claude CLI trajectories are
replayed from committed ablation results, so they reproduce without the CLI.
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/REPRODUCTION.md
git commit -m "docs: link the trajectory deliverable from the README and repro guide"
```

---

## Final verification

- [ ] `uv run --extra adapters --extra sweep --extra openenv pytest -q` — 270 pre-existing tests still green, plus the new file
- [ ] `ls results/trajectories/` — 8 JSON, 8 markdown, `INDEX.md`
- [ ] `git log --oneline worker/traj` — progressive commits, no AI attribution footer
- [ ] `git status` — clean, and nothing committed outside the worktree
