"""A second, blinded labelling of the planted-defect corpus.

    uv run --extra adapters python scripts/second_labelling.py --runs 3

`eval-methodology.md:64` says to measure inter-rater agreement before trusting
human labels. Assay's ground truth is one author reading source code, and the
changelog already says hand labels are error-prone -- so the tool that audits
other people's ground truth has never audited its own.

**What the second rater is, stated plainly, because it is the weakest part of
this and hiding it would be the exact failure this repo exists to catch.** It is
a language model reading the environment's source, once per environment, with no
sight of the existing labels. It is NOT a second human, and this does NOT fully
discharge what `eval-methodology.md` asks for. What it does discharge is the
substantive question underneath: are these labels reproducible by an independent
reader of the same source, or do they encode something only their author knows?

This does not violate the project's rule that no LLM judge scores anything. That
rule is about the ORACLES -- every probe verdict is a deterministic program, and
still is. This model labels ground truth, which is the human's job in the first
place, and its output is scored by arithmetic in `assay.agreement`, not by
another model.

Two things make the result readable rather than anecdotal:

  - **Blinding is enforced, not intended.** The prompt is built from source with
    every defect-class name and every catalogue line stripped, and the script
    refuses to send a bundle in which any `DefectClass` member name survives.
  - **The rater is run k times independently.** kappa(A, B_i) is meaningless
    without knowing how much B disagrees with itself, so kappa among the B runs
    is reported as the rater-noise floor. One run of a sampled labeller is a
    draw, not a rater -- the same pass@1-for-pass^k substitution this project
    already has on the record against itself.

One caveat that inflates agreement and is not fixable from here: the fixture
source carries the author's own explanatory comments ("Over-broad oracle: any
plausible category is accepted"). A second reader sees those. So the agreement
below is an UPPER bound on what an independent labeller working from behaviour
alone would reach.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.corpus import ground_truth, unavailable  # noqa: E402
from assay.llm import ClaudeCLIClient, LLMUnavailable, OllamaClient  # noqa: E402
from assay.runconfig import client_config, git_revision, prompt_version  # noqa: E402
from assay.types import DEFAULT_SEVERITY, DefectClass  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src" / "assay"
HARBOR_SUITE = SRC / "fixtures" / "harbor_suite"

#: What each defect class means, in the taxonomy's own words. This is the only
#: thing about the taxonomy the rater is given -- definitions, never examples,
#: and never which environment carries which.
DEFINITIONS: dict[DefectClass, str] = {
    DefectClass.GOLD_FAILS: "the known-good reference solution does NOT pass the verifier",
    DefectClass.NOOP_PASSES: "doing nothing, or submitting nothing, passes the verifier",
    DefectClass.INVERT_PASSES: (
        "the verifier still passes when the task specification is inverted -- it is "
        "not actually checking against the spec it was given"
    ),
    DefectClass.KNOWN_WRONG_PASSES: "a deliberately wrong answer passes the verifier",
    DefectClass.TRIVIAL_FLOOR_BREACH: (
        "a policy that ignores the input entirely scores as well as one that reads it"
    ),
    DefectClass.SEPARABILITY_LOSS: (
        "the environment cannot tell apart two policies that are known to differ in "
        "quality -- they get the same score"
    ),
    DefectClass.CONTAMINATION_EXACT: "an item appears verbatim in both the train and eval splits",
    DefectClass.CONTAMINATION_NEARDUP: (
        "an item in the eval split is a near-duplicate (paraphrase, one field jittered) "
        "of one in the train split"
    ),
    DefectClass.SHORTCUT_LEAK: (
        "the answer is recoverable from part of the input that is not the task -- an "
        "artefact, a length cue, a metadata field"
    ),
    DefectClass.SPEC_VERIFIER_MISMATCH: (
        "the verifier checks something other than what the instruction asked for"
    ),
    DefectClass.NONDETERMINISM: "the same seed and the same actions do not give the same result",
    DefectClass.DIFFICULTY_SATURATED: "essentially every policy solves it; solve rate near 1",
    DefectClass.DIFFICULTY_IMPOSSIBLE: "essentially no policy solves it; solve rate near 0",
    DefectClass.REWARD_HACKABLE: (
        "a policy can score highly WITHOUT doing the job -- the reported score and "
        "genuine task completion come apart"
    ),
}

SYSTEM = """You are labelling environments for a defect corpus.

