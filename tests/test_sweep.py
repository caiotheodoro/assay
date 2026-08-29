"""The task-safety filter, tested where it has to be right.

The filter is the correctness component of the wild sweep, not a performance
one: without it the adapter hands a scorer that reads a sandbox or a tool
transcript an empty world, gets a degenerate score back, and reports it as a
defect in a real published benchmark. So these tests are about refusal.

Everything here is offline. Scorers are built in-process with the same
`@scorer` decorator inspect_evals uses, and the datasets are `MemoryDataset`.
No task factory is called and no HF Hub request is made, so the suite runs the
same on a machine with no network as on one with.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.scorer import (  # noqa: E402
    CORRECT,
    INCORRECT,
    Score,
    Target,
    accuracy,
    choice,
    includes,
    match,
    scorer,
)
from inspect_ai.solver import TaskState, generate, multiple_choice  # noqa: E402

from assay.sweep import (  # noqa: E402
    MULTIPLE_CHOICE,
    POPULATED_STATE_ATTRS,
    RAW,
    StateEscapes,
    TaskRef,
    UnknownProtocol,
    WildInspectAdapter,
    detect_protocol,
    dynamic_filter,
    enumerate_tasks,
    gold_anchor,
    installed_scope,
    out_of_scope_tasks,
    sample_indices,
    scorer_functions,
    state_reads,
    static_filter,
)

QA = [
    ("q1", "What is the capital of France?", "Paris"),
    ("q2", "What is 12 multiplied by 12?", "144"),
    ("q3", "Which planet is closest to the Sun?", "Mercury"),
]


def qa_dataset():
    return MemoryDataset([Sample(input=q, target=t, id=i) for i, q, t in QA])


def mc_dataset():
    return MemoryDataset(
        [
            Sample(
                input="Which is a mammal?",
                choices=["Whale", "Trout", "Newt", "Crab"],
                target="A",
                id="m1",
            ),
            Sample(
                input="Which is a metal?",
                choices=["Argon", "Iron", "Neon", "Sulphur"],
                target="B",
                id="m2",
            ),
        ]
    )


def ref(name: str = "toy") -> TaskRef:
    return TaskRef(name=name, package="toy", source_file="toy/toy.py", factory=lambda: None)


# --------------------------------------------------------------------------
# state_reads -- the AST gate
# --------------------------------------------------------------------------


class TestStateReads:
    """What the gate can see, and what it admits it cannot."""

    def test_completion_only_scorer_reads_only_the_completion(self):
        @scorer(metrics=[accuracy()])
        def lexical():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(
                    value=CORRECT if state.output.completion == target.text else INCORRECT
                )

            return score

        assert state_reads(lexical()) == {"state.output.completion"}

    def test_maximal_chains_only_so_reading_output_is_not_confused_with_completion(self):
        """`state.output` reaches `.message` and therefore tool calls.

        Recording the prefix as well as the full chain would let a scorer that
        reads the whole output object slip through on the strength of the
        `state.output.completion` entry.
        """

        @scorer(metrics=[accuracy()])
        def whole_output():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if state.output else INCORRECT)

            return score

        assert state_reads(whole_output()) == {"state.output"}
        assert "state.output" not in POPULATED_STATE_ATTRS

    def test_store_reading_scorer_is_seen(self):
        @scorer(metrics=[accuracy()])
        def from_store():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if state.store.get("done") else INCORRECT)

            return score

        assert state_reads(from_store()) == {"state.store.get"}, (
            "the maximal chain is reported verbatim; the allowlist check is on "
            "the prefix, so this is still refused"
        )

    def test_transcript_reading_scorer_is_seen(self):
        @scorer(metrics=[accuracy()])
        def from_messages():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if len(state.messages) > 2 else INCORRECT)

            return score

        assert state_reads(from_messages()) == {"state.messages"}

    def test_a_scorer_that_forwards_state_is_refused_not_guessed_at(self):
        """This gate reads one function. A helper could touch anything."""

        def helper(state):
            return state.store.get("x")

        @scorer(metrics=[accuracy()])
        def forwards():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if helper(state) else INCORRECT)

            return score

        with pytest.raises(StateEscapes):
            state_reads(forwards())

    def test_state_in_an_fstring_still_counts_as_a_read(self):
        @scorer(metrics=[accuracy()])
        def explains():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT, explanation=f"saw {state.metadata}")

            return score

        assert "state.metadata" in state_reads(explains())


# --------------------------------------------------------------------------
# dynamic_filter -- refusal with a reason
# --------------------------------------------------------------------------


class TestDynamicFilter:
    def test_a_lexical_task_is_admitted_with_the_raw_protocol(self):
        task = Task(dataset=qa_dataset(), scorer=match(location="exact"), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert exclusion is None
        assert protocol is RAW

    def test_a_multiple_choice_task_is_admitted_with_its_own_protocol(self):
        task = Task(dataset=mc_dataset(), scorer=choice(), solver=multiple_choice())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert exclusion is None
        assert protocol is MULTIPLE_CHOICE

    def test_a_choice_scorer_without_the_multiple_choice_solver_is_refused(self):
        """`choice()` reads `state.choices`, which only the `multiple_choice`
        solver populates. Scoring it without that solver measures an unmarked
        `Choices` object, not the eval."""
        task = Task(dataset=mc_dataset(), scorer=choice(), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert protocol is None
        assert exclusion.rule == "unpopulated_state_read"
        assert "state.choices" in exclusion.reason

    def test_a_sandboxed_sample_is_refused(self):
        ds = MemoryDataset(
            [Sample(input="build it", target="ok", id="s1", sandbox="docker")]
        )
        task = Task(dataset=ds, scorer=match(), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert protocol is None
        assert exclusion.rule == "sample_sandbox"
        assert "degenerate" in exclusion.reason

    def test_a_store_reading_scorer_is_refused_with_the_attribute_named(self):
        @scorer(metrics=[accuracy()])
        def from_store():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if state.store.get("flag") else INCORRECT)

            return score

        task = Task(dataset=qa_dataset(), scorer=from_store(), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert protocol is None
        assert exclusion.rule == "unpopulated_state_read"
        assert "state.store" in exclusion.reason

    def test_multi_element_targets_are_refused_rather_than_truncated(self):
        ds = MemoryDataset([Sample(input="name two", target=["Paris", "Lyon"], id="t1")])
        task = Task(dataset=ds, scorer=match(), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert protocol is None
        assert exclusion.rule == "multi_target"

    def test_multiple_scorers_are_refused_rather_than_averaged(self):
        task = Task(
            dataset=qa_dataset(), scorer=[match(), includes()], solver=generate()
        )
        protocol, exclusion = dynamic_filter(ref(), task)
        assert protocol is None
        assert exclusion.rule == "multiple_scorers"

    def test_an_empty_dataset_is_refused(self):
        """inspect_ai itself rejects an empty dataset at `Task` construction, so
        this branch only fires on an object that got past it. Kept as a guard
        and tested through a stub rather than deleted -- a dataset that
        materialises to nothing must be a reason, not a zero-finding sweep."""

        class _EmptyTask:
            dataset = []
            scorer = match()
            solver = generate()

        protocol, exclusion = dynamic_filter(ref(), _EmptyTask())
        assert protocol is None
        assert exclusion.rule == "empty_dataset"

    def test_a_completion_derived_chain_is_still_admitted(self):
        """`state.output.completion.strip()` reaches no further than the string
        the adapter populated. Refusing it would cost real coverage for nothing."""

        @scorer(metrics=[accuracy()])
        def stripped():
            async def score(state: TaskState, target: Target) -> Score:
                answer = state.output.completion.strip().lower()
                return Score(value=CORRECT if answer == target.text.lower() else INCORRECT)

            return score

        task = Task(dataset=qa_dataset(), scorer=stripped(), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert exclusion is None, exclusion
        assert protocol is RAW

    def test_reading_the_whole_output_object_is_refused(self):
        """From `state.output` the scorer reaches `.message` and its tool calls,
        which the fabricated state does not have."""

        @scorer(metrics=[accuracy()])
        def whole_output():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if state.output is not None else INCORRECT)

            return score

        task = Task(dataset=qa_dataset(), scorer=whole_output(), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert protocol is None
        assert exclusion.rule == "unpopulated_state_read"
        assert "state.output" in exclusion.reason

    def test_every_exclusion_carries_a_reason(self):
        """Rule #2: a check that cannot run says so, with a cause."""
        cases = [
            Task(dataset=mc_dataset(), scorer=choice(), solver=generate()),
            Task(dataset=qa_dataset(), scorer=[match(), includes()], solver=generate()),
        ]
        for task in cases:
            _, exclusion = dynamic_filter(ref(), task)
            assert exclusion is not None
            assert exclusion.reason and len(exclusion.reason) > 20
            assert exclusion.rule


