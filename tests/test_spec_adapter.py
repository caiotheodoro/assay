"""The declarative adapter behind the Space.

The load-bearing property is not that it audits a good spec correctly. It is
that a *thin* spec produces a card full of NOT_APPLICABLE reasons rather than a
clean bill of health, because the Space's whole failure mode is a stranger
submitting three lines, seeing "no findings", and concluding their eval is fine.
"""

from __future__ import annotations

import pytest

from assay.adapters.spec import EnvSpec, SpecError, build
from assay.runner import audit
from assay.types import Capability, DefectClass, ProbeStatus

# A minimal but complete Yes/No eval. Written here from scratch: it is the
# SHAPE of a two-label classification eval, not any third party's content.
FULL = {
    "env_id": "example/yes-no",
    "verifier": "exact",
    "tasks": [
        {
            "task_id": "q1",
            "instruction": "Answer Yes or No: is 2 greater than 1?",
            "target": "Yes",
            "gold": "Yes",
            "known_wrong": "No",
            "asserts": ["the answer equals Yes"],
        },
        {
            "task_id": "q2",
            "instruction": "Answer Yes or No: is 1 greater than 2?",
            "target": "No",
            "gold": "No",
            "known_wrong": "Yes",
            "asserts": ["the answer equals No"],
        },
        {
            "task_id": "q3",
            "instruction": "Answer Yes or No: is 3 greater than 2?",
            "target": "Yes",
            "gold": "Yes",
            "known_wrong": "No",
            "asserts": ["the answer equals Yes"],
        },
    ],
    "train": [{"item_id": "tr1", "text": "is 5 greater than 4", "label": "Yes"}],
    "eval": [{"item_id": "ev1", "text": "is 4 greater than 5", "label": "No"}],
}

THIN = {
    "env_id": "example/thin",
    "tasks": [{"task_id": "only", "instruction": "do the thing", "target": "done"}],
}


# -- parsing ---------------------------------------------------------------


def test_a_spec_without_env_id_is_refused():
    with pytest.raises(SpecError, match="env_id is required"):
        EnvSpec.parse({"tasks": [{"target": "x"}]})


def test_a_task_without_a_target_is_refused_and_the_error_says_why():
    """`target` is separate from the verifier on purpose, and the error has to
    teach that, because a submitter who conflates them gets a vacuous audit."""
    with pytest.raises(SpecError, match="what the verifier accepts"):
        EnvSpec.parse({"env_id": "x", "tasks": [{"task_id": "a"}]})


def test_an_unknown_matcher_is_refused_rather_than_defaulted():
    with pytest.raises(SpecError, match="verifier must be one of"):
        EnvSpec.parse({"env_id": "x", "verifier": "vibes", "tasks": [{"target": "y"}]})


def test_malformed_json_reports_the_json_error_not_a_traceback():
    with pytest.raises(SpecError, match="not valid JSON"):
        EnvSpec.parse("{not json")


def test_duplicate_task_ids_are_refused():
    with pytest.raises(SpecError, match="unique"):
        EnvSpec.parse(
            {"env_id": "x", "tasks": [{"task_id": "a", "target": "1"},
                                      {"task_id": "a", "target": "2"}]}
        )


def test_oversized_submissions_are_refused_with_the_cap_named():
    raw = {"env_id": "x", "tasks": [{"task_id": f"t{i}", "target": "y"} for i in range(201)]}
    with pytest.raises(SpecError, match="the cap is 200"):
        EnvSpec.parse(raw)


# -- capabilities ----------------------------------------------------------


def test_capabilities_are_derived_from_content_not_claimed_by_the_submitter():
    """A spec cannot talk a probe into running by asserting a capability: the
    key is not even read."""
    raw = dict(THIN, capabilities=["GOLD_TRAJECTORY", "SPLITS"])
    caps = build(raw).manifest().capabilities
    assert Capability.GOLD_TRAJECTORY not in caps
    assert Capability.SPLITS not in caps


