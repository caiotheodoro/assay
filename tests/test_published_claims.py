"""Lock the corrections a red-team pass had to find by hand.

Each test here failed silently for weeks. They are not testing behaviour --
they are testing that a number this repository publishes is still sourced from
the artifact it claims to come from, which is the failure mode this whole
project exists to catch and did not catch in itself.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()


def _load(name: str) -> dict:
    path = ROOT / "results" / name
    if not path.exists():
        pytest.skip(f"{name} not generated")
    return json.loads(path.read_text())


def test_tau2_recall_is_reported_against_a_floor():
    """The trivial-floor rule applies to the auditor, not only to environments."""
    d = _load("tau2_recall.json")
    assert "trivial_floor" in d, "no floor reported for the external measurement"
    for row in ("combined", "combined_excluding_advisory_probe"):
        sig = d[row]["significance"]
        assert "p_one_sided" in sig and "base_rate" in sig


def test_the_headline_tau2_row_is_still_indistinguishable_from_random():
    """If this ever fails, the README's framing must change with it.

    Not a claim that 0.339 is bad -- a claim that the README currently says it
    is chance, and must not go on saying so if the measurement improves.
    """
    d = _load("tau2_recall.json")
    assert d["combined"]["significance"]["beats_random_at_0.05"] is False
    assert d["combined_excluding_advisory_probe"]["significance"]["beats_random_at_0.05"] is True
    assert "The 0.339 row is chance" in README


def test_the_corpus_split_is_published_on_provenance():
    """Split on who wrote the environment, not on the id prefix.

    Splitting on the `fixture/` prefix produced a README sentence claiming
    Assay loses on "the twelve environments this repo did not write" -- it
    wrote ten of them.
    """
    d = _load("corpus_splits.json")
    splits = d["splits"]
    assert {"external-envs", "self-authored", "third-party-format",
            "in-process-fixtures", "no-harbor"} <= set(splits)
    assert "provenance" in d, "the split is only trustworthy if provenance ships with it"

    research = splits["third-party-format"]["profiles"]["research-run"]
    # This assertion was the other way round until the two Harbor misses were
    # closed: Assay lost this split 240.0 to 114.0 and the README said so. It
    # now scores 0.0 here. Kept as an assertion rather than deleted, so a
    # regression is caught and the README is forced to change with it.
    assert research["assay"]["expected_loss"] < research["flag_everything"]["expected_loss"], (
        "Assay lost the third-party-format split again; the README claims it "
        "scores 0.0 there and must be corrected."
    )
    assert splits["in-process-fixtures"]["profiles"]["research-run"]["assay"]["expected_loss"] == 0.0


def test_the_readme_does_not_claim_a_third_party_corpus_it_does_not_have():
    """6 of 28 environments are genuinely external, and 2 are externally labelled.

    The count has moved three times: 2, then 4 when `inspect_evals/{paws,boolq}`
    were hand-triaged in, then 6 when `tau2/{retail,airline}` were registered
    under a mapping derived from a diff of two pinned revisions
    (`docs/PRE-REGISTRATION-TAU2.md`). Each move forced the README's
    honest-ceiling paragraph to be rewritten, which is the entire purpose of
    asserting a literal here rather than a bound.

    The second assertion is the one that matters more. `EXTERNAL` says this repo
    did not write the environment; it says nothing about who decided what is
    wrong with it. `EXTERNALLY_DERIVED` is the stronger claim, and this assertion
    exists because the first draft of the tau2 write-up said tau2 was the first
    use of it and that was **false** -- `openenv/textarena-wordle` has carried it
    since the OpenEnv corpus landed. The three are not the same kind of evidence
    and the README must not flatten them: wordle's label was derived here, by
    reading TextArena's own game state; tau2's was published by another
    organisation, as corrected task files, at a commit nobody here chose.
    """
    d = _load("corpus_splits.json")
    n = d["splits"]["external-envs"]["n_environments"]
    assert n == 6, (
        f"external control is n={n}; it was 2, then 4 with paws and boolq, then 6 with "
        "tau2/retail and tau2/airline. If this changed again the README's honest-ceiling "
        "paragraph must change with it."
    )

    derived = sorted(
        env
        for env, p in d["provenance"].items()
        if p["label_source"] == "externally_derived"
    )
    assert derived == ["openenv/textarena-wordle", "tau2/airline", "tau2/retail"], (
        f"environments whose labels were not decided by a judgement call here: {derived}. "
        "The README distinguishes these from the hand-triaged ones and must be corrected "
        "if the set changes."
    )
    assert "the twelve environments this repo did not write" not in README


def test_the_readme_does_not_advertise_a_signed_card():
    """It is an unkeyed digest unless ASSAY_CARD_KEY is set."""
    assert "signed Environment Card" not in README


def test_the_quickstart_command_produces_the_advertised_corpus():
    """--extra adapters alone omits openenv and audits fewer than the published 28.

    The docstring said "22 environments, not 24" from the corpus this was written
    on. `test_every_documented_headline_command_carries_the_extras_it_needs` is
    the one that checks all four extras against the current corpus; this one is
    the narrower, older assertion and is kept because it reads every `uv run`
    line in the README rather than only the ones matching a fuller pattern.
    """
    for line in README.splitlines():
        if "scripts/full_run.py" in line and "uv run" in line:
            assert "--extra openenv" in line, line


def test_the_published_example_card_matches_the_current_renderer():
    """`results/example-card.md` is the sample deliverable a judge reads.

    It is a committed artifact of a live renderer, so a field rename leaves it
    stale and nothing notices -- which is exactly what happened when
    `signature` became `content_digest`. This renders a card now and asserts
    the published one uses the same vocabulary.
    """
    from assay import audit
    from assay.card import to_markdown
    from assay.fixtures import build

    published = (ROOT / "results" / "example-card.md").read_text()
    fresh = to_markdown(audit(build("gold_broken"), {"solve_rates": {}}))

    for label in ("| Content digest |", "Produced by Assay. Unkeyed content digest"):
        assert label in fresh, f"renderer no longer emits {label!r}; update this test"
        assert label in published, (
            f"results/example-card.md is stale: the renderer emits {label!r} and the "
            "published card does not. Regenerate it with "
            "`uv run --extra adapters assay audit inspect/effort-scorer "
            "--card results/example-card.md`."
        )
    assert "| Signature |" not in published


def test_the_cost_crossover_matches_what_the_readme_claims():
    """The headline win depends on an underived constant. Lock the margin.

    `research-run.yaml` prices a missed CRITICAL at 120 and nothing derives it.
    Assay beats `flag_everything` only below the crossover, so if either the
    corpus or the profile moves, the README's "21%" stops being true and this
    is where that gets caught.
    """
    d = _load("cost_sensitivity.json")
    crossover = d["exact_crossover_critical_cost"]
    shipped = d["shipped_value"]
    assert crossover is not None, "no crossover computed; the arithmetic changed"
    assert shipped < crossover, (
        f"the shipped CRITICAL cost {shipped} is at or above the crossover "
        f"{crossover}: flag_everything now wins at the shipped profile and the "
        "README's headline is false"
    )
    margin_pct = round((crossover / shipped - 1) * 100)
    # Strip markdown emphasis: the README bolds the figure, and a test that
    # breaks on asterisks tests the formatting rather than the claim.
    plain = README.replace("*", "")
    assert f"survives a {margin_pct}% error" in plain or (
        f"survives an {margin_pct}% error" in plain
    ), f"computed margin is {margin_pct}% and the README does not say so"

    # And nowhere else may say a different one. This gate pointed only at the
    # README, so `docs/FOR_AGENTS.md`, `docs/METHOD.md` and `docs/RUBRIC.md` all
    # went on quoting a 942 crossover and an 815% margin after the taxonomy grew
    # -- three documents, none of them checked, one of them the file written to
    # be lifted by somebody else.
    others = re.compile(r"survives (?:a|an) ([0-9]{1,4})% error")
    wrong = []
    for doc in ("AGENTS.md", "llms.txt", "docs/FOR_AGENTS.md", "docs/METHOD.md",
                "docs/RUBRIC.md", "docs/RESULTS.md", "docs/REPRODUCTION.md"):
        path = ROOT / doc
        if not path.exists():
            continue
        for line in path.read_text().replace("*", "").splitlines():
            low = line.lower()
            # METHOD.md narrates the sequence 21% -> 685% -> 878% on purpose.
            if "moved" in low or "was " in low or "before" in low:
                continue
            for found in others.findall(line):
                if int(found) != margin_pct:
                    wrong.append(f"{doc}: says {found}%, the sweep says {margin_pct}%")
    assert not wrong, "stale cost-margin claims:\n  " + "\n  ".join(wrong)


def test_the_video_script_carries_no_retracted_claim():
    """The script is spoken aloud once and cannot be corrected afterwards.

    Its own header promises numbers stay `<>` until a final run freezes them.
    An earlier revision hardcoded every figure and went stale when twelve
    claims were corrected -- including the hot take, which `docs/RUBRIC.md`
    still instructs a reader to lift verbatim into the README.
    """
    video = (ROOT / "docs" / "VIDEO.md").read_text()
    retracted = [
        "not distinguishable from checking nothing",
        "not statistically distinguishable",
        "Recall a third.",
        "41 findings",
        "would score respectably",
    ]
    found = [phrase for phrase in retracted if phrase in video]
    assert not found, f"VIDEO.md still speaks retracted claims: {found}"


def test_the_llm_baseline_arm_survives_an_adapter_that_refuses_verify():
    """One refusing adapter must not take the whole corpus run down.

    `ToolAgentArm` called `adapter.verify()` unguarded, so `OpenEnvAdapter` --
    which computes reward inside `step()` and raises `NotSupported` -- crashed
    `full_run.py --llm-arms` outright. That is why the brief's own simple
    baseline was implemented and never scored: the command did not complete.
    """
    import inspect as pyinspect

    from assay.baselines import llm

    src = pyinspect.getsource(llm)
    assert "except NotSupported" in src, (
        "the LLM arm calls adapter.verify() with no refusal path; an adapter "
        "that withholds SEPARABLE_VERIFIER will crash the whole run"
    )
    assert "reward_basis" in src, (
        "when the verifier is unavailable the arm must record which source the "
        "number came from -- a silently unscored baseline is the defect this "
        "repository audits environments for"
    )


def test_the_llm_baseline_rows_match_the_measured_file():
    """The brief's own baseline, scored, with the README quoting the artifact.

    Reads `full_run.json`, deliberately -- the SAME file every other arm in
    that table comes from. The LLM rows used to be quoted from a separate
    24-environment `full_run_llm.json` while the rest of the table was 26, a
    comparison printed as one table and measured as two. Pinning both to one
    file is what stops that recurring, so this test asserts the arms are
    present there rather than merely present somewhere.
    """
    d = _load("full_run.json")
    arms = d["arms"]
    for name in ("direct_prompt", "agent_with_tools"):
        assert name in arms, (
            f"{name} is not in results/full_run.json -- re-run "
            f"scripts/full_run.py --llm-arms qwen3:8b so every arm shares a corpus"
        )
        assert f"{arms[name]['expected_loss']:.1f}" in README, (
            f"{name} scored {arms[name]['expected_loss']} and the README does not say so"
        )

    # Same corpus for every arm, checked rather than assumed.
    iv = _load("intervals.json")
    for name in ("direct_prompt", "agent_with_tools"):
        assert name in iv["arms"], f"{name} has no bootstrap interval"
        assert iv["arms"][name]["expected_loss"]["ci95"], f"{name} has an empty CI"

    # The claim the rows are there to support. It USED to be
    # `direct_prompt > stratified_random` -- the LLM arm losing outright to
    # flagging at base rates, separated at [201, 1627]. That flipped when the
    # taxonomy went 14 -> 16 classes: `stratified_random` draws one
    # `rng.random()` per class per environment in enum order, so two more
    # classes reshuffled its whole seeded sequence and cost it +878 with no
    # change to the corpus, the policy or the detector.
    #
    # The honest claim is now the weaker one, and it is what the README says:
    # the two are not distinguishable. Asserted on the paired bootstrap rather
    # than on the point estimates, because that is the claim -- and because
    # asserting the new ordering would be asserting one draw of a stochastic
    # baseline, which is the substitution this repo objects to elsewhere.
    paired = iv["arms"]["direct_prompt"]["loss_saved_vs"]["stratified_random"]
    assert not paired["separated"], (
        f"direct_prompt vs stratified_random has separated ({paired['point']} "
        f"{paired['ci95']}); the README says the two are indistinguishable and must "
        "be corrected in whichever direction this went"
    )
    assert "indistinguishable from" in README


def test_the_method_protocol_quotes_numbers_that_still_hold():
    """docs/METHOD.md is the framing artifact; its numbers must stay sourced.

    It is the one document written to be lifted by someone else, so a figure
    that drifts there is worse than a figure that drifts in the README.
    """
    method = (ROOT / "docs" / "METHOD.md").read_text()

    # Prose rounds; the artifacts do not. Compare at the precision a sentence
    # would actually use, or the test measures formatting rather than truth.
    tau2 = _load("tau2_recall.json")
    for row in ("combined", "combined_excluding_advisory_probe"):
        p_val = tau2[row]["significance"]["p_one_sided"]
        assert f"{p_val:.3f}" in method, f"{row}: p={p_val} not quoted in METHOD.md"

    cost = _load("cost_sensitivity.json")
    assert f"{cost['exact_crossover_critical_cost']:.0f}" in method, (
        "the crossover moved and METHOD.md still quotes the old one"
    )

    splits = _load("corpus_splits.json")
    assert str(splits["splits"]["external-envs"]["n_environments"]) in method

    iv = _load("intervals.json")
    saved = iv["arms"]["assay"]["loss_saved_vs"]["flag_everything"]
    assert saved["separated"], "METHOD.md claims the detector separates from its floor"
    assert f"{saved['point']:.1f}" in method


def test_the_outward_floor_test_quotes_its_own_artifact():
    """METHOD.md makes a claim about someone else's paper. Keep it sourced."""
    d = _load("floor_of_the_field.json")
    method = (ROOT / "docs" / "METHOD.md").read_text()
    for row in d["rows"]:
        knee = row["stops_clearing_the_floor_at_or_above"]
        assert knee, f"{row['claim']}: no knee computed"
        assert str(knee) in method, (
            f"{row['claim']}: knee {knee} not quoted in METHOD.md"
        )
        # The claim is about reportability, not about anyone's care. If a flag
        # count ever becomes recoverable, this stops being the right framing.
        assert row["n_flagged_is_reported"] is False


