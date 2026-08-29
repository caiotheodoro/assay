"""Baseline: the manual process people use today.

`gymnasium.utils.env_checker` and `stable_baselines3.common.env_checker` are
the only automated environment tooling in wide use. This arm reimplements what
they actually assert, against the adapter protocol:

  - the manifest is well formed and declares at least one task
  - reset() returns a well-formed observation
  - step() returns a StepResult with a boolean `done`
  - reward, when present, is a real number and not NaN or infinite
  - an unknown tool is rejected rather than silently accepted
  - **determinism**: the same seed and the same action produce the same
    observation

That last check was added after running the real thing. An earlier version of
this file omitted it, and an earlier version of the README claimed gymnasium
"does not even verify determinism across resets", citing Gymnasium #1084.

Both were wrong. `gymnasium.utils.env_checker` at 1.3.0 raises
`AssertionError: Deterministic step observations are not equivalent for the
same seed and action` on an environment that accepts a seed and ignores it --
measured in `scripts/real_check_env.py`, not assumed. Benchmarking against a
strawman weaker than the real tool would have inflated every number that
follows from this arm.

`stable_baselines3.common.env_checker` at 2.9.0 passes that same environment
without comment, so the two incumbents differ and this arm models the stronger.

What remains true is the shape of the ceiling: on five API-correct environments
carrying four planted defects, the real checkers detect one -- determinism --
and are silent on a verifier that pays full reward at reset, on a constant
action that beats every other, and on a score that comes apart from the task.
Those are checks about whether an environment will crash a trainer, not about
whether it measures anything.
"""

from __future__ import annotations

import math
from typing import Any

from ..adapter import EnvAdapter
from ..types import Action, DefectClass, canonical_json


class StructuralCheckArm:
    arm = "check_env"

    def run(self, adapter: EnvAdapter) -> tuple[frozenset[DefectClass], list[str]]:
        issues: list[str] = []
        manifest = adapter.manifest()

        if not manifest.tasks:
            issues.append("manifest declares no tasks")
        if not manifest.env_id:
            issues.append("manifest has no env_id")

        for task in manifest.tasks:
            obs = adapter.reset(task.task_id, seed=0)
            if not hasattr(obs, "ok") or not isinstance(obs.ok, bool):
                issues.append(f"{task.task_id}: reset() did not return a well-formed observation")

            result = adapter.step(Action("__assay_unknown_tool__", {}))
            if not isinstance(result.done, bool):
                issues.append(f"{task.task_id}: step().done is not a bool")
            if result.observation.ok:
                issues.append(f"{task.task_id}: unknown tool was accepted")
            if result.reward is not None and (
                math.isnan(result.reward) or math.isinf(result.reward)
            ):
                issues.append(f"{task.task_id}: step() reward is NaN or infinite")

        # Determinism, because the real gymnasium checker does check it: same
        # seed, same action, same observation. It has to be a REAL action --
        # stepping an unknown tool gets the same rejection every time, which
        # looks perfectly deterministic while executing nothing.
        detected: set[DefectClass] = set()
        for task in manifest.tasks:
            try:
                policies = adapter.trivial_policies(task.task_id)
            except Exception:  # noqa: BLE001 - no policies means nothing to step
                continue
            action = next(
                (a[0] for a in policies.values() if a), None
            )
            if action is None:
                continue
            fingerprints = set()
            for _ in range(2):
                adapter.reset(task.task_id, seed=1234)
                result = adapter.step(action)
                fingerprints.add(
                    canonical_json(
                        {"ok": result.observation.ok, "data": result.observation.data}
                    )
                )
            if len(fingerprints) > 1:
                detected.add(DefectClass.NONDETERMINISM)
                issues.append(f"{task.task_id}: same seed, different observation")

        # Everything else the incumbent asserts is about whether the environment
        # will crash a trainer, not about whether it measures anything. That is
        # the finding, not an omission.
        return frozenset(detected), issues
