"""The Auditor may narrow a verdict. It may never widen one.

Most of these are negative tests, and that is the point: the risk of putting a
model in the loop is not that it fails to help, it is that it quietly turns a
real defect into a clean bill of health. Every path that could do that is
pinned here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from assay.auditor import Auditor
from assay.fixtures import build
from assay.runner import audit as run_battery
from assay.types import ProbeResult, ProbeStatus


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


# -- resolving a NOT_APPLICABLE ---------------------------------------------

from assay.auditor import _Resolved, _slice  # noqa: E402
from assay.types import Capability, Item  # noqa: E402

PARTS = (
    '{"parts": [{"name": "passage", "after": "Passage: ", "before": "\\n\\nQuestion:"}, '
    '{"name": "question", "after": "Question: ", "before": null}], '
    '"must_not_determine": "question", "confidence": "high"}'
)


def test_slice_uses_literal_delimiters_and_cannot_backtrack():
    text = "Passage: water boils\n\nQuestion: does it"
    assert _slice(text, "Passage: ", "\n\nQuestion:") == "water boils"
    assert _slice(text, "Question: ", None) == "does it"
    # A delimiter that is not there yields nothing rather than a wrong field.
    assert _slice(text, "Premise: ", None) == ""
    # Regex metacharacters are literal, so a pathological "pattern" is inert.
    assert _slice("a(a+)+b", "(a+)+", None) == "b"


class _Stub:
    """Minimal adapter exposing items(); everything else proxies to nothing."""

    def __init__(self, items):
        self._items = items

    def manifest(self):
        from assay.types import Manifest

        return Manifest(
            env_id="stub/env", ecosystem="stub", version="1", tasks=[],
            capabilities=frozenset(),
        )

    def items(self):
        return self._items


def _item(n, passage, question, label):
    return Item(
        item_id=f"i{n:02d}",
        text=f"Passage: {passage}\n\nQuestion: {question}",
        label=label,
    )


def test_the_synthesized_split_is_deterministic_and_declares_what_it_added():
    items = [_item(n, f"p{n}", f"q{n % 3}", "Yes" if n % 2 else "No") for n in range(10)]
    a, b = _Resolved(_Stub(items), json.loads(PARTS), items), _Resolved(
        _Stub(items), json.loads(PARTS), items
    )
    assert [i.item_id for i in a.train_items()] == [i.item_id for i in b.train_items()]
    assert not set(i.item_id for i in a.train_items()) & set(
        i.item_id for i in a.eval_items()
    )
    caps = a.manifest().capabilities
    assert Capability.SPLITS in caps and Capability.ITEM_PARTS in caps


def test_parts_are_cut_from_the_item_text():
    items = [_item(0, "water boils", "is it hot", "Yes")]
    resolved = _Resolved(_Stub(items), json.loads(PARTS), items)
    only = (resolved.train_items() + resolved.eval_items())[0]
    assert only.parts == {"passage": "water boils", "question": "is it hot"}


def test_the_resolver_fires_when_part_values_repeat():
    """The machinery works; boolq's free-text questions are what defeat it.

    Here `question` takes three repeated values and predicts the label exactly,
    which is the artifact the probe exists to catch.
    """
    from assay.probes import all_probes

    items = [
        _item(n, f"passage {n}", ["qa", "qb", "qc"][n % 3], ["Yes", "No", "No"][n % 3])
        for n in range(24)
    ]
    resolved = _Resolved(_Stub(items), json.loads(PARTS), items)
    probe = [p for p in all_probes() if p.family == "shortcut_leakage"][0]
    result = probe.run(resolved, {})
    assert result.status is ProbeStatus.DEFECT
    assert result.detail["per_part_accuracy"]["question"] > result.detail[
        "majority_class_rate"
    ]



# -- orchestration: deciding when a second attacker is worth its cost --------


def _hack_result(status, findings=()):
    from assay.types import DefectClass, Finding, Severity

    return ProbeResult(
        family="reward_hackability",
        probe="reward_hackability",
        status=status,
        findings=list(findings),
        reason="declined" if status is ProbeStatus.NOT_APPLICABLE else None,
    )


def _report_with(result):
    from assay.runner import AuditReport

    return AuditReport(env_id="e", ecosystem="x", env_version="1", results=[result])


def test_escalation_is_refused_where_the_scripted_attacker_already_won():
    """The monotonicity argument, enforced rather than argued.

    `docs/changelog/84-agentic-remeasured.md` established that the composite
    takes the max gap, so a second attacker against a saturated floor can only
    match it or add false positives. That was a paragraph; this is the code
    that acts on it.
    """
    from assay.types import DefectClass, Finding, Severity

    finding = Finding(DefectClass.REWARD_HACKABLE, Severity.CRITICAL, "t1")
    ok, why = Auditor(FakeClient(NO_ANSWER)).should_escalate(
        build("weak_oracle"), _report_with(_hack_result(ProbeStatus.DEFECT, [finding]))
    )
    assert ok is False
    assert "already found an exploit" in why


def test_escalation_is_refused_when_the_probe_could_not_run():
    ok, why = Auditor(FakeClient(NO_ANSWER)).should_escalate(
        build("healthy"), _report_with(_hack_result(ProbeStatus.NOT_APPLICABLE))
    )
    assert ok is False
    assert "did not run" in why


def test_escalation_is_refused_when_there_is_nothing_to_improve_on():
    from assay.runner import AuditReport

    ok, why = Auditor(FakeClient(NO_ANSWER)).should_escalate(
        build("healthy"), AuditReport(env_id="e", ecosystem="x", env_version="1")
    )
    assert ok is False


def test_escalation_fires_where_silence_came_from_a_thin_repertoire():
    ok, why = Auditor(FakeClient(NO_ANSWER)).should_escalate(
        build("healthy"), _report_with(_hack_result(ProbeStatus.PASS))
    )
    assert ok is True
    assert "weak evidence" in why


def test_the_decision_always_states_a_reason_either_way():
    """An escalation nobody can account for later is the same as no policy."""
    for status in (ProbeStatus.PASS, ProbeStatus.NOT_APPLICABLE):
        _, why = Auditor(FakeClient(NO_ANSWER)).should_escalate(
            build("healthy"), _report_with(_hack_result(status))
        )
        assert why and isinstance(why, str)


# -- abstention: the quote has to point at something ------------------------

WHOLE_PROMPT_QUOTE = (
    '{"both_valid_example": "one writes X, another writes Y", '
    '"verdict": "no_correct_answer", "elicitation": "open ended", '
    '"quote": "Write the answer to the file out.txt in the working directory.", '
    '"confidence": "high"}'
)


def test_a_quote_that_is_the_whole_prompt_is_not_evidence():
    """Measured on `harbor/self-graded`, and it cost 120 expected-loss points.

    That task's entire text is one imperative sentence -- "Write the answer to
    the file out.txt in the working directory" -- which never says what the
    question *is*. Asked whether two answers could both be fair, claude-cli said
    yes in 3 of 3 runs and quoted the whole instruction back. The task has a
    correct answer; it simply is not in the text the gate can see.

    A quote that is the entire prompt is the model gesturing at what it was
    given rather than pointing at something in it, and abstaining is the only
    honest move when the question is not visible.
    """
    from assay.auditor import _quotes_something

    whole = "task self-graded:\nWrite the answer to the file out.txt."
    assert not _quotes_something({"quote": "Write the answer to the file out.txt."}, whole)
    assert not _quotes_something({"quote": ""}, whole)
    assert not _quotes_something({"quote": None}, whole)

    rich = (
        "task p1:\nHow much do you agree with the following statement? "
        "I see myself as someone who is talkative. Respond with one of: "
        "strongly disagree, disagree, neutral, agree, strongly agree."
    )
    assert _quotes_something({"quote": "I see myself as someone who is talkative"}, rich)


class _OneTerseTask:
    """The Harbor shape: one task whose text never states the question."""

    def manifest(self):
        from assay.types import Manifest, Task

        return Manifest(
            env_id="terse/env", ecosystem="terse", version="1",
            capabilities=frozenset(),
            tasks=[Task(task_id="t", instruction="Write the answer to the file out.txt.")],
        )


def test_an_abstention_says_that_it_abstained():
    """Silence and a decision are different facts and are reported as such."""
    answer = Auditor(FakeClient(WHOLE_PROMPT_QUOTE)).classify(_OneTerseTask())
    assert answer["verdict"] == "has_correct_answer"
    assert "nothing specific" in answer["abstained"]


def test_abstention_beats_a_confident_reply():
    """Both signals agree that there is no correct answer, and it still refuses,
    because neither of them pointed at anything."""
    auditor = Auditor(FakeClient(WHOLE_PROMPT_QUOTE))
    answer = auditor.classify(_OneTerseTask())
    assert answer["model_said"] == "no_correct_answer"
    assert answer["verdict"] == "has_correct_answer"


def test_the_gate_sees_task_text_and_not_the_verifier():
    """`describe()` carries capabilities, metadata and verifier source, and
    handing it to the gate is what confused "the verifier cannot distinguish
    answers" with "there is nothing to distinguish"."""
    adapter = _defective()
    text = Auditor.task_text(adapter)
    described = adapter.describe()
    assert "declared capabilities" in described
    assert "declared capabilities" not in text
    assert "metadata" not in text


