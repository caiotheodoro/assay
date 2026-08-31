"""Independent verification of the two tau2 corpus labels.

Assay is not imported into a single assertion below that establishes a label.
Every one of them reads the two pinned snapshots off disk with `json.load` and
compares records with `==` -- deliberately *not* through
`tau2_truth.changed_fields`, whose `leaf_paths` flattening and
`SCHEMA_ONLY_FIELDS` exclusion are production code and could be wrong in the
same direction as the label they produce.

That is the whole reason tau2 is in the corpus. `tests/test_probes_fire.py`
asserts detection on twelve fixtures this repository wrote, which is a CI gate
wearing a measurement's clothes. Here the answer key belongs to amazon-agi, it
was published at a commit, and this file's job is to check that the
`frozenset[DefectClass]` the registry hands out is a faithful reading of it.

The mapping being checked is two rules, derived in
`docs/PRE-REGISTRATION-TAU2.md` and committed before the provider:

    the graded answer changed          -> KNOWN_WRONG_PASSES
    only the brief changed             -> SPEC_VERIFIER_MISMATCH

Skips with a reason when the snapshots are absent, which on CI is always --
neither repository is redistributed here.
"""

from __future__ import annotations

import json
import re

import pytest

from assay.tau2_truth import (
    BASE_REV,
    DEFECT_CLASS_BY_MECHANICAL_CATEGORY,
    DOMAINS,
    EXCLUDED_DEFECT_CLASSES,
    UNMAPPABLE_FIX_CATEGORIES,
    VERIFIED_REV,
    env_defect_classes,
    task_defect_classes,
    tasks_path,
)
from assay.types import DefectClass

_HAVE = all(tasks_path(d, w).exists() for d in DOMAINS for w in ("base", "verified"))
pytestmark = pytest.mark.skipif(
    not _HAVE,
    reason=(
        "the two pinned tau2 snapshots are not in the cache; neither is redistributed "
        "here. Fetch with `uv run --extra tau2 python scripts/tau2_fetch.py`."
    ),
)

#: The field families the two revisions differ in, at LEAF level and not at
#: top-level-key level. The distinction is load-bearing and was got wrong first
#: time: `mechanical_category` is a fall-through, so anything that is not an
#: `/evaluation_criteria` change becomes `SPEC_VERIFIER_MISMATCH` -- and that
#: class is only justified for fields `Tau2Adapter._instruction` actually reads.
#: A future re-pin that moved `/user_scenario/persona` or `/description/notes`
#: would satisfy a top-level check, be labelled `SPEC_VERIFIER_MISMATCH`, and be
#: wrong: the solver's brief would not have moved at all.
BRIEF = ("/user_scenario/instructions/", "/description/purpose")
ANSWER_KEY = ("/evaluation_criteria",)


def _leaves(value, prefix=""):
    """Flatten to `{path: scalar}`. A local re-implementation on purpose.

    `tau2_truth.leaf_paths` does the same thing and is the code under test.
    """
    out = {}
    if isinstance(value, dict):
        for key, sub in value.items():
            out.update(_leaves(sub, f"{prefix}/{key}"))
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            out.update(_leaves(sub, f"{prefix}[{i}]"))
    else:
        out[prefix or "/"] = value
    return out


_ABSENT = object()


def _changed_leaves(before: dict, after: dict) -> set[str]:
    a, b = _leaves(before), _leaves(after)
    return {k for k in set(a) | set(b) if a.get(k, _ABSENT) != b.get(k, _ABSENT)}


def _is_brief(path: str) -> bool:
    return path.startswith(BRIEF)


def _is_answer_key(path: str) -> bool:
    return path.startswith(ANSWER_KEY)

#: Counted from the snapshots, and asserted rather than trusted: if amazon-agi
#: republishes, these move and every number this repository publishes about
#: tau2 has to be re-derived rather than quietly carried forward.
EXPECTED = {
    "retail": {"n_tasks": 114, "n_positives": 35, "answer_key": 8, "brief_only": 27},
    "airline": {"n_tasks": 50, "n_positives": 27, "answer_key": 12, "brief_only": 15},
}


def _raw(domain: str, which: str) -> dict[str, dict]:
    """Both snapshots, straight off disk. No Assay code in the path."""
    return {t["id"]: t for t in json.loads(tasks_path(domain, which).read_text())}


def _positives(domain: str) -> dict[str, tuple[dict, dict]]:
    """A task is a positive iff its record differs. That is the entire rule."""
    base, verified = _raw(domain, "base"), _raw(domain, "verified")
    return {
        tid: (base[tid], verified[tid])
        for tid in base
        if tid in verified and base[tid] != verified[tid]
    }


