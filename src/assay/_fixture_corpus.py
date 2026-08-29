"""In-process fixture environments. Always available: no Docker, no network."""

from __future__ import annotations

from .corpus import CorpusEntry, EnvAuthor, LabelSource, Provenance, register
from .fixtures import CATALOG, build


def corpus_entries() -> list[CorpusEntry]:
    return [
        (f"fixture/{variant}", (lambda v=variant: build(v)), defects)
        for variant, defects in CATALOG.items()
    ]


def corpus_provenance() -> dict[str, Provenance]:
    """Written here, planted here, and asserted by the test suite.

    `tests/test_probes_fire.py` asserts `detected == planted` on every one of
    these, so Assay's score on them is a passing build rather than a
    measurement. That is a fine thing for a fixture to be and a bad thing for a
    headline to average in, which is what this declaration exists to expose.
    """
    return {
        f"fixture/{variant}": Provenance(
            EnvAuthor.AUTHORED_HERE,
            LabelSource.PLANTED_HERE,
            "asserted exactly by tests/test_probes_fire.py",
        )
        for variant in CATALOG
    }


register("fixture", corpus_entries, provenance=corpus_provenance)
