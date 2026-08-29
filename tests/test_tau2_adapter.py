"""The tau2 adapter against the real, pinned tau2-bench snapshot.

These are the tests that need the two third-party revisions on disk. tau2-bench
is not redistributed here, so they skip -- with the command that fixes it --
when `scripts/tau2_fetch.py` has not run.

What they check is mostly the shape of an honest refusal. tau2 has no train
split, no item parts, no completion signal independent of its own scorer, and
its third evaluator is an LLM judge. Four of Assay's nine families therefore
cannot run against it, and the interesting assertion is that each says so with
a reason rather than passing quietly.
"""

from __future__ import annotations

import pytest

from assay.adapter import NotSupported, run_policy
from assay.probes import all_probes
from assay.types import Capability, ProbeStatus, Transcript

tau2 = pytest.importorskip("assay.adapters.tau2", reason="assay.adapters.tau2 missing")

_REASON = (
    "the pinned tau2-bench snapshots are not in the cache; run "
    "`uv run --extra tau2 python scripts/tau2_fetch.py`"
)
needs_tau2 = pytest.mark.skipif(not tau2.available(), reason=_REASON)

#: Three retail tasks with known, independently documented properties.
#: 0  clean: its gold sequence replays and every conjunct passes.
#: 12 the refund in its gold answer is refused by tau2's own tool.
#: 18 the office-chair exchange the tau2-bench-verified paper uses as its
#:    headline retail example -- the gold answer exchanges an item for itself.
CLEAN, REFUSED, IDENTICAL_EXCHANGE = "0", "12", "18"


@pytest.fixture(scope="module")
def retail():
    adapter = tau2.Tau2Adapter(
        "retail", task_ids=[CLEAN, REFUSED, IDENTICAL_EXCHANGE]
    )
    yield adapter
    adapter.close()


@needs_tau2
def test_manifest_declares_only_what_tau2_actually_has(retail):
    manifest = retail.manifest()
    assert manifest.ecosystem == "tau2"
    assert manifest.env_id == "tau2/retail"
    assert manifest.version.endswith("/base")
    assert manifest.has(Capability.GOLD_TRAJECTORY)
    assert manifest.has(Capability.SEPARABLE_VERIFIER)
    for absent in (
        Capability.INVERTIBLE_SPEC,
        Capability.SPLITS,
        Capability.ITEM_PARTS,
        Capability.TRUE_COMPLETION,
        Capability.TRIVIAL_POLICIES,
        Capability.GRADED_POLICIES,
    ):
        assert not manifest.has(absent), absent


@needs_tau2
def test_a_clean_gold_sequence_replays_and_passes(retail):
    transcript = run_policy(
        retail, CLEAN, retail.gold_actions(CLEAN), stop_on_done=False
    )
    score = retail.verify(transcript)
    assert score.passed
    assert score.profile["executable"] == 1.0
    assert score.profile["action_reward"] == 1.0
    assert score.profile["db_reward"] == 1.0


@needs_tau2
def test_a_gold_sequence_tau2_refuses_fails_on_executability_alone(retail):
    """The action and DB conjuncts still pass. That is the point.

    tau2's ActionEvaluator only asks whether each gold call appears in the
    trajectory, so a call that appeared and was rejected still scores 1.0. If
    Assay reported tau2's own reward it would call this task solved.
    """
    transcript = run_policy(
        retail, REFUSED, retail.gold_actions(REFUSED), stop_on_done=False
    )
    score = retail.verify(transcript)
    assert not score.passed
    assert score.profile["executable"] == 0.0
    assert score.profile["action_reward"] == 1.0
    assert [r["tool"] for r in score.profile["refused_writes"]] == [
        "return_delivered_order_items"
    ]


@needs_tau2
def test_the_nl_conjunct_is_reported_absent_not_passed(retail):
    transcript = run_policy(
        retail, CLEAN, retail.gold_actions(CLEAN), stop_on_done=False
    )
    profile = retail.verify(transcript).profile
    assert profile["nl_assertions_checked"] is False
    assert "judge" in profile["nl_assertions_note"]


@needs_tau2
def test_an_empty_transcript_does_not_pass_a_task_with_gold_actions(retail):
    retail.reset(CLEAN, seed=0)
    score = retail.verify(Transcript(task_id=CLEAN, seed=0))
    assert not score.passed


@needs_tau2
def test_the_policy_oracle_finds_the_identical_exchange(retail):
    violations = retail.policy_violations(IDENTICAL_EXCHANGE)
    assert [v.rule for v in violations] == ["retail.exchange_same_option"]
    assert "same product but of different product option" in violations[0].quote
    assert retail.policy_violations(CLEAN) == []


@needs_tau2
def test_known_wrong_is_the_gold_answer_only_where_policy_says_it_is_wrong(retail):
    assert retail.known_wrong_actions(CLEAN) == []
    known_wrong = retail.known_wrong_actions(IDENTICAL_EXCHANGE)
    assert known_wrong == retail.gold_actions(IDENTICAL_EXCHANGE)