# -- the label rule ----------------------------------------------------------


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_positive_set_is_plain_json_inequality_over_two_pinned_revisions(domain):
    """62 of 164, recomputed without touching the module that produces the label."""
    base, verified = _raw(domain, "base"), _raw(domain, "verified")
    assert set(base) == set(verified), "the fork added or dropped a task; the diff is not a diff"
    assert len(base) == EXPECTED[domain]["n_tasks"]
    assert len(_positives(domain)) == EXPECTED[domain]["n_positives"]


def test_the_two_domains_are_the_whole_of_the_published_measurement():
    assert sum(EXPECTED[d]["n_tasks"] for d in DOMAINS) == 164
    assert sum(len(_positives(d)) for d in DOMAINS) == 62


@pytest.mark.parametrize("domain", DOMAINS)
def test_no_positive_is_a_whitespace_change(domain):
    """A reflowed paragraph is not a defect, and would inflate the label set."""
    def flat(value):
        return re.sub(r"\s+", " ", json.dumps(value, sort_keys=True))

    cosmetic = [
        tid for tid, (b, v) in _positives(domain).items() if flat(b) == flat(v)
    ]
    assert not cosmetic, f"{domain}: {cosmetic} differ only in whitespace"


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_positive_moves_the_brief_or_the_answer_key_and_nothing_else(domain):
    """The premise the whole mapping rests on, checked instead of assumed.

    Checked at leaf level. A top-level check would pass for a change to
    `/user_scenario/persona` -- a field `Tau2Adapter._instruction` never reads --
    and `mechanical_category`'s fall-through would still label it
    `SPEC_VERIFIER_MISMATCH`. That is the silent-failure mode this guards.
    """
    unaccounted: set[str] = set()
    for before, after in _positives(domain).values():
        for path in _changed_leaves(before, after):
            if not (_is_brief(path) or _is_answer_key(path)):
                unaccounted.add(path)
    assert not unaccounted, (
        f"{domain}: the revisions also differ at {sorted(unaccounted)[:8]}, which is "
        "neither the brief Tau2Adapter._instruction reads nor the answer key. No rule "
        "in DEFECT_CLASS_BY_MECHANICAL_CATEGORY accounts for it, and the fall-through "
        "would silently call it SPEC_VERIFIER_MISMATCH."
    )


# -- the mapping, task by task -----------------------------------------------


@pytest.mark.parametrize("domain", DOMAINS)
def test_known_wrong_passes_is_claimed_exactly_when_the_answer_key_moved(domain):
    """The answer-key rule, checked against the raw records rather than itself."""
    labels = task_defect_classes(domain)
    claimed = {t for t, c in labels.items() if DefectClass.KNOWN_WRONG_PASSES in c}
    from_disk = {
        tid
        for tid, (b, v) in _positives(domain).items()
        if any(_is_answer_key(p) for p in _changed_leaves(b, v))
    }
    assert claimed == from_disk
    assert len(claimed) == EXPECTED[domain]["answer_key"]


@pytest.mark.parametrize("domain", DOMAINS)
def test_spec_verifier_mismatch_is_claimed_only_when_the_verifier_stood_still(domain):
    """The brief-only rule, and the half of it that carries the argument.

    The class means "the instruction and what the verifier asserts disagree".
    The evidence for that is the third party moving the instruction and leaving
    the graded answer *untouched* -- so this asserts the answer key is
    byte-for-byte identical on every task claiming the class, and that the field
    which did move is one `Tau2Adapter._instruction` actually concatenates into
    `Task.instruction`. Anything else and the class is being claimed about text
    no solver is shown.
    """
    labels = task_defect_classes(domain)
    base, verified = _raw(domain, "base"), _raw(domain, "verified")
    claimed = {t for t, c in labels.items() if DefectClass.SPEC_VERIFIER_MISMATCH in c}
    assert len(claimed) == EXPECTED[domain]["brief_only"]
    for tid in claimed:
        assert base[tid].get("evaluation_criteria") == verified[tid].get(
            "evaluation_criteria"
        ), f"{domain}/{tid} claims SPEC_VERIFIER_MISMATCH but its answer key also moved"
        moved = _changed_leaves(base[tid], verified[tid])
        assert any(_is_brief(p) for p in moved), (
            f"{domain}/{tid} claims SPEC_VERIFIER_MISMATCH and none of {sorted(moved)} "
            "is a field the solver is shown"
        )


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_positive_gets_exactly_one_class_and_every_negative_none(domain):
    labels = task_defect_classes(domain)
    positives = set(_positives(domain))
    for tid, classes in labels.items():
        assert len(classes) == (1 if tid in positives else 0), f"{domain}/{tid}: {classes}"


