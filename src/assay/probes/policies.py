"""Families 2, 3, 8 -- what scripted policies reveal about an environment.

All three ask the same underlying question from different sides: does the
score respond to capability at all?

  trivial floor  a policy that ignores the input must not win
  separability   policies known to differ must not tie
  difficulty     tasks must sit in a band where learning is possible
"""

from __future__ import annotations

from typing import Any

from ..adapter import EnvAdapter, run_policy
from ..types import Capability, DefectClass, Finding, DEFAULT_SEVERITY
from .base import Probe, register


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _score_policies(adapter: EnvAdapter, task_id: str, policies: dict[str, list]) -> dict[str, float]:
    out: dict[str, float] = {}
    for label, actions in policies.items():
        transcript = run_policy(adapter, task_id, actions)
        out[label] = adapter.verify(transcript).reward
    return out


@register
class TrivialFloor(Probe):
    """A system that cannot beat 'escalate everything' has not earned its existence.

    Aggregated across the whole task set on purpose. Per task, a trivial policy
    wins wherever the trivial answer happens to be correct, which says nothing
    about the environment.
    """

    family = "trivial_floor"
    name = "trivial_floor"
    requires = (
        Capability.TRIVIAL_POLICIES,
        Capability.GRADED_POLICIES,
        Capability.SEPARABLE_VERIFIER,
        Capability.LIVE_STEPPING,
    )

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        tasks = adapter.manifest().tasks
        trivial_totals: dict[str, list[float]] = {}
        graded_totals: dict[str, list[float]] = {}
        for task in tasks:
            for label, reward in _score_policies(
                adapter, task.task_id, adapter.trivial_policies(task.task_id)
            ).items():
                trivial_totals.setdefault(label, []).append(reward)
            for label, reward in _score_policies(
                adapter, task.task_id, adapter.graded_policies(task.task_id)
            ).items():
                graded_totals.setdefault(label, []).append(reward)

        if not trivial_totals or not graded_totals:
            return self.na("environment defines no trivial or no graded policies")

        trivial = {k: _mean(v) for k, v in trivial_totals.items()}
        graded = {k: _mean(v) for k, v in graded_totals.items()}
        best_trivial_name = max(trivial, key=lambda k: trivial[k])
        best_trivial = trivial[best_trivial_name]
        best_real = max(graded.values())

        detail = {"mean_trivial": trivial, "mean_graded": graded, "n_tasks": len(tasks)}
        if best_trivial < best_real:
            return self.ok(**detail)
        return self.defect(
            DefectClass.TRIVIAL_FLOOR_BREACH,
            best_trivial_policy=best_trivial_name,
            best_trivial_reward=round(best_trivial, 4),
            best_real_reward=round(best_real, 4),
            n_tasks=len(tasks),
            note="a policy that ignores the input scores at least as well, averaged "
            "over the whole task set, as the best real one",
        )


@register
class Separability(Probe):
    """Arena-Hard's meta-metric: a benchmark that cannot distinguish systems
    known to differ is dead, however well-formed it is.

    Aggregated for the same reason as the trivial floor -- a single task tying
    is normal; the whole set tying is the defect.
    """

    family = "separability"
    name = "separability"
    requires = (
        Capability.GRADED_POLICIES,
        Capability.SEPARABLE_VERIFIER,
        Capability.LIVE_STEPPING,
    )

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        tasks = adapter.manifest().tasks
        totals: dict[str, list[float]] = {}
        order: list[str] = []
        for task in tasks:
            graded = adapter.graded_policies(task.task_id)
            order = list(graded.keys())  # declared best-first
            for label, reward in _score_policies(adapter, task.task_id, graded).items():
                totals.setdefault(label, []).append(reward)

        if len(totals) < 2:
            return self.na("fewer than two graded policies to separate")

        means = {k: _mean(v) for k, v in totals.items()}
        best, worst = means[order[0]], means[order[-1]]
        detail = {"declared_order_best_first": order, "mean_reward": means, "n_tasks": len(tasks)}
        if best > worst:
            return self.ok(**detail)
        return self.defect(
            DefectClass.SEPARABILITY_LOSS,
            declared_order_best_first=order,
            mean_reward={k: round(v, 4) for k, v in means.items()},
            note="the environment does not separate policies of known-differing quality",
        )


@register
class DifficultyBand(Probe):
    """Always-fail and always-pass tasks contribute noise, not learning.

    A solve rate is a property of an (environment, policy) PAIR, never of the
    environment alone. A task that is impossible for a 1.7B model may sit
    comfortably in band for a frontier one, so the source of the estimate is
    recorded in every finding and belongs in the card next to the number.
    Without an estimate this reports NOT_APPLICABLE rather than inventing one.
    """

    family = "difficulty_band"
    name = "difficulty_band"
    LOW, HIGH = 0.10, 0.80

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        rates: dict[str, float] | None = ctx.get("solve_rates")
        if not rates:
            return self.na(
                "no solve-rate estimate supplied; pass ctx['solve_rates'] from a rollout sampler"
            )
        source = ctx.get("solve_rate_source", "unspecified policy")
        findings = []
        for task in adapter.manifest().tasks:
            rate = rates.get(task.task_id)
            if rate is None:
                continue
            if rate > self.HIGH:
                findings.append(
                    Finding(
                        defect=DefectClass.DIFFICULTY_SATURATED,
                        severity=DEFAULT_SEVERITY[DefectClass.DIFFICULTY_SATURATED],
                        task_id=task.task_id,
                        evidence={
                            "solve_rate": rate,
                            "band": [self.LOW, self.HIGH],
                            "measured_with": source,
                            "note": "solve rate is relative to the policy that produced it",
                        },
                    )
                )
            elif rate < self.LOW:
                findings.append(
                    Finding(
                        defect=DefectClass.DIFFICULTY_IMPOSSIBLE,
                        severity=DEFAULT_SEVERITY[DefectClass.DIFFICULTY_IMPOSSIBLE],
                        task_id=task.task_id,
                        evidence={
                            "solve_rate": rate,
                            "band": [self.LOW, self.HIGH],
                            "measured_with": source,
                            "note": "solve rate is relative to the policy that produced it",
                        },
                    )
                )
        return self.defects(findings, solve_rates=rates, measured_with=source)
