"""The prompted Challenger's loop mechanics, with a scripted model.

No real model here on purpose: these are properties of the loop, and they
should not depend on what a 8B parameter model happens to say today.
"""

from __future__ import annotations

import json

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


def test_it_does_stop_on_an_unearned_full_score():
    env = build("escalate_overrewarded")
    escalate = json.dumps(
        {"reasoning": "x", "tool": "escalate", "args": {}, "solves_the_task": False}
    )
    client = ScriptedClient([escalate, _reply("spam"), _reply("billing")])
    attempts = PromptedChallenger(client=client, turns=3).attack(env, "t1")
    assert len(attempts) == 1


def test_the_prompt_reports_the_best_unearned_score_not_the_best_score():
    env = build("healthy")
    client = ScriptedClient([_reply("billing", solves=True), _reply("spam")])
    PromptedChallenger(client=client, turns=2).attack(env, "t1")
    second = client.prompts[1]
    assert "Best UNEARNED score so far: 0.0" in second
    assert "does not count" in second


def test_a_malformed_reply_costs_a_turn_but_does_not_crash():
    env = build("healthy")
    client = ScriptedClient(["I will not comply.", _reply("spam")])
    attempts = PromptedChallenger(client=client, turns=2).attack(env, "t1")
    assert len(attempts) == 1
    assert any("not a single JSON object" in p for p in client.prompts[1:])
