"""τ²-bench's two domains, labelled by a diff of two pinned revisions.

These are the only environments in the corpus whose ground truth was
established by **another organisation**, in a repository, at a commit.
`inspect_evals/{paws,boolq}` next door are external environments whose labels a
person here worked out by driving upstream's own scorer; `openenv/*` likewise.
This is `EnvAuthor.EXTERNAL` + `LabelSource.EXTERNALLY_DERIVED`, and it is the
first use of `EXTERNALLY_DERIVED` in the registry.

`docs/ARCHITECTURE.md` said for three slices why this could not be registered:
tau2's ground truth is task-level *"this record differs between two pinned
revisions"*, not a `frozenset[DefectClass]`. That is still true. What changed is
that the mapping between the two has now been derived, written down and
argued -- `tau2_truth.DEFECT_CLASS_BY_MECHANICAL_CATEGORY`, pre-registered in
`docs/PRE-REGISTRATION-TAU2.md` and committed ahead of this file.

Three things worth stating in the same breath as the registration, because each
of them makes the entry look worse than it could:

  - **The label is recomputed, never stored.** `corpus_entries()` calls
    `env_defect_classes(domain)`, which reads both snapshots and re-derives the
    set from the diff on every run. There is no literal in this file to drift
    away from the evidence, and if amazon-agi's fork moves the label moves.
  - **The environment-level set is coarser than the evidence.** Both domains
    come out `{KNOWN_WRONG_PASSES, SPEC_VERIFIER_MISMATCH}`, which records that
    Assay found each class *somewhere* in a domain. Per task it is much weaker:
    0.185 recall on retail's `instruction_underspecification` half.
    `results/tau2_recall.json` is the number that is true about detection, and
    registering these does not retire it.
  - **Fourteen classes are excluded and two of them are things Assay reports
    here anyway.** `GOLD_FAILS` and `NOOP_PASSES` are not established by the
    diff, so findings of them score as spurious. That is the honest price of an
    externally-derived label: it is a lower bound on what is wrong with the
    environment, and the complement is *not* established absent.
"""

from __future__ import annotations

from .adapters.tau2 import DOMAINS, Tau2Adapter, available
from .corpus import CorpusEntry, EnvAuthor, LabelSource, Provenance, register
from .tau2_truth import (
    BASE_REPO,
    BASE_REV,
    VERIFIED_REPO,
    VERIFIED_REV,
    env_defect_classes,
)
from .types import DefectClass

#: The pre-fix task set is the defective one, and the only one the audit path
#: reads. `task_set="verified"` exists for the control run in
#: `scripts/tau2_recall.py` and is not registered: scoring a detector against
#: the corrected fork would be scoring it against an environment nobody ships.
TASK_SET = "base"

FETCH = "uv run --extra tau2 python scripts/tau2_fetch.py"


def _probe() -> tuple[bool, str]:
    """Whether the two pinned snapshots are on this machine.

    Neither repository is redistributed here (`.gitignore`, `.tau2_cache/`), and
    tau2 is not on PyPI, so this is absent far more often than it is present --
    on CI always. `corpus.entries()` drops an unusable provider and
    `unavailable()` reports the reason, which is why the reason carries the
    command rather than only the diagnosis.
    """
    if not available():
        return False, (
            "the two pinned tau2 snapshots are not in the cache and neither is "
            f"redistributed in this repository; fetch them with `{FETCH}`. Without "
            "them the corpus is 2 environments smaller and every arm's loss falls."
        )
    try:  # the runtime, not just the data -- the adapter drives tau2's evaluators
        from .adapters.tau2 import _tau2_modules

        _tau2_modules()
    except Exception as exc:  # pragma: no cover - depends on the local env
        return False, f"tau2 snapshots are present but its runtime is not importable ({exc})"
    return True, "ok"


def _note(domain: str, defects: frozenset[DefectClass]) -> str:
    return (
        f"tau2-bench {domain}, audited as shipped at {BASE_REPO}@{BASE_REV[:10]}. The "
        f"label is a diff, not a judgement: a task is a positive iff its record differs "
        f"at {VERIFIED_REPO}@{VERIFIED_REV[:10]}, which is a `json.load` and an `==` "
        f"anyone can recompute and nothing here gets a vote on. "
        f"{', '.join(sorted(d.value for d in defects))} follow from the two rules in "
        "tau2_truth.DEFECT_CLASS_BY_MECHANICAL_CATEGORY -- the answer key changed, or "
        "only the brief did -- derived and justified in docs/PRE-REGISTRATION-TAU2.md "
        "and checked against the snapshots, with Assay out of the loop, by "
        "tests/test_tau2_corpus_ground_truth.py. Fourteen classes are excluded with a "
        "written reason each in tau2_truth.EXCLUDED_DEFECT_CLASSES; GOLD_FAILS and "
        "NOOP_PASSES are among them and Assay reports both here, so they score as "
        "spurious. The environment-level set is coarser than the evidence -- per-task "
        "recall is in results/tau2_recall.json and is far lower."
    )


def corpus_entries() -> list[CorpusEntry]:
    return [
        (
            f"tau2/{domain}",
            (lambda d=domain: Tau2Adapter(d, task_set=TASK_SET)),
            env_defect_classes(domain),
        )
        for domain in DOMAINS
    ]


def corpus_provenance() -> dict[str, Provenance]:
    return {
        f"tau2/{domain}": Provenance(
            EnvAuthor.EXTERNAL,
            LabelSource.EXTERNALLY_DERIVED,
            _note(domain, env_defect_classes(domain)),
        )
        for domain in DOMAINS
    }


register("tau2", corpus_entries, _probe, provenance=corpus_provenance)
