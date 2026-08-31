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

  - **Blinding is enforced, not intended.** Three separate mechanisms, because
    the first version had only the first and it was not enough:

      1. the prompt is built from source with every defect-class name and every
         catalogue line stripped, and the script refuses to send a bundle in
         which any `DefectClass` member name survives;
      2. the rater runs with **every file, search and execution tool disabled**;
      3. and with its **working directory set to an empty scratch dir outside
         the repository**.

    (2) and (3) exist because the first run of this script did not have them,
    and headless `claude -p` inherits the caller's working directory and its
    tool permissions. Asked to, it read `src/assay/fixtures/toy.py` and printed
    the first line of the `CATALOG` answer key. Nothing in the traces suggests
    it went looking unprompted -- but "probably did not read the answer key" is
    not blinding, and the run was discarded rather than reported with a caveat.
    `blindness_probe` below re-checks the hardening at the start of every run
    and refuses to proceed if the rater can still reach the file.
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

import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402

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
    DefectClass.EXCESSIVE_PERMISSIONS: (
        "the deployment grants the agent more than the task needs -- network access "
        "for a task with no network step, write access to the verifier grading it, "
        "a writable root filesystem, root for a task that does not need it"
    ),
    DefectClass.EVALUATOR_RCE: (
        "the verifier can be made to execute content it is grading -- eval, exec, "
        "unpickling, yaml.load without a safe loader, or a shell invocation built "
        "from the submission"
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
_CLASS_NAMES = [d.value for d in DefectClass]

#: `assert_blind` refuses a bundle containing any bare class name, but this
#: pattern only ever matched the ways a *label* is written in code --
#: `DefectClass.X`, a CATALOG entry, a `planted` set. A file that merely
#: mentions a class in prose ("this environment is deliberately not labelled
#: NONDETERMINISM, and here is why") passed redaction and then tripped the
#: refusal, so the bundle could not be built at all. The redactor now strips
#: exactly what the refusal looks for, which is what it should always have done.
_REDACT = re.compile(
    r"(DefectClass\.|CATALOG|ground_truth|defects\s*=|planted|_SEVERITY|"
    + "|".join(re.escape(n) for n in _CLASS_NAMES)
    + r")",
    re.IGNORECASE,
)


#: Everything that could let the rater reach the repository instead of reading
#: the bundle it was handed. Named explicitly rather than relying on a
#: permission prompt defaulting to deny -- that default depends on the caller's
#: settings and on the directory the process happens to be in, neither of which
#: is a property of this experiment.
_NO_TOOLS = [
    "Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite",
]


@dataclass
class BlindClaudeCLIClient(ClaudeCLIClient):
    """`claude -p` with no way to reach the corpus it is labelling.

    `assay.llm.ClaudeCLIClient` runs the CLI in the caller's working directory
    with the caller's tool permissions. Inside this repo that is enough to read
    the answer key -- verified, not assumed, by `blindness_probe`. This subclass
    disables the tools and runs from an empty scratch directory, and the two are
    belt and braces on purpose: either alone would be a single point of failure
    on a property the whole measurement rests on.
    """

    scratch: str = ""

    @property
    def name(self) -> str:
        return f"claude-cli-blind:{self.model}"

    def complete(self, system: str, user: str) -> str:
        scratch = self.scratch or tempfile.mkdtemp(prefix="assay-blind-rater-")
        try:
            proc = subprocess.run(
                [
                    "claude", "-p", "--model", self.model,
                    "--append-system-prompt", system,
                    "--disallowed-tools", *_NO_TOOLS,
                ],
                input=user,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=scratch,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LLMUnavailable(f"{self.name}: {exc}") from exc
        if proc.returncode != 0:
            raise LLMUnavailable(f"{self.name}: exit {proc.returncode}: {proc.stderr[:200]}")
        return proc.stdout


def blindness_probe(client, target: Path) -> None:
    """Ask the rater to read the answer key. Refuse to run if it can.

    A reality anchor rather than a claim: the blinding is re-tested against the
    live client at the start of every run, in the same configuration the
    labelling will use. The first version of this script had no such check, and
    the run it produced had to be thrown away.
    """
    probe = (
        f"Read the file {target} and reply with the single word FOUND followed "
        "by the first line of the CATALOG dictionary in it. If you cannot read "
        "files, reply with exactly NOTOOLS."
    )
    try:
        reply = client.complete("You are a file-reading probe.", probe)
    except LLMUnavailable as exc:
        raise SystemExit(f"blindness probe could not run: {exc}")
    if "CATALOG" in reply or "FOUND" in reply.upper():
        raise SystemExit(
            "REFUSING to label: the rater can still read the repository.\n"
            f"  probe reply: {reply.strip()[:200]}\n"
            "A 'blinded' second labelling whose rater has the answer key within "
            "reach is worse than no second labelling, because the kappa it "
            "produces looks like evidence."
        )
    print(f"blindness probe: rater cannot read {target.name} -- {reply.strip()[:80]}\n")


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


def _upstream_task_source(name: str) -> Path | None:
    """Where `inspect_evals` keeps the task, or None if it cannot be found.

    Returns None rather than raising: a bundle that is thinner than intended is
    a worse label, but a second labelling that cannot run at all produces no
    agreement number, and the absence of one is what let single-author labels
    go unchecked in the first place.
    """
    try:
        sys.path.insert(0, str(SRC))
        from assay.sweep import enumerate_tasks

        ref = next((r for r in enumerate_tasks() if r.name == name), None)
    except Exception:  # noqa: BLE001 - absence is reported, not raised
        return None
    if ref is None or not ref.source_file:
        return None
    path = Path(ref.source_file)
    return path if path.is_file() else None


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
    elif ecosystem == "inspect_evals":
        # A published eval. The thing a second reader has to judge is upstream's
        # scorer, which lives in site-packages rather than in this tree, so the
        # task module is bundled from wherever inspect_evals is installed. Our
        # provider goes in too, because it records the deterministic
        # construction (shuffle=False, fixed subsample) the reader is judging.
        parts.append(
            f"This environment is the published `inspect_evals` task '{variant}', "
            "audited as shipped. The upstream task module below defines both the "
            "dataset and the scorer; the second file is how this repository "
            "constructs it.\n"
        )
        upstream = _upstream_task_source(variant)
        if upstream is not None:
            add(upstream, f"inspect_evals/{upstream.name}")
        else:
            parts.append(
                f"(upstream source for {variant!r} not locatable in this "
                "environment; judge from the provider below alone)\n"
            )
        add(SRC / "_inspect_evals_corpus.py")
    elif ecosystem == "tau2":
        # tau2-bench, audited as shipped, and the only corpus entry whose labels
        # a third party established rather than this repository. The thing a
        # second reader has to judge is therefore the *mapping* -- how a
        # task-level "this record differs between two pinned revisions" became a
        # frozenset[DefectClass] -- not the tasks themselves.
        #
        # tau2's own content is deliberately NOT bundled. It is third-party, it
        # lives in a gitignored cache, and `src/assay/publish.py` exists to stop
        # this repository redistributing other people's benchmark content. The
        # reader gets the pinned revisions and the derivation instead, which is
        # what the label actually rests on.
        parts.append(
            f"This environment is the published tau2-bench domain '{variant}', "
            "audited as shipped. Its labels are externally derived: a task counts "
            "as a positive iff its record differs between two pinned revisions, "
            "and the files below are how that diff was turned into defect classes. "
            "tau2's own task content is not reproduced here -- it is third-party "
            "and this repository does not redistribute it.\n"
        )
        add(SRC / "tau2_truth.py")
        add(SRC / "_tau2_corpus.py")
        add(SRC / "adapters" / "tau2.py")
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
    ap.add_argument("--num-predict", type=int, default=900)
    ap.add_argument("--out", default="results/second_labelling.json")
    args = ap.parse_args()

    client = (
        BlindClaudeCLIClient()
        if args.backend == "claude"
        # `num_predict` above the client default: the reply carries a per-defect
        # reasoning map as well as the list, and a truncated JSON object parses
        # as no defects -- which would silently become a "healthy" label.
        else OllamaClient(args.model, num_predict=args.num_predict)
    )
    usable, reason = client.availability()
    if not usable:
        print(f"FAILED: {client.name} unusable: {reason}", file=sys.stderr)
        return 1
    if args.backend == "claude":
        blindness_probe(client, SRC / "fixtures" / "toy.py")
    else:
        # Ollama's HTTP completion API has no tools to disable: the model gets
        # the prompt and returns text, with no path to the filesystem. Blind by
        # construction rather than by configuration, which is why the probe is
        # not run against it.
        print(f"{client.name}: blind by construction (HTTP completion, no tools)\n")

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

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def envelope(collected: list[dict]) -> dict:
        return {
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
            "enforced_by": [
                "scripts/second_labelling.py:assert_blind -- prompt-level redaction",
                "scripts/second_labelling.py:BlindClaudeCLIClient -- no file, search "
                "or execution tools, and an empty scratch working directory outside "
                "the repository",
                "scripts/second_labelling.py:blindness_probe -- re-tested against the "
                "live client before every run; the script exits if the rater can "
                "still read the answer key",
            ],
            "rule": (
                "every line naming a DefectClass member, a catalogue, a ground-truth "
                "map or a severity table is stripped, and the script refuses to send "
                "a bundle in which any class name survives"
            ),
            "why_three_mechanisms": (
                "the first version of this script had only the redaction. Headless "
                "`claude -p` inherits the caller's working directory and tool "
                "permissions, and from inside this repo it can read "
                "src/assay/fixtures/toy.py and print the CATALOG answer key -- "
                "verified directly. That run was discarded rather than published "
                "with a caveat: 'probably did not look' is not blinding."
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
        "runs": collected,
    }

    def snapshot(completed: list[dict], done: bool) -> None:
        """Persist after every pass.

        A three-pass run over 24 environments is a couple of hours of model
        calls, and writing only at the end means a timeout or a dropped
        connection throws away every label collected so far. `complete: false`
        is carried in the file so a partial result cannot be read as a finished
        one -- `scripts/label_agreement.py` reports the run count it actually
        found rather than the one that was asked for.
        """
        body = envelope(completed)
        body["complete"] = done
        body["n_runs_completed"] = len(completed)
        out.write_text(json.dumps(body, indent=2))

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
        snapshot(runs, done=False)

    snapshot(runs, done=True)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
