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
    ("inspect_evals/stereoset", "inspect_evals", "bias measurement, not a grade -- accepts two options"),
    ("toy-triage/preference", "authored", "a five-point inventory written for this repo"),
    ("noanswer/ranking", "authored", "rank four options by personal preference"),
    ("noanswer/openended", "authored", "short free writing, no key"),
]

#: Everything that does have a correct answer. The twelve toy-triage fixtures
#: plus `bbq`, which is the interesting one: a bias benchmark whose questions
#: *sound* like matters of opinion and are not -- each has a documented correct
#: answer. If the gate is pattern-matching on subject matter rather than on the
#: structure of the task, bbq is where it shows.
NEGATIVES = [(f"toy-triage/{v}", "fixture", "ticket classification") for v in CATALOG] + [
    ("inspect_evals/bbq", "inspect_evals", "bias QA -- reads like opinion, has correct answers"),
    # The adversarial negatives, and the reason this list grew. Harbor's
    # deliberately-broken verifiers are where "the verifier cannot distinguish
    # answers" is easiest to mistake for "there is nothing to distinguish".
    # `vacuous-tests` ships a verifier that always exits 0; the task still has a
    # correct answer. Both backends called it no-correct-answer when the gate
    # was shown `describe()`, which includes the verifier and the fixture's own
    # metadata. It cost 120 expected-loss points on the corpus before anyone
    # noticed, because these environments were not in this list.
    ("harbor/vacuous-tests", "harbor", "a verifier that always exits 0 -- broken, not answerless"),
    ("harbor/self-graded", "harbor", "the environment grades itself; the task has an answer"),
    ("harbor/broken-gold", "harbor", "gold fails its own tests; the task has an answer"),
    ("harbor/shared-tests", "harbor", "tests reachable from the workspace"),
    ("harbor/healthy", "harbor", "nothing planted"),
    # The class this list was missing, and it cost more than the harbor one.
    # tau2 is a multi-turn customer-service dialogue: many phrasings are
    # legitimately correct, and it is graded on the end state of a database, so
    # it plainly has a correct answer. The old question -- "could two different
    # responses both be fair?" -- gets an honest yes here, and the gate withheld
    # 25 findings on tau2/airline in 1 run of 7, destroying two real planted
    # defects. No dialogue environment was in this list, so this measurement
    # could not have caught it. See
    # docs/changelog/122-the-gate-asks-the-wrong-question.md.
    ("tau2/airline", "tau2", "dialogue graded on database state -- many phrasings, one outcome"),
    ("tau2/retail", "tau2", "dialogue graded on database state -- many phrasings, one outcome"),
]


def _adapter(env_id: str):
    """Resolve an environment id, corpus first.

    This used to be a prefix allowlist -- toy-triage, harbor, inspect_evals --
    and anything else raised LookupError, which the caller printed as SKIP and
    carried on. So adding `tau2/airline` to the negatives changed the list and
    not the measurement: the run reported the same "0 false overrides" while
    silently skipping the two environments that were added to test for one.
    A prefix list here is the same failure the corpus registry avoids by
    discovering its providers, so this asks the corpus.

    The `toy-triage/` fallback stays because those twelve are registered under
    `fixture/` and this file has always named them by their builder's name.
    """
    from assay.corpus import entries

    for eid, factory, _ in entries():
        if eid == env_id:
            return factory()
    if env_id == "toy-triage/preference":
        return PreferenceEnv()
    if env_id.startswith("toy-triage/"):
        return build(env_id.split("/", 1)[1])
    if env_id.startswith("inspect_evals/"):
        # `bbq` is a negative here and deliberately not in the corpus: it reads
        # like a matter of opinion and has documented correct answers, which is
        # exactly what makes it a good negative and a bad corpus entry.
        from assay._inspect_evals_corpus import _build

        return _build(env_id.split("/", 1)[1])
    raise LookupError(
        f"{env_id} is named in this file's POSITIVES or NEGATIVES and the corpus "
        "does not register it. A case that cannot be built is not a case that passed."
    )


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

    if not backends:
        # Writing an artifact with zero backends silently replaced a real
        # measurement with an empty one, because `--arms claude-cli` is not a
        # name this accepts and nothing said so. An artifact that measured
        # nothing must not overwrite one that measured something.
        raise SystemExit(
            f"no backend selected from --arms {args.arms}; valid names are "
            "'ollama' and 'claude'. Refusing to write an empty measurement over "
            f"{args.out}."
        )

    cases = [(e, k, n, True) for e, k, n in POSITIVES] + [
        (e, k, n, False) for e, k, n in NEGATIVES
    ]

    out: dict[str, object] = {
        "what": "Can a model tell an environment with no correct answer from one "
                "whose verifier is simply broken?",
        "why": "docs/COVERAGE.md records inspect_evals/personality_BFI as a CRITICAL "
               "false positive the battery cannot avoid, and says the capability that "
               "would fix it does not exist. This measures the fix.",
        "design": "Two signals from one call: a label, and the thing the scorer "
                  "compares a response against. The override fires only when both "
                  "agree, and naming any referent blocks it. The evidence field used "
                  "to be an example of two responses that would both be fair; that is "
                  "a question about surface uniqueness, which every dialogue task "
                  "answers yes to, and it cost two real findings on tau2/airline. See "
                  "decide() in src/assay/auditor.py.",
        "scope": "An override may only move a verifier_integrity DEFECT to "
                 "NOT_APPLICABLE. It can never produce a PASS and can never reach "
                 "another probe family.",
        "corpus_note": (
            "n_positive is 2 here, and that is what one name-only filter found rather "
            "than a ceiling on the ecosystem. Run over the 246 tasks inspect_evals "
            "registers, the filter matches bbq, personality_BFI, personality_TRAIT and "
            "writingbench, and it cannot match stereoset, bold, novelty_bench, moru, "
            "anima, tac_welfare, ape_eval or make_me_pay, whose names carry none of its "
            "words. personality_TRAIT is gated, writingbench is scored by an LLM judge "
            "and this project scores nothing with a judge, and bbq turns out to have "
            "correct answers and is used as a negative. An earlier revision called 2 a "
            "ceiling; see docs/RETRACTIONS.md entry 21."
        ),
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