def test_a_complete_spec_earns_the_capabilities_it_actually_supports():
    caps = build(FULL).manifest().capabilities
    for cap in (
        Capability.GOLD_TRAJECTORY,
        Capability.KNOWN_WRONG,
        Capability.GRADED_POLICIES,
        Capability.INVERTIBLE_SPEC,
        Capability.SPLITS,
        Capability.SEPARABLE_VERIFIER,
        Capability.TRUE_COMPLETION,
    ):
        assert cap in caps, cap


def test_an_always_pass_verifier_has_no_rule_to_invert():
    caps = build(dict(FULL, verifier="always_pass")).manifest().capabilities
    assert Capability.INVERTIBLE_SPEC not in caps


# -- the point of the whole thing -----------------------------------------


def test_a_thin_spec_is_unverified_not_valid():
    """The card must not read as a pass. This is the Space's entire risk."""
    report = audit(build(THIN))
    assert report.verdict == "UNVERIFIED"
    assert report.exit_code != 0
    assert not report.findings


def test_every_probe_that_could_not_run_carries_a_reason():
    report = audit(build(THIN))
    skipped = report.by_status(ProbeStatus.NOT_APPLICABLE)
    assert skipped, "a one-task spec with no splits must skip something"
    for result in skipped:
        assert result.reason


def test_no_probe_errors_on_a_thin_spec():
    """NOT_APPLICABLE is a finding about the environment; ERROR is a bug in us."""
    report = audit(build(THIN))
    assert report.by_status(ProbeStatus.ERROR) == []


# -- it finds real defects -------------------------------------------------


def test_a_substring_verifier_against_two_labels_is_caught():
    """The shape of the `paws` finding, written from scratch: a submission
    naming both labels satisfies a substring matcher on either target while
    answering neither task."""
    adapter = build(dict(FULL, verifier="includes", trivial_answers=["YesNo"]))
    report = audit(adapter)
    assert DefectClass.TRIVIAL_FLOOR_BREACH in report.detected
    assert report.verdict in ("DEFECTIVE", "INVALID")


def test_an_always_pass_verifier_is_flagged_as_unfalsifiable():
    report = audit(build(dict(FULL, verifier="always_pass")))
    assert DefectClass.NOOP_PASSES in report.detected


def test_a_leaked_eval_item_is_caught():
    leaked = dict(
        FULL,
        train=[{"item_id": "tr1", "text": "is 4 greater than 5", "label": "No"}],
        eval=[{"item_id": "ev1", "text": "is 4 greater than 5", "label": "No"}],
    )
    report = audit(build(leaked))
    assert DefectClass.CONTAMINATION_EXACT in report.detected


def test_a_healthy_spec_produces_no_findings():
    report = audit(build(FULL))
    assert report.findings == [], [f.summary() for f in report.findings]


# -- the honest-solve invariant -------------------------------------------


def test_true_completion_is_stricter_than_a_loose_verifier():
    """Otherwise the exploit gap is identically zero and the hackability probe
    measures nothing."""
    from assay.adapter import run_policy
    from assay.types import Action

    adapter = build(dict(FULL, verifier="includes"))
    transcript = run_policy(adapter, "q1", [Action("submit", {"answer": "YesNo"})])
    assert adapter.verify(transcript).passed is True
    assert adapter.true_completion(transcript) == 0.0


def test_the_ecosystem_is_spec_so_publishing_refuses_to_classify_it():
    """A submitted environment is neither ours nor a known third party's. The
    redistribution guard must refuse rather than guess -- see test_publish."""
    from assay.publish import OURS, THEIRS

    assert build(THIN).manifest().ecosystem not in OURS | THEIRS


# -- the Space's bundled examples ------------------------------------------
#
# An example labelled "Shortcut" that produces no shortcut finding teaches the
# wrong thing about the tool, and it drifts silently: the probe changes, the
# example still renders, nobody looks. Pinned exactly, the way
# tests/test_probes_fire.py pins the corpus.

import json
from pathlib import Path

EXAMPLES = json.loads(
    (Path(__file__).resolve().parent.parent / "space" / "examples.json").read_text()
)

