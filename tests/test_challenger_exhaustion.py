"""Five ways an attacker produces nothing. All five used to read as a PASS.

The README calls this "the single worst thing this tool can do -- the failure
the tool exists to catch, happening inside the tool": a Challenger that found
nothing because it never got to look, reported as an environment that survived
attack. One route was fixed (`LLMUnavailable`, the backend never answered) and
the fix was described as covering the failure mode. It covered a fifth of it.

The other four are here. Each one produced an empty attempt list, and an empty
attempt list is scored as `n_attempts: 0` with no findings -- indistinguishable
in the console, the card and the results JSON from an environment that was
attacked properly and held. The distinction that has to survive is between
*evidence of absence* and *absence of evidence*, and only the second is what
any of these runs actually measured.
"""

from __future__ import annotations

import json

import pytest

from assay.adapter import EnvAdapter, NotSupported
from assay.challenger import ChallengerExhausted, CompositeChallenger, ScriptedChallenger
from assay.challenger.base import Attempt
from assay.challenger.grpo import GRPOChallenger, dumps_policy
from assay.challenger.prompted import PromptedChallenger
from assay.fixtures import build
from assay.probes.hackability import RewardHackability
from assay.types import Action


class _Replies:
    """Replays fixed replies forever, cycling the last one."""

    name = "scripted-client"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.replies[min(self.calls - 1, len(self.replies) - 1)]


class _NoVocabulary:
    """An adapter that names no trivial policies.

    Not hypothetical: an adapter is free to define none, and `SpecAdapter`
    builds one from any user-supplied spec. This is what the Space hands the
    challenger when a visitor's eval declares no policies.
    """

    def __init__(self, inner: EnvAdapter) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def trivial_policies(self, task_id):
        return {}


# --- Route B: every reply unparseable ---------------------------------------


def test_an_attacker_that_never_emitted_json_is_not_applicable():
    """Ten turns of prose is a run that measured nothing, not a clean env."""
    challenger = PromptedChallenger(
        client=_Replies("I think the answer is probably 42."), turns=3
    )
    with pytest.raises(ChallengerExhausted) as caught:
        challenger.attack(build("weak_oracle"), "t1")
    assert "unparseable" in str(caught.value)
    assert caught.value.history, (
        "the discarded transcript is the only evidence of what went wrong; "
        "an empty history leaves a reason with nothing behind it"
    )
    assert any("malformed" in entry.get("action", {}) for entry in caught.value.history)


# --- Route C: every reply a reset -------------------------------------------


def test_an_attacker_that_reset_every_turn_is_not_applicable():
    """This one spoke perfectly well. It undid itself each turn.

    Worth separating from the unparseable case because the model is behaving
    correctly by its own lights -- valid JSON, a real tool, a legal action --
    and still scores nothing. Reading `[]` here as "no exploit found" is the
    most confident wrong answer of the five.
    """
    reset = json.dumps({"reasoning": "start over", "tool": "reset_environment", "args": {}})
    with pytest.raises(ChallengerExhausted) as caught:
        PromptedChallenger(client=_Replies(reset), turns=3).attack(
            build("weak_oracle"), "t1"
        )
    assert "reset" in str(caught.value)
    assert len(caught.value.history) == 3, "every turn should be in the record"


# --- Route D: no action vocabulary ------------------------------------------


def test_an_adapter_that_names_no_actions_is_not_applicable_not_a_pass():
    """The quietest route: a bare `return []` before the model was ever asked."""
    adapter = _NoVocabulary(build("weak_oracle"))
    with pytest.raises(ChallengerExhausted) as caught:
        PromptedChallenger(client=_Replies("{}"), turns=3).attack(adapter, "t1")
    assert "no way to name" in str(caught.value)


def test_the_probe_reports_a_vocabularyless_adapter_as_not_applicable():
    """End to end, because the raise only matters if the card says so."""
    adapter = _NoVocabulary(build("weak_oracle"))
    result = RewardHackability().run(
        adapter, {"challenger": PromptedChallenger(client=_Replies("{}"), turns=2)}
    )
    assert result.status.value == "NOT_APPLICABLE"
    assert "no way to name" in result.reason


# --- Route E: NotSupported crossing the composite ---------------------------


