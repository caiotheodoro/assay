"""Family 7 -- same seed, same result.

gymnasium's env_checker verifies that reset() accepts a seed. It does not
verify that seeding actually makes behaviour reproducible (Gymnasium #1084).
An environment that drifts between identical runs makes every comparison
between two policies partly noise.
"""

from __future__ import annotations

from typing import Any

from ..adapter import EnvAdapter, NotSupported, run_policy
from ..types import Action, Capability, DefectClass, Finding, DEFAULT_SEVERITY, digest
from .base import Probe, register

REPEATS = 3


@register
class SeedDeterminism(Probe):
    family = "determinism"
    name = "seed_determinism"
    requires = (Capability.SEEDED_RESET, Capability.SEPARABLE_VERIFIER)

    def _policy(self, adapter: EnvAdapter, task_id: str) -> list[Action]:
        try:
            return adapter.gold_actions(task_id)
        except NotSupported:
            return []

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        findings, detail = [], {}
        for task in adapter.manifest().tasks:
            actions = self._policy(adapter, task.task_id)
            fingerprints = []
            for _ in range(REPEATS):
                transcript = run_policy(adapter, task.task_id, actions, seed=1234)
                score = adapter.verify(transcript)
                fingerprints.append(
                    digest(
                        {
                            "observations": [
                                (o.ok, o.data, o.code) for o in transcript.observations
                            ],
                            "passed": score.passed,
                            "reward": score.reward,
                        }
                    )
                )
            unique = sorted(set(fingerprints))
            detail[task.task_id] = {"repeats": REPEATS, "distinct_fingerprints": len(unique)}
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
        return self.defects(findings, per_task=detail)