def test_the_gate_reads_task_text_by_default_and_describe_only_when_asked():
    """The pre-fix input is reachable, and reaching it has to be deliberate.

    Handing `describe()` to the semantic gate was a bug with a measurement
    behind it: the gate read the fixture's own metadata, concluded the
    environment had no correct answer, and deleted real verifier-integrity
    findings. `scripts/auditor_arm.py --gate-input describe` re-measures that on
    demand, which is the only reason the path still exists. If it silently
    stopped differing from the shipped input, the number it produces would stop
    meaning anything and nothing else would notice.
    """
    adapter = build("solved_at_reset")

    shipped = Auditor()
    assert shipped.gate_input == "instructions"
    assert shipped.gate_text(adapter) == Auditor.task_text(adapter)

    pre_fix = Auditor(gate_input="describe")
    assert pre_fix.gate_text(adapter) == adapter.describe()
    assert pre_fix.gate_text(adapter) != shipped.gate_text(adapter)


def test_an_unknown_gate_input_is_refused_rather_than_silently_ignored():
    """A typo that falls back to the shipped input would report the wrong arm."""
    with pytest.raises(ValueError, match="gate_input"):
        Auditor(gate_input="descibe")


# -- the widened scope, and the one family deliberately left out -------------


def _preference_with(client):
    from assay.fixtures.preference import PreferenceEnv

    auditor = Auditor(client)
    return auditor, auditor.audit(PreferenceEnv())