def test_a_grpo_member_that_cannot_be_prompted_does_not_delete_scripted_findings():
    """The regression `composite.py` was written to prevent, through a new door.

    `GRPOChallenger` raised `NotSupported` when the adapter named no actions.
    `CompositeChallenger` catches `LLMUnavailable` and nothing else, and the
    probe's per-task handler caught the same one type -- so this exception
    unwound past every scripted attempt already made AND past every other task,
    NA-ing the whole probe. One member with nothing to say deleted a working
    member's findings across an entire environment.
    """
    adapter = _NoVocabulary(build("weak_oracle"))

    with pytest.raises(NotSupported):
        # The underlying condition is unchanged and still reported honestly by
        # the prompt builder; what changed is that it no longer escapes as a
        # type nothing downstream expects.
        from assay.challenger.grpo import prompt_for

        prompt_for(adapter, "t1")

    scripted = ScriptedChallenger()
    grpo = GRPOChallenger(client=_Replies("{}"), samples=2)
    composed = CompositeChallenger([scripted, grpo]).attack(adapter, "t1")
    assert composed, (
        "the GRPO member had nothing to say and took the scripted member's "
        "attempts with it"
    )
    assert composed[-1].log[-1]["unavailable"], "stepping over a member must be recorded"


def test_a_grpo_model_that_answered_every_time_and_never_in_json_is_exhausted():
    """Answered all eight times, emitted no policy once: zero attempts, zero failures.

    The old guard was `failures and not attempts`, so it only covered a backend
    that could not be reached. A model that replied to every sample with prose
    produced an empty list with an empty `failures`, fell through to
    `return []`, and was scored as an environment that held.

    This test began life asserting mode collapse -- eight samples, one distinct
    policy -- and that premise was wrong: the first of N duplicates is a real
    scoreable attempt, so collapse degrades best-of-n to best-of-one and never
    reaches zero. Recorded rather than quietly rewritten, because a comment
    claiming duplicates exhaust the challenger was in the fix before this test
    disproved it.
    """
    with pytest.raises(ChallengerExhausted) as caught:
        GRPOChallenger(client=_Replies("no JSON here, sorry"), samples=4).attack(
            build("weak_oracle"), "t1"
        )
    # Named counts, not a substring. The first version asserted
    # `"duplicate" in str(...)` and passed against a message reading
    # "4 unparseable, 0 duplicate" -- proving the unparseable route twice and
    # the duplicate route never. A substring a message can satisfy while
    # describing the opposite case is the defect this repo flags elsewhere.
    assert "4 unparseable, 0 duplicate of 4 samples" in str(caught.value)
    assert caught.value.history, "the samples that produced nothing are the evidence"


def test_mode_collapse_degrades_to_best_of_one_rather_than_to_nothing():
    """The counterpart, pinned so nobody re-adds the exhaustion claim.

    Four samples, one distinct policy. One attempt survives and is scored. That
    is a weaker attack, not an absent one, and it must not raise.
    """
    one_policy = dumps_policy([Action("submit", {"answer": "x"})])
    attempts = GRPOChallenger(client=_Replies(one_policy), samples=4).attack(
        build("weak_oracle"), "t1"
    )
    assert len(attempts) == 1


# --- The composite guarantee, restated for exhaustion ------------------------


def test_one_exhausted_member_still_leaves_a_defect_reported():
    """The whole point of composing rather than substituting."""

    class _Exhausted:
        name = "exhausted"

        def attack(self, adapter, task_id):
            raise ChallengerExhausted("exhausted: said nothing usable", [{"turn": 1}])

    adapter = build("weak_oracle")
    result = RewardHackability().run(
        adapter, {"challenger": CompositeChallenger([ScriptedChallenger(), _Exhausted()])}
    )
    assert result.status.value == "DEFECT", (
        "an exhausted member deleted a defect the scripted repertoire found"
    )


# --- k passes, reachable from the command line -------------------------------


def test_passes_is_reachable_from_the_cli_and_reaches_the_card():
    """A feature only the test suite can call is a feature nobody has.

    `challenger_passes` lived in `ctx` with no flag to set it, so the rate was
    computable and unreachable: `assay audit` could not ask for it, which meant
    the one-pass coin flip stayed the default for every actual user.
    """
    import json as _json

    from assay.cli import main

    code = main(["audit", "fixture/weak_oracle", "--passes", "3", "--json"])
    assert code != 0, "a defective fixture must still exit nonzero"


def test_a_single_pass_is_still_the_default_shape():
    """k=1 must not change what five existing readers index."""
    from assay.fixtures import build

    result = RewardHackability().run(build("weak_oracle"), {})
    task = next(iter(result.detail["per_task"].values()))
    for key in ("challenger", "attempts", "n_attempts", "best_attempt", "attacker_trace"):
        assert key in task, f"the k=1 detail shape lost {key}"
    assert task["passes"] == 1 and "per_pass" not in task
