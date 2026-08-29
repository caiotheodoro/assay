"""Score Assay against 62 human-confirmed tau-bench defects.

    uv run --extra tau2 python scripts/tau2_fetch.py
    uv run --extra tau2 python scripts/tau2_recall.py

Runs the whole probe battery against the *pre-fix* tau2 retail and airline task
sets, treats every task that `amazon-agi/tau2-bench-verified` changed as a
labelled positive and every task it left alone as a negative, and reports
recall per defect category.

Three things this script deliberately does not do.

It does not tune anything against the labels. The adapter, the probes and the
policy oracle never read the verified task set; this script is the only place
the two revisions meet.

It does not report a single number. Recall over all 62 positives hides the
result that matters -- which categories Assay is structurally blind to -- so
the per-category table is the output and the aggregate is a footnote.

It does not stop at the pre-fix run. The same battery is run against the
*post-fix* task set as a control. A probe that still fires on a task after the
defect was fixed is either finding something the fix did not address or is
wrong, and either way the reader should see it.
"""

from __future__ import annotations

import json
from math import comb
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.adapters.tau2 import Tau2Adapter, available  # noqa: E402
from assay.runner import AuditReport, audit  # noqa: E402
from assay.tau2_truth import (  # noqa: E402
    BASE_REPO,
    BASE_REV,
    CATEGORIES,
    DOMAINS,
    MECHANICAL_CATEGORIES,
    VERIFIED_REPO,
    VERIFIED_REV,
    ground_truth,
)
from assay.types import canonical_json  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "results" / "tau2_recall.json"

#: The one probe whose own docstring calls its findings advisory.
ADVISORY = "assert_traceability"


def flagged(report: AuditReport) -> dict[str, list[dict]]:
    """task id -> the findings that name it."""
    out: dict[str, list[dict]] = defaultdict(list)
    for result in report.results:
        for finding in result.findings:
            if finding.task_id is None:
                continue
            out[finding.task_id].append(
                {"probe": result.probe, "defect": finding.defect.value}
            )
    return dict(out)


def confusion(labels: dict, predicted: set[str]) -> dict[str, int]:
    tp = sum(1 for tid, lab in labels.items() if lab.defective and tid in predicted)
    fp = sum(1 for tid, lab in labels.items() if not lab.defective and tid in predicted)
    fn = sum(1 for tid, lab in labels.items() if lab.defective and tid not in predicted)
    tn = sum(1 for tid, lab in labels.items() if not lab.defective and tid not in predicted)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def rates(cm: dict[str, int]) -> dict[str, float | None]:
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    return {
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
    }


def significance(cm: dict[str, int]) -> dict:
    """Hold the auditor to the trivial-floor rule it applies to environments.

    `metrics.py`: "if it cannot beat the best policy that ignores its input, it
    has not earned its existence." On the planted corpus that floor is
    `flag_everything`. Here it is a flagger that picks the same number of tasks
    uniformly at random, which is what a recall number has to beat before it is
    evidence of anything. The p-value is exact -- hypergeometric, no normal
    approximation, no sampling.
    """
    tp, fp, fn, tn = cm["tp"], cm["fp"], cm["fn"], cm["tn"]
    n_tasks, n_pos, n_flagged = tp + fp + fn + tn, tp + fn, tp + fp
    p = sum(
        comb(n_pos, i) * comb(n_tasks - n_pos, n_flagged - i)
        for i in range(tp, min(n_pos, n_flagged) + 1)
    ) / comb(n_tasks, n_flagged)
    return {
        "n_tasks": n_tasks,
        "n_positives": n_pos,
        "n_flagged": n_flagged,
        "base_rate": round(n_pos / n_tasks, 4),
        "expected_tp_if_flagged_at_random": round(n_flagged * n_pos / n_tasks, 2),
        "observed_tp": tp,
        "random_recall_at_same_flag_rate": round(n_flagged / n_tasks, 4),
        "p_one_sided": round(p, 4),
        "beats_random_at_0.05": bool(p < 0.05),
    }


def trivial_floor(cm: dict[str, int]) -> dict:
    """flag_everything, the same floor the planted corpus reports.

    Derived from any confusion matrix over the same task set: flagging every
    task moves the whole negative column into false positives.
    """
    n_pos, n_neg = cm["tp"] + cm["fn"], cm["fp"] + cm["tn"]
    every = {"tp": n_pos, "fp": n_neg, "fn": 0, "tn": 0}
    return {"arm": "flag_everything", "confusion": every, "rates": rates(every)}


