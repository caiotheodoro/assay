"""Baseline: the manual process people use today.

`gymnasium.utils.env_checker` and `stable_baselines3.common.env_checker` are
the only automated environment tooling in wide use. This arm reimplements what
they actually assert, against the adapter protocol:

  - the manifest is well formed and declares at least one task
  - reset() returns a well-formed observation
  - step() returns a StepResult with a boolean `done`
  - reward, when present, is a real number and not NaN or infinite
  - an unknown tool is rejected rather than silently accepted

That is the complete list. Every check is about whether the environment will
crash a trainer. None of them is about whether it measures anything. Included
as a baseline precisely so the ceiling of the incumbent approach is visible
rather than asserted.
"""

from __future__ import annotations

import math
from typing import Any

from ..adapter import EnvAdapter
from ..types import Action, DefectClass


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

        # Deliberately empty. None of the above maps onto a validity defect --
        # that is the finding, not an omission.
        return frozenset(), issues
