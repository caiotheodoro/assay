"""Independent verification of the OpenEnv corpus labels.

Correcting a label because the tool disagreed with it is circular. These tests
establish each label from the environment's own behaviour -- reaching into
TextArena's internal state to read the secret word directly, which the adapter
itself is forbidden to do -- so the label stands on its own and Assay can be
scored against it honestly.

Reading server-side internals is exactly what the adapter refuses to do, and
exactly what a ground-truth check is for. The distinction is the point: the
adapter audits what a training run can see, while this file is allowed to look
behind the curtain because its job is to check the answer key, not to produce
the audit.
"""

from __future__ import annotations

import inspect as pyinspect

import pytest

from assay import audit
from assay._openenv_corpus import _probe as openenv_available
from assay.corpus import entries, ground_truth
from assay.types import DefectClass

_USABLE, _REASON = openenv_available()
pytestmark = pytest.mark.skipif(not _USABLE, reason=_REASON)

SEED = 1234
REPEATS = 6


def _secret_word(env) -> str:
    """The Wordle answer, read straight off TextArena's own game state."""
    return str(env._ta_env.state.game_state.get("secret_word"))


# -- openenv/textarena-wordle: NONDETERMINISM -------------------------------


def test_wordle_redraws_its_secret_word_under_a_fixed_seed():
    """The label, established without asking Assay anything.

    `reset(seed=...)` is part of OpenEnv's Environment contract. Passing the
    same seed six times and getting six different hidden words means every
    comparison between two policies on this environment is partly a comparison
    between two different games.
    """
    from textarena_env.server.environment import TextArenaEnvironment

    env = TextArenaEnvironment(env_id="Wordle-v0", num_players=1, download_nltk=False)
    try:
        words = []
        for _ in range(REPEATS):
            env.reset(seed=SEED)
            words.append(_secret_word(env))
    finally:
        env.close()

    assert len(set(words)) > 1, (
        f"expected the secret word to vary under a fixed seed, saw {words}; "
        "if this ever starts passing, textarena_env has been fixed and the "
        "NONDETERMINISM label in _openenv_corpus.py must be removed"
    )


def test_the_seed_is_never_forwarded_to_the_underlying_textarena_env():
    """Corroboration for the behavioural test above, and the mechanism.

    `TextArenaEnvironment.reset` accepts `seed` and calls
    `self._ta_env.reset(num_players=...)` without it, so the argument is
    accepted and dropped. gymnasium's env_checker has the same blind spot --
    it verifies that reset() accepts a seed, never that seeding does anything.
    """
    from textarena_env.server.environment import TextArenaEnvironment

    source = pyinspect.getsource(TextArenaEnvironment.reset)
    assert "seed" in source, "reset no longer takes a seed; this test is stale"
    assert "self._ta_env.reset(num_players=self.num_players)" in source
    assert "seed=seed" not in source


def test_assay_detects_exactly_the_defect_the_environment_has():
    """Exact match, not 'at least'. Recall alone cannot separate detection from
    guessing."""
    planted = ground_truth(only=["openenv"])["openenv/textarena-wordle"]
    assert planted == frozenset({DefectClass.NONDETERMINISM})

    factory = {env_id: f for env_id, f, _ in entries(only=["openenv"])}[
        "openenv/textarena-wordle"
    ]
    adapter = factory()
    try:
        detected = audit(adapter).detected
    finally:
        adapter.close()
    assert detected == planted


# -- openenv/echo: no defect this battery can see ---------------------------


def test_echo_is_reproducible_under_a_fixed_seed():
    """The empty label for openenv/echo, checked rather than assumed."""
    from echo_env.server.echo_environment import EchoEnvironment
    from openenv.core.env_server.mcp_types import CallToolAction

    env = EchoEnvironment()
    try:
        results = []
        for _ in range(REPEATS):
            env.reset(seed=SEED)
            obs = env.step(
                CallToolAction(tool_name="echo_message", arguments={"message": "assay"})
            )
            results.append(str(getattr(obs, "result", obs)))
    finally:
        env.close()
    assert len(set(results)) == 1, results


def test_echo_reports_no_defect_and_still_does_not_read_as_valid():
    """An empty defect set here means 'nothing this battery can see', not
    'clean'. The verdict has to keep those apart or the card lies by omission.
    """
    factory = {env_id: f for env_id, f, _ in entries(only=["openenv"])}["openenv/echo"]
    adapter = factory()
    try:
        report = audit(adapter)
    finally:
        adapter.close()

    assert report.detected == frozenset()
    assert ground_truth(only=["openenv"])["openenv/echo"] == frozenset()
    assert report.verdict == "UNVERIFIED"
    assert report.exit_code == 1


# -- the structural finding, asserted -----------------------------------------


def test_no_openenv_environment_can_be_probed_for_verifier_integrity():
    """The headline result, as a test rather than a claim in a docstring.

    If OpenEnv ever grows a callable verifier this test starts failing, which
    is the right way round: the finding is about the standard as it stands, and
    it should stop being asserted the moment it stops being true.
    """
    for env_id, factory, _ in entries(only=["openenv"]):
        adapter = factory()
        try:
            unrunnable = {
                r.probe: r.reason
                for r in audit(adapter).results
                if r.status.value == "NOT_APPLICABLE"
            }
        finally:
            adapter.close()
        for probe in ("gold_passes", "inverted_fails", "known_wrong_fails", "challenger"):
            assert probe in unrunnable, f"{env_id}: {probe} unexpectedly ran"
            assert "SEPARABLE_VERIFIER" in unrunnable[probe], (env_id, probe)


def test_an_empty_replay_would_have_missed_this_entirely():
    """The determinism probe used to replay nothing, and so could not fail.

    Reproduces both code paths side by side on an environment that genuinely
    is nondeterministic. The old one fingerprints an episode with no turns in
    it and reports PASS; the new one takes six turns and reports a defect. Kept
    as a test because "the check was vacuous" is a claim, and a claim in a
    changelog that nobody can rerun is just an assertion.
    """
    from assay.adapter import NotSupported, run_policy
    from assay.adapters.openenv import OpenEnvAdapter, wordle_binding
    from assay.types import digest

    adapter = OpenEnvAdapter(wordle_binding())
    try:
        try:
            old_policy = adapter.gold_actions("Wordle-v0")
        except NotSupported:
            old_policy = []
        assert old_policy == [], "textarena_env now ships gold; this test is stale"

        old = set()
        for _ in range(3):
            transcript = run_policy(adapter, "Wordle-v0", old_policy, seed=SEED)
            old.add(
                digest(
                    {"observations": [(o.ok, o.data, o.code) for o in transcript.observations]}
                )
            )
        assert len(old) == 1, "the old path was vacuous, not merely weak"

        new_policy = next(
            (list(a) for a in adapter.trivial_policies("Wordle-v0").values() if a), []
        )
        assert new_policy, "the fallback needs a policy that takes at least one turn"

        new = set()
        for _ in range(3):
            opening = adapter.reset("Wordle-v0", seed=SEED)
            transcript = run_policy(adapter, "Wordle-v0", new_policy, seed=SEED)
            new.add(
                digest(
                    {
                        "reset": (opening.ok, opening.data),
                        "observations": [
                            (o.ok, o.data, o.code) for o in transcript.observations
                        ],
                    }
                )
            )
    finally:
        adapter.close()

    assert len(new) > 1, "the same seed should be producing different games"
