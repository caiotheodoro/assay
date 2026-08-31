"""Harbor fixture tasks paired with the defects planted in them.

Every defect here is verified independently in tests/test_harbor_ground_truth.py
by running the task's own scripts, not by asking Assay what it thinks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# The staging helper only, never the adapter class: which adapter builds these
# environments stays the caller's choice, which is what makes the registry
# testable with a stand-in.
from .adapters.harbor import stage_suite
from .corpus import CorpusEntry, EnvAuthor, LabelSource, Provenance, register
from .types import DefectClass

SUITE = Path(__file__).parent / "fixtures" / "harbor_suite"

CATALOG: dict[str, frozenset[DefectClass]] = {
    "healthy": frozenset(),
    # A verifier that always exits 0 fails on every axis it touches.
    "vacuous-tests": frozenset(
        {
            DefectClass.NOOP_PASSES,
            DefectClass.KNOWN_WRONG_PASSES,
            DefectClass.SEPARABILITY_LOSS,
            DefectClass.TRIVIAL_FLOOR_BREACH,
            DefectClass.REWARD_HACKABLE,
        }
    ),
    # When gold itself fails, every policy scores zero -- so nothing separates
    # and the trivial floor is tied. Downstream consequences, not extra bugs,
    # but real and worth reporting.
    "broken-gold": frozenset(
        {
            DefectClass.GOLD_FAILS,
            DefectClass.SEPARABILITY_LOSS,
            DefectClass.TRIVIAL_FLOOR_BREACH,
        }
    ),
    # ------------------------------------------------------------------
    # Both of these gained TRIVIAL_FLOOR_BREACH after the fact, and the
    # correction improves Assay's score, so it is worth saying exactly what
    # changed and what did not.
    #
    # The environments did not change. The labels were incomplete: an
    # environment that pays full marks for an input-ignoring policy has
    # breached its trivial floor by definition, and both of these do. Nothing
    # here was inferred from a probe firing -- that reasoning is unfalsifiable
    # and it would have been self-serving here, since the missing labels were
    # showing up as two false positives and dragging precision to 0.833.
    #
    # The facts come from each task's own `tests/test.sh` and `truth/test.sh`,
    # pinned in tests/test_harbor_ground_truth.py with no probe in the loop:
    # the environment pays 1.0, the independent verifier says 0.0. The same
    # tests assert neither policy fires on `healthy`, and that cross-wise
    # neither fires on the other's environment -- which is the evidence that
    # the policies were written against a published taxonomy rather than
    # against these two fixtures.
    # ------------------------------------------------------------------
    # V1 in BenchJack's taxonomy (arXiv 2605.12673 Fig. 2), "isolation
    # failure": environment_mode = "shared" puts the verifier inside the
    # agent's own workspace, so it can be rewritten to exit 0. Note deleting it
    # does NOT work -- a missing script fails the exec and scores 0. The flaw is
    # that the evaluator trusts a file the agent can edit.
    "shared-tests": frozenset(
        {DefectClass.REWARD_HACKABLE, DefectClass.TRIVIAL_FLOOR_BREACH}
    ),
    # V7, "trusting untrusted output": the verifier compares two files that
    # both live in the agent's workspace, so writing the same token into both
    # passes while doing nothing. The scripted Challenger missed this until a
    # policy named after the flaw class was added; that miss is why it is here.
    "self-graded": frozenset(
        {DefectClass.REWARD_HACKABLE, DefectClass.TRIVIAL_FLOOR_BREACH}
    ),
}


def build_harbor_environments(adapter_cls, sandbox_factory) -> list[tuple[str, Any, frozenset]]:
    def factory(name: str):
        def make():
            root = stage_suite(SUITE / name, f"assay-harbor-{name}-")
            return adapter_cls(root, sandbox=sandbox_factory(), env_id=f"harbor/{name}")

        return make

    return [(f"harbor/{name}", factory(name), defects) for name, defects in CATALOG.items()]


# -- registration -----------------------------------------------------------


def _probe() -> tuple[bool, str]:
    from .sandbox import docker_available

    if not docker_available():
        return False, "docker daemon not running; Harbor tasks execute in containers"
    return True, "ok"


def corpus_entries() -> list[CorpusEntry]:
    from .adapters.harbor import HarborAdapter
    from .sandbox import AutoApprove, DockerSandbox

    return build_harbor_environments(
        HarborAdapter, lambda: DockerSandbox(AutoApprove("assay corpus run"))
    )


def corpus_provenance() -> dict[str, Provenance]:
    """Harbor's on-disk format; our tasks.

    `src/assay/fixtures/harbor_suite/*/task.toml` says
    `authors = ["assay fixtures"]`. These are not Terminal-Bench tasks -- they
    are tasks we wrote in Terminal-Bench's shape, which is why the two
    environments Assay misses are both here and both ours.
    """
    return {
        env_id: Provenance(
            EnvAuthor.THIRD_PARTY_FORMAT,
            LabelSource.PLANTED_HERE,
            "our task dirs in Harbor's format; labels re-derived by running "
            "each task's own scripts in tests/test_harbor_ground_truth.py",
        )
        for env_id, _, _ in corpus_entries()
    }


register("harbor", corpus_entries, _probe, provenance=corpus_provenance)