# -- three fixes read the way the mapping says they do -----------------------


def test_retail_12_is_an_answer_key_that_rewarded_a_forbidden_refund():
    """A named `KNOWN_WRONG_PASSES` case, read off the snapshots.

    The pre-fix key required `return_delivered_order_items` paid to PayPal; the
    verified key replaces that action with `transfer_to_human_agents`. The
    pre-fix verifier therefore passes -- is obliged to pass -- a trajectory the
    third party judged to be against the domain policy.
    """
    base, verified = _raw("retail", "base"), _raw("retail", "verified")
    names = lambda t: [a["name"] for a in t["evaluation_criteria"]["actions"]]  # noqa: E731
    assert "return_delivered_order_items" in names(base["12"])
    assert "return_delivered_order_items" not in names(verified["12"])
    assert names(verified["12"])[-1] == "transfer_to_human_agents"
    assert DefectClass.KNOWN_WRONG_PASSES in task_defect_classes("retail")["12"]


def test_airline_2_is_an_answer_key_whose_own_prose_was_inverted():
    """The clearest single case: the graded claim reverses sign.

    "Agent should offer a certificate of $50" becomes "Agent should **not**
    offer a certificate of $50", and the `send_certificate` action is deleted.
    """
    base, verified = _raw("airline", "base"), _raw("airline", "verified")
    assert any(
        a["name"] == "send_certificate" for a in base["2"]["evaluation_criteria"]["actions"]
    )
    assert not any(
        a["name"] == "send_certificate"
        for a in verified["2"]["evaluation_criteria"]["actions"]
    )
    before = " ".join(base["2"]["evaluation_criteria"]["nl_assertions"])
    after = " ".join(verified["2"]["evaluation_criteria"]["nl_assertions"])
    assert "should offer a certificate" in before
    assert "should not offer a certificate" in after
    assert DefectClass.KNOWN_WRONG_PASSES in task_defect_classes("airline")["2"]


def test_retail_0_is_a_brief_that_asked_for_something_the_key_never_graded():
    """A named `SPEC_VERIFIER_MISMATCH` case, with the key held fixed.

    The brief said "exchange the mechanical keyboard for **a similar one**"
    while the graded answer always required the same item id. The fork rewrote
    the brief and touched nothing else.
    """
    base, verified = _raw("retail", "base"), _raw("retail", "verified")
    before = base["0"]["user_scenario"]["instructions"]["reason_for_call"]
    after = verified["0"]["user_scenario"]["instructions"]["reason_for_call"]
    assert "for a similar one" in before
    assert "for a similar one" not in after
    assert base["0"]["evaluation_criteria"] == verified["0"]["evaluation_criteria"]
    assert task_defect_classes("retail")["0"] == frozenset(
        {DefectClass.SPEC_VERIFIER_MISMATCH}
    )


# -- the exclusions, which are half the mapping ------------------------------


def test_gold_execution_failure_is_not_what_the_revision_diff_is_about():
    """The stated reason for excluding `GOLD_FAILS`, checked against the data.

    `results/tau2_recall.json` records Assay's `gold_passes` probe firing on
    retail tasks 18, 64, 91 and 105 even against the *corrected* task set. Two
    of those -- 64 and 105 -- are tasks amazon-agi inspected and left alone. A
    class whose evidence sits on records the third party did not touch is not a
    class the revision diff establishes, whatever else it may be.
    """
    positives = set(_positives("retail"))
    for tid in ("64", "105"):
        assert tid not in positives, (
            f"retail/{tid} is now a labelled positive; the written reason for excluding "
            "GOLD_FAILS in tau2_truth.EXCLUDED_DEFECT_CLASSES cites it as untouched and "
            "must be rewritten"
        )
    assert DefectClass.GOLD_FAILS in EXCLUDED_DEFECT_CLASSES


