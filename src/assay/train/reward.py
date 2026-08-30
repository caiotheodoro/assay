"""The reward the Challenger is trained on: score it was given minus job done.

    reward = environment's reported score - independent true completion

Dense, not binary. A binary "did it hack" signal is flat almost everywhere at
low capability -- a 1.7B model that has never emitted a valid tool call gets
the same zero for a near-miss as for gibberish, and GRPO's group-relative
advantage is exactly zero whenever a group all scores the same. The gap is
graded, so partial credit the environment hands out for work that was not done
shows up as partial reward.

Three things make this honest rather than circular:

1. It is computed HERE, by the harness, from the environment's own scorer and
   an independent verifier the attacker cannot reach. The policy is handed a
   scalar and never the two terms it came from.
2. The policy is REPLAYED before it is measured. On a stateful environment,
   scoring a transcript recorded earlier scores whatever the last policy left
   behind. `assay.probes.hackability.exploit_gap` does the replay; this module
   defers to it rather than keeping a second copy of that reasoning.
3. Solving the task honestly pays ZERO, not one. reported 1.0 minus completed
   1.0 is nothing. The only way to earn reward is credit that was not earned.

An environment that cannot supply an independent ground-truth signal cannot
appear in this reward at all -- not with a guess, not with the environment's
own score standing in for truth. `trainable_environments` filters on the
declared capability and reports every exclusion with its reason.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..adapter import EnvAdapter, close_adapter
from ..challenger.grpo import MAX_ACTIONS, parse_policy, policy_digest
from ..probes.hackability import exploit_gap
from ..types import Capability, Transcript

#: Paid when the completion contains no decodable policy. Strictly below the
#: worst score any executable policy can earn (a policy can lose at most 1.0 by
#: doing the job and being under-credited for it), so format is learned before
#: anything else and emitting nothing is never the safe option.
PARSE_PENALTY = -1.5

#: Paid when a syntactically fine policy blew up the environment. Kept distinct
#: from PARSE_PENALTY so the run log can say which of the two a step was made
#: of; a training run drowning in harness errors is a different failure from one
#: drowning in malformed JSON, and averaging them together hides both.
ERROR_PENALTY = -1.5

#: Capabilities without which an environment cannot contribute to this reward.
REQUIRED = (Capability.TRUE_COMPLETION, Capability.SEPARABLE_VERIFIER)


@dataclass
class RewardBreakdown:
    """Every term behind one scalar, so a run can be audited after the fact."""

    reward: float
    parsed: bool
    n_actions: int = 0
    reported: float | None = None
    completed: float | None = None
    gap: float | None = None
    policy: str = ""
    reason: str = "ok"

    def as_row(self, **extra: Any) -> dict[str, Any]:
        return {**asdict(self), **extra}


def _completion_text(completion: Any) -> str:
    """TRL hands back either a string or a list of chat messages depending on
    the dataset shape and the version. Normalising here means the reward does
    not silently score the repr of a list."""
    if isinstance(completion, str):
        return completion
    if not isinstance(completion, list):
        return str(completion)
    parts: list[str] = []
    for msg in completion:
        if isinstance(msg, str):
            parts.append(msg)
            continue
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    parts.append(part.get("text") or "")
    return "".join(parts)


def policy_reward(
    adapter: EnvAdapter,
    task_id: str,
    completion: Any,
    *,
    max_actions: int = MAX_ACTIONS,
) -> RewardBreakdown:
    """One completion -> one reward, with the arithmetic kept alongside it."""
    text = _completion_text(completion)
    actions = parse_policy(text, max_actions)
    if actions is None:
        return RewardBreakdown(
            reward=PARSE_PENALTY, parsed=False, reason="no decodable policy in completion"
        )

    transcript = Transcript(task_id=task_id, seed=0, actions=list(actions))
    try:
        gap, reported, completed = exploit_gap(adapter, transcript)
    except Exception as exc:  # noqa: BLE001 - a broken policy must not end the run
        return RewardBreakdown(
            reward=ERROR_PENALTY,
            parsed=True,
            n_actions=len(actions),
            policy=policy_digest(actions),
            reason=f"{type(exc).__name__}: {exc}",
        )

    return RewardBreakdown(
        reward=float(gap),
        parsed=True,
        n_actions=len(actions),
        reported=float(reported),
        completed=float(completed),
        gap=float(gap),
        policy=policy_digest(actions),
    )


# --------------------------------------------------------------------------
# Environment pool
# --------------------------------------------------------------------------


@dataclass
class EnvPool:
    """One live adapter per env_id, built once and reused.

    Harbor adapters hold a container open for the whole suite. Rebuilding one
    per reward call would spend the entire training budget on `docker run`.
    """

    factories: dict[str, Callable[[], EnvAdapter]]
    _live: dict[str, EnvAdapter] = field(default_factory=dict, init=False)

    def get(self, env_id: str) -> EnvAdapter:
        if env_id not in self._live:
            self._live[env_id] = self.factories[env_id]()
        return self._live[env_id]

    def env_ids(self) -> list[str]:
        return sorted(self.factories)

    def close(self) -> None:
        """Close every adapter, even if one of them refuses to.

        This used to abort on the first exception, which stranded every
        remaining container in the pool -- the signature is a cluster of
        orphans all sharing one dead pid. Teardown must never let one failure
        prevent the rest of teardown.
        """
        live, self._live = dict(self._live), {}
        for adapter in live.values():
            try:
                close_adapter(adapter)
            except Exception:  # noqa: BLE001 - teardown never blocks teardown
                pass

    def __enter__(self) -> "EnvPool":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


@dataclass(frozen=True)
class EnvSelection:
    pool: EnvPool
    #: env_id -> why it cannot be trained against. Never dropped in silence.
    excluded: dict[str, str]
    #: ecosystem -> why its whole provider could not load here.
    unavailable: dict[str, str]

    def report(self) -> str:
        lines = [f"trainable environments ({len(self.pool.factories)}):"]
        lines += [f"  + {env_id}" for env_id in self.pool.env_ids()]
        if self.excluded:
            lines.append("excluded, with reason:")
            lines += [f"  - {env_id}: {why}" for env_id, why in sorted(self.excluded.items())]
        if self.unavailable:
            lines.append("ecosystems unavailable here:")
            lines += [f"  ! {name}: {why}" for name, why in sorted(self.unavailable.items())]
        return "\n".join(lines)


def trainable_environments(
    only: list[str] | None = None,
    skip: list[str] | None = None,
    holdout: list[str] | None = None,
) -> EnvSelection:
    """Corpus environments that can supply an independent ground-truth signal.

    `only`/`skip` select ecosystems; `holdout` drops individual environments by
    env_id. The holdout exists because every environment in this corpus is also
    something Assay is scored on: training on `harbor/self-graded` and then
    reporting that the trained Challenger cracks `harbor/self-graded` would be
    train-on-test, and the number would mean nothing.

    This is where "deliberately not OpenEnv" is enforced as a rule rather than
    a hard-coded list: an ecosystem that cannot say what the policy actually
    accomplished is excluded by the capability it declines to declare. Training
    against its own reported score would make the reward `score - score`, which
    is identically zero, and a reward that is always zero is not a weak
    training signal, it is no training signal at all.
    """
    from .. import corpus

    factories: dict[str, Callable[[], EnvAdapter]] = {}
    excluded: dict[str, str] = {}
    held = set(holdout or ())
    for env_id, factory, _defects in corpus.entries(only=only, skip=skip):
        if env_id in held:
            excluded[env_id] = "held out of training so the ablation is not train-on-test"
            continue
        try:
            adapter = factory()
        except Exception as exc:  # noqa: BLE001
            excluded[env_id] = f"could not be constructed: {type(exc).__name__}: {exc}"
            continue
        missing = [c for c in REQUIRED if not adapter.manifest().has(c)]
        close_adapter(adapter)
        if missing:
            excluded[env_id] = "does not declare " + ", ".join(c.value for c in missing)
            continue
        factories[env_id] = factory
    return EnvSelection(
        pool=EnvPool(factories), excluded=excluded, unavailable=corpus.unavailable()
    )


# --------------------------------------------------------------------------
# TRL reward_funcs callable
# --------------------------------------------------------------------------


def make_reward_func(
    pool: EnvPool,
    *,
    max_actions: int = MAX_ACTIONS,
    log_path: str | Path | None = None,
    name: str = "exploit_gap",
) -> Callable[..., list[float]]:
    """Build the callable TRL's `GRPOTrainer(reward_funcs=...)` expects.

    TRL passes every non-`prompt` dataset column through as a parallel list, so
    `env_id` and `task_id` arrive alongside the completions. That is what lets
    one training run span several environments without the policy ever being
    told which environment it is attacking.
    """
    handle = None
    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")

    state = {"calls": 0}

    def reward_func(
        completions: list[Any],
        env_id: list[str] | None = None,
        task_id: list[str] | None = None,
        **kwargs: Any,
    ) -> list[float]:
        if env_id is None or task_id is None:
            raise ValueError(
                "the dataset must carry env_id and task_id columns; without them "
                "a completion cannot be replayed and no reward can be computed"
            )
        state["calls"] += 1
        out: list[float] = []
        for i, completion in enumerate(completions):
            eid, tid = env_id[i], task_id[i]
            breakdown = policy_reward(
                pool.get(eid), tid, completion, max_actions=max_actions
            )
            out.append(breakdown.reward)
            if handle is not None:
                handle.write(
                    json.dumps(
                        breakdown.as_row(
                            call=state["calls"],
                            env_id=eid,
                            task_id=tid,
                            completion=_completion_text(completion)[:600],
                        )
                    )
                    + "\n"
                )
        if handle is not None:
            handle.flush()
        return out

    reward_func.__name__ = name  # TRL logs one reward column per func name
    return reward_func


#: Convenience for a caller that just wants the whole trainable corpus.
_DEFAULT: dict[str, Any] = {}


def exploit_gap_reward_func(completions: list[Any], **kwargs: Any) -> list[float]:
    """Module-level TRL reward func over every trainable corpus environment."""
    if "func" not in _DEFAULT:
        selection = trainable_environments()
        print(selection.report(), flush=True)
        _DEFAULT["selection"] = selection
        _DEFAULT["func"] = make_reward_func(selection.pool)
    return _DEFAULT["func"](completions, **kwargs)

