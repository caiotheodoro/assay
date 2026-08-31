"""Published `inspect_evals` tasks, audited as shipped.

These are the only environments in the corpus this repo did not write. The
`inspect/*` entries next door run on inspect_ai's runtime but the dataset and
the defective scorers are ours; these are somebody else's eval, somebody else's
scorer, and a defect somebody else shipped.

Both labels were established with Assay out of the loop, by driving the
upstream project's own scorer, and are pinned by `tests/test_wild_findings.py`
independently of anything here.

Only the two hand-triaged tasks are registered. The other 32 the sweep reached
are not: "Assay reported no defect" is Assay's claim, not established truth,
and an environment carrying `frozenset()` on that basis would pay
`flag_everything` 14 points -- 112 under `benchmark-publication` -- for work
nobody did. `scored_entries()` would hold them out anyway; not registering them
says the same thing without asking the guard to catch it.

A deviation worth stating plainly, because it costs us a defect we could
otherwise have claimed. Roughly 35 `inspect_evals` factories take
`shuffle: bool = True` and pass it on unseeded, so two identical calls return
different sample orders; `sweep.deterministic_task_args` pins `shuffle=False`
where the factory accepts it, and this module does the same, because a corpus
environment whose dataset order moves would stop `results/full_run.json`
reproducing. **That is why `paws` is not labelled NONDETERMINISM here** even
though the unseeded shuffle is real and execution-confirmed
(`results/wild_sweep_triage.json`): pinning the order removes the defect from
the environment we audit, and scoring a detector against a defect we deleted
would be dishonest in the direction that flatters us.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from .corpus import CorpusEntry, EnvAuthor, LabelSource, Provenance, register
from .types import DefectClass

#: Deterministic subsample size and seed. The sweep audited 25 items per task;
#: the same numbers are used here so a corpus row and a sweep row describe the
#: same thing.
N_SAMPLES = 25
SEED = 0

#: task name -> (planted defects, provenance note).
CATALOG: dict[str, tuple[frozenset[DefectClass], str]] = {
    "paws": (
        frozenset({DefectClass.REWARD_HACKABLE}),
        "third-party eval audited as shipped; label established through "
        "inspect_ai's own includes() over inspect_evals' own record_to_sample, "
        "with Assay out of the loop -- the constant string 'yesno' contains "
        "both targets and scores 8000/8000 on the full pinned split. Pinned by "
        "tests/test_wild_findings.py::TestPawsSubstringScorer. NONDETERMINISM "
        "is deliberately NOT labelled: the unseeded dataset shuffle is real and "
        "execution-confirmed, but this entry pins shuffle=False for "
        "reproducibility, so the defect is absent from the environment audited "
        "here and scoring against it would be planting a defect and deleting it.",
    ),
    "personality_BFI": (
        frozenset(),
        "third-party eval audited as shipped, and the only environment in the "
        "corpus registered because Assay is WRONG about it. The Big Five "
        "Inventory has no correct answer: five responses are equally valid and "
        "the trait score comes from `answer_mapping` metadata, not from "
        "grading. Its scorer's own docstring says it 'checks for response "
        "format rather than factual correctness', so a format check is the "
        "right design. The battery returns INVALID with INVERT_PASSES anyway -- "
        "mechanically correct, semantically wrong -- and that finding is scored "
        "as the false positive it is. Pinned by "
        "tests/test_personality_false_positive.py, which establishes the "
        "upstream half with Assay out of the loop: every offered letter is "
        "accepted, and appending to the target does not invalidate gold. "
        "docs/COVERAGE.md argued this environment OUT of the corpus, correctly, "
        "on the grounds that adding it labelled either way would corrupt the "
        "number -- true while nothing could withhold the false positive, and "
        "no longer true now that `--auditor` can. The premise changed, so the "
        "decision did; see docs/PRE-REGISTRATION-NOANSWER.md.",
    ),
    "boolq": (
        frozenset({DefectClass.SHORTCUT_LEAK}),
        "third-party eval audited as shipped; label established through "
        "inspect_ai's own pattern() with the regex read from inspect_evals' "
        "boolq.py -- r'(Yes|No).?\\Z' anchors, which genuinely helps, but "
        "'know' is 'no' plus one character, so 'I don't know' is credited on "
        "every No item. Pinned by "
        "tests/test_wild_findings.py::TestBoolqAnchoredPattern. Assay reported "
        "this task clean, so it is a real false negative and it is here because "
        "of that, not despite it. Note the hand triage judged this MEDIUM while "
        "DEFAULT_SEVERITY[SHORTCUT_LEAK] is HIGH; scoring uses the class "
        "default and the disagreement is recorded rather than resolved quietly.",
    ),
}

REQUIRED_MODULES = ("inspect_ai", "inspect_evals")


def _probe() -> tuple[bool, str]:
    missing = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        return False, (
            f"{', '.join(missing)} not installed; these are published evals audited "
            "as shipped. Install with `uv sync --extra sweep`."
        )
    return True, "ok"


def _build(name: str) -> Any:
    """One published task, pinned to a deterministic subsample."""
    from .sweep import (
        WildInspectAdapter,
        deterministic_task_args,
        detect_protocol,
        enumerate_tasks,
        subsample,
    )

    ref = next((r for r in enumerate_tasks() if r.name == name), None)
    if ref is None:
        raise LookupError(f"inspect_evals no longer registers a task named {name!r}")
    task = ref.factory(**deterministic_task_args(ref.factory))
    subsample(task, N_SAMPLES, SEED)
    return WildInspectAdapter(
        task, protocol=detect_protocol(task), env_id=f"inspect_evals/{name}"
    )


def corpus_entries() -> list[CorpusEntry]:
    return [
        (f"inspect_evals/{name}", (lambda n=name: _build(n)), defects)
        for name, (defects, _note) in CATALOG.items()
    ]


def corpus_provenance() -> dict[str, Provenance]:
    return {
        f"inspect_evals/{name}": Provenance(
            EnvAuthor.EXTERNAL, LabelSource.HAND_TRIAGED, note
        )
        for name, (_defects, note) in CATALOG.items()
    }


register("inspect_evals", corpus_entries, _probe, provenance=corpus_provenance)
