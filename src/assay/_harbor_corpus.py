"""Harbor fixture tasks paired with the defects planted in them.

Every defect here is verified independently in tests/test_harbor_ground_truth.py
by running the task's own scripts, not by asking Assay what it thinks.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

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
    # The verifier runs inside the agent's own workspace, so the agent can
    # rewrite test.sh to exit 0. Verified directly in
    # tests/test_harbor_ground_truth.py, not inferred from what Assay reported.
    "shared-tests": frozenset({DefectClass.REWARD_HACKABLE}),
    # The verifier reads its expectation from a file the agent can overwrite.
    # A policy that writes the same value to both passes while doing nothing.
    # The scripted Challenger does not find this; that is the point of it being
    # in the corpus.
    "self-graded": frozenset({DefectClass.REWARD_HACKABLE}),
}


def build_harbor_environments(adapter_cls, sandbox_factory) -> list[tuple[str, Any, frozenset]]:
    def factory(name: str):
        def make():
            root = Path(tempfile.mkdtemp(prefix=f"assay-harbor-{name}-"))
            shutil.copytree(SUITE / name, root / name)
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