def test_the_coverage_matrix_names_every_defect_class_and_flaw_class():
    """docs/COVERAGE.md states what the tool cannot see. Keep it complete.

    A coverage document that silently drops a class is worse than none: the
    omission reads as coverage. Both directions are checked, because a
    one-directional map is always the flattering one.
    """
    from assay.types import DefectClass

    coverage = (ROOT / "docs" / "COVERAGE.md").read_text()
    for cls in DefectClass:
        assert cls.value in coverage, f"COVERAGE.md does not mention {cls.value}"
    for v in range(1, 9):
        assert f"**V{v}**" in coverage, f"COVERAGE.md does not cover BenchJack V{v}"


def test_the_coverage_matrix_agrees_with_the_shipped_miss():
    """Its central example must stay the environment actually missed."""
    fr = _load("full_run.json")
    missed = {e: r["missed"] for e, r in fr["per_env"].items() if r["missed"]}
    coverage = (ROOT / "docs" / "COVERAGE.md").read_text()
    assert missed == {"inspect_evals/boolq": ["SHORTCUT_LEAK"]}, (
        f"the corpus miss set changed to {missed}; COVERAGE.md's closing "
        "example and the README both describe the old one"
    )
    assert "inspect_evals/boolq" in coverage


# --- Gates added after two dead paths shipped in the reviewer-facing docs -----
#
# `docs/FOR_AGENTS.md` told a reviewer "every claim cites a file you can open"
# while citing seven paths that did not resolve, two of them inside the block a
# reviewer is invited to run. Nothing checked, so nothing caught it. These two
# tests are the check.

