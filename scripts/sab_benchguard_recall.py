"""Score Assay against BenchGuard's 12 confirmed ScienceAgentBench defects.

The point of this script is what it does NOT do: it does not compute recall.
It converts Assay's audit output into the schema BenchGuard's eval pipeline
expects and then shells out to three files nobody here wrote --

  1. auto-bench-audit's ``audits_to_benchguard_findings.py``  (converter)
  2. BenchGuard's ``eval/match.py``                           (LLM-judge matcher)
  3. BenchGuard's ``eval/metrics.py``                         (recall/precision)

-- so the number is theirs. Assay verifies its own corpus labels against an
environment's own scorer rather than against Assay; the same reasoning applies
when Assay is the thing being scored.

Two arms, both explicit:

``--arm assay``
    Assay exactly as it ships. Runs the real probe registry through
    ``assay.runner.audit`` against the SAB adapter and forwards whatever
    findings come out. Expect none: eight of the nine families need to execute
    a verifier, and SAB's verifier is inside a gated archive.

``--arm rejected-r1``
    The metadata heuristic docs/SCIENCEAGENTBENCH.md already rejected -- "the
    task declares an output path the instruction never names" -- which recovers
    real instruction defects while firing on 61 of 102 tasks. It is NOT part of
    Assay and is scored only to measure what the rejection cost, and to show
    what BenchGuard's precision metric can and cannot see: that metric counts
    findings on the 12 revised tasks only, so a detector firing on 61 tasks is
    scored on 12 of them and its trivial-floor breach is invisible.

Stage 2 is an LLM judge (Gemini, via LiteLLM). That is BenchGuard's design, not
Assay's, and it is why the arm that produces zero findings is the one that
scores fully offline: ``match.py`` skips tasks with no findings, so zero
findings means zero judge calls and a deterministic run. The ``rejected-r1``
arm does produce findings and therefore does need GEMINI_API_KEY; without one
it stops after the converter and says so.

Run (see docs/changelog/61-benchguard-recall.md for the exact invocation):

    uv run --extra sab --extra adapters python scripts/sab_benchguard_recall.py \
        --benchguard-root /path/to/BenchGuard \
        --converter /path/to/auto-bench-audit/benchmarks/benchguard/audits_to_benchguard_findings.py

Redistribution: this writes verdicts about ScienceAgentBench, never its
content. No instruction text, gold program, or eval script is copied into
results/. See src/assay/publish.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from assay.adapters.scienceagentbench import (  # noqa: E402
    SPLITS,
    SabTask,
    ScienceAgentBenchAdapter,
    load_tasks_from_hub,
)
from assay.runner import audit  # noqa: E402
from assay.types import DefectClass, Severity  # noqa: E402

# --------------------------------------------------------------------------
# Assay's taxonomy -> the audit schema the converter reads
# --------------------------------------------------------------------------

#: The converter maps ambiguity->INST, test_quality->EVAL, environment->ENV.
#: Assay never emits `ambiguity`: "this instruction is ambiguous" is a
#: judgement and Assay scores nothing with a judge. That absence is the
#: headline result, so it is encoded here rather than papered over.
CATEGORY_OF_DEFECT: dict[DefectClass, str] = {
    DefectClass.GOLD_FAILS: "test_quality",
    DefectClass.NOOP_PASSES: "test_quality",
    DefectClass.INVERT_PASSES: "test_quality",
    DefectClass.KNOWN_WRONG_PASSES: "test_quality",
    DefectClass.TRIVIAL_FLOOR_BREACH: "test_quality",
    DefectClass.SEPARABILITY_LOSS: "test_quality",
    DefectClass.CONTAMINATION_EXACT: "test_quality",
    DefectClass.CONTAMINATION_NEARDUP: "test_quality",
    DefectClass.SHORTCUT_LEAK: "test_quality",
    DefectClass.SPEC_VERIFIER_MISMATCH: "test_quality",
    DefectClass.NONDETERMINISM: "environment",
    DefectClass.DIFFICULTY_SATURATED: "test_quality",
    DefectClass.DIFFICULTY_IMPOSSIBLE: "test_quality",
    DefectClass.REWARD_HACKABLE: "test_quality",
}

SEVERITY_INT: dict[Severity, int] = {
    Severity.CRITICAL: 3,
    Severity.HIGH: 2,
    Severity.MEDIUM: 1,
    Severity.LOW: 0,
}

# --------------------------------------------------------------------------
# The rejected heuristic, reproduced from scripts/sab_metadata_probe.py
# --------------------------------------------------------------------------

_QUOTED = re.compile(r'"([^"]*?\.[A-Za-z0-9]{1,5})"')
_BACKTICKED = re.compile(r"`([^`]*?\.[A-Za-z0-9]{1,5})`")


def referenced_paths(instruction: str) -> set[str]:
    return set(_QUOTED.findall(instruction)) | set(_BACKTICKED.findall(instruction))


def output_path_unstated(task: SabTask) -> bool:
    """R1: the task declares an output path the instruction never names."""
    stem = task.output_fname.rsplit("/", 1)[-1]
    return not any(
        stem in p or p in task.output_fname for p in referenced_paths(task.task_inst)
    )


# --------------------------------------------------------------------------
# Building audit records
# --------------------------------------------------------------------------


def evidence_items(evidence: dict[str, Any]) -> list[dict[str, str]]:
    return [{"note": f"{k}: {v}"} for k, v in sorted(evidence.items())]


def assay_records(
    tasks: list[SabTask], adapter: ScienceAgentBenchAdapter
) -> tuple[dict[str, dict], dict]:
    """Run Assay for real and bucket its findings by task."""
    report = audit(adapter)

    by_task: dict[str, list[dict]] = {t.task_id: [] for t in tasks}
    for finding in report.findings:
        if finding.task_id in by_task:
            by_task[finding.task_id].append(
                {
                    "category": CATEGORY_OF_DEFECT.get(finding.defect, "test_quality"),
                    "subtype": finding.defect.value,
                    "severity": SEVERITY_INT[finding.severity],
                    "claim": f"{finding.defect.value} on task {finding.task_id}",
                    "why_it_matters": finding.evidence.get("note", finding.defect.value),
                    "evidence": evidence_items(finding.evidence),
                }
            )

    coverage = {
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
    }
    records = {
        t.task_id: {
            "task_id": t.task_id,
            "confidence": "high",
            "findings": by_task[t.task_id],
        }
        for t in tasks
    }
    return records, coverage


def rejected_r1_records(tasks: list[SabTask]) -> tuple[dict[str, dict], dict]:
    """The heuristic Assay rejected, as a labelled non-shipping baseline."""
    fired_ids = {t.task_id for t in tasks if output_path_unstated(t)}

    records: dict[str, dict] = {}
    for t in tasks:
        findings: list[dict] = []
        if t.task_id in fired_ids:
            findings.append(
                {
                    "category": "ambiguity",
                    "subtype": "output_path_unstated",
                    "severity": 2,
                    "claim": (
                        f"The instruction never names the output path the task "
                        f"declares ({t.output_fname})."
                    ),
                    "why_it_matters": (
                        "An agent following the instruction cannot know where to write "
                        "its result, so the grader can fail a correct solution on "
                        "placement alone."
                    ),
                    "evidence": [
                        {"path": t.output_fname, "note": "declared output_fname"},
                        {
                            "note": "paths the instruction does name: "
                            + (", ".join(sorted(referenced_paths(t.task_inst))) or "none")
                        },
                    ],
                }
            )
        records[t.task_id] = {
            "task_id": t.task_id,
            "confidence": "medium",
            "findings": findings,
        }

    coverage = {
        "rule": "R1_output_path_unstated",
        "status": "REJECTED - not part of Assay",
        "fired_on": len(fired_ids),
        "of_total": len(tasks),
        "fire_rate": round(len(fired_ids) / len(tasks), 3) if tasks else 0.0,
        "why_rejected": (
            "By Assay's own trivial-floor rule a detector that flags 60% of a "
            "benchmark has not earned its existence. Scored here only to measure "
            "what the rejection cost."
        ),
    }
    return records, coverage


# --------------------------------------------------------------------------
# Driving their three scripts
# --------------------------------------------------------------------------


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=1800
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


#: BenchGuard's matcher imports litellm. That is their dependency, not Assay's,
#: so it is installed into a throwaway env at call time rather than added to
#: this project -- `assay` must stay installable without an LLM client.
THEIR_PYTHON = ["uv", "run", "--no-project", "--with", "litellm", "python"]


def git_sha(path: Path) -> str:
    code, out = run(["git", "-C", str(path), "rev-parse", "HEAD"])
    return out.splitlines()[0] if code == 0 and out else "unknown"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gold_still_present(tasks: list[SabTask], gold: dict) -> dict:
    """Which of the 12 gold defects are actually in the split being read.

    Recall against a gold set assumes the defect is still in the text. SAB
    shipped a verified split on 2026/04/30 "to mitigate false negatives", and
    that split adopted most of BenchGuard's corrections -- so a detector
    pointed at `verified` is being scored on finding wording that is no longer
    there. This measures it per task instead of assuming either way, by
    comparing the split's instruction against BenchGuard's own
    `original_question` / `updated_question` pair.
    """
    by_id = {t.task_id: t for t in tasks}

    def norm(text: str) -> str:
        return " ".join(text.split())

    status: dict[str, str] = {}
    for task_id, entry in gold["tasks"].items():
        task = by_id.get(task_id)
        if task is None:
            status[task_id] = "absent_from_split"
            continue
        here = norm(task.task_inst)
        if here == norm(entry["original_question"]):
            status[task_id] = "defect_present"
        elif here == norm(entry["updated_question"]):
            status[task_id] = "already_fixed_upstream"
        else:
            status[task_id] = "differs_from_both"
    counts: dict[str, int] = {}
    for value in status.values():
        counts[value] = counts.get(value, 0) + 1
    return {
        "per_task": status,
        "counts": counts,
        "note": (
            "`already_fixed_upstream` means the split already contains "
            "BenchGuard's corrected wording, so no reader of that text can find "
            "the defect. `differs_from_both` is usually a transcription typo; "
            "check it by hand before treating it as either."
        ),
    }


def redact_gold_text(report: dict) -> dict:
    """Keep BenchGuard's verdicts, drop BenchGuard's gold text.

    ``per_issue_detail[].description`` is BenchGuard's wording, and it quotes
    fragments of ScienceAgentBench instructions to say what changed. Verdicts
    about other people's software may ship; their content may not (see
    src/assay/publish.py -- `scienceagentbench` is already in THEIRS). So the
    committed artefact carries the issue id, the task id and the verdict, plus
    a digest of the description so a reader can confirm their gold file is the
    same one this was scored against.
    """
    out = json.loads(json.dumps(report))
    for issue in out.get("per_issue_detail", []):
        description = issue.pop("description", "")
        issue["description_sha256"] = hashlib.sha256(
            description.encode("utf-8")
        ).hexdigest()
    out["_redaction"] = (
        "per_issue_detail[].description removed: it is BenchGuard's gold text and "
        "quotes ScienceAgentBench instructions. Recover it from "
        "BenchGuard eval/data/gold/sab_gold.json at the sha256 recorded under "
        "provenance.gold_sha256; the digests above let you confirm the match."
    )
    return out


def base_result(
    args, tasks, gold, gold_path, adapter, excluded,
    arm_detail, n_findings, n_on_gold, needs_judge, steps,
) -> dict:
    """Everything this run established that does not come from their scorer."""
    gold_ids = set(gold["tasks"])
    return {
        "what_this_is": (
            "Assay scored against BenchGuard's 12 author-confirmed ScienceAgentBench "
            "defects. Every number under 'their_report' was computed by BenchGuard's "
            "eval/metrics.py from verdicts produced by BenchGuard's eval/match.py. "
            "Nothing in this file recomputes them."
        ),
        "arm": args.arm,
        "provenance": {
            "benchguard_repo": "https://github.com/XinmingTu/BenchGuard",
            "benchguard_sha": git_sha(args.benchguard_root),
            "converter": "auto-bench-audit benchmarks/benchguard/"
            "audits_to_benchguard_findings.py",
            "converter_sha256": sha256_file(args.converter),
            "auto_bench_audit_repo": "https://github.com/IsThatYou/auto-bench-audit",
            "gold_path": str(gold_path),
            "gold_sha256": sha256_file(gold_path),
            "gold_human_verified": gold.get("human_verified"),
            "sab_split": args.split,
            "sab_split_file": SPLITS[args.split],
            "n_sab_tasks": len(tasks),
            "benchmark_root_supplied": args.benchmark_root is not None,
            "eval_programs_present": adapter.eval_programs_dir is not None,
        },
        "exclusions": {
            "criterion": "declared output_fname is an image",
            "reason_class": (
                "scored by SAB's GPT-4o visual judge, not a deterministic verifier"
            ),
            "n_excluded_of_102": len(excluded),
            "excluded_gold_tasks": sorted(
                (k for k in excluded if k in gold_ids), key=int
            ),
            "note": (
                "Exclusion suppresses findings, never the denominator: metrics.py "
                "scores all 12 gold issues regardless, so this can only lower recall."
            ),
            "per_task": excluded,
        },
        "gold_defect_presence": gold_still_present(tasks, gold),
        "arm_detail": arm_detail,
        "findings_submitted": {
            "total": n_findings,
            "on_revised_tasks": n_on_gold,
            "judge_calls_required": needs_judge,
        },
        "steps": steps,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", choices=["assay", "rejected-r1"], default="assay")
    ap.add_argument(
        "--benchguard-root",
        type=Path,
        required=True,
        help="checkout of github.com/XinmingTu/BenchGuard (supplies eval/match.py, "
        "eval/metrics.py and eval/data/gold/sab_gold.json)",
    )
    ap.add_argument(
        "--converter",
        type=Path,
        required=True,
        help="path to auto-bench-audit's audits_to_benchguard_findings.py",
    )
    ap.add_argument("--gold", type=Path, default=None)
    ap.add_argument(
        "--split",
        choices=sorted(SPLITS),
        default="original",
        help="which SAB split the detector reads. Default `original`: nine of "
        "BenchGuard's twelve defects are already corrected in `verified`, so "
        "scoring against `verified` asks a detector to find text that is not there.",
    )
    ap.add_argument(
        "--benchmark-root",
        type=Path,
        default=None,
        help="ScienceAgentBench benchmark/ from the gated archive, if you have it",
    )
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "sab_benchguard")
    ap.add_argument(
        "--judge-model",
        default="gemini/gemini-3-flash-preview",
        help="BenchGuard's matcher model; only reached when findings exist",
    )
    args = ap.parse_args()

    # match.py and metrics.py run with cwd=benchguard_root, so every path handed
    # to them has to be absolute or it resolves against the wrong directory.
    args.benchguard_root = args.benchguard_root.resolve()
    args.converter = args.converter.resolve()
    args.out = args.out.resolve()
    if args.gold:
        args.gold = args.gold.resolve()
    if args.benchmark_root:
        args.benchmark_root = args.benchmark_root.resolve()

    gold_path = args.gold or (
        args.benchguard_root / "eval" / "data" / "gold" / "sab_gold.json"
    )
    if not gold_path.is_file():
        print(f"ERROR: gold not found at {gold_path}", file=sys.stderr)
        return 2

    out = args.out / f"{args.arm}__{args.split}"
    audits_dir = out / "audits"
    audits_dir.mkdir(parents=True, exist_ok=True)

    print(f"==> [0/4] loading ScienceAgentBench `{args.split}` split from the Hub")
    tasks = load_tasks_from_hub(split=args.split)
    adapter = ScienceAgentBenchAdapter(
        tasks, benchmark_root=args.benchmark_root, env_version=args.split
    )

    gold = json.loads(gold_path.read_text())
    gold_ids = set(gold["tasks"])

    # SAB scores its visualization tasks with GPT-4o (gpt4_visual_judge.py,
    # temperature 0.2, n=3). Assay's inverted-spec and known-wrong probes assume
    # the verifier is a deterministic function of the transcript; against a judge
    # they measure the judge's mood. Excluded with the reason recorded per task
    # rather than scored quietly.
    excluded = {
        t.task_id: (
            f"declared output is `{Path(t.output_fname).suffix}`, so SAB scores this "
            f"task with its GPT-4o visual judge (SAB README: 'our evaluation leverages "
            f"GPT-4o to judge output visualizations'; gpt4_visual_judge.py runs at "
            f"temperature 0.2, n=3). Assay's verifier-integrity probes assume a "
            f"deterministic verifier and cannot honestly probe a judge."
        )
        for t in tasks
        if t.llm_judged
    }

    print(f"==> [1/4] running Assay ({args.arm} arm)")
    if args.arm == "assay":
        records, arm_detail = assay_records(tasks, adapter)
    else:
        records, arm_detail = rejected_r1_records(tasks)

    # Every excluded task reports nothing, whatever the arm produced. The
    # denominator is untouched: BenchGuard computes recall over all 12 gold
    # issues either way, so excluding a task can only ever lower our number.
    for task_id in excluded:
        record = records.get(task_id)
        if record and record["findings"]:
            arm_detail.setdefault("suppressed_by_exclusion", {})[task_id] = len(
                record["findings"]
            )
            record["findings"] = []

    for task_id, record in records.items():
        (audits_dir / f"{task_id}.json").write_text(json.dumps(record, indent=2))

    n_findings = sum(len(r["findings"]) for r in records.values())
    n_on_gold = sum(len(r["findings"]) for k, r in records.items() if k in gold_ids)
    print(
        f"    {len(records)} audit records | {n_findings} findings total "
        f"| {n_on_gold} on the 12 revised tasks"
    )

    normalized = out / "normalized" / "sab_findings.json"
    matches = out / "matches" / "sab_matches.json"
    reports = out / "reports"
    normalized.parent.mkdir(parents=True, exist_ok=True)
    matches.parent.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    steps: list[dict] = []

    print("==> [2/4] their converter: audits -> BenchGuard findings")
    code, log = run(
        [
            sys.executable, str(args.converter),
            "--benchmark", "sab",
            "--audits-dir", str(audits_dir),
            "--gold", str(gold_path),
            "--output", str(normalized),
        ]
    )
    steps.append({"step": "audits_to_benchguard_findings.py", "exit": code, "log": log})
    print(f"    exit={code} {log}")
    if code != 0:
        (out / "run_log.json").write_text(json.dumps(steps, indent=2))
        return 1

    print("==> [3/4] their matcher: BenchGuard eval/match.py")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(args.benchguard_root / "src"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    needs_judge = n_on_gold > 0
    if needs_judge and not (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API")):
        msg = (
            f"BLOCKED: {n_on_gold} findings land on revised tasks, so match.py must "
            f"call the {args.judge_model} judge, and no GEMINI_API_KEY is set. "
            f"Stopping rather than reporting an unjudged number."
        )
        print(f"    {msg}", file=sys.stderr)
        steps.append({"step": "eval/match.py", "exit": None, "log": msg})
        # Still emit everything that was measured without a judge. A blocked run
        # that writes nothing is indistinguishable from a run that never
        # happened, and the deterministic half is the half worth keeping.
        partial = base_result(
            args, tasks, gold, gold_path, adapter, excluded,
            arm_detail, n_findings, n_on_gold, needs_judge, steps,
        )
        partial["their_report"] = None
        partial["blocked"] = msg
        blocked_path = args.out / f"{args.arm}__{args.split}_result.json"
        blocked_path.write_text(json.dumps(partial, indent=2))
        print(f"    wrote {blocked_path} (no recall/precision: their scorer did not run)")
        return 3
    code, log = run(
        [
            *THEIR_PYTHON, str(args.benchguard_root / "eval" / "match.py"),
            "--gold", str(gold_path),
            "--findings", str(normalized),
            "--output", str(matches),
            "--cache-dir", str(matches.parent / "cache"),
            "--model", args.judge_model,
            "--max-concurrent", "10",
        ],
        cwd=args.benchguard_root,
        env=env,
    )
    steps.append({"step": "eval/match.py", "exit": code, "log": log})
    print(f"    exit={code} {log}")
    if code != 0:
        (out / "run_log.json").write_text(json.dumps(steps, indent=2))
        return 1

    print("==> [4/4] their metrics: BenchGuard eval/metrics.py")
    code, log = run(
        [
            *THEIR_PYTHON, str(args.benchguard_root / "eval" / "metrics.py"),
            "--matches", str(matches),
            "--gold", str(gold_path),
            "--findings", str(normalized),
            "--output", str(reports),
        ],
        cwd=args.benchguard_root,
        env=env,
    )
    steps.append({"step": "eval/metrics.py", "exit": code, "log": log})
    print(f"    exit={code}\n{log}")
    if code != 0:
        (out / "run_log.json").write_text(json.dumps(steps, indent=2))
        return 1

    their_report = json.loads((reports / "sab_eval.json").read_text())

    result = base_result(
        args, tasks, gold, gold_path, adapter, excluded,
        arm_detail, n_findings, n_on_gold, needs_judge, steps,
    )
    result["their_report"] = redact_gold_text(their_report)

    result_path = args.out / f"{args.arm}__{args.split}_result.json"
    result_path.write_text(json.dumps(result, indent=2))

    r = their_report["recall"]
    p = their_report["precision"]
    print()
    print(f"  arm                : {args.arm}")
    print(
        f"  Recall@ALIGNED     : {r['aligned']['count']}/{r['aligned']['total']}"
        f" = {r['aligned']['rate']:.1%}"
    )
    print(
        f"  Recall@PARTIAL+    : {r['partial_plus']['count']}/{r['partial_plus']['total']}"
        f" = {r['partial_plus']['rate']:.1%}"
    )
    print(
        f"  Precision@ALIGNED  : {p['aligned']['count']}/{p['aligned']['total']}"
        f" = {p['aligned']['rate']:.1%}"
    )
    print(
        f"  Precision@PARTIAL+ : {p['partial_plus']['count']}/{p['partial_plus']['total']}"
        f" = {p['partial_plus']['rate']:.1%}"
    )
    print(f"\nwrote {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
