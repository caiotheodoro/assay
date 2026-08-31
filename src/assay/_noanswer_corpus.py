"""Environments with no correct answer, and nothing planted in them.

These exist to measure a false-positive class rather than a detection. The
battery's verifier-integrity, separability and spec-match probes all ask
questions that presuppose a correct answer, and on an opinion inventory or a
free-writing prompt that presumption is false -- so the probes fire, correctly
by their own logic and wrongly about the environment.

`frozenset()` here means what it says: **nothing is planted, and we know it**.
That is not the same value as an unaudited environment carrying `frozenset()`
because nobody looked, which is the distinction `corpus.scored_entries()` was
built to keep. Every finding Assay reports on these is a false positive, they
are scored, and the deterministic arm pays for them.

Predicted before they were written, in `docs/PRE-REGISTRATION-NOANSWER.md`:
four spurious classes each, and `assay+auditor` recovering all four.

One deviation from that document, recorded rather than quietly reconciled: it
names the Likert environment `noanswer/likert`, and it ships as
`toy-triage/preference` because trajectories 9 and 10 already reference that id
and renaming it would break two committed deliverables to tidy a name.
"""

from __future__ import annotations

from .corpus import CorpusEntry, EnvAuthor, LabelSource, Provenance, register
from .fixtures.preference import OpenEndedEnv, PreferenceEnv, RankingEnv

#: env_id -> (factory, why this environment has no correct answer)
CATALOG = {
    "toy-triage/preference": (
        PreferenceEnv,
        "a five-point agreement scale; every point is a legitimate response and "
        "the trait score is computed from the answer, not graded against a key",
    ),
    "noanswer/ranking": (
        RankingEnv,
        "rank four options by personal preference; every permutation is a "
        "defensible answer",
    ),
    "noanswer/openended": (
        OpenEndedEnv,
        "a short free-writing prompt with no key to grade against",
    ),
}


def corpus_entries() -> list[CorpusEntry]:
    return [
        (env_id, (lambda f=factory: f()), frozenset())
        for env_id, (factory, _) in CATALOG.items()
    ]


def corpus_provenance() -> dict[str, Provenance]:
    return {
        env_id: Provenance(
            EnvAuthor.AUTHORED_HERE,
            LabelSource.PLANTED_HERE,
            f"nothing planted, deliberately: {why}. Every finding Assay reports "
            "here is a false positive and is scored as one.",
        )
        for env_id, (_, why) in CATALOG.items()
    }


register("noanswer", corpus_entries, provenance=corpus_provenance)
