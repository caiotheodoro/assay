"""The inspect_ai adapter against real inspect_ai Tasks.

Every environment here is a genuine `inspect_ai.Task` with a real scorer --
not a mock of one. The defective ones are built by writing a scorer with the
defect in it, which is how these defects actually reach production.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import Task as InspectTask  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, match, scorer  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from assay import audit  # noqa: E402
from assay.adapters import InspectAdapter  # noqa: E402
from assay.types import Capability, DefectClass, ProbeStatus  # noqa: E402


SAMPLES = [
    Sample(input="What is the capital of France?", target="Paris", id="q1"),
    Sample(input="What is 12 multiplied by 12?", target="144", id="q2"),
    Sample(input="Which planet is closest to the Sun?", target="Mercury", id="q3"),
]


def _dataset():
    return MemoryDataset([Sample(input=s.input, target=s.target, id=s.id) for s in SAMPLES])


@scorer(metrics=[accuracy()])
def always_correct():
    """A scorer that cannot fail. The defect that makes every number void."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT, answer=state.output.completion)

    return score


@scorer(metrics=[accuracy()])
def accepts_anything_nonempty():
    """Weak oracle: rewards effort rather than correctness."""

    async def score(state: TaskState, target: Target) -> Score:
        answer = (state.output.completion or "").strip()
        return Score(value=CORRECT if answer else INCORRECT, answer=answer)

    return score


def healthy_task() -> InspectTask:
    return InspectTask(dataset=_dataset(), scorer=match(location="exact"))


# --------------------------------------------------------------------------


def test_adapter_declares_what_inspect_ai_actually_exposes():
    manifest = InspectAdapter(healthy_task()).manifest()
    assert manifest.ecosystem == "inspect_ai"
    assert len(manifest.tasks) == 3
    for cap in (
        Capability.SEPARABLE_VERIFIER,
        Capability.GOLD_TRAJECTORY,
        Capability.INVERTIBLE_SPEC,
        Capability.GRADED_POLICIES,
    ):
        assert manifest.has(cap), cap
    # No train split was supplied, so it must not claim one.
    assert not manifest.has(Capability.SPLITS)


def test_healthy_inspect_task_has_no_verifier_defects():
    report = audit(InspectAdapter(healthy_task()))
    verifier = [r for r in report.results if r.family == "verifier_integrity"]
    assert all(r.status is ProbeStatus.PASS for r in verifier), [
        (r.probe, r.status.value, r.findings and r.findings[0].summary()) for r in verifier
    ]
    assert DefectClass.INVERT_PASSES not in report.detected


def test_unfalsifiable_scorer_is_caught():
    """The scorer always returns CORRECT. Assay must call the suite INVALID."""
    task = InspectTask(dataset=_dataset(), scorer=always_correct())
    report = audit(InspectAdapter(task, env_id="inspect/always-correct"))
    assert DefectClass.INVERT_PASSES in report.detected
    assert DefectClass.NOOP_PASSES in report.detected
    assert report.verdict == "INVALID"
    assert report.exit_code == 1


def test_weak_oracle_rewards_a_wrong_but_nonempty_answer():
    task = InspectTask(dataset=_dataset(), scorer=accepts_anything_nonempty())
    report = audit(InspectAdapter(task, env_id="inspect/effort-scorer"))
    assert DefectClass.KNOWN_WRONG_PASSES in report.detected
    assert DefectClass.REWARD_HACKABLE in report.detected


def test_contamination_probe_is_not_applicable_without_a_train_split():
    report = audit(InspectAdapter(healthy_task()))
    probe = [r for r in report.results if r.family == "contamination"][0]
    assert probe.status is ProbeStatus.NOT_APPLICABLE
    # The capability gate answers first, before the adapter's own message.
    assert "SPLITS" in probe.reason


def test_leaked_train_split_is_caught():
    """Same rows in both splits -- the default failure when one generator with
    two seeds produces 'train' and 'held out'."""
    task = healthy_task()
    adapter = InspectAdapter(task, train_dataset=_dataset(), env_id="inspect/leaky")
    report = audit(adapter)
    assert DefectClass.CONTAMINATION_EXACT in report.detected
    assert report.verdict == "INVALID"


def test_spec_match_is_not_applicable_when_scorers_are_opaque():
    """inspect_ai scorers are plain functions. Claiming to read their intent
    lexically would manufacture findings, so the probe declines instead."""
    report = audit(InspectAdapter(healthy_task()))
    probe = [r for r in report.results if r.family == "spec_verifier_match"][0]
    assert probe.status is ProbeStatus.NOT_APPLICABLE
    assert "machine-readable" in probe.reason
