"""The OpenEnv adapter against real environments, instantiated in process.

The point of these tests is mostly what does NOT happen. OpenEnv exposes no
separable verifier, so the interesting assertions are that the adapter refuses
to pretend otherwise, that the probes needing one report NOT_APPLICABLE rather
than erroring, and that the reasons they give name the missing capability
instead of trailing off.

They skip cleanly when the environments are not installed. echo_env and
textarena_env are not on PyPI; `uv sync --extra openenv` installs them from the
pinned huggingface/OpenEnv revision.
"""

from __future__ import annotations

import pytest

from assay import audit
from assay.adapter import NotSupported
from assay._openenv_corpus import _probe as openenv_available
from assay.types import Action, Capability, ProbeStatus, Transcript

#: Same availability check the corpus uses, for the same reason: a suite that
#: silently shrank because a dependency was missing would make every arm look
#: better than it is. One source of truth, and the reason travels with it.
_USABLE, _REASON = openenv_available()
needs_openenv = pytest.mark.skipif(not _USABLE, reason=_REASON)
echo_only = needs_openenv
wordle_only = needs_openenv


@pytest.fixture
def echo():
    from assay.adapters.openenv import OpenEnvAdapter, echo_binding

    adapter = OpenEnvAdapter(echo_binding())
    yield adapter
    adapter.close()


@pytest.fixture
def wordle():
    from assay.adapters.openenv import OpenEnvAdapter, wordle_binding

    adapter = OpenEnvAdapter(wordle_binding())
    yield adapter
    adapter.close()


# -- the capabilities that are deliberately absent --------------------------


@echo_only
def test_manifest_withholds_the_separable_verifier(echo):
    """The whole point of the adapter. OpenEnv computes reward inside step(),
    so declaring SEPARABLE_VERIFIER would be a lie that manufactures results
    from probes that never really ran."""
    manifest = echo.manifest()
    assert not manifest.has(Capability.SEPARABLE_VERIFIER)


@echo_only
@pytest.mark.parametrize(
    "capability",
    [
        Capability.GOLD_TRAJECTORY,
        Capability.INVERTIBLE_SPEC,
        Capability.KNOWN_WRONG,
        Capability.GRADED_POLICIES,
        Capability.TRUE_COMPLETION,
        Capability.SPLITS,
        Capability.ITEM_PARTS,
    ],
)
def test_manifest_withholds_everything_openenv_cannot_back(echo, capability):
    assert not echo.manifest().has(capability)


@echo_only
def test_manifest_declares_only_what_openenv_really_offers(echo):
    caps = echo.manifest().capabilities
    assert caps == frozenset(
        {Capability.LIVE_STEPPING, Capability.SEEDED_RESET, Capability.TRIVIAL_POLICIES}
    )


@echo_only
def test_verify_refuses_and_says_why(echo):
    with pytest.raises(NotSupported) as exc:
        echo.verify(Transcript(task_id="echo", seed=0))
    reason = str(exc.value)
    # The message ends up in the card verbatim, so it has to explain itself to
    # a reader who has never opened this adapter.
    assert "step()" in reason
    assert "rfcs/002-env-spec.md" in reason
    assert "episode_reward" in reason


@echo_only
def test_verify_refuses_an_inverted_spec_rather_than_ignoring_it(echo):
    """Returning the step reward here would answer an inverted-spec probe with
    the un-inverted score. Refusing is the only honest option."""
    with pytest.raises(NotSupported):
        echo.verify(Transcript(task_id="echo", seed=0), spec="anything at all")


# -- the in-process seam ----------------------------------------------------


@echo_only
def test_echo_runs_in_process_without_docker_or_http(echo):
    """Instantiating the server-side Environment directly, as OpenEnv's own
    tests do. No container, no uvicorn, no port."""
    from assay.adapters.openenv import CALL_TOOL, LIST_TOOLS

    opening = echo.reset("echo", seed=0)
    assert opening.ok

    listed = echo.step(Action(LIST_TOOLS))
    assert listed.observation.ok
    tools = str(listed.observation.data)
    assert "echo_message" in tools and "echo_with_length" in tools

    said = echo.step(
        Action(CALL_TOOL, {"tool_name": "echo_message", "arguments": {"message": "assay"}})
    )
    assert said.observation.ok
    assert "assay" in str(said.observation.data)


@echo_only
def test_an_unknown_tool_is_an_observation_not_a_crash(echo):
    echo.reset("echo", seed=0)
    result = echo.step(Action("definitely_not_a_tool"))
    assert not result.observation.ok
    assert result.observation.code == "UNKNOWN_TOOL"


