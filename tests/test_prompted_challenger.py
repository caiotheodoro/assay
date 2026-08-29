"""The prompted Challenger's loop mechanics, with a scripted model.

No real model here on purpose: these are properties of the loop, and they
should not depend on what a 8B parameter model happens to say today.
"""

from __future__ import annotations

import json

import pytest

from assay.challenger.prompted import PromptedChallenger
from assay.fixtures import build


class ScriptedClient:
    """Replays fixed replies, and records the prompts it was given."""

    name = "scripted-client"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, system: str, user: str) -> str:
        self.prompts.append(user)
        return self.replies.pop(0) if self.replies else "{}"


def _reply(label: str, solves: bool = False) -> str:
    return json.dumps(
        {"reasoning": "x", "tool": "submit", "args": {"label": label}, "solves_the_task": solves}
    )


class CountingEnv:
    """Wraps a fixture and counts resets."""

    def __init__(self, inner):
        self.inner = inner
        self.resets = 0

    def reset(self, task_id, seed=0):
        self.resets += 1
        return self.inner.reset(task_id, seed)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_the_episode_is_opened_once_not_once_per_turn():
    """Resetting per turn wiped the attacker's own writes between turns."""
    env = CountingEnv(build("healthy"))
    client = ScriptedClient([_reply("spam"), _reply("billing"), _reply("technical")])
    PromptedChallenger(client=client, turns=3).attack(env, "t1")
    assert env.resets == 1, f"expected one reset for the whole attack, got {env.resets}"


def test_each_attempt_is_a_prefix_of_the_same_run():
    env = build("healthy")
    client = ScriptedClient([_reply("spam"), _reply("billing"), _reply("technical")])
    attempts = PromptedChallenger(client=client, turns=3).attack(env, "t1")
    assert [len(a.transcript.actions) for a in attempts] == [1, 2, 3]


def test_snapshots_do_not_alias_the_live_transcript():
    """A shared list would make every attempt look like the final one."""
    env = build("healthy")
    client = ScriptedClient([_reply("spam"), _reply("billing")])
    attempts = PromptedChallenger(client=client, turns=2).attack(env, "t1")
    assert attempts[0].transcript.actions is not attempts[1].transcript.actions
    assert len(attempts[0].transcript.actions) == 1


def test_it_does_not_stop_on_a_score_it_admits_it_earned():
    """Breaking on score alone let it stop the moment it solved the task."""
    env = build("healthy")
    client = ScriptedClient([_reply("billing", solves=True), _reply("spam"), _reply("technical")])
    attempts = PromptedChallenger(client=client, turns=3).attack(env, "t1")
    assert len(attempts) == 3, "an earned score must not end the search"


def test_the_attacker_never_gets_to_end_the_search_early():
    """Both ways of letting it decide failed in practice: stopping on score
    ended the run when it legitimately solved the task; stopping on its
    self-report ended the run when it said "not solved" about something the
    independent verifier scored as a full solve. It cannot see true completion,
    so it cannot know, so it does not choose."""
    env = build("escalate_overrewarded")
    escalate = json.dumps(
        {"reasoning": "x", "tool": "escalate", "args": {}, "solves_the_task": False}
    )
    client = ScriptedClient([escalate, _reply("spam"), _reply("billing")])
    attempts = PromptedChallenger(client=client, turns=3).attack(env, "t1")
    assert len(attempts) == 3, "the whole budget is spent; the probe picks the best gap"


def test_the_prompt_discounts_a_score_the_attacker_says_it_earned():
    env = build("healthy")
    client = ScriptedClient([_reply("billing", solves=True), _reply("spam")])
    PromptedChallenger(client=client, turns=2).attack(env, "t1")
    second = client.prompts[1]
    assert "Best score on an answer you believe is wrong: 0.0" in second
    assert "does not count" in second
    assert "a high score is not proof" in second.lower()


def test_the_prompt_calls_out_a_stuck_loop():
    """Claude repeated one action eight times after scoring; silence let it."""
    env = build("healthy")
    same = [_reply("spam"), _reply("spam"), _reply("spam"), _reply("spam")]
    client = ScriptedClient(same)
    PromptedChallenger(client=client, turns=4).attack(env, "t1")
    assert any("repeated the same action three times" in p for p in client.prompts)
    assert any("reset_environment" in p for p in client.prompts)


