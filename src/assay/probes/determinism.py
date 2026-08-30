"""Family 7 -- same seed, same result.

gymnasium's env_checker verifies that reset() accepts a seed. It does not
verify that seeding actually makes behaviour reproducible (Gymnasium #1084).
An environment that drifts between identical runs makes every comparison
between two policies partly noise.
"""

from __future__ import annotations

from typing import Any

from ..adapter import EnvAdapter, NotSupported, run_policy
from ..types import (
    SANDBOX_TIMEOUT,
    Action,
    Capability,
    DefectClass,
    Finding,
    DEFAULT_SEVERITY,
    digest,
)
from .base import Probe, register

REPEATS = 3


@register
class SeedDeterminism(Probe):
    """Reproducibility needs a seed, not a verifier.

    SEPARABLE_VERIFIER is deliberately NOT required. "Same seed, same episode"
    is answerable from the observations the environment hands back, and
    demanding a callable scorer would silence this probe on exactly the
    ecosystems most likely to fail it: OpenEnv computes reward inside step()
    and exposes no scorer at all, and its textarena_env accepts a seed on
    reset() and never passes it on. Where a scorer IS available its verdict is
    folded in too, because a run can be observationally identical and still
    score differently.
    """

    family = "determinism"
    name = "seed_determinism"
    requires = (Capability.SEEDED_RESET, Capability.LIVE_STEPPING)

    def _policy(self, adapter: EnvAdapter, task_id: str) -> list[Action]:
        """Gold first; failing that, an input-ignoring policy.

        The fallback matters more than it looks. Without it an environment
        shipping no gold trajectory was replayed with an EMPTY action list, so
        the probe fingerprinted an empty episode and passed whatever the
        environment did -- a check that could not fail.
        """
        try:
            return adapter.gold_actions(task_id)
        except NotSupported:
            pass
        try:
            policies = adapter.trivial_policies(task_id)
        except NotSupported:
            return []
        # The first declared policy that actually takes a turn. Adapters
        # declare them in a fixed order, so the choice is reproducible.
        return next((list(a) for a in policies.values() if a), [])

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        separable = adapter.manifest().has(Capability.SEPARABLE_VERIFIER)
        findings, detail = [], {}
        for task in adapter.manifest().tasks:
            actions = self._policy(adapter, task.task_id)
            fingerprints, timeouts = [], 0
            clear = getattr(adapter, "clear_cache", None)
            for _ in range(REPEATS):
                # A cached verification would answer with a memory rather than a
                # run, which is exactly what this probe must not accept.
                if clear:
                    clear()
                # The seed is consumed at reset, so what reset produced belongs
                # in the fingerprint. Leaving it out is how an environment that
                # redraws its hidden state every episode reads as deterministic.
                opening = adapter.reset(task.task_id, seed=1234)
                transcript = run_policy(adapter, task.task_id, actions, seed=1234)
                if any(o.code == SANDBOX_TIMEOUT for o in transcript.observations):
                    timeouts += 1
                payload = {
                    "reset": (opening.ok, opening.data),
                    "observations": [
                        (o.ok, o.data, o.code) for o in transcript.observations
                    ],
                }
                if separable:
                    score = adapter.verify(transcript)
                    payload["passed"] = score.passed
                    payload["reward"] = score.reward
                fingerprints.append(digest(payload))
            unique = sorted(set(fingerprints))
            detail[task.task_id] = {
                "repeats": REPEATS,
                "distinct_fingerprints": len(unique),
                "timed_out_repeats": timeouts,
            }
            if timeouts:
                # A repeat the harness abandoned is not a repeat that came back
                # different. Comparing it anyway reported NONDETERMINISM on
                # `harbor/broken-gold` in 1 of 6 full-corpus runs -- only under
                # the load of a full run, never on the harbor slice alone. An
                # inconclusive observation must not become a defect: that is the
                # same "absence of evidence read as evidence" this probe exists
                # to catch, happening inside it.
                detail[task.task_id]["inconclusive"] = (
                    f"{timeouts} of {REPEATS} repeats hit the sandbox wall clock, so "
                    "the observations cannot be compared. Not reported as "
                    "nondeterminism; re-run on a less loaded machine or raise the "
                    "sandbox wall_seconds."
                )
                continue
            if len(unique) > 1:
                findings.append(
                    Finding(
                        defect=DefectClass.NONDETERMINISM,
                        severity=DEFAULT_SEVERITY[DefectClass.NONDETERMINISM],
                        task_id=task.task_id,
                        evidence={
                            "seed": 1234,
                            "repeats": REPEATS,
                            "distinct_fingerprints": len(unique),
                            "fingerprints": [f[:16] for f in unique],
                        },
                    )
                )
        inconclusive = [k for k, v in detail.items() if "inconclusive" in v]
        if inconclusive and len(inconclusive) == len(detail):
            # Nothing could be compared on any task. PASS would be a claim this
            # probe did not earn, and it is the claim the whole project exists
            # to refuse: a check that could not run reported as a check that
            # passed.
            return self.na(
                "every task's repeats hit the sandbox wall clock, so no two runs "
                f"could be compared: {', '.join(sorted(inconclusive))}",
                per_task=detail,
            )
        return self.defects(findings, per_task=detail)
