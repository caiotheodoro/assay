"""Lock the corrections a red-team pass had to find by hand.

Each test here failed silently for weeks. They are not testing behaviour --
they are testing that a number this repository publishes is still sourced from
the artifact it claims to come from, which is the failure mode this whole
project exists to catch and did not catch in itself.
"""

from __future__ import annotations

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
    wrong with it. Only `EXTERNALLY_DERIVED` does, and until tau2 was registered
    nothing in the corpus carried it -- every "external" label was still a
    judgement made here, by hand, against somebody else's scorer.
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
    assert derived == ["tau2/airline", "tau2/retail"], (
        f"environments whose labels a third party established: {derived}. The README "
        "distinguishes these from the hand-triaged ones and must be corrected if the "
        "set changes."
    )
    assert "the twelve environments this repo did not write" not in README


def test_the_readme_does_not_advertise_a_signed_card():
    """It is an unkeyed digest unless ASSAY_CARD_KEY is set."""
    assert "signed Environment Card" not in README


def test_the_quickstart_command_produces_the_advertised_corpus():
    """--extra adapters alone omits openenv and gives 22 environments, not 24."""
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
    assert f"survives a {margin_pct}% error" in plain, (
        f"computed margin is {margin_pct}% and the README does not say so"
    )


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

    # The claim the rows are there to support.
    assert arms["direct_prompt"]["expected_loss"] > arms["stratified_random"]["expected_loss"], (
        "the LLM arm now beats flagging at base rates -- the README says it "
        "does not, and must be updated with this"
    )


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