def per_category(labels: dict, predicted: set[str], key: str, names) -> dict:
    out = {}
    for name in names:
        members = [tid for tid, lab in labels.items() if lab.defective and getattr(lab, key) == name]
        if not members:
            continue
        hit = [tid for tid in members if tid in predicted]
        out[name] = {
            "n_positives": len(members),
            "n_detected": len(hit),
            "recall": round(len(hit) / len(members), 4),
            "missed": sorted(set(members) - set(hit), key=lambda t: int(t)),
        }
    return out


def run_domain(domain: str) -> dict:
    labels = ground_truth(domain)
    adapter = Tau2Adapter(domain, task_set="base")

    started = time.time()
    report = audit(adapter)
    elapsed = round(time.time() - started, 1)

    hits = flagged(report)
    predicted = set(hits)
    cm = confusion(labels, predicted)

    # `assert_traceability` describes itself as advisory: it is a content-word
    # overlap test, not semantic understanding. It is in the headline because it
    # is in the report Assay actually emits -- but a reader deciding whether to
    # trust a finding wants the number without it too, so both are published.
    strict = {tid for tid, fs in hits.items() if any(f["probe"] != ADVISORY for f in fs)}
    cm_strict = confusion(labels, strict)

    # Which probe is doing the work, and on which side of the ledger.
    by_probe: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0})
    for tid, findings in hits.items():
        side = "tp" if labels[tid].defective else "fp"
        for probe in {f["probe"] for f in findings}:
            by_probe[probe][side] += 1

    # Recall if a single probe family were the only detector. Reported because
    # a family that adds nothing but false positives should be visible as such.
    per_probe_alone = {}
    for probe in sorted(by_probe):
        only = {tid for tid, fs in hits.items() if any(f["probe"] == probe for f in fs)}
        per_probe_alone[probe] = rates(confusion(labels, only)) | confusion(labels, only)

    rule_fires: Counter = Counter()
    rule_tasks: dict[str, list[str]] = defaultdict(list)
    for tid in labels:
        for violation in adapter.policy_violations(tid):
            rule_fires[violation.rule] += 1
            if tid not in rule_tasks[violation.rule]:
                rule_tasks[violation.rule].append(tid)

    control = run_control(domain, labels, predicted)
    adapter.close()

    return {
        "domain": domain,
        "n_tasks": len(labels),
        "n_positives": sum(1 for lab in labels.values() if lab.defective),
        "audit_seconds": elapsed,
        "verdict": report.verdict,
        "coverage": report.coverage,
        "probes": [
            {
                "family": r.family,
                "probe": r.probe,
                "status": r.status.value,
                "reason": r.reason,
                "n_findings": len(r.findings),
            }
            for r in report.results
        ],
        "confusion": cm,
        "rates": rates(cm),
        "confusion_excluding_advisory_probe": cm_strict,
        "rates_excluding_advisory_probe": rates(cm_strict),
        "recall_by_category": per_category(labels, predicted, "category", CATEGORIES),
        "recall_by_category_excluding_advisory_probe": per_category(
            labels, strict, "category", CATEGORIES
        ),
        "recall_by_mechanical_category": per_category(
            labels, predicted, "mechanical", MECHANICAL_CATEGORIES
        ),
        "by_probe": {k: dict(v) for k, v in sorted(by_probe.items())},
        "each_probe_alone": per_probe_alone,
        "policy_rule_fires": {
            rule: {"n_violations": n, "tasks": sorted(rule_tasks[rule], key=int)}
            for rule, n in sorted(rule_fires.items())
        },
        "false_positives": sorted(
            (tid for tid in predicted if not labels[tid].defective), key=int
        ),
        "false_negatives": sorted(
            (tid for tid, lab in labels.items() if lab.defective and tid not in predicted),
            key=int,
        ),
        "control_post_fix": control,
    }