#: name prefix -> exactly the defects that example must produce
EXPECTED = {
    "1": (set(), "UNVERIFIED"),
    "2": (set(), "UNVERIFIED"),
    "3": ({"REWARD_HACKABLE", "TRIVIAL_FLOOR_BREACH"}, "INVALID"),
    "4": (
        {
            "KNOWN_WRONG_PASSES",
            "NOOP_PASSES",
            "REWARD_HACKABLE",
            "SEPARABILITY_LOSS",
            "TRIVIAL_FLOOR_BREACH",
        },
        "INVALID",
    ),
    "5": ({"CONTAMINATION_EXACT"}, "INVALID"),
    "6": ({"CONTAMINATION_NEARDUP"}, "DEFECTIVE"),
    "7": ({"SHORTCUT_LEAK"}, "DEFECTIVE"),
}


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["name"][:3])
def test_each_bundled_example_demonstrates_exactly_what_it_claims(example):
    expected, verdict = EXPECTED[example["name"][0]]
    report = audit(build(example["spec"]))
    assert {d.value for d in report.detected} == expected, example["name"]
    assert report.verdict == verdict, example["name"]


def test_the_thin_example_is_the_one_that_teaches_the_lesson():
    """It exists to show that a short submission is mostly unaudited. If it
    ever stops skipping most of the battery it has stopped making the point."""
    thin = next(e for e in EXAMPLES if e["name"].startswith("2"))
    report = audit(build(thin["spec"]))
    assert report.coverage["NOT_APPLICABLE"] >= 9
    assert report.verdict == "UNVERIFIED"


def test_no_bundled_example_errors():
    for example in EXAMPLES:
        report = audit(build(example["spec"]))
        assert report.by_status(ProbeStatus.ERROR) == [], example["name"]


# -- submitted patterns cannot hang the host --------------------------------


def test_a_catastrophic_submitted_regex_is_bounded_not_endured():
    """A spec arrives from a stranger, and for `kind: regex` the task's own
    target becomes the pattern. Python's engine backtracks: `(a+)+$` against 31
    characters takes about 100 seconds in-process, which on a public Space is a
    denial of service with a dozen-byte payload.

    The guard is what makes the `regex` matcher shippable at all. It cannot be
    dropped instead -- boolq scores with `pattern(r"(Yes|No).?\\Z")`, and a spec
    format that cannot express that cannot describe the evals this tool audits.
    """
    import time

    from assay.adapters.spec import _matches
    from assay.safe_regex import PatternTooSlow

    started = time.time()
    with pytest.raises(PatternTooSlow):
        _matches("regex", "a" * 30 + "!", "(a+)+$")
    elapsed = time.time() - started
    assert elapsed < 30, f"took {elapsed:.0f}s; the budget was not enforced"


def test_an_ordinary_regex_target_still_works():
    """The narrow-leak finding on boolq depends on this exact pattern being
    expressible, so the guard must not have cost the capability."""
    from assay.adapters.spec import _matches

    assert _matches("regex", "No.", r"(Yes|No).?\Z") is True
    assert _matches("regex", "I cannot determine the answer.", r"(Yes|No).?\Z") is False


def test_an_uncompilable_target_is_a_spec_error_not_a_hang():
    from assay.adapters.spec import SpecError, _matches

    with pytest.raises(SpecError, match="not a regex"):
        _matches("regex", "text", "(unclosed")


# -- the paws defect, on a spec a stranger wrote ----------------------------


def test_a_substring_verifier_yields_the_both_targets_policy():
    """The defect this project leads with, findable on submitted specs.

    `paws` is scored by `includes()` against `Yes` and `No`, and the constant
    string `"yesno"` takes 8000 of 8000. Until this existed, Assay could find
    that in a published eval and **not** in a spec a reader submitted -- the one
    thing this adapter is for. A judge wrote their own eval with a substring
    verifier, watched Assay report nothing about it, and said so.

    It is not a heuristic. `includes` asks whether the target occurs in the
    answer, so an answer containing every target satisfies every task. The
    adapter proposes the policy; the reward-hackability probe decides whether it
    actually pays.
    """
    from assay.adapters.spec import build

    spec = {
        "env_id": "t/yesno",
        "verifier": "includes",
        "tasks": [
            {"task_id": "q1", "instruction": "Answer Yes or No: is 2 > 1?",
             "target": "Yes", "gold": "Yes", "known_wrong": "No"},
            {"task_id": "q2", "instruction": "Answer Yes or No: is 1 > 2?",
             "target": "No", "gold": "No", "known_wrong": "Yes"},
        ],
    }
    adapter = build(spec)
    policies = adapter.trivial_policies("q1")
    assert "every_target_at_once" in policies

    from assay.runner import audit
    from assay.types import DefectClass

    report = audit(adapter)
    assert DefectClass.REWARD_HACKABLE in report.detected
    assert report.verdict == "INVALID"


