#!/usr/bin/env python3
"""Produce `results/auditor_arm.json`: the battery with the Auditor switched on.

This script exists because the artifact it writes used to be written by hand.
A cold judge found that out and was right to: the file's most-quoted figure --
the pre-fix gate scoring 163.0 by deleting real findings -- was a claim with a
narrative behind it and no command. On a submission whose whole argument is
that a finding is not a result until you know what it is worth, that is the
wrong kind of number to lead with.

So the regression is a flag now. `--gate-input describe` hands the semantic
gate what it used to read -- capabilities, task metadata and verifier source --
and re-measures the damage. `--gate-input instructions` is the shipped
behaviour. `both` runs the pair and writes the comparison.

    uv run --extra adapters --extra openenv --extra tau2 \
        python scripts/auditor_arm.py --backend qwen3:8b

Needs a live backend and the full corpus. It writes one file and never touches
`results/full_run.json` or `results/intervals.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.corpus import (  # noqa: E402
    scored_entries,
    scored_ground_truth,
    unavailable,
)
from assay.costs import load  # noqa: E402
from assay.runconfig import git_revision  # noqa: E402
from full_run import run_assay, run_auditor_arm  # noqa: E402

#: What each gate input reads, in the artifact's own words.
GATE_INPUTS = {
    "instructions": "task instructions only",
    "describe": "adapter.describe() -- capabilities, task metadata and verifier source",
}


def _row(arm, profile) -> dict:
    row = arm.profile_row(profile)
    return {
        "expected_loss": row["expected_loss"],
        "recall": row["recall"],
        "precision": row["precision"],
        "recall_on_checkable": row["recall_on_checkable"],
        "n_missed": row["n_missed"],
        "n_unchecked": row["n_unchecked"],
        "n_spurious": row["n_spurious"],
    }


def _reading(gate_input: str, arm_row: dict, base_row: dict) -> str:
    """The interpretation, emitted only where the numbers support it.

    A reading hard-coded next to a number it no longer describes is the drift
    this repository gates everything else against, so each branch below states
    the condition it was written for and none of them fire otherwise.
    """
    delta = arm_row["expected_loss"] - base_row["expected_loss"]
    # n_missed alone stopped being comparable across arms when the scorer gained
    # a third state: a planted defect the gate withheld, or one whose probe
    # declined, lands in n_unchecked instead. Comparing only n_missed let the
    # branch whose whole job is to say "the agent made the tool worse" report a
    # near-zero regression while the gate deleted real findings.
    def failures(row: dict) -> int:
        return row["n_missed"] + row.get("n_unchecked", 0)

    extra_misses = failures(arm_row) - failures(base_row)
    if delta > 0:
        return (
            f"The agent made the tool worse: {arm_row['expected_loss']} against "
            f"{base_row['expected_loss']} deterministic, {extra_misses} further "
            "environments missed. Reading "
            f"{GATE_INPUTS[gate_input]}, it withheld real verifier-integrity "
            "findings on Harbor environments after taking the fixture's own "
            "metadata -- 'The verifier always exits 0. Nothing it reports means "
            "anything' -- as evidence the environment had no correct answer. It "
            "has one; the verifier is broken, which is the defect the battery "
            "found and the gate deleted."
        )
    if delta == 0:
        return (
            "Identical to the deterministic arm on every figure. On a corpus "
            "containing no environment without a correct answer, the gate has "
            "nothing to act on, and the number that matters is that it does no "
            "harm rather than that it does good."
        )
    return (
        f"The gate improved the arm by {abs(delta)} expected loss. This corpus "
        "was not expected to show that; check what changed before quoting it."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--backend", default="qwen3:8b",
        help="an ollama tag (e.g. qwen3:8b), or 'claude' for the CLI client",
    )
    ap.add_argument(
        "--gate-input", choices=["both", "instructions", "describe"], default="both",
        help="what the semantic gate may read. 'describe' restores the pre-fix "
             "input and re-measures the regression it caused",
    )
    ap.add_argument("--out", default="results/auditor_arm.json")
    ap.add_argument("--profile", default="research-run")
    ap.add_argument(
        "--allow-reduced", action="store_true",
        help="report from a corpus missing a provider. Off by default for the "
             "same reason as in full_run.py: the environments that go missing "
             "are the ones Assay does worst on",
    )
    args = ap.parse_args()

    if unavailable() and not args.allow_reduced:
        raise SystemExit(
            "refusing to write an auditor arm from a reduced corpus.\n"
            f"missing providers: {sorted(unavailable())}\n"
            "The arm is a comparison against the deterministic headline, and a "
            "comparison on a different corpus is not one. Install the extras, "
            "or pass --allow-reduced and do not quote the result."
        )

    corpus = scored_entries()
    truth = scored_ground_truth()
    profile = load(args.profile)

    from assay.llm import ClaudeCLIClient, OllamaClient

    client = ClaudeCLIClient() if args.backend == "claude" else OllamaClient(args.backend)
    usable, reason = client.availability()
    if not usable:
        raise SystemExit(
            f"backend unusable: {reason}\n"
            "An arm missing from a comparison is a result about the run, not "
            "the method -- but it is not this file, which exists to carry the "
            "comparison. Start the backend and re-run."
        )

    print(f"running deterministic arm over {len(corpus)} environments ...", flush=True)
    base = run_assay(corpus)
    base_row = _row(base, profile)

    wanted = ["describe", "instructions"] if args.gate_input == "both" else [args.gate_input]
    measured, calls = {}, {}
    for gate_input in wanted:
        print(f"running auditor arm (gate reads: {GATE_INPUTS[gate_input]}) ...", flush=True)
        arm, logs = run_auditor_arm(corpus, client, gate_input=gate_input)
        row = _row(arm, profile)
        measured[gate_input] = {
            "gate_input": GATE_INPUTS[gate_input],
            "backend": logs["backend"],
            "result": row,
            "reading": _reading(gate_input, row, base_row),
        }
        calls[gate_input] = logs["model_calls"]

    payload = {
        "what": "The same battery, read by the Auditor before the verdict is "
                "recorded, on the same corpus as the headline.",
        "why": "A cold judge wrote: 'the agent is off in every number the "
               "submission leads with.' That is fair, and this is the row that "
               "answers it. It is not the headline -- the shipped default has "
               "no model in it -- but the comparison is a measurement rather "
               "than an argument.",
        "harness": (
            "uv run --extra adapters --extra openenv --extra tau2 python "
            f"scripts/auditor_arm.py --backend {args.backend} "
            f"--gate-input {args.gate_input}"
        ),
        "assay_revision": git_revision(),
        "corpus": {
            "environments": len(corpus),
            "planted": sum(len(v) for v in truth.values()),
            "cost_profile": profile.name,
        },
        "deterministic_arm": base_row,
        "honesty": "This arm does not demonstrate the agent helping. It "
                   "demonstrates that it stopped hurting, and that the corpus "
                   "cannot show the other thing: inspect_evals/personality_BFI "
                   "is the environment the gate exists for and is deliberately "
                   "excluded, because an environment the tool is wrong about "
                   "does not belong in the set used to measure the tool. The "
                   "evidence that it helps is results/semantic_gate.json, "
                   "measured off-corpus.",
        "model_calls": calls,
    }
    if "describe" in measured:
        payload["before_the_fix"] = measured["describe"]
    if "instructions" in measured:
        payload["after_the_fix"] = measured["instructions"]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {out}")
    for name, block in measured.items():
        print(f"  {name}: expected_loss {block['result']['expected_loss']}, "
              f"n_missed {block['result']['n_missed']}")
    print(f"  deterministic: expected_loss {base_row['expected_loss']}, "
          f"n_missed {base_row['n_missed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
