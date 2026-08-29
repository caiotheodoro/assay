"""Real OpenEnv environments, with the defects they actually have.

Unlike the inspect_ai and Harbor entries, nothing here is planted. These are
two environments shipped by huggingface/OpenEnv, audited as published, and the
ground truth is what an independent check of the environment's own behaviour
establishes -- see `tests/test_openenv_ground_truth.py`, which reads the
underlying TextArena state directly rather than asking Assay what it thinks.

Ground truth here is therefore thin, and honestly so. OpenEnv exposes no
separable verifier, so eight of the nine probe families have no surface to run
on and cannot label anything either way. An empty defect set for `openenv/echo`
means "no defect this battery can see", not "clean" -- which is exactly why the
runner's verdict for both of these is UNVERIFIED rather than VALID.
"""

from __future__ import annotations

import importlib.util

from .corpus import CorpusEntry, EnvAuthor, LabelSource, Provenance, register
from .types import DefectClass

#: Neither environment is on PyPI; only the `openenv` framework is. Both are
#: installed from the pinned revision in the `openenv` extra of pyproject.toml.
REQUIRED_MODULES = {
    "echo_env.server.echo_environment": "openenv/echo",
    "textarena_env.server.environment": "openenv/textarena-wordle",
}


def _missing(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is None
    except (ImportError, ValueError):
        return True


def _nltk_words_present() -> bool:
    """TextArena's Wordle draws its secret word from the NLTK `words` corpus.

    Checked rather than downloaded: an audit that silently pulls a corpus off
    the network is an audit whose result depends on whether the network was up.
    """
    try:
        import nltk
    except ImportError:
        return False
    try:
        nltk.data.find("corpora/words")
    except LookupError:
        return False
    return True


def _probe() -> tuple[bool, str]:
    missing = sorted(m for m in REQUIRED_MODULES if _missing(m))
    if missing:
        return False, (
            f"OpenEnv environments not importable ({', '.join(missing)}); they are not "
            "published to PyPI -- install them with `uv sync --extra openenv`, which "
            "pins the huggingface/OpenEnv revision the audit was run against"
        )
    if not _nltk_words_present():
        return False, (
            "the NLTK `words` corpus is not present locally and TextArena's Wordle "
            "draws its secret word from it; run "
            "`uv run python -c \"import nltk; nltk.download('words')\"` once"
        )
    return True, "ok"


def corpus_entries() -> list[CorpusEntry]:
    from .adapters.openenv import OpenEnvAdapter, echo_binding, wordle_binding

    return [
        (
            "openenv/echo",
            lambda: OpenEnvAdapter(echo_binding()),
            # Reward is hardcoded 0.0 at reset and None on every MCP action, so
            # the environment makes no validity claim there is anything to
            # falsify. Wiring-only, by the environment's own design.
            frozenset(),
        ),
        (
            "openenv/textarena-wordle",
            lambda: OpenEnvAdapter(wordle_binding()),
            # `TextArenaEnvironment.reset(seed=...)` accepts a seed and never
            # passes it to `self._ta_env.reset(...)`, so the secret word is
            # redrawn from an unseeded RNG on every reset. Verified directly
            # against the environment's own state in
            # tests/test_openenv_ground_truth.py, not inferred from Assay.
            frozenset({DefectClass.NONDETERMINISM}),
        ),
    ]


def corpus_provenance() -> dict[str, Provenance]:
    """The only genuinely external environments in the corpus.

    Pinned to `huggingface/OpenEnv@e059726`. Nothing is planted in either. The
    one defect on `textarena-wordle` -- `reset(seed=...)` never forwarding the
    seed -- was found, not planted, and verified against TextArena's own state.

    `openenv/echo` carries `frozenset()`, and here that genuinely means "this
    battery found nothing" rather than "nobody looked": every probe that could
    not run reported NOT_APPLICABLE with a reason, and the verdict is
    UNVERIFIED rather than VALID.
    """
    return {
        "openenv/echo": Provenance(
            EnvAuthor.EXTERNAL,
            LabelSource.HAND_TRIAGED,
            "audited as shipped; no separable verifier, so 11 of 12 probes are "
            "NOT_APPLICABLE and the verdict is UNVERIFIED, not clean",
        ),
        "openenv/textarena-wordle": Provenance(
            EnvAuthor.EXTERNAL,
            LabelSource.EXTERNALLY_DERIVED,
            "defect found in shipping upstream code, still on main; verified "
            "against TextArena's own state in tests/test_openenv_ground_truth.py",
        ),
    }


register("openenv", corpus_entries, _probe, provenance=corpus_provenance)