DOCS_THAT_CITE_PATHS = (
    "README.md",
    "AGENTS.md",
    "docs/FOR_AGENTS.md",
    "docs/RUBRIC.md",
)

# Prefixes belonging to somebody else's repository. Cited on purpose, not
# vendored here -- see docs/LINEAGE.md, which keeps "read, not vendored"
# separate from "vendored with attribution".
EXTERNAL_PREFIXES = ("third_party/", "BenchGuard/", "eval/")

_CITATION = re.compile(
    r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\."
    r"(?:md|py|json|jsonl|ts|tsx|mjs|yaml|yml|cast|html|toml|lock|cff|txt))"
    r"(?::[0-9]+(?:-[0-9]+)?)?`"
)

def test_every_file_path_cited_in_the_reviewer_docs_resolves():
    """A citation a reviewer cannot open is worse than no citation.

    The whole argument of these documents is "do not trust the prose, open the
    file". That argument inverts the moment a path is wrong: one dead link and a
    reader is entitled to assume the rest are decorative too.
    """
    broken: list[str] = []
    for doc in DOCS_THAT_CITE_PATHS:
        doc_path = ROOT / doc
        if not doc_path.exists():
            continue
        for cited in sorted(set(_CITATION.findall(doc_path.read_text()))):
            # A bare filename is a mention, not a citation: `expected.txt` is a
            # file the reward-hack exploit writes inside a sandbox, and
            # `match.py` lives in BenchGuard's tree. Only a path with a
            # directory component is a claim about *this* repository.
            if "/" not in cited:
                continue
            if cited.startswith(EXTERNAL_PREFIXES):
                continue
            if not (ROOT / cited).exists():
                broken.append(f"{doc} cites {cited!r}, which does not exist")
    assert not broken, "dead citations:\n  " + "\n  ".join(broken)

