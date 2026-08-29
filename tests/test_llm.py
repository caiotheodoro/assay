"""Model clients degrade; they never guess.

Assay's scoring never calls a model -- every oracle is a program -- so an
unreachable backend must weaken the Challenger and leave the verdict alone.
These tests pin that down without depending on any model being installed.
"""

from __future__ import annotations

import pytest

from assay.llm import LLMUnavailable, OllamaClient, default_client


def test_an_unreachable_backend_reports_unavailable_rather_than_raising():
    client = OllamaClient(model="does-not-exist", host="http://localhost:1")
    assert client.available() is False


def test_calling_an_unreachable_backend_raises_a_typed_error():
    client = OllamaClient(model="does-not-exist", host="http://localhost:1")
    with pytest.raises(LLMUnavailable):
        client.complete("system", "user")


def test_thinking_is_off_by_default():
    """A model that reasons in <think> blocks spends its budget on prose when
    the answer is one JSON object."""
    assert OllamaClient().think is False
    assert OllamaClient().num_predict > 0


def test_client_names_identify_the_backend_for_the_card():
    assert OllamaClient("qwen3:8b").name == "ollama:qwen3:8b"


def test_a_challenger_with_no_backend_does_not_take_down_the_audit():
    """The audit must still produce a verdict, and the hackability probe must
    say it could not run rather than reporting a clean nothing."""
    from assay import audit
    from assay.challenger.prompted import PromptedChallenger
    from assay.fixtures import build
    from assay.types import ProbeStatus

    challenger = PromptedChallenger(client=OllamaClient(host="http://localhost:1"))
    report = audit(build("escalate_overrewarded"), {"challenger": challenger})
    probe = [r for r in report.results if r.family == "reward_hackability"][0]
    # Not an ERROR -- an unreachable backend is a degradation, not a crash --
    # and not a PASS either. This used to assert only the first half, and a
    # Challenger that never spoke came back as a clean probe with an empty
    # trace, which the ablation then printed as `missed gap=0.00 attempts= 0`.
    assert probe.status is ProbeStatus.NOT_APPLICABLE
    assert "could not act" in (probe.reason or "")
    assert "Connection refused" in (probe.reason or "")
    assert report.verdict in {"VALID", "DEFECTIVE", "INVALID", "UNVERIFIED"}
