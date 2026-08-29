"""Adapter for OpenEnv (huggingface/OpenEnv) environments, run in process.

The headline result of this adapter is a negative one, and it is structural
rather than a bug in any particular environment.

**OpenEnv has no separable verifier, so most of the battery cannot run.**

OpenEnv's environment spec (`rfcs/002-env-spec.md`) gives an environment three
members: `reset(seed, episode_id)`, `step(action)`, and a `state` property.
Reward is computed *inside* `step` and handed back as a field on the returned
`Observation` (`openenv.core.env_server.types.Observation.reward`). There is no
`verify`, no `score`, no scorer object and no target argument -- not on the
base class and not on any environment surveyed. The only way to obtain a number
is to drive a live episode and read what the environment chose to report.

Three probe families die on that, and they are the three that matter most:

* **Inverted spec.** There is no spec to substitute. `step` takes an action,
  not a target, so there is nothing to invert. The probe that asks "can this
  eval fail at all" -- the CRITICAL one -- has no surface to push on.
* **Gold / known-wrong.** Scoring a *recorded* transcript requires a scorer you
  can call on your own terms. Here, re-scoring means re-running, and re-running
  a stateful environment measures the environment's current state, not the
  transcript.
* **Reward hackability.** The Challenger maximises the gap between the
  environment's reported score and an independent reading of whether the job
  got done. With only one of those two numbers obtainable, there is no gap to
  measure.

Extracting the reward by importing an environment's server-side internals --
reaching into `env._ta_env.state.game_state["secret_word"]` to build a gold
trajectory, say -- would make some of these probes appear to run. This adapter
deliberately does not do that. It is bespoke per environment, it breaks on
every version bump, and, worse, it produces clean-looking results from checks
that were never really performed. The client contract is what a training run
actually consumes, so the client contract is what gets audited.

So the manifest withholds `SEPARABLE_VERIFIER`, `GOLD_TRAJECTORY`,
`INVERTIBLE_SPEC`, `KNOWN_WRONG`, `GRADED_POLICIES` and `TRUE_COMPLETION`, and
the probes that need them report NOT_APPLICABLE with a reason. That is the
finding: the RL environment standard the ecosystem is standardising on cannot
express a verifier an auditor can call on its own terms.

Why `verify` raises instead of returning the last step reward
-------------------------------------------------------------
Both were on the table. `verify` raises `NotSupported`, because returning the
step reward would satisfy the signature while breaking both promises the
signature makes:

1. `spec` would have to be silently ignored. A probe passing an inverted spec
   would get the *un*-inverted score back and read it as a real answer. That is
   a manufactured result from a check that never ran -- exactly the failure
   this tool exists to catch.
2. `Score.passed` would have to be invented. OpenEnv reports a bare float with
   no declared scale and no declared success threshold; nothing on the client
   contract says what counts as solved. Picking a cutoff here would put the
   auditor's opinion inside a number the card attributes to the environment.

Raising also puts the reason itself into the card, because probes turn
`NotSupported` into NOT_APPLICABLE and print the message.

The reward is still reachable, under a name that does not claim to be a
verifier: `episode_reward()` returns what the live episode actually reported,
and `describe()` prints the reward every trivial policy earned, so a human
reviewer can read the landscape directly.

What still runs
---------------
`determinism` -- same seed, same episode -- needs no verifier, and it is the
probe that pays for this adapter: it catches `textarena_env` dropping the seed
argument on the floor. `difficulty_band` runs whenever the caller supplies
`ctx['solve_rates']` from a real sampler.

Running in process, not over HTTP
---------------------------------
The server-side `Environment` subclass is instantiated directly, the way
OpenEnv's own tests do it. Docker and uvicorn add a process boundary, a
serialization round trip and a startup cost without adding a single
observation, and a probe battery that needs a container is a probe battery that
does not get run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..adapter import BaseAdapter, NotSupported, run_policy
from ..types import (
    Action,
    Capability,
    Manifest,
    Observation,
    Score,
    StepResult,
    Task,
    Transcript,
)

#: Fields that identify one particular episode rather than describing what the
#: environment did. Excluded from observation payloads so the determinism probe
#: does not report a fresh uuid4 per reset as nondeterministic behaviour --
#: which every OpenEnv environment would then "fail", telling you nothing.
EPISODE_HANDLES = ("episode_id", "session_id", "request_id")


def _payload(observation: Any) -> Any:
    """A stable, hashable projection of an OpenEnv observation.

    Pydantic's json mode first, because it is canonical. Some environments put
    non-serialisable objects on the observation (fastmcp's `CallToolResult`),
    so python mode is the fallback and `repr` the last resort.
    """
    for mode in ("json", "python"):
        try:
            dumped = observation.model_dump(mode=mode)
        except Exception:  # noqa: BLE001 - any dump failure falls through
            continue
        if isinstance(dumped, dict):
            return {k: v for k, v in dumped.items() if k not in EPISODE_HANDLES}
        return dumped
    return repr(observation)


@dataclass(frozen=True)
class OpenEnvBinding:
    """Everything environment-specific about driving one OpenEnv environment.

    Kept as data rather than a subclass so that adding an environment is adding
    a binding, not adding a class -- and so what is environment-specific is
    visible in one place instead of spread over overrides.
    """

    env_id: str
    #: Builds the server-side `Environment` subclass. Called lazily: some
    #: environments do real work in `__init__` (TextArena calls `ta.make` and a
    #: first `reset`), and reading a manifest should not cost that.
    factory: Callable[[], Any]
    #: Assay `Action` -> the environment's native action object. Raises
    #: `ValueError` for a tool the environment does not have.
    to_native: Callable[[Action], Any]
    tasks: list[Task]
    #: Input-ignoring policies, most informative first. These are honest: not
    #: one of them reads an observation.
    trivial: dict[str, list[Action]] = field(default_factory=dict)
    version: str = "unknown"
    source: str = ""
    #: True for an observation reporting that the action was rejected.
    is_error: Callable[[Any], bool] = lambda obs: bool(
        (getattr(obs, "metadata", None) or {}).get("error")
    )


class OpenEnvAdapter(BaseAdapter):
    """Audit one OpenEnv environment through its client-facing contract only.

    Every optional capability is inherited from `BaseAdapter`, which refuses by
    default -- this adds back only `reset`/`step`, which is all OpenEnv offers.
    """

    def __init__(self, binding: OpenEnvBinding) -> None:
        self._binding = binding
        self._env: Any | None = None
        self._task_id: str | None = None
        #: Rewards the live episode reported, in order. Cleared on reset.
        self._rewards: list[float | None] = []

    # -- lifecycle ---------------------------------------------------------

    def _ensure(self) -> Any:
        if self._env is None:
            self._env = self._binding.factory()
        return self._env

    def close(self) -> None:
        if self._env is not None:
            close = getattr(self._env, "close", None)
            if close:
                close()
            self._env = None

    # -- manifest ----------------------------------------------------------

    def manifest(self) -> Manifest:
        caps = {
            Capability.LIVE_STEPPING,
            # `reset(seed=...)` is on the OpenEnv Environment ABC, so a seed can
            # always be *passed*. Whether passing it changes anything is what
            # the determinism probe is for -- and on textarena_env it does not.
            # Declaring the capability is what lets that probe run at all.
            Capability.SEEDED_RESET,
        }
        if self._binding.trivial:
            caps.add(Capability.TRIVIAL_POLICIES)
        # Deliberately absent, each for a reason in the module docstring:
        #   SEPARABLE_VERIFIER  reward is computed inside step()
        #   GOLD_TRAJECTORY     neither environment ships one
        #   INVERTIBLE_SPEC     step() takes an action, never a target
        #   KNOWN_WRONG         no scorer to run a wrong policy against
        #   GRADED_POLICIES     ranking two policies needs a score you can call
        #   TRUE_COMPLETION     no independent signal on the client contract
        #   SPLITS / ITEM_PARTS neither environment ships a dataset at all
        return Manifest(
            env_id=self._binding.env_id,
            ecosystem="openenv",
            version=self._binding.version,
            source=self._binding.source,
            capabilities=frozenset(caps),
            tasks=list(self._binding.tasks),
        )

    def describe(self) -> str:
        """The manifest, plus the one number OpenEnv does hand over.

        A human reviewer can see here that a policy ignoring the input earns
        0.1 while a policy genuinely trying earns 0.0. Assay cannot turn that
        into a probe result -- nothing on the client contract says which of
        those is a pass -- but printing it beats withholding it.
        """
        lines = [
            super().describe(),
            "",
            "verifier: NONE. OpenEnv computes reward inside step() and returns it on the",
            "Observation. There is no scorer to call with a transcript or a target, so",
            "gold, inverted-spec, known-wrong, separability and reward-hackability cannot",
            "be probed. The module docstring says why faking it was refused.",
            "",
            "reward reported by the environment, per input-ignoring policy:",
        ]
        for task in self._binding.tasks:
            for label, actions in self._binding.trivial.items():
                try:
                    trace = self.episode_reward(task.task_id, actions)
                except Exception as exc:  # noqa: BLE001 - this probes the env, not us
                    lines.append(f"  {task.task_id} / {label}: unavailable ({exc})")
                    continue
                lines.append(
                    f"  {task.task_id} / {label}: final={trace['final']} "
                    f"steps={trace['steps']} rewards={trace['rewards']}"
                )
        return "\n".join(lines)

    # -- episode -----------------------------------------------------------

    def reset(self, task_id: str, seed: int = 0) -> Observation:
        known = {t.task_id for t in self._binding.tasks}
        if task_id not in known:
            raise KeyError(f"unknown task id: {task_id} (have {sorted(known)})")
        env = self._ensure()
        self._task_id = task_id
        self._rewards = []
        native = env.reset(seed=seed)
        self._rewards.append(getattr(native, "reward", None))
        return Observation(ok=True, data=_payload(native))

    def step(self, action: Action) -> StepResult:
        if self._task_id is None:
            raise RuntimeError("step() before reset()")
        env = self._ensure()
        try:
            native_action = self._binding.to_native(action)
        except ValueError as exc:
            return StepResult(
                Observation(ok=False, code="UNKNOWN_TOOL", message=str(exc)), done=False
            )
        native = env.step(native_action)
        reward = getattr(native, "reward", None)
        self._rewards.append(reward)
        return StepResult(
            Observation(ok=not self._binding.is_error(native), data=_payload(native)),
            done=bool(getattr(native, "done", False)),
            reward=None if reward is None else float(reward),
        )

    # -- the verifier that is not there ------------------------------------

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        raise NotSupported(
            "OpenEnv has no separable verifier: reward is computed inside step() and "
            "returned on the Observation (rfcs/002-env-spec.md). There is no scorer to "
            "call on a recorded transcript and no target argument to substitute, so a "
            "Score here would have to ignore `spec` and invent a pass threshold the "
            "environment never declares. Use episode_reward() for what the live episode "
            "actually reported."
        )

    # -- what the environment will tell you --------------------------------

    def episode_reward(
        self, task_id: str, actions: list[Action], seed: int = 0
    ) -> dict[str, Any]:
        """Run one live episode and report the rewards it emitted.

        Deliberately not named `verify` and deliberately not returning a
        `Score`. This is the environment's running commentary on an episode it
        is still holding the state for -- not a judgement on a recorded
        transcript, and not a pass/fail. A caller wanting a solve rate has to
        supply its own notion of solved; this will not guess one.
        """
        transcript = run_policy(self, task_id, actions, seed=seed)
        rewards = list(self._rewards)
        final = next((r for r in reversed(rewards) if r is not None), None)
        return {
            "task_id": task_id,
            "seed": seed,
            "steps": len(transcript.actions),
            "rewards": rewards,
            "final": final,
        }

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        if not self._binding.trivial:
            raise NotSupported("no input-ignoring policy is defined for this environment")
        return {k: list(v) for k, v in self._binding.trivial.items()}


# --------------------------------------------------------------------------
# Bindings for the two environments audited here
# --------------------------------------------------------------------------

LIST_TOOLS = "list_tools"
CALL_TOOL = "call_tool"
SAY = "say"

#: The commit both environments are read from. They are not published to PyPI
#: -- only the `openenv` framework is -- so the audit is pinned to a revision
#: rather than a release, and the pin is recorded here so a reader can check
#: out exactly what was audited.
OPENENV_REV = "e059726da215f615c44dd10f60402970a3cb20ad"


def _echo_action(action: Action) -> Any:
    from openenv.core.env_server.mcp_types import CallToolAction, ListToolsAction

    if action.tool == LIST_TOOLS:
        return ListToolsAction()
    if action.tool == CALL_TOOL:
        return CallToolAction(
            tool_name=str(action.args.get("tool_name", "")),
            arguments=dict(action.args.get("arguments", {})),
        )
    raise ValueError(f"echo_env exposes {LIST_TOOLS} and {CALL_TOOL}, not {action.tool!r}")


def echo_binding() -> OpenEnvBinding:
    """`envs/echo_env` -- a pure MCP environment, wiring only.

    Its reward is hardcoded: `0.0` at reset and on the unknown-action path, and
    `None` on every MCP action, because `MCPEnvironment` never sets one. There
    is nothing here for a validity probe to measure even in principle, so the
    entry earns its place by proving the in-process seam works against a real
    shipped OpenEnv environment rather than against a mock of one.
    """
    from echo_env.server.echo_environment import EchoEnvironment

    return OpenEnvBinding(
        env_id="openenv/echo",
        factory=EchoEnvironment,
        to_native=_echo_action,
        tasks=[
            Task(
                task_id="echo",
                instruction=(
                    "Echo a message back through the MCP tools the environment exposes: "
                    "echo_message(message) and echo_with_length(message)."
                ),
                metadata={"mcp": True, "reward": "hardcoded 0.0 at reset, None on MCP actions"},
            )
        ],
        trivial={
            "list_tools_only": [Action(LIST_TOOLS)],
            "echo_empty_string": [
                Action(CALL_TOOL, {"tool_name": "echo_message", "arguments": {"message": ""}})
            ],
            "noop": [],
        },
        version=f"openenv-echo-env@{OPENENV_REV[:12]}",
        source="huggingface/OpenEnv envs/echo_env",
    )


def _wordle_action(action: Action) -> Any:
    from textarena_env.models import TextArenaAction

    if action.tool == SAY:
        return TextArenaAction(message=str(action.args.get("message", "")))
    raise ValueError(f"textarena_env takes a single {SAY!r} action, not {action.tool!r}")


def wordle_binding(*, download_nltk: bool = False) -> OpenEnvBinding:
    """`envs/textarena_env` on `Wordle-v0` -- the one with real reward logic.

    `rewards.py` declares a `RewardProvider` protocol and a Wordle provider
    scoring greens, yellows and repeated guesses. None of it is callable from
    outside: the providers are constructed in the environment's `__init__`,
    invoked from inside `step`, and their output folded into
    `observation.info["reward_signals"]`. A real reward function, reachable
    only by playing.

    `download_nltk` defaults to False so an audit does not reach the network.
    The corpus provider checks for the NLTK data first and reports the reason
    when it is missing, rather than downloading behind the caller's back.
    """
    from textarena_env.server.environment import TextArenaEnvironment

    def factory():
        return TextArenaEnvironment(
            env_id="Wordle-v0", num_players=1, download_nltk=download_nltk
        )

    def say(message: str) -> Action:
        return Action(SAY, {"message": message})

    return OpenEnvBinding(
        env_id="openenv/textarena-wordle",
        factory=factory,
        to_native=_wordle_action,
        tasks=[
            Task(
                task_id="Wordle-v0",
                instruction=(
                    "Play Wordle. A secret 5-letter word has been chosen; you have six "
                    "attempts. Wrap each guess in square brackets, e.g. [crane]. Feedback "
                    "marks each letter G (right letter, right place), Y (right letter, "
                    "wrong place) or X (not in the word)."
                ),
                metadata={"textarena_env_id": "Wordle-v0", "num_players": 1},
            )
        ],
        # Input-ignoring by construction: each replays a fixed script and never
        # reads the feedback. `repeat_one_guess` is first because it is the one
        # that reveals something -- TextArena ends the episode on a repeated
        # guess and still pays out, which is the closest thing to a trivial
        # floor breach obtainable without a verifier.
        trivial={
            "repeat_one_guess": [say("[crane]")] * 6,
            "fixed_six_guesses": [
                say(w)
                for w in ("[crane]", "[slate]", "[pound]", "[mirth]", "[flute]", "[bingo]")
            ],
            "non_answer": [say("I do not know the word.")] * 6,
            "noop": [],
        },
        version=f"openenv-textarena@{OPENENV_REV[:12]}",
        source="huggingface/OpenEnv envs/textarena_env",
    )
