#!/usr/bin/env python
"""Does the new question fix `tau2/airline`, or did five clean runs get lucky?

The corpus-level measurement cannot answer this. The false override happened in
1 run of 7, so at that rate five clean runs occur about 46% of the time with no
fix at all -- `results/gate_reliability.json` records a rate, not a repair.

This asks the question directly instead: classify one environment k times under
each wording and count. One model call per trial rather than a whole corpus run,
so k can be large enough to separate the two.

    uv run --extra adapters --extra sweep --extra openenv --extra tau2 \
        python scripts/gate_question_ablation.py --k 10 --env tau2/airline

The old wording is reconstructed here rather than imported, because it no longer
exists in the tree. It is the exact string the failing run used, kept verbatim so
the comparison is against what shipped and not against a paraphrase of it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assay.auditor import _SYSTEM as NEW_SYSTEM, Auditor, decide, _parse  # noqa: E402
from assay.corpus import scored_entries  # noqa: E402
from assay.llm import ClaudeCLIClient  # noqa: E402

OLD_SYSTEM = """\
You read one evaluation environment and answer one concrete question about it:

    Could two DIFFERENT responses to the same task both be legitimately correct,
    such that a fair scorer ought to accept both?

Answer that question first, with an example, and let the verdict follow from it.

If no -- one response is right and the others are wrong -- the environment
has a correct answer. Maths, code, question answering, classification.

If yes -- two different responses are both legitimately correct -- the
environment has no correct answer. It is eliciting an opinion, a preference, a
self-report, a personality trait, or an open-ended piece of writing. On these a
scorer that only checks the response FORMAT is correct design, not a bug: the
result is computed from the response, not graded against a key.

Reply with one JSON object and nothing else:

{"both_valid_example": "<two different responses that would both be fair, or 'none'>",
 "verdict": "has_correct_answer" | "no_correct_answer",
 "elicitation": "<what the environment elicits, three words>",
 "quote": "<the exact task text that shows it>",
 "confidence": "high" | "low"}

Quote real text from the environment. If you cannot find text that settles it,
answer has_correct_answer with low confidence -- that is the safe direction,
because it changes nothing.\
"""


def _old_decide(answer: dict) -> str | None:
    """decide() as it stood when the false override happened."""
    none = {"none", "none.", "n/a", "na", "", "-", "null"}
    label, example = answer.get("verdict"), answer.get("both_valid_example")
    if label not in ("has_correct_answer", "no_correct_answer"):
        return None
    if not isinstance(example, str):
        return None
    if label == "no_correct_answer" and example.strip().lower().strip(".") not in none:
        return "no_correct_answer"
    return "has_correct_answer"


def _revision() -> dict:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--env", default="tau2/airline")
    ap.add_argument("--out", default=str(ROOT / "results/gate_question_ablation.json"))
    args = ap.parse_args()

    factory = next(f for e, f, _ in scored_entries() if e == args.env)
    adapter = factory()
    task_text = Auditor.task_text(adapter)
    client = ClaudeCLIClient()

    arms = {}
    for name, system, decider in (
        ("old_question", OLD_SYSTEM, _old_decide),
        ("new_question", NEW_SYSTEM, decide),
    ):
        verdicts, replies = [], []
        for i in range(args.k):
            raw = client.complete(system, task_text)
            parsed = _parse(raw) or {}
            v = decider(parsed) if parsed else None
            verdicts.append(v)
            replies.append({"verdict": parsed.get("verdict"),
                            "evidence": parsed.get("both_valid_example")
                            or parsed.get("compared_against"),
                            "decided": v})
            print(f"  {name} {i + 1}/{args.k}: {v}", flush=True)
        counts = Counter(verdicts)
        arms[name] = {
            "k": args.k,
            "counts": {str(k): v for k, v in counts.items()},
            "false_override_rate": counts.get("no_correct_answer", 0) / args.k,
            "replies": replies,
        }

    payload = {
        "what": f"How often each wording of the gate's question calls {args.env} "
                "an environment with no correct answer.",
        "why": "It has one. tau2 is graded on the end state of a database. The "
               "corpus-level measurement saw this in 1 run of 7, which is too rare "
               "for five clean runs to demonstrate a fix -- at that rate five clean "
               "runs happen about 46% of the time with no fix at all.",
        "harness": f"uv run ... python scripts/gate_question_ablation.py --k {args.k} "
                   f"--env {args.env}",
        "assay_revision": _revision(),
        "environment": args.env,
        "arms": arms,
        "reading": (
            f"old question: {arms['old_question']['false_override_rate']:.0%} of {args.k} "
            f"calls withheld; new question: "
            f"{arms['new_question']['false_override_rate']:.0%}."
        ),
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print("\n" + payload["reading"])
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
