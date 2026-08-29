"""The adapter protocol -- the smallest surface that makes the probes possible.

An adapter translates one ecosystem (inspect_ai, Harbor, OpenEnv) into this
shape. The load-bearing design decision is that `verify` is separable from
`step`: a probe must be able to score a transcript, or an inverted spec,
without driving a live episode. Environments that entangle the two are
auditable only by expensive black-box probing, and their adapters say so by
withholding Capability.SEPARABLE_VERIFIER.

Two methods are used by callers but are NOT part of the protocol, because only
some adapters can implement them meaningfully:

  * `close()`   -- release a live resource. Call it via `close_adapter`.
  * `clear_cache()` -- discard memoised verification. The determinism probe
    calls it when present, so an adapter that caches `verify` MUST define it or
    the probe fingerprints a memory instead of a run. Harbor is the only
    adapter that caches, and the only one that defines it.

Both are duck-typed rather than declared. That is a known seam, not an
oversight; `docs/ARCHITECTURE.md` records why it was left that way.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import (
    Action,
    Capability,
    Item,
    Manifest,
    Observation,
    Score,
    StepResult,
    Transcript,
)


class NotSupported(Exception):
    """Raised by an adapter when a capability it did not declare is used.

    Probes catch this and report NOT_APPLICABLE. It is never an ERROR: an
    environment that lacks gold trajectories is not broken, it is just less
    auditable, and the card has to say which.
    """


@runtime_checkable
class EnvAdapter(Protocol):
    """Everything a probe is allowed to assume about an environment."""

    def manifest(self) -> Manifest: ...

    # -- episode -----------------------------------------------------------

    def reset(self, task_id: str, seed: int = 0) -> Observation: ...

    def step(self, action: Action) -> StepResult: ...

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        """Score a transcript. `spec` overrides the task's own success spec,
        which is what makes the inverted-spec probe possible."""
        ...

    # -- optional capabilities --------------------------------------------

    def gold_actions(self, task_id: str) -> list[Action]: ...

    def invert_spec(self, task_id: str) -> Any: ...

    def known_wrong_actions(self, task_id: str) -> list[Action]: ...

    def train_items(self) -> list[Item]: ...

    def eval_items(self) -> list[Item]: ...

    def verifier_asserts(self, task_id: str) -> list[str]:
        """What the verifier actually checks, as human-readable claims.

        Family 6 compares these against the task instruction. Adapters derive
        them from the real scorer (assertion list, test names, rubric items) --
        never from the instruction itself, which would make the check vacuous.
        """
        ...

    def true_completion(self, transcript: Transcript) -> float:
        """Ground truth in [0,1]: did the policy actually do the job.

        Held separately from `verify`, which is the environment's own opinion.
        The gap between them is exactly what the Challenger maximises.
        """
        ...

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        """Degenerate policies that ignore the input: always-abstain,
        majority-class, always-escalate, stratified-random. If one of these
        wins, the environment is not measuring capability."""
        ...

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        """Policies of known-differing quality, best first. Family 3 asserts
        the environment can actually tell them apart."""
        ...


class BaseAdapter:
    """Convenience base: every optional capability refuses by default."""

    def gold_actions(self, task_id: str) -> list[Action]:
        raise NotSupported("environment ships no gold trajectory")

    def invert_spec(self, task_id: str) -> Any:
        raise NotSupported("environment exposes no invertible success spec")

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        raise NotSupported("environment ships no known-wrong policy")

    def train_items(self) -> list[Item]:
        raise NotSupported("environment exposes no train split")

    def eval_items(self) -> list[Item]:
        raise NotSupported("environment exposes no eval split")

    def verifier_asserts(self, task_id: str) -> list[str]:
        raise NotSupported("verifier assertions are not machine-readable")

    def true_completion(self, transcript: Transcript) -> float:
        raise NotSupported("no ground-truth completion signal available")

    def describe(self) -> str:
        """Everything a careful human reviewer could read without executing
        anything: the manifest, the instructions, and the verifier's source
        where it can be obtained.

        The baselines get this. Handing them less than a person would have and
        then reporting that they found nothing would not be a fair comparison.
        """
        manifest = self.manifest()
        lines = [
            f"environment: {manifest.env_id}",
            f"ecosystem: {manifest.ecosystem}",
            f"declared capabilities: {sorted(c.value for c in manifest.capabilities)}",
            "",
            "tasks:",
        ]
        for task in manifest.tasks:
            lines.append(f"  - id: {task.task_id}")
            lines.append(f"    instruction: {task.instruction}")
            if task.metadata:
                lines.append(f"    metadata: {task.metadata}")
        return "\n".join(lines)

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        raise NotSupported("adapter defines no trivial policies for this environment")

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        raise NotSupported("adapter defines no quality-graded policies")


def close_adapter(adapter: object) -> None:
    """Release whatever an adapter is holding, if it holds anything.

    `close` is optional and deliberately not on `EnvAdapter`: only the three
    adapters that own a live resource (Harbor's sandbox session, OpenEnv's
    server, tau2's environment) define it, and requiring it of the rest would
    put a no-op on every pure-data adapter to satisfy a type checker.

    It is called through here rather than through `getattr` at each site so
    that the contract is written down in one place. `Probe`-visible behaviour
    is unchanged: an adapter with no `close` is not an error.
    """
    close = getattr(adapter, "close", None)
    if callable(close):
        close()


def run_policy(
    adapter: EnvAdapter,
    task_id: str,
    actions: list[Action],
    seed: int = 0,
    turn_cap: int = 64,
    stop_on_done: bool = True,
) -> Transcript:
    """Drive a scripted action list through the environment and record it.

    `stop_on_done=False` when REPLAYING a trajectory that was already recorded.
    The environment accepted all of those actions once; stopping early replays
    a different, shorter policy and measures that instead. That is not a
    hypothetical -- it is how a real two-step exploit came back scored as
    nothing at all.
    """
    adapter.reset(task_id, seed=seed)
    transcript = Transcript(task_id=task_id, seed=seed)
    for action in actions[:turn_cap]:
        result = adapter.step(action)
        transcript.record(action, result)
        if result.done and stop_on_done:
            break
    return transcript
