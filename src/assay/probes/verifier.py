"""Family 1 -- verifier integrity.

Four questions, in order of how badly a "no" invalidates the environment:

  gold        must PASS         else the task may be unsolvable as specified
  no-op       must FAIL         else the task is already solved at reset
  inverted    must FAIL         else the eval cannot fail at all
  known-wrong must FAIL         else the oracle rubber-stamps
                                (SWE-bench: 7.8% of "passing" patches wrong)
"""

from __future__ import annotations

from typing import Any

from ..adapter import EnvAdapter, run_policy
from ..types import Capability, DefectClass, Finding, Transcript, DEFAULT_SEVERITY
from .base import Probe, register

FAMILY = "verifier_integrity"


@register
class GoldPasses(Probe):
    family = FAMILY
    name = "gold_passes"
    detects = (DefectClass.GOLD_FAILS,)
    requires = (
        Capability.GOLD_TRAJECTORY,
        Capability.SEPARABLE_VERIFIER,
        Capability.LIVE_STEPPING,
    )

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        findings, detail = [], {}
        for task in adapter.manifest().tasks:
            actions = adapter.gold_actions(task.task_id)
            transcript = run_policy(adapter, task.task_id, actions)
            score = adapter.verify(transcript)
            detail[task.task_id] = {"passed": score.passed, "reward": score.reward}
            if not score.passed:
                findings.append(
                    Finding(
                        defect=DefectClass.GOLD_FAILS,
                        severity=DEFAULT_SEVERITY[DefectClass.GOLD_FAILS],
                        task_id=task.task_id,
                        evidence={
                            "gold_actions": [a.tool for a in actions],
                            "reward": score.reward,
                            "profile": score.profile,
                        },
                    )
                )
        return self.defects(findings, per_task=detail)


@register
class NoopFails(Probe):
    family = FAMILY
    name = "noop_fails"
    detects = (DefectClass.NOOP_PASSES,)
    requires = (Capability.SEPARABLE_VERIFIER, Capability.LIVE_STEPPING)

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        findings, detail = [], {}
        for task in adapter.manifest().tasks:
            adapter.reset(task.task_id, seed=0)
            transcript = Transcript(task_id=task.task_id, seed=0)
            score = adapter.verify(transcript)
            detail[task.task_id] = {"passed": score.passed, "reward": score.reward}
            if score.passed:
                findings.append(
                    Finding(
                        defect=DefectClass.NOOP_PASSES,
                        severity=DEFAULT_SEVERITY[DefectClass.NOOP_PASSES],
                        task_id=task.task_id,
                        evidence={
                            "note": "task is already solved at reset; it measures nothing",
                            "reward": score.reward,
                        },
                    )
                )
        return self.defects(findings, per_task=detail)


@register
class InvertedFails(Probe):
    family = FAMILY
    name = "inverted_fails"
    detects = (DefectClass.INVERT_PASSES,)
    requires = (
        Capability.GOLD_TRAJECTORY,
        Capability.INVERTIBLE_SPEC,
        Capability.SEPARABLE_VERIFIER,
        Capability.LIVE_STEPPING,
    )

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        findings, detail = [], {}
        for task in adapter.manifest().tasks:
            actions = adapter.gold_actions(task.task_id)
            transcript = run_policy(adapter, task.task_id, actions)
            shadow = adapter.invert_spec(task.task_id)
            score = adapter.verify(transcript, spec=shadow)
            detail[task.task_id] = {"passed": score.passed, "reward": score.reward}
            if score.passed:
                findings.append(
                    Finding(
                        defect=DefectClass.INVERT_PASSES,
                        severity=DEFAULT_SEVERITY[DefectClass.INVERT_PASSES],
                        task_id=task.task_id,
                        evidence={
                            "note": (
                                "gold passes even against an inverted success spec: "
                                "the verifier cannot fail, so no score from it means anything"
                            ),
                            "reward": score.reward,
                        },
                    )
                )
        return self.defects(findings, per_task=detail)


@register
class KnownWrongFails(Probe):
    family = FAMILY
    name = "known_wrong_fails"
    detects = (DefectClass.KNOWN_WRONG_PASSES,)
    requires = (
        Capability.KNOWN_WRONG,
        Capability.SEPARABLE_VERIFIER,
        Capability.LIVE_STEPPING,
    )

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        findings, detail = [], {}
        for task in adapter.manifest().tasks:
            actions = adapter.known_wrong_actions(task.task_id)
            transcript = run_policy(adapter, task.task_id, actions)
            score = adapter.verify(transcript)
            detail[task.task_id] = {"passed": score.passed, "reward": score.reward}
            if score.passed:
                findings.append(
                    Finding(
                        defect=DefectClass.KNOWN_WRONG_PASSES,
                        severity=DEFAULT_SEVERITY[DefectClass.KNOWN_WRONG_PASSES],
                        task_id=task.task_id,
                        evidence={
                            "note": "a policy known to be wrong was accepted: weak oracle",
                            "known_wrong_actions": [a.tool for a in actions],
                            "reward": score.reward,
                        },
                    )
                )
        return self.defects(findings, per_task=detail)
