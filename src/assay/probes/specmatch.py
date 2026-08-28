"""Family 6 -- does the verifier check what the instruction asked for.

This is the tau-bench bug class: gold actions that disagree with the task
spec, DB assertions that outlived the instruction they were written for.
75+ ad hoc fixes were applied across labs without anyone publishing a
systematic check.

Honest about its own precision. The rule is a content-word overlap test, not
semantic understanding, so it is tuned to surface candidates for human review
rather than to be believed unconditionally -- and the card says so. It is the
one family here whose findings are advisory.
"""

from __future__ import annotations

import re
from typing import Any

from ..adapter import EnvAdapter
from ..types import DefectClass, Finding, DEFAULT_SEVERITY
from .base import Probe, register

_WORD = re.compile(r"[a-z0-9_]+")

_STOP = {
    "the", "a", "an", "is", "are", "be", "to", "of", "and", "or", "in", "on",
    "for", "with", "that", "this", "it", "as", "at", "by", "from", "must",
    "should", "you", "your", "we", "if", "then", "not", "no", "any", "all",
    "each", "every", "into", "out", "up", "down", "has", "have", "was", "were",
    "check", "checks", "ensure", "verify", "assert", "value", "values",
}


def content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


@register
class SpecVerifierMatch(Probe):
    family = "spec_verifier_match"
    name = "assert_traceability"

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        findings, detail = [], {}
        for task in adapter.manifest().tasks:
            asserts = adapter.verifier_asserts(task.task_id)
            instruction = content_words(task.instruction)
            if not instruction:
                continue
            untraceable = []
            for claim in asserts:
                claim_words = content_words(claim)
                if claim_words and not (claim_words & instruction):
                    untraceable.append(claim)
            detail[task.task_id] = {
                "n_asserts": len(asserts),
                "n_untraceable": len(untraceable),
            }
            if untraceable:
                findings.append(
                    Finding(
                        defect=DefectClass.SPEC_VERIFIER_MISMATCH,
                        severity=DEFAULT_SEVERITY[DefectClass.SPEC_VERIFIER_MISMATCH],
                        task_id=task.task_id,
                        evidence={
                            "untraceable_asserts": untraceable,
                            "instruction": task.instruction,
                            "note": "the verifier requires something the instruction never asks "
                            "for; an agent following the instruction cannot pass",
                            "confidence": "advisory - lexical overlap heuristic, review by hand",
                        },
                    )
                )
        return self.defects(findings, per_task=detail, method="content-word overlap")