def run_control(domain: str, labels: dict, predicted_pre: set[str]) -> dict:
    """The same battery against the corrected task set.

    A true positive that survives the fix means Assay is flagging something
    other than what was fixed. Counting those as detections would inflate
    recall with coincidences.
    """
    adapter = Tau2Adapter(domain, task_set="verified")
    report = audit(adapter)
    predicted_post = set(flagged(report))
    # The sharpest of these: a corrected gold answer that the domain's own
    # tools refuse to execute. Recorded separately because it is a claim about
    # tau2-bench-verified rather than about tau2-bench, and a reader will want
    # to check it first.
    unexecutable = sorted(
        {
            f.task_id
            for r in report.results
            for f in r.findings
            if f.defect.value == "GOLD_FAILS" and f.task_id is not None
        },
        key=int,
    )
    adapter.close()
    tp_pre = {tid for tid in predicted_pre if labels[tid].defective}
    still = sorted(tp_pre & predicted_post, key=int)
    return {
        "n_flagged_post_fix": len(predicted_post),
        "true_positives_that_survive_the_fix": still,
        "n_true_positives_cleared_by_the_fix": len(tp_pre) - len(still),
        "post_fix_gold_answers_the_tools_refuse": unexecutable,
        "note": (
            "A finding on a task that is still flagged after the fix was not resolved "
            "by that fix. Reported, not subtracted -- both readings are defensible and "
            "hiding the count is not."
        ),
    }


def main() -> int:
    if not available():
        print(
            "tau2 snapshots are not in the cache. Run:\n"
            "    uv run --extra tau2 python scripts/tau2_fetch.py",
            file=sys.stderr,
        )
        return 2

    domains = [run_domain(d) for d in DOMAINS]

    total, total_strict = Counter(), Counter()
    for row in domains:
        total.update(row["confusion"])
        total_strict.update(row["confusion_excluding_advisory_probe"])
    combined, combined_strict = dict(total), dict(total_strict)

    merged_cat: dict[str, dict] = {}
    for row in domains:
        for name, stats in row["recall_by_category"].items():
            acc = merged_cat.setdefault(
                name, {"n_positives": 0, "n_detected": 0, "missed": []}
            )
            acc["n_positives"] += stats["n_positives"]
            acc["n_detected"] += stats["n_detected"]
            acc["missed"] += [f"{row['domain']}/{t}" for t in stats["missed"]]
    for stats in merged_cat.values():
        stats["recall"] = round(stats["n_detected"] / stats["n_positives"], 4)

    payload = {
        "measurement": "assay recall against third-party-confirmed tau-bench defects",
        "pre_fix": {"repo": BASE_REPO, "rev": BASE_REV},
        "post_fix": {"repo": VERIFIED_REPO, "rev": VERIFIED_REV},
        "label_rule": (
            "A task is a positive iff its record differs between the two pinned "
            "revisions. SCHEMA_ONLY_FIELDS is applied but excludes nothing: the "
            "field it names is absent from both revisions, and recomputing the diff "
            "with no exclusion at all gives the same 62. Categories come from "
            "FIXES.md, attached to a task only when a "
            "quoted before/after excerpt is found verbatim in both revisions of it."
        ),
        "not_measured": [
            "nl_assertions -- tau2 scores them with an LLM judge and Assay scores "
            "nothing with a judge, so every task's NL conjunct is absent, not passed",
            "difficulty band -- needs a solve-rate estimate, which needs a model",
            "reward hackability -- needs a completion signal independent of tau2's own "
            "scorer, which tau2 does not expose",
            "contamination and shortcut leakage -- tau2 ships one split and no item "
            "parts",
        ],
        "trivial_floor": trivial_floor(combined),
        "combined": {
            "confusion": combined,
            "rates": rates(combined),
            "significance": significance(combined),
        },
        "combined_excluding_advisory_probe": {
            "confusion": combined_strict,
            "rates": rates(combined_strict),
            "significance": significance(combined_strict),
            "note": (
                "assert_traceability removed. Its own docstring calls its findings "
                "advisory -- a content-word overlap heuristic tuned to surface "
                "candidates for a human, not to be believed."
            ),
        },
        "combined_recall_by_category": merged_cat,
        "domains": domains,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")

    print(f"wrote {OUT}")
    print()
    for row in domains:
        cm, rt = row["confusion"], row["rates"]
        print(
            f"{row['domain']:<8} tasks={row['n_tasks']:<4} positives={row['n_positives']:<3} "
            f"tp={cm['tp']:<3} fp={cm['fp']:<3} fn={cm['fn']:<3} "
            f"recall={rt['recall']} precision={rt['precision']}  ({row['audit_seconds']}s)"
        )
    print()
    print(f"{'category':<26} {'positives':>9} {'detected':>9} {'recall':>7}")
    for name, stats in sorted(merged_cat.items(), key=lambda kv: -kv[1]["n_positives"]):
        print(
            f"{name:<26} {stats['n_positives']:>9} {stats['n_detected']:>9} "
            f"{stats['recall']:>7}"
        )
    print()
    print(f"combined              {combined}  {rates(combined)}")
    print(f"combined, no advisory {combined_strict}  {rates(combined_strict)}")
    print(f"signature {canonical_json(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