@echo_only
def test_unknown_task_id_is_rejected(echo):
    with pytest.raises(KeyError):
        echo.reset("not-a-task", seed=0)


@echo_only
def test_echo_reports_no_usable_reward(echo):
    """echo_env hardcodes 0.0 at reset and leaves reward None on MCP actions.
    Recorded as a fact about the environment, not worked around."""
    from assay.adapters.openenv import LIST_TOOLS

    trace = echo.episode_reward("echo", [Action(LIST_TOOLS)])
    assert trace["rewards"][0] == 0.0  # reset
    assert trace["rewards"][1] is None  # the MCP step reports nothing at all


# -- the reward that step() does return -------------------------------------


@wordle_only
def test_wordle_reports_a_real_reward_through_step(wordle):
    """textarena_env's rewards.py is real logic -- and reachable only by
    playing, which is the constraint this adapter exists to document."""
    trace = wordle.episode_reward(
        "Wordle-v0", wordle.trivial_policies("Wordle-v0")["repeat_one_guess"]
    )
    assert trace["steps"] >= 1
    assert isinstance(trace["final"], float)
    # No assertion on the value: the secret word is drawn unseeded (see
    # tests/test_openenv_ground_truth.py), so the reward genuinely varies run
    # to run. Asserting a number here would be asserting a coin flip.
    assert 0.0 <= trace["final"] <= 1.0


@wordle_only
def test_trivial_policies_are_declared_and_ignore_the_input(wordle):
    policies = wordle.trivial_policies("Wordle-v0")
    assert set(policies) >= {"repeat_one_guess", "fixed_six_guesses", "non_answer", "noop"}
    # "Input-ignoring" is structural here: every policy is a fixed list of
    # actions built before the episode starts, so none of them can read an
    # observation even in principle.
    for actions in policies.values():
        assert all(isinstance(a, Action) for a in actions)


@wordle_only
def test_describe_prints_the_reward_landscape_a_reviewer_would_want(wordle):
    text = wordle.describe()
    assert "verifier: NONE" in text
    assert "reward reported by the environment, per input-ignoring policy" in text
    assert "repeat_one_guess" in text


# -- what the battery does with all that ------------------------------------


@echo_only
def test_probes_needing_a_verifier_are_not_applicable_not_errors(echo):
    """A probe that cannot run is a reportable outcome. A probe that crashed is
    a bug, and the card must not confuse the two."""
    report = audit(echo)
    assert not report.by_status(ProbeStatus.ERROR), [
        (r.probe, r.reason) for r in report.by_status(ProbeStatus.ERROR)
    ]
    unrunnable = report.by_status(ProbeStatus.NOT_APPLICABLE)
    assert len(unrunnable) >= 10
    assert all(r.reason for r in unrunnable)

    blocked_on_verifier = [
        r for r in unrunnable if "SEPARABLE_VERIFIER" in (r.reason or "")
    ]
    assert {r.probe for r in blocked_on_verifier} >= {
        "gold_passes",
        "noop_fails",
        "inverted_fails",
        "known_wrong_fails",
        "trivial_floor",
        "separability",
        "challenger",
    }


@echo_only
def test_an_unprobeable_environment_never_reads_as_valid(echo):
    """Absence of evidence is not evidence of absence, and the verdict says so."""
    report = audit(echo)
    assert report.verdict == "UNVERIFIED"
    assert report.exit_code == 1


@echo_only
def test_determinism_still_runs_without_a_verifier(echo):
    """The one probe that pays for this adapter. Same seed, same episode needs
    observations, not a scorer."""
    report = audit(echo)
    determinism = [r for r in report.results if r.family == "determinism"][0]
    assert determinism.status is ProbeStatus.PASS


@wordle_only
def test_difficulty_band_runs_when_a_solve_rate_is_supplied(wordle):
    """The other probe that needs no verifier -- but it needs an estimate, and
    the finding has to name the policy the estimate came from."""
    from assay.types import DefectClass

    ctx = {
        "solve_rates": {"Wordle-v0": 0.0},
        "solve_rate_source": "scripted input-ignoring policies (no model in the loop)",
    }
    report = audit(wordle, ctx)
    band = [r for r in report.results if r.family == "difficulty_band"][0]
    assert band.status is ProbeStatus.DEFECT
    finding = band.findings[0]
    assert finding.defect is DefectClass.DIFFICULTY_IMPOSSIBLE
    assert finding.evidence["measured_with"] == ctx["solve_rate_source"]
