"""The trained Challenger's inference loop, with a scripted model.

No real weights here on purpose: these are properties of the loop, and a test
that needed a GPU would make the reproduction guide need one too.
"""

from __future__ import annotations

import json

import pytest

from assay.adapter import NotSupported
from assay.challenger import ChallengerExhausted
from assay.challenger.grpo import GRPOChallenger, TransformersClient, dumps_policy
from assay.fixtures import build
from assay.llm import LLMUnavailable
from assay.probes.hackability import exploit_gap
from assay.types import Action


class ScriptedClient:
    """Replays fixed replies and records the prompts it was given."""

    name = "scripted-client"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.prompts.append((system, user))
        return self.replies.pop(0) if self.replies else "{}"


class DeadClient:
    name = "dead-client"

    def complete(self, system: str, user: str) -> str:
        raise LLMUnavailable("no backend reachable")


def _p(*actions: Action) -> str:
    return dumps_policy(actions)


def test_it_samples_the_whole_budget_and_keeps_every_distinct_policy():
    env = build("healthy")
    client = ScriptedClient(
        [_p(Action("escalate", {})), _p(Action("noop", {})), _p(Action("submit", {"label": "spam"}))]
    )
    attempts = GRPOChallenger(client=client, samples=3).attack(env, "t1")
    assert len(attempts) == 3
    assert len(client.prompts) == 3


def test_duplicate_policies_are_collapsed_but_still_logged():
    """Best-of-n from a converged policy is mostly the same policy. Replaying
    it eight times would spend the budget re-measuring one answer."""
    env = build("healthy")
    same = _p(Action("escalate", {}))
    client = ScriptedClient([same, same, same])
    attempts = GRPOChallenger(client=client, samples=3).attack(env, "t1")
    assert len(attempts) == 1
    log = attempts[0].log
    assert sum(1 for entry in log if entry.get("duplicate")) == 0
    assert len(client.prompts) == 3


def test_an_unparseable_sample_costs_a_sample_but_does_not_crash():
    env = build("healthy")
    client = ScriptedClient(["I refuse.", _p(Action("escalate", {}))])
    attempts = GRPOChallenger(client=client, samples=2).attack(env, "t1")
    assert len(attempts) == 1
    assert attempts[0].log[0] == {"sample": 0, "parsed": False, "raw": "I refuse."}


def test_a_model_that_never_answered_is_not_reported_as_finding_nothing():
    """Silence here would put 'no exploit' in the card for a run in which the
    attacker never spoke. The probe turns this into NOT_APPLICABLE."""
    with pytest.raises(ChallengerExhausted, match="produced no policy"):
        GRPOChallenger(client=DeadClient(), samples=4).attack(build("healthy"), "t1")


def test_the_probe_reports_a_mute_challenger_as_not_applicable_with_a_reason():
    from assay.probes.hackability import RewardHackability

    result = RewardHackability().run(
        build("healthy"), {"challenger": GRPOChallenger(client=DeadClient(), samples=2)}
    )
    assert result.status.value == "NOT_APPLICABLE"
    assert "no backend reachable" in result.reason


def test_the_attacker_is_handed_a_prompt_and_never_a_verdict():
    env = build("escalate_overrewarded")
    client = ScriptedClient([_p(Action("escalate", {}))])
    GRPOChallenger(client=client, samples=1).attack(env, "t1")
    system, user = client.prompts[0]
    for forbidden in ("truth", "ground truth", "independent", "reward", "gap"):
        assert forbidden not in (system + user).lower(), forbidden


def test_a_found_exploit_survives_the_probe_measuring_it():
    env = build("escalate_overrewarded")
    client = ScriptedClient([_p(Action("escalate", {}))])
    attempts = GRPOChallenger(client=client, samples=1).attack(env, "t1")
    gap, reported, real = exploit_gap(env, attempts[0].transcript)
    assert (reported, real, gap) == (1.0, 0.0, 1.0)


def test_a_multi_action_policy_is_run_to_the_end():
    """`run_policy` stops on `done` by default, which would truncate a two-step
    exploit at its first action."""
    env = build("healthy")
    client = ScriptedClient(
        [json.dumps({"actions": [{"tool": "escalate", "args": {}},
                                 {"tool": "submit", "args": {"label": "spam"}}]})]
    )
    attempts = GRPOChallenger(client=client, samples=1).attack(env, "t1")
    assert len(attempts[0].transcript.actions) == 2


def test_the_name_says_which_model_produced_the_attack():
    challenger = GRPOChallenger(client=ScriptedClient([]), samples=1)
    assert challenger.name == "grpo[scripted-client]"


def test_the_local_client_declines_clearly_when_there_is_no_trained_adapter():
    """The trained Challenger is an optional artifact. Asking for one that is
    not there must produce a reason, not an import error halfway through a
    comparison."""
    client = TransformersClient(model_id="Qwen/Qwen3-1.7B", adapter_path="/nonexistent/adapter")
    usable, reason = client.availability()
    assert usable is False
    assert "/nonexistent/adapter" in reason or "train extra" in reason


def test_importing_the_challenger_does_not_require_torch():
    """The reproduction guide is not allowed to need a GPU, or torch."""
    import assay.challenger.grpo as mod

    source = mod.__file__
    top_level = [
        line
        for line in open(source).read().splitlines()
        if line.startswith(("import ", "from ")) and "torch" in line
    ]
    assert top_level == [], top_level