class TestProtocolDetection:
    def test_multiple_correct_is_read_off_the_solver_not_assumed(self):
        task = Task(
            dataset=mc_dataset(), scorer=choice(), solver=multiple_choice(multiple_correct=True)
        )
        with pytest.raises(UnknownProtocol, match="multiple_correct=True"):
            detect_protocol(task)

    def test_a_plain_generate_task_gets_the_null_protocol(self):
        task = Task(dataset=qa_dataset(), scorer=match(), solver=generate())
        assert detect_protocol(task) is RAW


# --------------------------------------------------------------------------
# The gold anchor
# --------------------------------------------------------------------------


class TestGoldAnchor:
    def test_a_working_lexical_scorer_anchors_every_item(self):
        task = Task(dataset=qa_dataset(), scorer=match(location="exact"), solver=generate())
        adapter = WildInspectAdapter(task, protocol=RAW, env_id="toy")
        anchor = gold_anchor(adapter)
        assert anchor.unverified == []
        assert len(anchor.anchored) == len(QA)
        assert anchor.rate == 1.0

    def test_the_multiple_choice_protocol_anchors_a_choice_scorer(self):
        """The proof that replaying inspect_ai's own answer-parsing step is
        faithful: a bare "A" would score wrong, "ANSWER: A" scores right."""
        task = Task(dataset=mc_dataset(), scorer=choice(), solver=multiple_choice())
        anchored = gold_anchor(
            WildInspectAdapter(task, protocol=MULTIPLE_CHOICE, env_id="toy")
        )
        assert anchored.rate == 1.0

        task2 = Task(dataset=mc_dataset(), scorer=choice(), solver=multiple_choice())
        unanchored = gold_anchor(WildInspectAdapter(task2, protocol=RAW, env_id="toy"))
        assert unanchored.anchored == [], (
            "without the protocol the gold answer is not even recognised, which is "
            "exactly the case the anchor exists to catch"
        )

    def test_a_scorer_that_understands_nothing_anchors_nothing(self):
        @scorer(metrics=[accuracy()])
        def always_wrong():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=INCORRECT, answer=state.output.completion)

            return score

        task = Task(dataset=qa_dataset(), scorer=always_wrong(), solver=generate())
        anchor = gold_anchor(WildInspectAdapter(task, protocol=RAW, env_id="toy"))
        assert anchor.anchored == []
        assert anchor.rate == 0.0

    def test_gold_unverified_items_are_recorded_with_what_was_submitted(self):
        task = Task(dataset=mc_dataset(), scorer=choice(), solver=multiple_choice())
        anchor = gold_anchor(WildInspectAdapter(task, protocol=RAW, env_id="toy"))
        for tid in anchor.unverified:
            detail = anchor.detail[tid]
            assert detail["gold_completion"] is not None
            assert detail["target"] is not None
            assert detail["passed"] is False