def test_the_suite_size_the_docs_advertise_is_the_suite_size_that_ran(request):
    """Three documents said 589 while two others said 591, for the same suite.

    `docs/CHANGELOG.md` slice 38c records fixing exactly this -- three live
    present-tense claims of 513 against a suite of 589 -- and it came back,
    because the fix was a careful edit and not a gate. The number is checked
    against the collection that is running this assertion, so it cannot drift
    from the suite again without failing.
    """
    # A reduced-extras run collects fewer tests for a good reason, and the docs
    # are not wrong when it does. `uv sync --extra dev` alone collects 498 of
    # 593; only the full optional set makes the advertised number meaningful.
    pytest.importorskip("inspect_evals", reason="needs --extra sweep")
    pytest.importorskip("openenv", reason="needs --extra openenv")

    collected = request.session.testscollected
    if collected < 400:
        pytest.skip(f"partial run ({collected} collected); only meaningful on the full suite")

    live_docs = (
        "README.md",
        "AGENTS.md",
        "docs/FOR_AGENTS.md",
        "docs/REPRODUCTION.md",
        "docs/ARCHITECTURE.md",
        "docs/RUBRIC.md",
    )
    # "N passed" in a live doc is a present-tense claim about this suite.
    # docs/CHANGELOG.md and docs/RED-TEAM.md are excluded wholesale: they are
    # historical records, and their old numbers are the point of keeping them.
    # Inside a live doc the same distinction is drawn per line -- a sentence that
    # says when it was true is a record, not a promise.
    claim = re.compile(r"\b([0-9]{3,4}) passed\b")
    HISTORICAL = (
        "at the time",
        "an earlier",
        "earlier revision",
        "before the suite grew",
        "previously",
        "historical",
    )

    wrong: list[str] = []
    for doc in live_docs:
        doc_path = ROOT / doc
        if not doc_path.exists():
            continue
        for line in doc_path.read_text().splitlines():
            # A heading can retire everything under it. docs/RUBRIC.md keeps its
            # superseded 74/100 scorecard in full, and every number below that
            # heading is a record of what was true then.
            low = line.lower()
            if low.startswith("#") and ("historical" in low or "superseded" in low):
                break
            if any(marker in low for marker in HISTORICAL):
                continue
            for number in set(claim.findall(line)):
                if int(number) != collected:
                    wrong.append(
                        f"{doc}: {number!r} passed is claimed in the present tense; "
                        f"the suite collected {collected}  --  {line.strip()[:90]}"
                    )
    assert not wrong, "stale suite-size claims:\n  " + "\n  ".join(wrong)