def test_the_noop_exclusion_names_nine_tasks_and_all_nine_really_have_no_gold_action():
    """The stated reason for excluding `NOOP_PASSES`, made checkable.

    The reason is not "the third party left those tasks alone" -- that is the
    absence of evidence, and the label rule says a negative means "unchanged",
    never "clean". It is that `noop_fails`' nine findings are an artifact of
    Assay's own verifier: `Tau2Adapter.verify` drops tau2's LLM-judged
    `nl_assertions` conjunct, so a task with no gold agent action has nothing
    left to require and an empty transcript scores 1.0 by construction.

    Reading the tasks straight off disk, without the adapter, so this is a claim
    about tau2's files rather than about our own `_gold()`.
    """
    empty = {
        domain: sorted(
            (
                tid
                for tid, task in _raw(domain, "base").items()
                if not [
                    a
                    for a in (task.get("evaluation_criteria") or {}).get("actions") or []
                    if a.get("requestor") != "user"
                ]
            ),
            key=int,
        )
        for domain in DOMAINS
    }
    assert empty == {
        "retail": ["24", "57"],
        "airline": ["0", "10", "26", "28", "31", "34", "46"],
    }, f"the nine tasks the NOOP_PASSES exclusion names have changed: {empty}"
    reason = EXCLUDED_DEFECT_CLASSES[DefectClass.NOOP_PASSES]
    assert "nl_assertions" in reason and "scores 1.0" in reason


def test_the_schema_only_exclusion_still_excludes_nothing():
    """A tripwire on the one field that could silently move a task's class.

    `SCHEMA_ONLY_FIELDS` strips `/evaluation_criteria/reward_basis` before the
    diff. `results/tau2_recall.json` records that it excludes nothing today --
    the field is absent from both revisions. It is also the single field whose
    change would be the strongest possible answer-key evidence, so if a re-pin
    ever reintroduced it, stripping it would demote a task from
    `KNOWN_WRONG_PASSES` to `SPEC_VERIFIER_MISMATCH` and no other test would
    notice.
    """
    from assay.tau2_truth import SCHEMA_ONLY_FIELDS

    assert SCHEMA_ONLY_FIELDS == (("evaluation_criteria", "reward_basis"),)
    for domain in DOMAINS:
        for which in ("base", "verified"):
            for task in _raw(domain, which).values():
                assert "reward_basis" not in (task.get("evaluation_criteria") or {}), (
                    f"{domain}/{which}/{task['id']} now carries reward_basis, which "
                    "SCHEMA_ONLY_FIELDS strips before the diff -- the exclusion is no "
                    "longer inert and the label rule has to be re-derived"
                )


def test_every_defect_class_is_either_mapped_or_excluded_with_a_reason():
    """A class added to the taxonomy must force a decision, not a default.

    `docs/changelog/97-dead-zone-probes.md` is the precedent: two classes were
    added, `flag_everything` gained 52 points of free floor, and nothing in the
    type system noticed. Both directions are checked, because a one-directional
    map is always the flattering one.
    """
    mapped = set(DEFECT_CLASS_BY_MECHANICAL_CATEGORY.values())
    excluded = set(EXCLUDED_DEFECT_CLASSES)
    assert not (mapped & excluded), f"claimed and excluded at once: {mapped & excluded}"
    assert mapped | excluded == set(DefectClass), (
        f"undecided: {sorted(c.value for c in set(DefectClass) - mapped - excluded)}"
    )
    for cls, reason in EXCLUDED_DEFECT_CLASSES.items():
        assert len(reason) > 40, f"{cls.value} is excluded without a real reason"


def test_the_categories_with_no_home_in_the_taxonomy_are_named_not_absorbed():
    """`database_accuracy` is a real tau2 defect class and Assay has no word for it."""
    assert "database_accuracy" in UNMAPPABLE_FIX_CATEGORIES
    assert "relabelling" in UNMAPPABLE_FIX_CATEGORIES["database_accuracy"]


# -- what the registry hands out ---------------------------------------------


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_environment_label_is_the_union_of_its_task_labels(domain):
    union: frozenset[DefectClass] = frozenset()
    for classes in task_defect_classes(domain).values():
        union |= classes
    assert env_defect_classes(domain) == union
    assert union == frozenset(
        {DefectClass.KNOWN_WRONG_PASSES, DefectClass.SPEC_VERIFIER_MISMATCH}
    )


def test_the_corpus_hands_out_what_the_diff_establishes_and_the_right_provenance():
    """The registry entry, checked against the snapshots rather than against itself."""
    from assay.corpus import ground_truth, provenance
    from assay.corpus import EnvAuthor, LabelSource

    truth, prov = ground_truth(only=["tau2"]), provenance(only=["tau2"])
    assert set(truth) == {"tau2/retail", "tau2/airline"}
    for domain in DOMAINS:
        env = f"tau2/{domain}"
        assert truth[env] == env_defect_classes(domain)
        assert prov[env].env_author is EnvAuthor.EXTERNAL
        assert prov[env].label_source is LabelSource.EXTERNALLY_DERIVED
        assert prov[env].is_evidence
        for rev in (BASE_REV[:10], VERIFIED_REV[:10]):
            assert rev in prov[env].note, "the note must pin the revisions it claims"
