"""Family 5 -- is the answer recoverable from a part of the input that should
not determine it.

This is the partial-input baseline (Gururangan et al., N18-2017) ported from
NLP classification to environments. The method is not new; pointing it at an
environment's own splits, automatically, is.

Direction matters. A partial-input baseline that BEATS majority class is
strong evidence an artifact exists. The reverse does not hold -- a baseline
that fails to beat majority does not prove the full model is not exploiting
the same artifact (Misleading Failures of Partial-Input Baselines, P19-1554).
So this probe only ever reports a positive finding, never a clean bill.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ..adapter import EnvAdapter
from ..types import Capability, DefectClass, Finding, Item, DEFAULT_SEVERITY
from .base import Probe, register

#: How far above the majority-class rate a single part must predict before we
#: call it an artifact rather than noise.
MARGIN = 0.10


def _majority_rate(items: list[Item]) -> float:
    labels = [str(i.label) for i in items]
    if not labels:
        return 0.0
    return Counter(labels).most_common(1)[0][1] / len(labels)


def _part_accuracy(train: list[Item], evals: list[Item], part: str) -> float:
    """Fit value -> majority label on train, score on eval. No model, no LLM."""
    buckets: dict[str, Counter] = defaultdict(Counter)
    for item in train:
        value = item.parts.get(part)
        if value is not None:
            buckets[value][str(item.label)] += 1
    lookup = {v: c.most_common(1)[0][0] for v, c in buckets.items()}
    fallback = Counter(str(i.label) for i in train).most_common(1)[0][0] if train else None
    correct = sum(
        1
        for item in evals
        if lookup.get(item.parts.get(part, ""), fallback) == str(item.label)
    )
    return correct / len(evals) if evals else 0.0


@register
class PartialInputBaseline(Probe):
    family = "shortcut_leakage"
    name = "partial_input_baseline"
    requires = (Capability.SPLITS, Capability.ITEM_PARTS)

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        train, evals = adapter.train_items(), adapter.eval_items()
        if not train or not evals:
            return self.na("one of the splits is empty; nothing to compare")

        parts = sorted({p for item in train for p in item.parts})
        if not parts:
            return self.na("items declare no separable parts to hold out")

        majority = _majority_rate(evals)
        findings, per_part = [], {}
        for part in parts:
            acc = _part_accuracy(train, evals, part)
            per_part[part] = round(acc, 4)
            if acc >= majority + MARGIN:
                findings.append(
                    Finding(
                        defect=DefectClass.SHORTCUT_LEAK,
                        severity=DEFAULT_SEVERITY[DefectClass.SHORTCUT_LEAK],
                        task_id=None,
                        evidence={
                            "part": part,
                            "partial_input_accuracy": round(acc, 4),
                            "majority_class_rate": round(majority, 4),
                            "margin": MARGIN,
                            "note": f"'{part}' alone predicts the label; the task can be "
                            "solved without the signal it claims to measure",
                        },
                    )
                )
        return self.defects(
            findings,
            majority_class_rate=round(majority, 4),
            per_part_accuracy=per_part,
            asymmetry=(
                "A part beating majority is evidence of an artifact. A part failing to "
                "beat majority is not evidence of its absence."
            ),
        )
