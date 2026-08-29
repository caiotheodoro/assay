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

from .adapter import EnvAdapter
from .types import DefectClass

#: (env_id, factory, planted defects)
CorpusEntry = tuple[str, Callable[[], EnvAdapter], frozenset[DefectClass]]

#: What a `_<name>_corpus.py` module returns from `corpus_entries()`.
Loader = Callable[[], list[CorpusEntry]]


@dataclass(frozen=True)
class Provider:
    name: str
    loader: Loader
    #: Returns (usable, reason). Checked before loading; the reason is reported.
    probe: Callable[[], tuple[bool, str]] = lambda: (True, "ok")


_PROVIDERS: dict[str, Provider] = {}
_DISCOVERED = False


def register(
    name: str,
    loader: Loader,
    probe: Callable[[], tuple[bool, str]] | None = None,
) -> None:
    _PROVIDERS[name] = Provider(name, loader, probe or (lambda: (True, "ok")))


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


def unavailable() -> dict[str, str]:
    """Ecosystems that could not be loaded here, and the reason for each."""
    return {name: reason for name, (usable, reason) in availability().items() if not usable}
