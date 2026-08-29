"""In-process fixture environments. Always available: no Docker, no network."""

from __future__ import annotations

from .corpus import CorpusEntry, register
from .fixtures import CATALOG, build


def corpus_entries() -> list[CorpusEntry]:
    return [
        (f"fixture/{variant}", (lambda v=variant: build(v)), defects)
        for variant, defects in CATALOG.items()
    ]


register("fixture", corpus_entries)
