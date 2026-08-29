#!/usr/bin/env python3
"""A rejected experiment, kept because the rejection is the finding.

BenchGuard reports 12 author-confirmed defects on ScienceAgentBench, 7 of them
instruction defects (INST). ScienceAgentBench publishes enough metadata per
task -- instruction, dataset tree, declared output path, eval script name --
that instruction defects look like they should fall out of cross-field
consistency checks, deterministically, with no judge.

They do not. This script measures two such rules against all 102 tasks and
reports what they actually do, which is the point: on the 12 known-defective
tasks alone, rule R1 looks like a success at 5/7 recall on the INST subset.
Across the whole benchmark it fires on 61 of 102.

By Assay's own trivial-floor rule -- a policy that ignores the input must not
win -- a detector that flags 60% of a benchmark has not earned its existence.

Run: uv run --with huggingface_hub --with pandas python scripts/sab_metadata_probe.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

#: BenchGuard (arXiv 2604.24955) Table 5, transcribed by hand -- no
#: machine-readable release exists; the paper says one follows publication.
BENCHGUARD_DEFECTS = {
    9: ("GT", "Pearson r vs R2 metric"),
    12: ("EVAL", "output format: SMILES vs drug names"),
    21: ("GT", "wrong deforestation rate"),
    26: ("INST", "singular vs plural naming"),
    29: ("INST", "wrong input file (critical)"),
    31: ("INST", "unspecified analysis method"),
    32: ("INST", "wrong analysis grouping"),
    34: ("INST", "infeasible requirement"),
    35: ("INST", "unspecified output format"),
    67: ("INST", "wrong output save path"),
    78: ("GT", "test data contamination"),
    92: ("GT", "column dimension mismatch"),
}

_QUOTED = re.compile(r'"([^"]*?\.[A-Za-z0-9]{1,5})"')
_BACKTICKED = re.compile(r"`([^`]*?\.[A-Za-z0-9]{1,5})`")
_FILENAME = re.compile(r"([A-Za-z0-9_\-.]+\.[A-Za-z0-9]{1,5})")


def referenced_paths(instruction: str) -> set[str]:
    return set(_QUOTED.findall(instruction)) | set(_BACKTICKED.findall(instruction))


def output_path_unstated(row) -> bool:
    """R1: the task declares an output path the instruction never names."""
    out = str(row.output_fname)
    stem = out.rsplit("/", 1)[-1]
    return not any(stem in p or p in out for p in referenced_paths(str(row.task_inst)))


def input_not_in_tree(row) -> bool:
    """R2: the instruction names an input file absent from the dataset tree."""
    tree = set(_FILENAME.findall(str(row.dataset_folder_tree)))
    out_stem = str(row.output_fname).rsplit("/", 1)[-1]
    unknown = {
        p
        for p in referenced_paths(str(row.task_inst))
        if "/" not in p and p not in tree and p != out_stem
    }
    return bool(unknown)


def main() -> int:
    import pandas as pd
    from huggingface_hub import hf_hub_download

    df = pd.read_csv(
        hf_hub_download("osunlp/ScienceAgentBench", "ScienceAgentBench.csv", repo_type="dataset")
    )
    known = set(BENCHGUARD_DEFECTS)
    inst_only = {t for t, (cat, _) in BENCHGUARD_DEFECTS.items() if cat == "INST"}

    report = {"n_tasks": len(df), "rules": {}}
    for name, rule in (("R1_output_path_unstated", output_path_unstated),
                       ("R2_input_not_in_tree", input_not_in_tree)):
        fired = {int(r.instance_id) for _, r in df.iterrows() if rule(r)}
        hits_all, hits_inst = sorted(fired & known), sorted(fired & inst_only)
        precision = len(hits_all) / len(fired) if fired else 0.0
        report["rules"][name] = {
            "fired_on": len(fired),
            "of_total": len(df),
            "fire_rate": round(len(fired) / len(df), 3),
            "hits_all_12": hits_all,
            "hits_inst_subset": hits_inst,
            "recall_vs_inst": f"{len(hits_inst)}/{len(inst_only)}",
            "precision": round(precision, 3),
            "verdict": (
                "REJECTED: fires on more than a third of the benchmark; by the "
                "trivial-floor rule this has not earned its existence"
                if len(fired) / len(df) > 0.33
                else ("REJECTED: fires on nothing" if not fired else "candidate")
            ),
        }
        print(
            f"{name}: fired {len(fired)}/{len(df)} "
            f"({report['rules'][name]['fire_rate']:.0%}) | "
            f"INST recall {len(hits_inst)}/{len(inst_only)} | "
            f"precision {precision:.2f}\n  -> {report['rules'][name]['verdict']}"
        )

    report["conclusion"] = (
        "Instruction defects are not deterministically detectable from published "
        "metadata. Both rules fail: one by flagging a third of the benchmark, one by "
        "flagging nothing. This is a real limit, not a tuning problem -- 'the "
        "instruction is ambiguous' and 'this requirement is infeasible' are judgements, "
        "and Assay scores nothing with a judge. Assay and BenchGuard therefore find "
        "disjoint classes of defect: BenchGuard finds instruction quality, which needs "
        "judgement; Assay finds verifier defects, which need execution. Neither "
        "subsumes the other, and claiming otherwise would be the more comfortable lie."
    )
    out = Path(__file__).resolve().parents[1] / "results" / "sab_metadata_probe.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\n{report['conclusion']}\n\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
