"""Real inspect_ai environments with defects written into the scorer.

Each defect is introduced the way it actually reaches production -- as a
plausible-looking scorer somebody wrote in a hurry -- rather than as a mock.
"""

from __future__ import annotations

from typing import Any

from .corpus import CorpusEntry, EnvAuthor, LabelSource, Provenance, register
from .types import DefectClass

_QA = [
    ("q1", "What is the capital of France?", "Paris"),
    ("q2", "What is 12 multiplied by 12?", "144"),
    ("q3", "Which planet is closest to the Sun?", "Mercury"),
    ("q4", "Who wrote the novel Frankenstein?", "Mary Shelley"),
    ("q5", "What is the chemical symbol for gold?", "Au"),
]


def _dataset():
    from inspect_ai.dataset import MemoryDataset, Sample

    return MemoryDataset([Sample(input=q, target=t, id=i) for i, q, t in _QA])


def build_inspect_environments(adapter_cls) -> list[tuple[str, Any, frozenset[DefectClass]]]:
    from inspect_ai import Task
    from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, match, scorer
    from inspect_ai.solver import TaskState

    @scorer(metrics=[accuracy()])
    def always_correct():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=CORRECT, answer=state.output.completion)

        return score

    @scorer(metrics=[accuracy()])
    def any_nonempty():
        async def score(state: TaskState, target: Target) -> Score:
            answer = (state.output.completion or "").strip()
            return Score(value=CORRECT if answer else INCORRECT, answer=answer)

        return score

    @scorer(metrics=[accuracy()])
    def constant_partial():
        """Gives everyone the same middling score. Separable? No."""

        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=0.5, answer=state.output.completion)

        return score

    def env(name, scorer_fn, *, train=None):
        task = Task(dataset=_dataset(), scorer=scorer_fn)
        return (
            f"inspect/{name}",
            (lambda t=task, tr=train: adapter_cls(t, env_id=f"inspect/{name}", train_dataset=tr)),
        )

    healthy_id, healthy_factory = env("healthy", match(location="exact"))
    unfalsifiable_id, unfalsifiable_factory = env("always-correct", always_correct())
    weak_id, weak_factory = env("effort-scorer", any_nonempty())
    flat_id, flat_factory = env("constant-score", constant_partial())
    leaky_id, leaky_factory = env("leaky-split", match(location="exact"), train=_dataset())

    return [
        (healthy_id, healthy_factory, frozenset()),
        (
            unfalsifiable_id,
            unfalsifiable_factory,
            frozenset(
                {
                    DefectClass.INVERT_PASSES,
                    DefectClass.NOOP_PASSES,
                    DefectClass.KNOWN_WRONG_PASSES,
                    DefectClass.SEPARABILITY_LOSS,
                    DefectClass.TRIVIAL_FLOOR_BREACH,
                    DefectClass.REWARD_HACKABLE,
                }
            ),
        ),
        (
            weak_id,
            weak_factory,
            # Accepting any non-empty answer also destroys separability: a
            # strong and a weak answer are both non-empty. Verified directly
            # against the scorer in tests/test_corpus_ground_truth.py.
            frozenset(
                {
                    DefectClass.KNOWN_WRONG_PASSES,
                    DefectClass.INVERT_PASSES,
                    DefectClass.REWARD_HACKABLE,
                    DefectClass.TRIVIAL_FLOOR_BREACH,
                    DefectClass.SEPARABILITY_LOSS,
                }
            ),
        ),
        (
            flat_id,
            flat_factory,
            # A constant 0.5 for everyone is four defects, not one: the gold
            # answer never passes, nothing separates, an input-ignoring answer
            # ties the best real one, and a wrong answer is paid full price for
            # completing nothing. Each verified against the scorer directly.
            frozenset(
                {
                    DefectClass.SEPARABILITY_LOSS,
                    DefectClass.GOLD_FAILS,
                    DefectClass.TRIVIAL_FLOOR_BREACH,
                    DefectClass.REWARD_HACKABLE,
                }
            ),
        ),
        (leaky_id, leaky_factory, frozenset({DefectClass.CONTAMINATION_EXACT})),
    ]


# -- registration -----------------------------------------------------------


def _probe() -> tuple[bool, str]:
    try:
        import inspect_ai  # noqa: F401
    except ImportError as exc:
        return False, f"inspect_ai not installed: {exc}"
    return True, "ok"


def corpus_entries() -> list[CorpusEntry]:
    from .adapters.inspect_ai_adapter import InspectAdapter

    return build_inspect_environments(InspectAdapter)


def corpus_provenance() -> dict[str, Provenance]:
    """Third-party runtime, first-party environments.

    inspect_ai is somebody else's framework, but the dataset is five QA pairs
    written in this file and the defective scorers (`always_correct`,
    `any_nonempty`, `constant_partial`) are written here too. Calling these
    "third-party environments" because they run on inspect_ai would be the same
    move as calling a defect in our own fixture a finding about Python.

    The labels are re-derived without Assay in the loop --
    `tests/test_corpus_ground_truth.py` drives inspect_ai's own scorer -- but
    they are still ours.
    """
    return {
        env_id: Provenance(
            EnvAuthor.THIRD_PARTY_FORMAT,
            LabelSource.PLANTED_HERE,
            "our dataset and our scorers on inspect_ai's runtime; labels "
            "re-derived from inspect_ai's own scorer in tests",
        )
        for env_id, _, _ in corpus_entries()
    }


register("inspect_ai", corpus_entries, _probe, provenance=corpus_provenance)