You will be shown the source of one environment from a benchmark-auditing corpus
and a fixed taxonomy of defect classes. Decide which defects, if any, that
environment has.

Judge only from the source in front of you. You have not been told the answer and
there is no answer key in the text; if you think you have found one, you have
misread a comment.

An environment with NO defects is a normal and expected answer -- the corpus
contains healthy environments on purpose. Do not reach for a label to have
something to say.

Reply with ONE JSON object and nothing else:
{"defects": ["DEFECT_CLASS_NAME", ...], "reasoning": {"DEFECT_CLASS_NAME": "one short sentence"}}

Use an empty list for a healthy environment. Use only names from the taxonomy."""

#: Anything matching these is stripped before a bundle is sent. Deliberately
#: broad: over-redacting costs the rater some context, under-redacting hands it
#: the answer, and only one of those two errors is recoverable.
_REDACT = re.compile(
    r"(DefectClass\.|CATALOG|ground_truth|defects\s*=|planted|_SEVERITY)", re.IGNORECASE
)
_CLASS_NAMES = [d.value for d in DefectClass]


def redact(text: str) -> str:
    return "\n".join(
        "# <line redacted: it names or maps a defect label>" if _REDACT.search(line) else line
        for line in text.splitlines()
    )


def assert_blind(bundle: str, env_id: str) -> None:
    """Refuse to send a bundle that leaks a label. Fails closed."""
    leaked = [name for name in _CLASS_NAMES if name in bundle]
    if leaked:
        raise SystemExit(
            f"REFUSING to send the {env_id} bundle: it still contains {leaked}. "
            "A 'blinded' second labelling that was shown the answer is worse than "
            "no second labelling, because the kappa it produces looks like evidence."
        )


def bundle_for(env_id: str) -> tuple[str, list[str]]:
    """The source a second reader would read, with the labels stripped out."""
    ecosystem, variant = env_id.split("/", 1)
    parts: list[str] = []
    files: list[str] = []

    def add(path: Path, label: str | None = None) -> None:
        files.append(str(path.relative_to(SRC.parent.parent)))
        parts.append(f"----- {label or path.name} -----\n{redact(path.read_text())}")

    if ecosystem == "fixture":
        parts.append(f"This environment is the '{variant}' variant of the source below.\n")
        add(SRC / "fixtures" / "toy.py")
    elif ecosystem == "inspect":
        parts.append(f"This environment is '{variant}' from the source below.\n")
        add(SRC / "_inspect_corpus.py")
    elif ecosystem == "openenv":
        parts.append(f"This environment is '{variant}' from the source below.\n")
        add(SRC / "_openenv_corpus.py")
        add(SRC / "adapters" / "openenv.py")
    elif ecosystem == "harbor":
        parts.append(
            f"This environment is the Harbor task '{variant}'. Its whole task "
            "directory follows. The verifier is the script under tests/.\n"
        )
        root = HARBOR_SUITE / variant
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.stat().st_size < 40_000:
                add(path, str(path.relative_to(root)))
        add(SRC / "adapters" / "harbor.py")
    else:
        raise SystemExit(f"no source bundle rule for ecosystem {ecosystem!r}")

    return "\n\n".join(parts), files


def taxonomy_block() -> str:
    lines = ["The taxonomy. These names, and no others:", ""]
    for defect, meaning in DEFINITIONS.items():
        lines.append(f"  {defect.value} (severity {DEFAULT_SEVERITY[defect].value}): {meaning}")
    return "\n".join(lines)


def parse(reply: str) -> tuple[frozenset[DefectClass], dict, str | None]:
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.DOTALL)
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    depth, start, parsed = 0, None, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    parsed = json.loads(text[start : i + 1])
                    break
                except json.JSONDecodeError:
                    start = None
    if not isinstance(parsed, dict) or "defects" not in parsed:
        return frozenset(), {}, f"unparseable reply: {(reply or '')[:160]!r}"
    names = parsed.get("defects")
    if not isinstance(names, list):
        return frozenset(), {}, f"'defects' was not a list: {names!r}"
    known, unknown = set(), []
    for name in names:
        try:
            known.add(DefectClass(str(name).strip().upper()))
        except ValueError:
            unknown.append(name)
    note = f"reply named {unknown} which are not in the taxonomy" if unknown else None
    return frozenset(known), parsed.get("reasoning") or {}, note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3, help="independent labelling passes")
    ap.add_argument("--backend", choices=["claude", "ollama"], default="claude")
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--out", default="results/second_labelling.json")
    args = ap.parse_args()

    client = (
        ClaudeCLIClient() if args.backend == "claude" else OllamaClient(args.model)
    )
    usable, reason = client.availability()
    if not usable:
        print(f"FAILED: {client.name} unusable: {reason}", file=sys.stderr)
        return 1

    truth = ground_truth()
    missing = unavailable()
    if missing:
        print(
            "WARNING: some ecosystems are unavailable here, so the second labelling "
            f"covers a smaller corpus than the published one: {missing}",
            file=sys.stderr,
        )

    taxonomy = taxonomy_block()
    bundles: dict[str, tuple[str, list[str]]] = {}
    for env_id in sorted(truth):
        bundle, files = bundle_for(env_id)
        assert_blind(bundle, env_id)
        bundles[env_id] = (bundle, files)

    runs: list[dict] = []
    for run_index in range(1, args.runs + 1):
        labels: dict[str, list[str]] = {}
        notes: dict[str, dict] = {}
        failures: dict[str, str] = {}
        for env_id, (bundle, files) in bundles.items():
            user = f"{taxonomy}\n\n{bundle}\n\nWhich defects does this environment have?"
            try:
                reply = client.complete(SYSTEM, user)
            except LLMUnavailable as exc:
                failures[env_id] = str(exc)
                print(f"  run {run_index} {env_id}: UNAVAILABLE {exc}", flush=True)
                continue
            defects, reasoning, note = parse(reply)
            if note:
                failures[env_id] = note
            labels[env_id] = sorted(d.value for d in defects)
            notes[env_id] = {"reasoning": reasoning, "source_files": files}
            print(
                f"  run {run_index} {env_id:32} -> {labels[env_id] or '[]'}"
                + (f"   ({note})" if note else ""),
                flush=True,
            )
        runs.append({"run": run_index, "labels": labels, "notes": notes, "failures": failures})

    body = {
        "what": "a second, blinded labelling of the planted-defect corpus",
        "rater": {
            "kind": "language model reading source, blinded to the existing labels",
            "not_a_human": (
                "eval-methodology.md:64 asks for inter-rater agreement among humans. "
                "This is not that, and does not fully discharge it. What it does test "
                "is whether the labels are reproducible by an independent reader of "
                "the same source."
            ),
            "config": client_config(client),
        },
        "blinding": {
            "enforced_by": "scripts/second_labelling.py:assert_blind",
            "rule": (
                "every line naming a DefectClass member, a catalogue, a ground-truth "
                "map or a severity table is stripped, and the script refuses to send "
                "a bundle in which any class name survives"
            ),
            "known_leak_that_cannot_be_stripped": (
                "the fixture source carries the author's own explanatory comments "
                "(e.g. 'Over-broad oracle: any plausible category is accepted'). A "
                "second reader sees those, so the agreement reported here is an "
                "UPPER bound on what a labeller working from behaviour alone reaches."
            ),
        },
        "prompt_version": prompt_version(SYSTEM, taxonomy),
        "assay_revision": git_revision(),
        "n_runs": args.runs,
        "n_environments": len(bundles),
        "unavailable_ecosystems": missing,
        "runs": runs,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