@needs_tau2
def test_the_verifier_accepts_that_known_wrong_answer(retail):
    """The finding this measurement is built on, asserted directly.

    A task whose gold answer breaks the domain policy is graded correct by the
    environment, because the gold answer is the answer key.
    """
    transcript = run_policy(
        retail,
        IDENTICAL_EXCHANGE,
        retail.known_wrong_actions(IDENTICAL_EXCHANGE),
        stop_on_done=False,
    )
    assert retail.verify(transcript).passed


@needs_tau2
@pytest.mark.parametrize(
    "call, expected",
    [
        ("invert_spec", "env_assertions"),
        ("train_items", "train"),
        ("eval_items", "partial-input"),
        ("trivial_policies", "judge"),
        ("graded_policies", "graded"),
    ],
)
def test_every_refusal_carries_a_reason(retail, call, expected):
    method = getattr(retail, call)
    with pytest.raises(NotSupported) as excinfo:
        method(CLEAN) if call not in ("train_items", "eval_items") else method()
    assert expected in str(excinfo.value)


@needs_tau2
def test_true_completion_refuses_with_a_reason(retail):
    with pytest.raises(NotSupported) as excinfo:
        retail.true_completion(Transcript(task_id=CLEAN, seed=0))
    assert "independent of its own" in str(excinfo.value)


@needs_tau2
def test_no_probe_errors_and_every_skip_names_what_is_missing(retail):
    """A probe that could not run has to say why, and 'why' has to be specific."""
    results = [probe.run(retail) for probe in all_probes()]
    assert not [r for r in results if r.status is ProbeStatus.ERROR]
    skipped = [r for r in results if r.status is ProbeStatus.NOT_APPLICABLE]
    assert skipped, "tau2 exposes less than Assay asks for; some probes must skip"
    for result in skipped:
        assert result.reason and len(result.reason) > 20, result.probe


@needs_tau2
def test_the_label_set_is_the_one_the_published_numbers_were_measured_on():
    """A guard on the ground truth, not on Assay.

    `results/tau2_recall.json` reports recall over 62 positives. If either
    pinned revision were repointed, or the diff rule changed, the denominator
    would move and every number in the changelog would quietly become wrong.
    """
    from assay.tau2_truth import ground_truth

    counts = {}
    for domain in ("retail", "airline"):
        labels = ground_truth(domain)
        counts[domain] = (
            len(labels),
            sum(1 for label in labels.values() if label.defective),
        )
    assert counts == {"retail": (114, 35), "airline": (50, 27)}


@needs_tau2
def test_the_adapter_defaults_to_the_pre_fix_task_set():
    """Nothing an audit constructs by default can see the corrected answers.

    The two revisions meet in `scripts/tau2_recall.py`, which asks for the
    verified set by name. Everywhere else the default is the pre-fix one, and
    the two really do differ on the task the paper uses as its example.
    """
    default = tau2.Tau2Adapter("retail", task_ids=[IDENTICAL_EXCHANGE])
    verified = tau2.Tau2Adapter(
        "retail", task_set="verified", task_ids=[IDENTICAL_EXCHANGE]
    )
    try:
        assert default.task_set == "base"
        assert default.manifest().version.endswith("/base")
        pre = default.gold_actions(IDENTICAL_EXCHANGE)
        post = verified.gold_actions(IDENTICAL_EXCHANGE)
        assert pre != post
        assert [v.rule for v in default.policy_violations(IDENTICAL_EXCHANGE)] == [
            "retail.exchange_same_option"
        ]
        # And the corrected answer trips a different rule -- see
        # test_the_corrected_answer_for_that_task_is_itself_unexecutable.
        assert [v.rule for v in verified.policy_violations(IDENTICAL_EXCHANGE)] == [
            "retail.exchange_unavailable"
        ]
    finally:
        default.close()
        verified.close()


@needs_tau2
def test_the_corrected_answer_for_that_task_is_itself_unexecutable():
    """A finding about tau2-bench-verified, not about tau2-bench.

    The fix for the office-chair task replaces the identical item with
    3609437808. That item is `available: false` in the retail database, which
    the verified fork ships byte-identical to the original (sha256
    413a6516...6765 in both). tau2's own `exchange_delivered_order_items`
    refuses the call.

    Reproduce:
        uv run --extra tau2 python scripts/tau2_recall.py
        # results/tau2_recall.json -> domains[0].control_post_fix
    """
    adapter = tau2.Tau2Adapter(
        "retail", task_set="verified", task_ids=[IDENTICAL_EXCHANGE]
    )
    try:
        transcript = run_policy(
            adapter,
            IDENTICAL_EXCHANGE,
            adapter.gold_actions(IDENTICAL_EXCHANGE),
            stop_on_done=False,
        )
        score = adapter.verify(transcript)
        assert not score.passed
        assert score.profile["executable"] == 0.0
        assert "not found or available" in score.profile["refused_writes"][0]["error"]
    finally:
        adapter.close()
