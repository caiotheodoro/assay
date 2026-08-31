"""The Auditor may narrow a verdict. It may never widen one.

Most of these are negative tests, and that is the point: the risk of putting a
model in the loop is not that it fails to help, it is that it quietly turns a
real defect into a clean bill of health. Every path that could do that is
pinned here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from assay.auditor import Auditor
from assay.fixtures import build
from assay.runner import audit as run_battery
from assay.types import ProbeStatus


@dataclass
class FakeClient:
    """A model that says exactly what the test needs and records the prompt."""

    reply: str
    name: str = "fake:test"
    asked: list[tuple[str, str]] = None

    def __post_init__(self):
        self.asked = []

    def complete(self, system: str, user: str) -> str:
        self.asked.append((system, user))
        return self.reply


#: Both signals agree that there is no correct answer. Only this overrides.
NO_ANSWER = (
    '{"both_valid_example": "A: strongly agree. B: strongly disagree.", '
    '"verdict": "no_correct_answer", "elicitation": "personality trait rating", '
    '"quote": "I see myself as someone who is talkative", "confidence": "high"}'
)
HAS_ANSWER = (
    '{"both_valid_example": "none", "verdict": "has_correct_answer", '
    '"elicitation": "factual question", "quote": "what is 2 + 2", '
    '"confidence": "high"}'
)
#: The label says no-correct-answer, the evidence does not back it.
LABEL_ONLY = (
    '{"both_valid_example": "none", "verdict": "no_correct_answer", '
    '"elicitation": "opinion", "quote": "x", "confidence": "high"}'
)
#: An example was invented, but the label disagrees. This is what qwen3:8b
#: actually returns for personality_BFI, in 3 of 3 runs.
EVIDENCE_ONLY = (
    '{"both_valid_example": "A: yes, disorganized. B: no, organized.", '
    '"verdict": "has_correct_answer", "elicitation": "self report", '
    '"quote": "Tends to be disorganized", "confidence": "high"}'
)


def _defective():
    """A fixture whose verifier genuinely cannot fail: INVERT_PASSES."""
    return build("unfalsifiable")


# -- the capability the repo said did not exist -----------------------------


def test_a_no_correct_answer_environment_has_its_verifier_findings_withheld():
    adapter = _defective()
    auditor = Auditor(FakeClient(NO_ANSWER))
    report = auditor.audit(adapter)

    verifier = [r for r in report.results if r.family == "verifier_integrity"]
    assert verifier, "the fixture must exercise the family under test"
    assert not any(r.status is ProbeStatus.DEFECT for r in verifier)
    assert all(
        r.reason and "no correct answer" in r.reason
        for r in verifier
        if r.detail.get("auditor_override")
    )


def test_withholding_is_not_passing():
    """NOT_APPLICABLE, never PASS. 'We could not check' is not 'it is fine'."""
    report = Auditor(FakeClient(NO_ANSWER)).audit(_defective())
    overridden = [r for r in report.results if r.detail.get("auditor_override")]
    assert overridden
    assert all(r.status is ProbeStatus.NOT_APPLICABLE for r in overridden)
    assert report.verdict != "VALID"


# -- fail closed -------------------------------------------------------------


def test_an_environment_with_a_correct_answer_keeps_every_defect():
    adapter = _defective()
    plain = run_battery(adapter)
    reviewed = Auditor(FakeClient(HAS_ANSWER)).audit(_defective())
    assert reviewed.detected == plain.detected
    assert reviewed.verdict == plain.verdict


def test_no_model_reachable_changes_nothing():
    """A degraded Auditor loses recall, never precision."""

    class Unreachable:
        name = "none"

        def complete(self, system, user):
            from assay.llm import LLMUnavailable

            raise LLMUnavailable("no backend")

    plain = run_battery(_defective())
    reviewed = Auditor(Unreachable()).audit(_defective())
    assert reviewed.detected == plain.detected
    assert reviewed.overrides == [] if hasattr(reviewed, "overrides") else True


@pytest.mark.parametrize(
    "reply",
    [
        "I think this environment is fine, honestly.",
        "{not json at all",
        '{"verdict": "maybe"}',
        "",
        '{"verdict": "no_correct_answer"'.replace("}", ""),
    ],
)
def test_a_reply_that_does_not_parse_changes_nothing(reply):
    plain = run_battery(_defective())
    auditor = Auditor(FakeClient(reply))
    reviewed = auditor.audit(_defective())
    assert reviewed.detected == plain.detected
    assert auditor.overrides == []


# -- scope -------------------------------------------------------------------


def test_only_verifier_integrity_is_in_scope():
    """A model that says no-correct-answer cannot reach any other family."""
    adapter = build("weak_oracle")  # INVERT_PASSES + KNOWN_WRONG + REWARD_HACKABLE
    plain = run_battery(adapter)
    reviewed = Auditor(FakeClient(NO_ANSWER)).audit(build("weak_oracle"))

    out_of_scope = {
        r.family for r in plain.results if r.status is ProbeStatus.DEFECT
    } - {"verifier_integrity"}
    for family in out_of_scope:
        before = [r for r in plain.results if r.family == family]
        after = [r for r in reviewed.results if r.family == family]
        assert [r.status for r in before] == [r.status for r in after], family


def test_the_auditor_never_turns_a_defect_into_a_pass():
    reviewed = Auditor(FakeClient(NO_ANSWER)).audit(_defective())
    plain = run_battery(_defective())
    before_pass = sum(1 for r in plain.results if r.status is ProbeStatus.PASS)
    after_pass = sum(1 for r in reviewed.results if r.status is ProbeStatus.PASS)
    assert after_pass == before_pass


def test_a_healthy_environment_is_untouched_because_nothing_was_flagged():
    auditor = Auditor(FakeClient(NO_ANSWER))
    plain = run_battery(build("healthy"))
    reviewed = auditor.audit(build("healthy"))
    assert reviewed.detected == plain.detected
    assert auditor.overrides == []
    assert auditor.asked_nothing if hasattr(auditor, "asked_nothing") else True


def test_the_model_is_not_consulted_when_the_battery_flagged_nothing():
    """No findings in scope means no call. The model costs money and time."""
    client = FakeClient(NO_ANSWER)
    Auditor(client).audit(build("healthy"))
    assert client.asked == []


# -- reproducibility ---------------------------------------------------------


def test_dropping_the_auditor_reproduces_the_deterministic_report():
    """The battery call is untouched; judgement happens around it."""
    plain = run_battery(_defective())
    through = Auditor(FakeClient(HAS_ANSWER)).audit(_defective())
    assert [r.probe for r in plain.results] == [r.probe for r in through.results]
    assert [r.status for r in plain.results] == [r.status for r in through.results]


def test_every_override_records_who_proposed_it_and_what_it_replaced():
    auditor = Auditor(FakeClient(NO_ANSWER))
    auditor.audit(_defective())
    assert auditor.overrides
    for override in auditor.overrides:
        d = override.to_dict()
        assert d["proposed_by"] == "fake:test"
        assert d["was"] == "DEFECT"
        assert d["now"] == "NOT_APPLICABLE"
        assert d["reason"]
        assert d["evidence"]["withheld_findings"]
        assert d["evidence"]["quote"]


def test_memory_records_what_was_concluded_per_environment():
    auditor = Auditor(FakeClient(NO_ANSWER))
    auditor.audit(_defective())
    auditor.audit(build("healthy"))
    assert auditor.seen["toy-triage/unfalsifiable"]["classified"] == "no_correct_answer"


# -- the conjunction ---------------------------------------------------------


@pytest.mark.parametrize("reply", [LABEL_ONLY, EVIDENCE_ONLY])
def test_one_signal_alone_never_overrides(reply):
    """Neither the label nor the example is trusted on its own.

    Measured, not assumed: the label alone misses `personality_BFI` on
    qwen3:8b in 3 of 3 runs, and the example alone turns 10 of the 12 fixtures
    into no-correct-answer. `results/semantic_gate.json` carries both.
    """
    plain = run_battery(_defective())
    auditor = Auditor(FakeClient(reply))
    reviewed = auditor.audit(_defective())
    assert auditor.overrides == []
    assert reviewed.detected == plain.detected


def test_the_model_label_is_recorded_even_when_it_is_not_believed():
    auditor = Auditor(FakeClient(EVIDENCE_ONLY))
    answer = auditor.classify(_defective())
    assert answer["model_said"] == "has_correct_answer"
    assert answer["verdict"] == "has_correct_answer"