def test_an_exact_verifier_gets_no_such_policy():
    """Only substring matchers are satisfied by naming every target."""
    from assay.adapters.spec import build

    spec = {
        "env_id": "t/exact",
        "verifier": "exact",
        "tasks": [
            {"task_id": "q1", "instruction": "2+2?", "target": "4"},
            {"task_id": "q2", "instruction": "1+1?", "target": "2"},
        ],
    }
    assert "every_target_at_once" not in build(spec).trivial_policies("q1")


def test_one_distinct_target_is_not_an_exploit():
    """With a single target the policy is just the majority class."""
    from assay.adapters.spec import build

    spec = {
        "env_id": "t/one",
        "verifier": "includes",
        "tasks": [
            {"task_id": "q1", "instruction": "say yes", "target": "Yes"},
            {"task_id": "q2", "instruction": "say yes again", "target": "Yes"},
        ],
    }
    assert "every_target_at_once" not in build(spec).trivial_policies("q1")


# --- YAML: advertised at cli.py:163,176,187 and unsupported until now ---------


def _minimal(fmt: str) -> str:
    if fmt == "json":
        return (
            '{"env_id": "demo/yaml", "tasks": [{"task_id": "t1", '
            '"instruction": "say hi", "target": "hi"}]}'
        )
    return (
        "env_id: demo/yaml\n"
        "tasks:\n"
        "  - task_id: t1\n"
        "    instruction: say hi\n"
        "    target: hi\n"
    )


def test_a_yaml_spec_parses_to_the_same_thing_as_the_equivalent_json():
    """The CLI accepted .yaml, told the user it accepted YAML, then rejected it.

    `cli.py:163` routes `.yaml`/`.yml` into the spec adapter, `:176` says "A spec
    is JSON or YAML with `env_id` and a non-empty `tasks` list", and `:187` tells
    the user to pass `.json/.yaml`. `EnvSpec.parse` called `json.loads` and
    nothing else, so following the error message produced the same error message.
    """
    from assay.adapters.spec import EnvSpec

    from_yaml = EnvSpec.parse(_minimal("yaml"))
    from_json = EnvSpec.parse(_minimal("json"))
    assert from_yaml.env_id == from_json.env_id == "demo/yaml"
    assert len(from_yaml.tasks) == len(from_json.tasks) == 1
    assert from_yaml.tasks[0].task_id == from_json.tasks[0].task_id == "t1"


def test_a_broken_spec_still_reports_the_json_parser_error():
    """When neither parser accepts it, the JSON error is the useful one.

    It names a byte offset; YAML tends to report a structural surprise several
    lines from the actual typo.
    """
    from assay.adapters.spec import EnvSpec, SpecError

    with pytest.raises(SpecError) as caught:
        EnvSpec.parse('{"env_id": "demo/broken", "tasks": [}')
    assert "not valid JSON" in str(caught.value)


def test_yaml_is_not_imported_at_module_scope():
    """`adapters.spec` is the audit path the browser demo runs under Pyodide.

    That build is deliberately stdlib-only. A module-scope `import yaml` would
    load it for every JSON spec and break the static demo for a dependency
    almost no caller reaches, so the import lives inside the fallback branch.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src/assay/adapters/spec.py"
    tree = ast.parse(src.read_text())
    top_level = [
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in getattr(node, "names", [])
    ]
    assert "yaml" not in top_level, (
        "yaml must be imported inside the branch that needs it, not at module scope"
    )