def test_a_malformed_reply_costs_a_turn_but_does_not_crash():
    env = build("healthy")
    client = ScriptedClient(["I will not comply.", _reply("spam")])
    attempts = PromptedChallenger(client=client, turns=2).attack(env, "t1")
    assert len(attempts) == 1
    assert any("not a single JSON object" in p for p in client.prompts[1:])


# -- composition ------------------------------------------------------------


def test_a_composite_never_loses_what_a_member_would_find():
    """The regression this exists for: pointing the prompted Challenger at a
    verifier that always passes LOST the defect the scripted repertoire catches
    for free, because the model never tried submitting nothing."""
    from assay import audit
    from assay.challenger import CompositeChallenger, ScriptedChallenger
    from assay.types import DefectClass

    env = build("escalate_overrewarded")

    class Useless:
        """A Challenger that tries one harmless thing and finds nothing."""

        name = "useless"

        def attack(self, adapter, task_id):
            from assay.adapter import run_policy
            from assay.challenger.base import Attempt
            from assay.types import Action as Act

            actions = [Act("submit", {"label": adapter._target(task_id)})]
            return [Attempt("useless:1", run_policy(adapter, task_id, actions))]

    alone = audit(env, {"challenger": Useless()})
    assert DefectClass.REWARD_HACKABLE not in alone.detected

    composed = audit(
        env, {"challenger": CompositeChallenger([ScriptedChallenger(), Useless()])}
    )
    assert DefectClass.REWARD_HACKABLE in composed.detected


def test_a_composite_finding_names_the_attacker_that_produced_it():
    from assay import audit
    from assay.challenger import CompositeChallenger, ScriptedChallenger
    from assay.types import DefectClass

    report = audit(
        build("escalate_overrewarded"),
        {"challenger": CompositeChallenger([ScriptedChallenger()])},
    )
    finding = [f for f in report.findings if f.defect is DefectClass.REWARD_HACKABLE][0]
    assert finding.evidence["exploit_policy"].startswith("scripted/")


def test_a_composite_needs_a_member():
    from assay.challenger import CompositeChallenger

    with pytest.raises(ValueError):
        CompositeChallenger([])


class DeadClient:
    """A backend that is reachable at availability() time and dies on use."""

    name = "dead-client"

    def __init__(self, die_after: int = 0) -> None:
        self.die_after = die_after
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        from assay.llm import LLMUnavailable

        self.calls += 1
        if self.calls > self.die_after:
            raise LLMUnavailable("dead-client: ollama daemon went away")
        return _reply(f"turn{self.calls}")


def test_a_challenger_that_never_spoke_is_not_applicable_not_a_clean_pass():
    """The whole point of the ablation: an arm that could not speak is not an
    arm that found nothing.

    A silent `break` on the first LLMUnavailable returned an empty attempt
    list, which the probe reported as PASS with `n_attempts=0` and an empty
    `attacker_trace` -- identical, in the console and in the results JSON, to a
    challenger that attacked ten times and failed. Observed for real: two
    `--models qwen3:8b` ablation runs printed `missed gap=0.00 attempts= 0`
    after ~187s, just past the 180s client timeout.
    """
    from assay import audit
    from assay.types import ProbeStatus

    report = audit(
        build("escalate_overrewarded"),
        {"challenger": PromptedChallenger(client=DeadClient(die_after=0), turns=5)},
    )
    probe = [r for r in report.results if r.family == "reward_hackability"][0]
    assert probe.status is ProbeStatus.NOT_APPLICABLE
    assert "went away" in (probe.reason or "")
    assert "could not act" in (probe.reason or "")


def test_a_challenger_that_spoke_then_died_keeps_what_it_managed():
    """Partial evidence beats none: the attempts that were scored survive, and
    the trace says the run ended early rather than ending silently.

    Per task, not per run: the probe attacks each task with a fresh budget, so a
    task on which nothing was scored is still an ERROR. That is the same rule,
    applied at the level the attempts are counted at.
    """
    env = build("escalate_overrewarded")
    task_id = env.manifest().tasks[0].task_id
    challenger = PromptedChallenger(client=DeadClient(die_after=2), turns=5)

    attempts = challenger.attack(env, task_id)

    assert len(attempts) == 2
    assert any("unavailable" in str(turn.get("action", {})) for turn in attempts[-1].log)
