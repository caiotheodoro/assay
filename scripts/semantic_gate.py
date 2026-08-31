#!/usr/bin/env python3
"""Measure the Auditor's semantic gate: does it know when there is no right answer?

`docs/COVERAGE.md` records a CRITICAL false positive the probe battery cannot
avoid. `inspect_evals/personality_BFI` returns INVALID with 25 x INVERT_PASSES,
which is mechanically correct and semantically wrong, because a personality
inventory has no correct answer and a scorer that checks the response *format*
is the right design. That section ends: "The right fix is a capability an eval
can withhold -- 'this environment has no correct answer' -- and it does not
exist yet."

This measures the fix. It produces `results/semantic_gate.json`.

The gate must be judged on precision first. A false override hides a real
defect, which is strictly worse than missing one: the tool's whole argument is
that a probe reporting CRITICAL on a healthy environment costs a reader the
tool's credibility, and an *auditor* that quietly deletes a true CRITICAL costs
more. So the negatives outnumber the positives here on purpose.

Run:

    ASSAY_APPROVE_ALL="semantic gate" uv run --extra adapters --extra sweep \
        python scripts/semantic_gate.py --k 3

`--k` is runs per environment per backend. The default is 3 because one run of
a stochastic classifier reported as a capability is the error this repository
is about.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assay.auditor import Auditor  # noqa: E402
from assay.fixtures import CATALOG, build  # noqa: E402
from assay.fixtures.preference import PreferenceEnv  # noqa: E402
from assay.llm import ClaudeCLIClient, LLMUnavailable, OllamaClient  # noqa: E402

#: Environments with no correct answer. Two, and the write-up says why it is
#: two rather than ten: of 246 tasks `inspect_evals` registers, a deliberately
#: broad lexical filter (person|opinion|survey|moral|value|preference|writ|
#: creativ|style|bbq|ethic|bias|attitude) matches four. `personality_TRAIT` is
#: a gated dataset. `writingbench` is scored by an LLM judge, and this project
#: scores nothing with a judge. `bbq` has correct answers and is used below as
#: a negative. That leaves one real environment, and one written here.
POSITIVES = [
    ("inspect_evals/personality_BFI", "inspect_evals", "personality inventory, audited as shipped"),
    ("toy-triage/preference", "authored", "a five-point inventory written for this repo"),
]

#: Everything that does have a correct answer. The twelve toy-triage fixtures
#: plus `bbq`, which is the interesting one: a bias benchmark whose questions
#: *sound* like matters of opinion and are not -- each has a documented correct
#: answer. If the gate is pattern-matching on subject matter rather than on the
#: structure of the task, bbq is where it shows.
NEGATIVES = [(f"toy-triage/{v}", "fixture", "ticket classification") for v in CATALOG] + [
    ("inspect_evals/bbq", "inspect_evals", "bias QA -- reads like opinion, has correct answers"),
]


def _adapter(env_id: str):
    if env_id == "toy-triage/preference":
        return PreferenceEnv()
    if env_id.startswith("toy-triage/"):
        return build(env_id.split("/", 1)[1])
    if env_id.startswith("inspect_evals/"):
        from assay._inspect_evals_corpus import _build

        return _build(env_id.split("/", 1)[1])
    raise LookupError(env_id)


def _revision() -> dict[str, str]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3, help="runs per environment per backend")
    ap.add_argument("--ollama-model", default="qwen3:8b")
    ap.add_argument("--out", default=str(ROOT / "results" / "semantic_gate.json"))
    ap.add_argument("--arms", nargs="*", default=["ollama", "claude"])
    args = ap.parse_args()

    backends = []
    if "ollama" in args.arms:
        backends.append(OllamaClient(args.ollama_model))
    if "claude" in args.arms:
        backends.append(ClaudeCLIClient())

    cases = [(e, k, n, True) for e, k, n in POSITIVES] + [
        (e, k, n, False) for e, k, n in NEGATIVES
    ]

    out: dict[str, object] = {
        "what": "Can a model tell an environment with no correct answer from one "
                "whose verifier is simply broken?",
        "why": "docs/COVERAGE.md records inspect_evals/personality_BFI as a CRITICAL "
               "false positive the battery cannot avoid, and says the capability that "
               "would fix it does not exist. This measures the fix.",
        "design": "Two signals from one call: a label, and a concrete example of two "
                  "different responses that would both be fair. The override fires only "
                  "when both agree -- see decide() in src/assay/auditor.py for the two "
                  "measurements that rule each single-signal design out.",
        "scope": "An override may only move a verifier_integrity DEFECT to "
                 "NOT_APPLICABLE. It can never produce a PASS and can never reach "
                 "another probe family.",
        "corpus_note": "n_positive is 2, and that is a ceiling rather than a choice. Of "
                       "the 246 tasks inspect_evals registers, a deliberately broad "
                       "lexical filter matches four: personality_TRAIT is gated, "
                       "writingbench is scored by an LLM judge and this project scores "
                       "nothing with a judge, and bbq turns out to have correct answers "
                       "and is used as a negative. Environments with no correct answer "
                       "are rare in the eval ecosystem, which is part of why the "
                       "false positive went unnoticed.",
        "k": args.k,
        "assay_revision": _revision(),
        "backends": {},
    }

    for client in backends:
        ok, reason = (client.available(), "") if not hasattr(client, "availability") else client.availability()
        if not ok:
            print(f"SKIP {client.name}: {reason}", flush=True)
            out["backends"][client.name] = {"unavailable": reason}
            continue
        rows, t0 = [], time.time()
        for env_id, kind, note, is_positive in cases:
            try:
                adapter_factory = lambda e=env_id: _adapter(e)
                adapter_factory()
            except Exception as exc:  # noqa: BLE001
                rows.append({"env": env_id, "error": f"{type(exc).__name__}: {exc}"[:200]})
                print(f"  SKIP {env_id}: {type(exc).__name__}", flush=True)
                continue
            verdicts = []
            for _ in range(args.k):
                try:
                    ans = Auditor(client).classify(adapter_factory())
                except LLMUnavailable as exc:
                    ans, _ = None, exc
                verdicts.append((ans or {}).get("verdict", "UNPARSED"))
            fired = sum(1 for v in verdicts if v == "no_correct_answer")
            rows.append({
                "env": env_id, "source": kind, "note": note,
                "has_correct_answer": not is_positive,
                "verdicts": verdicts,
                "fired_no_correct_answer": fired,
                "rate": round(fired / args.k, 3),
            })
            mark = "HIT " if (fired and is_positive) else ("FP  " if fired else "    ")
            print(f"  {mark}{env_id:34} {fired}/{args.k}", flush=True)

        scored = [r for r in rows if "verdicts" in r]
        pos = [r for r in scored if not r["has_correct_answer"]]
        neg = [r for r in scored if r["has_correct_answer"]]
        out["backends"][client.name] = {
            "rows": rows,
            "n_positive": len(pos), "n_negative": len(neg),
            "true_positive_runs": sum(r["fired_no_correct_answer"] for r in pos),
            "positive_runs": len(pos) * args.k,
            "false_positive_runs": sum(r["fired_no_correct_answer"] for r in neg),
            "negative_runs": len(neg) * args.k,
            "seconds": round(time.time() - t0, 1),
        }
        b = out["backends"][client.name]
        print(f"-> {client.name}: tp {b['true_positive_runs']}/{b['positive_runs']}, "
              f"fp {b['false_positive_runs']}/{b['negative_runs']}, {b['seconds']}s\n", flush=True)

    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
