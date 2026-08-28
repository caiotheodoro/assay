"""The adapter protocol -- the smallest surface that makes the probes possible.

An adapter translates one ecosystem (inspect_ai, Harbor, OpenEnv) into this
shape. The load-bearing design decision is that `verify` is separable from
`step`: a probe must be able to score a transcript, or an inverted spec,
without driving a live episode. Environments that entangle the two are
auditable only by expensive black-box probing, and their adapters say so by
withholding Capability.SEPARABLE_VERIFIER.
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

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        raise NotSupported("adapter defines no trivial policies for this environment")

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        raise NotSupported("adapter defines no quality-graded policies")


def run_policy(
    adapter: EnvAdapter,
    task_id: str,
    actions: list[Action],
    seed: int = 0,
    turn_cap: int = 64,
) -> Transcript:
    """Drive a scripted action list through the environment and record it."""
    adapter.reset(task_id, seed=seed)
    transcript = Transcript(task_id=task_id, seed=seed)
    for action in actions[:turn_cap]:
        result = adapter.step(action)
        transcript.record(action, result)
        if result.done:
            break
    return transcript