def test_every_cited_path_is_actually_in_the_repository_a_judge_clones():
    """Existing on this disk is not the same as existing in the clone.

    `docs/FOR_AGENTS.md` invited a reviewer to run
    `node video/capture/check-shot-reality.mjs` and cited
    `video/src/components/Panels.tsx` as evidence. Both are real files here and
    neither is tracked, so in a fresh clone the command fails and the citation
    points at nothing. A filesystem check cannot see that; only git can.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git
        pytest.skip("git unavailable")
    if out.returncode != 0:
        pytest.skip("not a git checkout")

    tracked = set(out.stdout.split("\n"))
    untracked: list[str] = []
    for doc in DOCS_THAT_CITE_PATHS:
        doc_path = ROOT / doc
        if not doc_path.exists():
            continue
        for cited in sorted(set(_CITATION.findall(doc_path.read_text()))):
            if "/" not in cited or cited.startswith(EXTERNAL_PREFIXES):
                continue
            if not (ROOT / cited).exists():
                continue  # the sibling test owns that failure
            if cited not in tracked:
                untracked.append(f"{doc} cites {cited!r}, which is not tracked by git")
    assert not untracked, (
        "citations that exist here but not in a clone:\n  "
        + "\n  ".join(untracked)
        + "\n\nA reviewer clones the repository. Either `git add` these paths or stop citing them."
    )


def test_the_externally_labelled_count_is_the_one_in_the_registry():
    """"Third-party" and "labelled by a third party" are different claims.

    Six of the 28 environments are `EnvAuthor.EXTERNAL`. Only three carry
    ground truth this repository did not produce -- `openenv/textarena-wordle`
    and the two tau2 domains, whose labels come from a diff of two pinned
    upstream revisions. The other three are external environments that *we*
    hand-triaged, which is a weaker thing and reads as a stronger one.

    The README said two. It was neither the registry's number nor any split's
    number, and nothing was checking it.
    """
    splits = json.loads((ROOT / "results" / "corpus_splits.json").read_text())
    prov = splits["provenance"]
    external = [k for k, v in prov.items() if v["env_author"] == "external"]
    derived = [k for k, v in prov.items() if v["label_source"] == "externally_derived"]

    claim = f"{len(external)} of {len(prov)} genuinely third-party, {len(derived)} of them externally"
    assert claim in README, (
        f"the README does not carry the registry's own counts: expected "
        f"{claim!r} (external={sorted(external)}, externally_derived={sorted(derived)})"
    )


def test_the_results_doc_carries_every_arm_it_claims_to_explain():
    """`docs/RESULTS.md` is linked as "every number, with its caveats".

    It drifted once and badly: the corpus grew to 28 environments and that file
    kept the whole 26-environment table, so a judge following the README's own
    "Start here" link landed on eight arm values that contradicted the README
    two clicks earlier. Nothing was checking it, because the gates all pointed
    at the README.

    Every arm in the measured file has to appear in the doc that explains the
    arms. It does not fix a wrong *caveat*, but it makes a stale *table*
    impossible.
    """
    run = json.loads((ROOT / "results" / "full_run.json").read_text())
    doc = (ROOT / "docs" / "RESULTS.md").read_text()
    missing = [
        f"{name}={arm['expected_loss']}"
        for name, arm in sorted(run["arms"].items())
        if f"{arm['expected_loss']}" not in doc
    ]
    assert not missing, (
        "docs/RESULTS.md does not carry these measured arm values: "
        + ", ".join(missing)
    )


def test_every_assay_audit_command_in_a_live_doc_names_a_real_environment():
    """A command a reader can copy has to be one that runs.

    The README gained an "agent, in one command" block and the first draft of it
    said `assay audit inspect_evals/personality_BFI --auditor`. That environment
    is deliberately **not** registered -- `docs/COVERAGE.md` argues at length
    that an environment the tool is wrong about does not belong in the corpus
    used to measure the tool -- so the command printed `unknown environment` and
    a list. Publishing it would have been worse than publishing nothing: a judge
    running the one command the README offers for its headline agent result and
    watching it fail reads everything after it differently.

    Historical documents are exempt for the usual reason: they record commands
    that were true when they were written.
    """
    from assay.corpus import entries

    known = {env_id for env_id, _, _ in entries()}
    pattern = re.compile(r"assay audit\s+([A-Za-z0-9_][\w./-]*)")
    live = [
        "README.md", "AGENTS.md", "docs/FOR_AGENTS.md", "docs/REPRODUCTION.md",
        "docs/RESULTS.md", "docs/METHOD.md",
    ]
    bad = []
    for name in live:
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            for env in pattern.findall(line):
                if env.startswith("-") or env in ("--help",):
                    continue
                if env not in known:
                    bad.append(f"{name}: `assay audit {env}` -- not a registered environment")
    assert not bad, "commands a reader cannot run:\n  " + "\n  ".join(bad)


# --- The gate for the failure that has now happened twice ---------------------
#
# The corpus went 26 -> 28 and the taxonomy 14 -> 16. `README.md` and
# `docs/RESULTS.md` were corrected; six other reader-facing documents were not,
# and a judge reading cold landed on them by following the README's own "Start
# here" table -- which sends you to two documents that contradict the README's
# headline. The sibling gate above fixed exactly one of those documents, by name.
# This one takes the general case: any live document that puts a number next to
# an arm has to put the measured one there.

# The documents a reader is sent to. Records are excluded wholesale -- their old
# numbers are the point of keeping them: `docs/RED-TEAM.md`,
# `docs/RETRACTIONS.md`, `docs/history/`, `docs/changelog/` and both
# pre-registrations, which are predictions made before the numbers moved and must
# never be rewritten to match them. `docs/CHANGELOG.md` is listed rather than
# excluded because its Baseline -> Final table is a live claim; everything below
# its "Every slice -- the historical record" heading is retired by the heading
# rule, the same way `docs/RUBRIC.md` retires its superseded scorecard.
LIVE_DOCS = (
    "README.md",
    "AGENTS.md",
    "llms.txt",
    "docs/FOR_AGENTS.md",
    "docs/RESULTS.md",
    "docs/METHOD.md",
    "docs/RUBRIC.md",
    "docs/ARCHITECTURE.md",
    "docs/REPRODUCTION.md",
    "docs/COVERAGE.md",
    "docs/CHANGELOG.md",
    "space/app.py",
    "space/static/index.template.html",
)

# The suite-size gate's list, plus the phrasings this sweep actually found in
# use. A sentence that says when it was true is a record, not a promise.
RETIRED = (
    "at the time",
    "an earlier",
    "earlier revision",
    "before the suite grew",
    "previously",
    "historical",
    "superseded",
    "used to",
    "at that revision",
    "it originally",
    "prediction held",
    "predicted",
)

# A number in the shape a loss is written in. Two digits are not enough to be one
# of these losses, and one decimal place is as far as any of these documents goes.
_LOSS = re.compile(r"(?<![\w.])(\d{1,4}(?:\.\d)?)(?![\w.\d])")
# `flag_everything` **394.0** -- the arm, then punctuation, then its number.
_QUOTES_IT = re.compile(r"[`*\s:=,—-]{1,4}\*{0,2}\d")
# "assay vs `flag_everything` 351.0" prices the *difference*, not the arm named
# second, and "`check_env` saves 16.0" prices a saving. Neither is a claim about
# that arm's own expected loss, and reading them as one turns every paired
# difference table in docs/RESULTS.md into a false alarm.
_OTHER_HALF = re.compile(r"(?:vs|versus|against|saved|saves|over|than)\W{0,8}$", re.I)
_THE_SAVING = re.compile(r"^[`*\s,]{0,4}(?:saves?|saved)\b", re.I)


def _arms_priced_on(line: str, context: str, arm_res: dict) -> set[str]:
    """Arms this line gives a loss to, as opposed to arms it merely names."""
    low, ctx = line.lower(), context.lower()
    offset = len(ctx) - len(low)
    priced: set[str] = set()

    def its_own(m: "re.Match[str]") -> bool:
        before = ctx[max(0, offset + m.start() - 20) : offset + m.start()]
        return not _OTHER_HALF.search(before) and not _THE_SAVING.match(low[m.end() :])

    cells = [c.strip() for c in line.split("|")] if line.lstrip().startswith("|") else []
    # A table row whose first cell is a short label naming one arm is that arm's
    # row. The length cap is load-bearing: `docs/ARCHITECTURE.md` has a review
    # table whose first cell is a paragraph that happens to say "Assay".
    if len(cells) >= 3 and len(cells[1]) <= 80 and " vs " not in cells[1].lower():
        for arm, rx in arm_res.items():
            if rx.search(cells[1].lower()):
                priced.add(arm)
    for arm, rx in arm_res.items():
        for m in rx.finditer(low):
            if its_own(m) and _QUOTES_IT.match(low[m.end() :]):
                priced.add(arm)
    # A sentence that says "expected loss" out loud is quoting one whether or not
    # the number sits against the name: `llms.txt` said "Assay scores an expected
    # loss of 40.0" with six words in between, and nothing caught it.
    if "expected loss" in low:
        for arm, rx in arm_res.items():
            if any(its_own(m) for m in rx.finditer(low)):
                priced.add(arm)
    return priced


def test_no_live_document_prices_an_arm_at_a_number_that_is_no_longer_measured():
    """Every reader-facing document, checked against `results/full_run.json`.

    This is the recurring failure in this repository and no person has ever
    caught it: a measurement moves, the README is corrected, and the documents
    downstream of it keep the old figure until somebody reads them cold. It
    happened at 24 -> 26 (`docs/CHANGELOG.md` slice 22f: three claims corrected
    in one place and left standing in the document people actually read) and
    again at 26 -> 28, across six documents at once -- including the required
    improvement changelog and the deployed demo, which was still telling
    visitors the trivial floor beat the tool outright.

    The rule is narrow on purpose, because a gate that cries wolf gets deleted:
    a line that puts a loss-shaped number against an arm's name must put the
    measured one there. It does not police paired differences, per-profile rows
    or intervals -- those have their own artifacts and their own gates -- and it
    retires a line the moment the prose says when it was true, using the marker
    list and heading rule the suite-size gate already uses. Whole documents that
    exist to hold old numbers are excluded by not being listed.
    """
    run = json.loads((ROOT / "results" / "full_run.json").read_text())
    current = {name: arm["expected_loss"] for name, arm in run["arms"].items()}
    arm_res = {a: re.compile(rf"(?<![a-z_]){a}(?![a-z_])") for a in current}
    # Prose calls the arm under test "Assay", which is also the tool's own name.
    arm_res["assay"] = re.compile(r"(?<![a-z_])assay(?![a-z_])")

    stale: list[str] = []
    for doc in LIVE_DOCS:
        path = ROOT / doc
        if not path.exists():
            continue
        previous = ""
        for number, line in enumerate(path.read_text().splitlines(), 1):
            low = line.lower()
            if low.startswith("#") and ("historical" in low or "superseded" in low):
                break
            # Two lines of context, because a sentence that retires its own
            # numbers often wraps before it reaches them, and because a bullet
            # can put "assay vs" on one line and the figure on the next.
            context, previous = f"{previous} {line}", line
            if "→" in context:
                continue  # "290.0 → 316.0" records a move; it does not claim one
            if any(marker in context.lower() for marker in RETIRED):
                continue
            priced = _arms_priced_on(line, context, arm_res)
            if not priced:
                continue
            written = {n for n in _LOSS.findall(line) if "." in n or len(n) >= 3}
            if not written:
                continue
            measured = {
                s for a in priced for s in (f"{current[a]:.1f}", f"{current[a]:.0f}")
            }
            if written & measured:
                continue
            stale.append(
                f"{doc}:{number}: prices {', '.join(sorted(priced))} at "
                f"{sorted(written)}; the measured value is {sorted(measured)}"
                f"  --  {line.strip()[:90]}"
            )
    assert not stale, (
        "live documents quoting an arm value results/full_run.json does not "
        "support:\n  " + "\n  ".join(stale)
    )


def test_the_agent_measurements_are_gated_like_every_other_number():
    """The one row that most needed a gate was the one row without one.

    This file gates arm values, cited paths, suite size and the cost crossover.
    It gated nothing in `results/semantic_gate.json` or
    `results/policy_synthesis.json` -- the two artifacts behind the agent claims,
    which is the criterion this submission is weakest on and the one where a
    wrong number costs most.

    A judge found the consequence: the semantic gate's size was stated three
    incompatible ways across the README and two other live documents, none of
    them the artifact's. The corpus grew 15 -> 20 environments when the Harbor
    negatives were added and only some of the prose followed.
    """
    gate = json.loads((ROOT / "results" / "semantic_gate.json").read_text())
    synth = json.loads((ROOT / "results" / "policy_synthesis.json").read_text())

    backends = [b for b in gate["backends"].values() if "rows" in b]
    assert backends, "semantic_gate.json carries no measured backend"
    n_pos = {b["n_positive"] for b in backends}
    n_neg = {b["n_negative"] for b in backends}
    assert len(n_pos) == 1 and len(n_neg) == 1, "backends disagree on the corpus size"
    pos, neg = n_pos.pop(), n_neg.pop()
    total = pos + neg

    # Same marker vocabulary the suite-size gate uses; a sentence that says
    # when it was true is a record, not a promise.
    historical = ("at the time", "an earlier", "earlier revision",
                  "before the suite grew", "previously", "historical")
    live = ["README.md", "docs/REPRODUCTION.md", "AGENTS.md", "docs/FOR_AGENTS.md",
            "docs/RESULTS.md", "results/trajectories/INDEX.md"]
    bad = []
    for name in live:
        path = ROOT / name
        if not path.exists():
            continue
        text = path.read_text()
        for line in text.splitlines():
            low = line.lower()
            if any(m in low for m in historical):
                continue
            # A line that sizes the gate must size it correctly.
            m = re.search(r"(\d+)\s+environments\s*[-—,]\s*(\d+) with no correct answer", line)
            if m and (int(m.group(1)), int(m.group(2))) != (total, pos):
                bad.append(f"{name}: says {m.group(1)}/{m.group(2)}; the artifact is {total}/{pos}")
            # A false-positive denominator must be the measured run count.
            for fp in re.findall(r"fp\s+\d+\s*/\s*(\d+)", line):
                measured = {str(b["negative_runs"]) for b in backends}
                if fp not in measured:
                    bad.append(f"{name}: fp denominator {fp}; measured {sorted(measured)}")

    floor = synth["floor"]["n_detected"]
    assert f"{floor} / 25" in (ROOT / "README.md").read_text() or f"{floor}/25" in (
        ROOT / "README.md"
    ).read_text(), f"the README does not carry the scripted floor of {floor}/25"

    # The scripted floor's timing was invented once and lived in four documents
    # (docs/changelog/108). It is measured now, so nothing may quote the old one.
    floor_secs = json.loads((ROOT / "results" / "scripted_floor.json").read_text())
    measured = floor_secs["measured"]["seconds"]
    retracted = re.compile(r"~2s|\b2s vs 26\ds\b|about \*\*2 seconds\*\*")
    for name in live + ["docs/RUBRIC.md"]:
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if any(m in line.lower() for m in historical):
                continue
            if retracted.search(line):
                bad.append(
                    f"{name}: quotes the retracted ~2s scripted floor; "
                    f"results/scripted_floor.json measured {measured}s"
                )

    assert not bad, "agent measurements misstated:\n  " + "\n  ".join(bad)


def test_every_documented_headline_command_carries_the_extras_it_needs():
    """The documented command did not reproduce the documented number.

    A judge ran it from a fresh clone and got **24 environments, 48 defects,
    assay 0.0 at recall 1.000** against the published 28 / 54 / 43.0. Two causes,
    both invisible on a machine that had ever installed anything else:
    `--extra sweep` was missing, dropping the two `inspect_evals` environments
    including `boolq`, the single documented miss; and `tau2` imports `toml` at
    module scope, which was only reaching the venv as a transitive dependency of
    `inspect_evals`.

    Both flattering. The environments a missing provider takes with it are the
    ones Assay does worst on, so the reduced run produced a *better* number and
    exited 0. `scripts/full_run.py` now refuses that outright; this stops the
    documents drifting back.
    """
    needed = {"adapters", "sweep", "openenv", "tau2"}
    pattern = re.compile(r"uv run((?: --extra [\w-]+)+) python scripts/full_run\.py")
    # docs/RESULTS.md was not on this list and printed the two-extra command
    # directly under "28 environments, 54 planted defects" -- the same flattering
    # 24/48 run this test was written for, in the document the README sends a
    # reader to for "every number, with its caveats".
    live = ["README.md", "AGENTS.md", "docs/FOR_AGENTS.md", "docs/REPRODUCTION.md",
            "docs/RESULTS.md"]
    bad = []
    for name in live:
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            low = line.lower()
            if any(m in low for m in ("at the time", "an earlier", "previously", "historical")):
                continue
            for extras in pattern.findall(line):
                have = set(re.findall(r"--extra ([\w-]+)", extras))
                missing = needed - have
                if missing:
                    bad.append(f"{name}: full_run command missing {sorted(missing)} -- {line.strip()[:80]}")
    assert not bad, (
        "documented commands that do not produce the documented corpus:\n  "
        + "\n  ".join(bad)
    )


# The words a separation can be pronounced in, and which way each one reads.
# `separated` is the artifact's own field: the paired interval excludes zero.
_SEPARATED = re.compile(r"\bseparated\b|\bseparates\b|\bseparating\b", re.I)
#: How far from a separation word an arm name may sit and still be what the
#: word is about. Wide enough for "`stratified_random`'s 2793.0 -- and that gap
#: is now separated ... over `direct_prompt`", which is the sentence this gate
#: was written for; narrow enough that the next sentence along cannot supply
#: the second arm.
_REACH = 120
_NOT_SEPARATED = re.compile(
    r"\bnot separated\b|\bnot separate\b|\bdoes not separate\b"
    r"|\bdid not separate\b|\bnever separated\b|\boverlaps zero\b"
    r"|\bcross(?:es|ing)? zero\b|\bincludes? zero\b|\bincluding zero\b"
    r"|\bindistinguishable\b",
    re.I,
)


def test_a_separation_claimed_in_prose_is_the_one_the_bootstrap_recorded():
    """The sign was right and the verdict was backwards, in the file judges read.

    `docs/RESULTS.md` said stratified random *saves* 869.0 over `direct_prompt`
    and that the pair was separated. `results/intervals.json` says the opposite
    on both counts: `direct_prompt` saves 339.0 on [-244, 942] with
    `separated: false`. Every arm value on that page was gated, and the word
    that decides what those values *mean* was not, so a document could invert a
    published result with every number in it still sourced.

    The rule: prose naming exactly two arms and pronouncing on separation must
    pronounce what `loss_saved_vs[...]["separated"]` says. Exactly two, because
    a sentence sweeping over several arms at once is not making a pairwise
    claim -- "wins all four and separates on all four" names one arm and a
    count of profiles, and belongs to the per-profile gate, not this one. The
    marker list and heading rule retire a line that says when it was true.

    Two scopes, because prose and tables put the claim together differently.

    A paired-difference table row carries the whole comparison on one line, so
    a row naming two arms and a verdict is read on its own and nothing outside
    it can bleed in. Wrapped prose does not: the sentence this test exists for
    put "separated" on one line, `direct_prompt` on the next and
    `agent_with_tools` on the one after, so a line-only reading walks straight
    past the bug it was written to catch. For prose the paragraph is flattened
    and each separation word is attached to the two arm names *nearest to it*,
    within `_REACH` characters -- which is also what stops a paragraph's
    unrelated neighbouring sentence supplying the second arm. A paragraph where
    any line resolves on its own is treated as a table and never window-read.
    """
    intervals = json.loads((ROOT / "results" / "intervals.json").read_text())
    arms = intervals["arms"]
    arm_res = {a: re.compile(rf"(?<![a-z_]){a}(?![a-z_])") for a in arms}
    arm_res["assay"] = re.compile(r"(?<![a-z_])assay(?![a-z_])")

    def pair_on(scope: str) -> tuple[list[str], bool] | None:
        """`([arm, arm], separation was claimed)` for a line that self-resolves."""
        low = scope.lower()
        if any(marker in low for marker in RETIRED):
            return None
        claims_not = bool(_NOT_SEPARATED.search(low))
        if not claims_not and not _SEPARATED.search(low):
            return None
        named = sorted(a for a, rx in arm_res.items() if rx.search(low))
        return (named, not claims_not) if len(named) == 2 else None

    def pairs_near(flat: str):
        """Each verdict in a paragraph, with the two arm names closest to it."""
        low = flat.lower()
        at = [(m.start(), a) for a, rx in arm_res.items() for m in rx.finditer(low)]
        for m in re.finditer(
            rf"{_NOT_SEPARATED.pattern}|{_SEPARATED.pattern}", low, re.I
        ):
            window = low[max(0, m.start() - _REACH) : m.end() + _REACH]
            if any(marker in window for marker in RETIRED):
                continue
            near = sorted(
                {a for where, a in at if abs(where - m.start()) <= _REACH},
                key=lambda a: min(
                    abs(w - m.start()) for w, name in at if name == a
                ),
            )
            if len(near) != 2:
                continue
            yield sorted(near), not _NOT_SEPARATED.search(m.group(0))

    wrong: list[str] = []
    for doc in LIVE_DOCS:
        path = ROOT / doc
        if not path.exists():
            continue
        body = path.read_text()
        cut = re.search(r"(?im)^#+ .*(historical|superseded).*$", body)
        if cut:
            body = body[: cut.start()]
        for paragraph in body.split("\n\n"):
            lines = paragraph.splitlines()
            resolved = [(n, ln, pair_on(ln)) for n, ln in enumerate(lines)]
            rows = [(n, ln, r) for n, ln, r in resolved if r]
            claims = (
                [(ln, r) for _, ln, r in rows]
                if rows
                else [(paragraph, r) for r in pairs_near(" ".join(lines))]
            )
            for shown, ((first, second), claimed) in claims:
                measured = arms[first]["loss_saved_vs"][second]["separated"]
                if measured is claimed:
                    continue
                where = body[: body.index(paragraph)].count("\n") + 1
                wrong.append(
                    f"{doc}:~{where}: calls {first} vs {second} "
                    f"{'separated' if claimed else 'not separated'}; "
                    f"results/intervals.json records separated={measured}"
                    f"  --  {' '.join(shown.split())[:100]}"
                )
    assert not wrong, (
        "live documents pronouncing a separation the bootstrap does not:\n  "
        + "\n  ".join(wrong)
    )


# The k=1 semantic-gate figures, retracted in `README.md` as "wrong in both
# directions" and re-measured at k=3 in `docs/changelog/107-semantic-gate-
# remeasured.md`. Written the several ways this sweep found them still in use,
# including the two argparse `help=` strings.
_RETRACTED_K1 = re.compile(
    r"\b[01][- ]of[- ]1\b|\b13[- ]environment|\bin 39\b"
    r"|\b4 of 6 runs\b|\b2 false overrides\b",
    re.I,
)
# Only lines that are talking about the gate: "1 of 1" is an ordinary phrase.
_ABOUT_THE_GATE = re.compile(
    r"semantic[_ ]gate|auditor|personality_bfi|override", re.I
)


def _k1_offences(text: str, where: str) -> list[str]:
    """Retracted figures on a line, in text that is talking about the gate.

    The topic is read over three lines either side and the figure over one.
    `AGENTS.md` wrapped "1 of 1 with 0 false / overrides" across a line break,
    so a line-scoped topic test walked past the very instance this was written
    for; a line-scoped *figure* test is what keeps "1 of 1" from being an
    ordinary phrase anywhere else. A retired marker on the line retires it --
    the README's own retraction of these numbers has to survive this gate.
    """
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        low = line.lower()
        if any(marker in low for marker in RETIRED):
            continue
        if not _RETRACTED_K1.search(low):
            continue
        about = " ".join(lines[max(0, index - 3) : index + 4]).lower()
        if _ABOUT_THE_GATE.search(about):
            found.append(f"{where}:{index + 1}: {line.strip()[:100]}")
    return found


def test_the_retracted_k1_semantic_gate_figures_are_gone_including_from_help():
    """A retraction that does not reach the CLI has not landed.

    `README.md` retracts the 1-of-1 / 0-of-1 gate numbers as a single draw over
    13 environments and "wrong in both directions". They kept shipping in
    `src/assay/cli.py` twice -- the second printed by `assay audit --help`,
    where a user meets it -- and in `AGENTS.md` and `docs/COVERAGE.md`, while
    the README carried a third unretracted variant of its own. Every other gate
    in this file reads documents. A string a program prints is a published
    claim too, and nothing was reading those.

    Checked against the source and against the help text argparse actually
    renders, so a figure cannot survive by hiding in a `help=` kwarg.
    """
    gate = json.loads((ROOT / "results" / "semantic_gate.json").read_text())
    backends = [b for b in gate["backends"].values() if "rows" in b]
    assert backends, "semantic_gate.json carries no measured backend"
    assert gate["k"] == 3, "the gate is no longer measured at k=3; re-read this test"
    sized = backends[0]["n_positive"] + backends[0]["n_negative"]

    offences: list[str] = []
    for doc in (*LIVE_DOCS, "src/assay/cli.py", "src/assay/auditor.py"):
        path = ROOT / doc
        if path.exists():
            offences += _k1_offences(path.read_text(), doc)

    from assay.cli import main as cli_main

    for argv in (["--help"], ["audit", "--help"]):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
            cli_main(argv)
        offences += _k1_offences(buf.getvalue(), f"assay {' '.join(argv)}")

    assert not offences, (
        "the retracted k=1 semantic-gate figures are still published; "
        f"results/semantic_gate.json measures k={gate['k']} over {sized} "
        "environments:\n  " + "\n  ".join(offences)
    )
