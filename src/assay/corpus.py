"""The audited corpus: environments paired with the defects planted in them.

Ecosystems register themselves. A module named `_<name>_corpus.py` anywhere in
this package is discovered automatically and asked for its entries, so adding
an ecosystem means adding a file -- never editing this one. That matters when
several people are adding ecosystems at once: a shared registration function is
a merge conflict waiting to happen, and the conflict lands on the file that
decides what gets audited.

An ecosystem whose runtime is missing is reported, loudly, with the reason. It
is never quietly dropped: a corpus that shrank because Docker was not running
would make every arm look better than it is.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

from enum import Enum

from .adapter import EnvAdapter
from .types import DefectClass

#: (env_id, factory, planted defects)
CorpusEntry = tuple[str, Callable[[], EnvAdapter], frozenset[DefectClass]]


class EnvAuthor(Enum):
    """Who wrote the environment being audited."""

    #: Written in this repository, top to bottom.
    AUTHORED_HERE = "authored_here"
    #: Our content in somebody else's file format or runtime. An `inspect_ai`
    #: task whose scorer we wrote is this, not EXTERNAL -- the ecosystem is
    #: third-party, the environment is not.
    THIRD_PARTY_FORMAT = "third_party_format"
    #: Somebody else's environment, audited as shipped.
    EXTERNAL = "external"


class LabelSource(Enum):
    """Who established the ground truth, which is the harder question."""

    #: We planted the defect, so we know it is there.
    PLANTED_HERE = "planted_here"
    #: Derived from something outside this repo that can be recomputed --
    #: a diff between two pinned upstream revisions, an upstream issue.
    EXTERNALLY_DERIVED = "externally_derived"
    #: A human read it and judged, with the judgement written down.
    HAND_TRIAGED = "hand_triaged"
    #: Nobody has established anything. An empty defect set here means
    #: "not looked at", NOT "clean" -- and the two must never score alike.
    UNAUDITED = "unaudited"


@dataclass(frozen=True)
class Provenance:
    """Where an environment and its labels came from.

    This exists because `frozenset()` is ambiguous. On a loss function where a
    clean environment is worth 14 free points against `flag_everything`, an
    environment nobody audited and an environment verified clean score
    identically -- so a corpus can be grown into a better headline without
    anybody lying. Provenance is what makes that visible.
    """

    env_author: EnvAuthor
    label_source: LabelSource
    note: str = ""

    @property
    def is_evidence(self) -> bool:
        """Whether this environment's score means anything on its own."""
        return self.label_source is not LabelSource.UNAUDITED

#: What a `_<name>_corpus.py` module returns from `corpus_entries()`.
Loader = Callable[[], list[CorpusEntry]]


@dataclass(frozen=True)
class Provider:
    name: str
    loader: Loader
    #: Returns (usable, reason). Checked before loading; the reason is reported.
    probe: Callable[[], tuple[bool, str]] = lambda: (True, "ok")
    #: env_id -> Provenance. A provider that declares none leaves its
    #: environments UNAUDITED, which `tests/test_corpus_registry.py` fails on
    #: rather than letting an undeclared environment pass as clean.
    provenance: Callable[[], dict[str, "Provenance"]] = dict


_PROVIDERS: dict[str, Provider] = {}
_DISCOVERED = False


def register(
    name: str,
    loader: Loader,
    probe: Callable[[], tuple[bool, str]] | None = None,
    provenance: Callable[[], dict[str, Provenance]] | None = None,
) -> None:
    _PROVIDERS[name] = Provider(
        name, loader, probe or (lambda: (True, "ok")), provenance or dict
    )


def _discover() -> None:
    """Import every `_*_corpus.py` in this package so it can register."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True
    package = __name__.rsplit(".", 1)[0]
    module = importlib.import_module(package)
    for info in pkgutil.iter_modules(module.__path__):
        if info.name.startswith("_") and info.name.endswith("_corpus"):
            importlib.import_module(f"{package}.{info.name}")


def providers() -> dict[str, Provider]:
    _discover()
    return dict(_PROVIDERS)


def availability() -> dict[str, tuple[bool, str]]:
    """What the corpus can actually run here, and why not when it cannot."""
    return {name: p.probe() for name, p in providers().items()}


def entries(only: list[str] | None = None, skip: list[str] | None = None) -> list[CorpusEntry]:
    out: list[CorpusEntry] = []
    for name, provider in sorted(providers().items()):
        if only and name not in only:
            continue
        if skip and name in skip:
            continue
        usable, _reason = provider.probe()
        if not usable:
            continue
        out.extend(provider.loader())
    return out


def ground_truth(
    only: list[str] | None = None, skip: list[str] | None = None
) -> dict[str, frozenset[DefectClass]]:
    return {env_id: defects for env_id, _, defects in entries(only, skip)}


#: What an environment gets when its provider declared nothing. Deliberately
#: the loudest value: absence of a declaration is absence of evidence.
UNDECLARED = Provenance(
    EnvAuthor.AUTHORED_HERE,
    LabelSource.UNAUDITED,
    "no provenance declared by the registering provider",
)


def provenance(
    only: list[str] | None = None, skip: list[str] | None = None
) -> dict[str, Provenance]:
    """Provenance for every environment the corpus would load here."""
    declared: dict[str, Provenance] = {}
    for name, provider in sorted(providers().items()):
        if only and name not in only:
            continue
        if skip and name in skip:
            continue
        usable, _reason = provider.probe()
        if not usable:
            continue
        declared.update(provider.provenance())
    return {
        env_id: declared.get(env_id, UNDECLARED)
        for env_id, _, _ in entries(only, skip)
    }


def unavailable() -> dict[str, str]:
    """Ecosystems that could not be loaded here, and the reason for each."""
    return {name: reason for name, (usable, reason) in availability().items() if not usable}