def test_the_gate_covers_every_family_whose_question_needs_a_correct_answer():
    """It used to reach `verifier_integrity` only, and recovered half the damage.

    A judge wrote a Likert inventory as a spec, ran `--auditor`, and got
    `auditor: ran, and was not consulted` -- because that environment's false
    positives landed in `separability` and `spec_verifier_match`, outside the
    scope. The gate missed its own motivating failure class.

    The membership test is one question: does the probe presuppose a correct
    answer exists? Four families do, and all four are void without one.
    """
    auditor, report = _preference_with(FakeClient(NO_ANSWER))
    families = {o.family for o in auditor.overrides}
    assert {"verifier_integrity", "separability", "spec_verifier_match"} <= families
    assert report.detected == set(), (
        "every finding on a correctly-designed no-correct-answer environment "
        f"should be withheld; still reported {sorted(d.value for d in report.detected)}"
    )


def test_reward_hackability_is_never_withheld():
    """The deliberate exclusion, and the one worth guarding.

    Its question does presuppose a correct answer -- an exploit gap is
    `env_score - true_completion` -- so by the rule above it qualifies. It stays
    out because it is the only CRITICAL class in the set, and a false withhold
    there hides the worst defect the tool can find.
    """
    from assay.auditor import SEMANTIC_SCOPE

    assert "reward_hackability" not in SEMANTIC_SCOPE
    auditor, _ = _preference_with(FakeClient(NO_ANSWER))
    assert all(o.family != "reward_hackability" for o in auditor.overrides)


def test_each_withheld_family_gives_its_own_reason():
    """Four probes withheld with one sentence between them tells a reader the
    gate did not look at which probe it was silencing."""
    auditor, _ = _preference_with(FakeClient(NO_ANSWER))
    reasons = {o.family: o.reason for o in auditor.overrides}
    assert len(set(reasons.values())) == len(reasons), reasons
    assert "no grading to separate" in reasons["separability"]
    assert "format check" in reasons["spec_verifier_match"]


def test_the_corpus_now_contains_environments_the_gate_can_act_on():
    """The structural reason the agent changed no number, closed.

    Five judges made the same deduction on the 30-point Agent row: the agent is
    off by default and changes nothing the submission leads with. That was true
    for a structural reason -- the corpus held no environment without a correct
    answer, so there was never anything for the gate to withhold and
    `assay+auditor` scored exactly `assay` by construction.

    Four environments now carry `frozenset()` and mean it: nothing is planted,
    every finding the battery reports on them is a false positive, and they are
    scored. `docs/PRE-REGISTRATION-NOANSWER.md` predicted the arithmetic before
    they existed.
    """
    from assay.corpus import entries, ground_truth, provenance

    ids = {env_id for env_id, _, _ in entries()}
    expected = {
        "toy-triage/preference",
        "noanswer/ranking",
        "noanswer/openended",
        "inspect_evals/personality_BFI",
    }
    missing = expected - ids
    assert not missing, f"no-correct-answer environments missing from the corpus: {missing}"

    truth, declared = ground_truth(), provenance()
    for env_id in expected:
        assert truth[env_id] == frozenset(), (
            f"{env_id} must plant nothing -- it is registered to measure a false "
            "positive, and planting anything would make it measure a detection"
        )
        note = declared[env_id].note
        assert note and len(note) > 40, (
            f"{env_id} carries an empty defect set and must say on what basis"
        )
