"""Family 4 -- does this suite's own train split leak into its own eval split.

Distinct from the pretraining-contamination literature (LM Contamination
Index, GSM1k, LLM-Decontaminator), which asks whether an eval leaked into a
model's pretraining corpus. This asks a question that tooling exists for but
nobody points at environments: same generator, two seeds, and the "held-out"
set is a paraphrase of the training set.

Exact hashing alone cannot see a task that is the same template with one
field jittered, which is exactly the default failure mode -- hence MinHash.
"""

from __future__ import annotations

from typing import Any

from ..adapter import EnvAdapter
from ..minhash import estimated_jaccard, exact_signature, signature
from ..types import Capability, DefectClass, Finding, DEFAULT_SEVERITY
from .base import Probe, register

SHINGLE_SIZE = 5
NUM_PERM = 128
THRESHOLD = 0.8


@register
class Contamination(Probe):
    family = "contamination"
    name = "train_eval_leak"
    detects = (DefectClass.CONTAMINATION_EXACT, DefectClass.CONTAMINATION_NEARDUP)
    requires = (Capability.SPLITS,)

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        train = adapter.train_items()
        evals = adapter.eval_items()
        if not train or not evals:
            return self.na("one of the splits is empty; nothing to compare")

        findings: list[Finding] = []

        # exact
        train_exact = {}
        for item in train:
            train_exact.setdefault(exact_signature(item.text), item.item_id)
        exact_hits = [
            (e.item_id, train_exact[exact_signature(e.text)])
            for e in evals
            if exact_signature(e.text) in train_exact
        ]
        for eval_id, train_id in exact_hits:
            findings.append(
                Finding(
                    defect=DefectClass.CONTAMINATION_EXACT,
                    severity=DEFAULT_SEVERITY[DefectClass.CONTAMINATION_EXACT],
                    task_id=eval_id,
                    evidence={"train_item": train_id, "match": "exact content hash"},
                )
            )

        # near-duplicate
        train_sigs = [(i.item_id, signature(i.text, SHINGLE_SIZE, NUM_PERM)) for i in train]
        near_hits = []
        exact_eval_ids = {e for e, _ in exact_hits}
        for item in evals:
            if item.item_id in exact_eval_ids:
                continue  # already reported as the stronger defect
            sig = signature(item.text, SHINGLE_SIZE, NUM_PERM)
            best_id, best_j = None, 0.0
            for train_id, tsig in train_sigs:
                j = estimated_jaccard(sig, tsig)
                if j > best_j:
                    best_id, best_j = train_id, j
            if best_j >= THRESHOLD:
                near_hits.append((item.item_id, best_id, best_j))
                findings.append(
                    Finding(
                        defect=DefectClass.CONTAMINATION_NEARDUP,
                        severity=DEFAULT_SEVERITY[DefectClass.CONTAMINATION_NEARDUP],
                        task_id=item.item_id,
                        evidence={
                            "train_item": best_id,
                            "estimated_jaccard": round(best_j, 4),
                            "threshold": THRESHOLD,
                            "params": {"shingle_size": SHINGLE_SIZE, "num_perm": NUM_PERM},
                        },
                    )
                )

        detail = {
            "n_train": len(train),
            "n_eval": len(evals),
            "exact_overlap": len(exact_hits),
            "near_dup_count": len(near_hits),
            "near_dup_rate": round(len(near_hits) / len(evals), 4),
            "params": {
                "shingle_size": SHINGLE_SIZE,
                "num_perm": NUM_PERM,
                "threshold": THRESHOLD,
            },
            "bounds": (
                "This bounds contamination within this environment only. It says nothing "
                "about whether a third-party model saw similar data in pretraining."
            ),
        }
        return self.defects(findings, **detail)