# --------------------------------------------------------------------------
# The adapter still detects a real defect once anchored
# --------------------------------------------------------------------------


class TestTheFilterDoesNotDisarmTheProbes:
    """A filter that refused everything would also report nothing, honestly and
    uselessly. These pin that an admitted, anchored task with a genuinely loose
    scorer still produces the finding."""

    def test_a_substring_scorer_is_admitted_anchored_and_caught(self):
        """`includes()` on a numeric target: "144" is accepted, and so is any
        answer containing it. That is a real KNOWN_WRONG_PASSES shape."""
        ds = MemoryDataset(
            [
                Sample(input="What is 12x12?", target="144", id="a"),
                Sample(input="What is 12x12, with working?", target="14", id="b"),
            ]
        )
        task = Task(dataset=ds, scorer=includes(), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert exclusion is None

        adapter = WildInspectAdapter(task, protocol=protocol, env_id="toy")
        assert gold_anchor(adapter).rate == 1.0

        # Sample "a" declares target "144"; answering with sample "b"'s target
        # "14" is a known-wrong answer, and `includes()` accepts it as a
        # substring of nothing -- but the reverse holds: gold "144" contains
        # "14", so sample "b" is scored correct by sample "a"'s gold answer.
        wrong = adapter.known_wrong_actions("b")
        from assay.adapter import run_policy

        score = adapter.verify(run_policy(adapter, "b", wrong))
        assert score.passed, "the loose scorer accepts a known-wrong answer"

    def test_an_always_correct_scorer_is_admitted_and_reported_as_invalid(self):
        from assay import audit
        from assay.types import DefectClass

        @scorer(metrics=[accuracy()])
        def always_correct():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT, answer=state.output.completion)

            return score

        task = Task(dataset=qa_dataset(), scorer=always_correct(), solver=generate())
        protocol, exclusion = dynamic_filter(ref(), task)
        assert exclusion is None

        adapter = WildInspectAdapter(task, protocol=protocol, env_id="toy")
        assert gold_anchor(adapter).rate == 1.0

        report = audit(adapter)
        assert report.verdict == "INVALID"
        assert DefectClass.INVERT_PASSES in report.detected
        assert DefectClass.NOOP_PASSES in report.detected


