"""The audited corpus: environments paired with the defects planted in them.

Ground truth is exact because the defects were planted. Everything here is
constructed in-process and deterministically, so the whole comparison reruns
on a laptop with no GPU, no API key, and no network.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from .adapter import EnvAdapter
from .fixtures import CATALOG as FIXTURE_CATALOG, build as build_fixture
from .types import DefectClass

CorpusEntry = tuple[str, Callable[[], EnvAdapter], frozenset[DefectClass]]


def fixture_entries() -> list[CorpusEntry]:
    return [
        (f"fixture/{variant}", (lambda v=variant: build_fixture(v)), defects)
        for variant, defects in FIXTURE_CATALOG.items()
    ]


def inspect_entries() -> list[CorpusEntry]:
    """Real `inspect_ai.Task` objects with defects written into the scorer.

    Skipped, with a reason, when inspect_ai is not installed -- an absent
    optional dependency must not silently shrink the corpus.
    """
    try:
        from .adapters.inspect_ai_adapter import InspectAdapter
        from ._inspect_corpus import build_inspect_environments
    except ImportError:
        return []
    return build_inspect_environments(InspectAdapter)


def entries(include_inspect: bool = True) -> list[CorpusEntry]:
    out = fixture_entries()
    if include_inspect:
        out += inspect_entries()
    return out


def ground_truth(include_inspect: bool = True) -> dict[str, frozenset[DefectClass]]:
    return {env_id: defects for env_id, _, defects in entries(include_inspect)}