class TestTrivialPoliciesAreNotProtocolFormatted:
    """Rendering "I cannot determine the answer." as "ANSWER: I cannot ..."
    would manufacture a protocol-conformant answer out of a refusal, and the
    resulting score would be an artifact of the sweep, not the eval."""

    def test_the_escalate_policy_is_submitted_verbatim(self):
        task = Task(dataset=mc_dataset(), scorer=choice(), solver=multiple_choice())
        adapter = WildInspectAdapter(task, protocol=MULTIPLE_CHOICE, env_id="toy")
        policies = adapter.trivial_policies("m1")
        escalate = policies["always_escalate"][0]
        assert escalate.args["answer"] == "I cannot determine the answer."
        assert "assay_as_answer" not in escalate.args

        majority = policies["majority_class"][0]
        assert majority.args["assay_as_answer"] is True

    def test_true_completion_reads_the_raw_answer_not_the_rendered_one(self):
        from assay.adapter import run_policy

        task = Task(dataset=mc_dataset(), scorer=choice(), solver=multiple_choice())
        adapter = WildInspectAdapter(task, protocol=MULTIPLE_CHOICE, env_id="toy")
        gold = run_policy(adapter, "m1", adapter.gold_actions("m1"))
        assert adapter.true_completion(gold) == 1.0


# --------------------------------------------------------------------------
# Enumeration and the static gate, against the installed distribution
# --------------------------------------------------------------------------

inspect_evals = pytest.importorskip(
    "inspect_evals", reason="the sweep dependency group is not installed"
)


class TestEnumeration:
    def test_every_registered_task_is_located_in_the_package(self):
        assert out_of_scope_tasks() == [], (
            "a registered task defined outside inspect_evals/ means the scope "
            "statement in sweep.py is stale"
        )
        assert len(enumerate_tasks()) > 100

    def test_the_register_directory_is_not_shipped_in_the_wheel(self):
        """The sweep claims `register/` entries are out of scope. That claim is
        only true while they are absent; this is the check, not the assertion."""
        scope = installed_scope()
        assert scope["register_dir_present"] is False
        assert scope["yaml_pointer_files"] == []

    def test_the_named_agentic_families_are_excluded_with_a_reason(self):
        _, exclusions = static_filter(enumerate_tasks())
        by_task = {e.task: e for e in exclusions}
        for name in ("gaia", "cybench", "agentharm", "agentdojo"):
            hits = [t for t in by_task if t.startswith(name)]
            assert hits, f"{name} tasks should be enumerated and excluded"
            for hit in hits:
                assert by_task[hit].reason
                assert by_task[hit].gate == "static"

    def test_gdm_and_agent_prefixed_packages_are_excluded(self):
        kept, _ = static_filter(enumerate_tasks())
        assert not [r for r in kept if r.package.startswith(("gdm_", "agent_"))]

    def test_no_kept_package_ships_a_container_definition(self):
        kept, _ = static_filter(enumerate_tasks())
        from assay.sweep import package_signals

        for package in {r.package for r in kept}:
            assert package_signals(package)["container_artifacts"] == []

    def test_the_static_gate_keeps_the_lexical_benchmarks(self):
        """A filter that excluded everything would be safe and useless."""
        kept = {r.name for r in static_filter(enumerate_tasks())[0]}
        for name in ("gsm8k", "arc_easy", "arc_challenge", "boolq", "hellaswag"):
            assert name in kept

    def test_exclusions_and_survivors_partition_the_registry(self):
        refs = enumerate_tasks()
        kept, excluded = static_filter(refs)
        assert len(kept) + len(excluded) == len(refs)
        assert {r.name for r in kept}.isdisjoint({e.task for e in excluded})


class TestSampling:
    def test_the_subsample_is_deterministic_so_triage_is_repeatable(self):
        assert sample_indices(1000, 25, seed=7) == sample_indices(1000, 25, seed=7)
        assert sample_indices(1000, 25, seed=7) != sample_indices(1000, 25, seed=8)

    def test_a_small_dataset_is_taken_whole(self):
        assert sample_indices(5, 25, seed=0) == [0, 1, 2, 3, 4]
