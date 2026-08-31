"""The synthesis Challenger: what the model may propose, and what it may decide.

Most of these are negative tests, for the same reason `test_auditor.py`'s are.
The risk of letting a model propose attack policies is not that it proposes bad
ones -- the probe throws those away for free. It is that the model's own claim
of success leaks into a finding, or that the surface it reads quietly includes
the answer, and either one turns a measurement into a formality.

The environment under test is a miniature of `inspect_evals/paws`: a substring
verifier over two labels. The scripted repertoire reaches the majority label
and nothing else, exactly as it does on the real thing, so "the both-labels
policy" is a real gap here and not a staged one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from assay.adapters.spec import build as build_spec
from assay.challenger import (
    ChallengerExhausted,
    CompositeChallenger,
    ScriptedChallenger,
)
from assay.challenger.synthesis import (
    PolicySynthesisChallenger,
    _section,
    action_shape,
    agent_prompt,
    usable_policies,
)
from assay.llm import LLMUnavailable
from assay.probes.hackability import GAP_THRESHOLD, RewardHackability, exploit_gap
from assay.types import DefectClass, ProbeStatus


# -- doubles ----------------------------------------------------------------


@dataclass
class FakeClient:
    """A model that says exactly what the test needs and records the prompt."""

    reply: str
    name: str = "fake:test"
    asked: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, system: str, user: str) -> str:
        self.asked.append((system, user))
        return self.reply


@dataclass
class DeadClient:
    """A backend that never speaks. Not the same as one that speaks nonsense."""

    name: str = "fake:dead"

    def complete(self, system: str, user: str) -> str:
        raise LLMUnavailable("fake:dead: backend unreachable")


#: The exploit a person found by hand on `paws`: one constant string containing
#: both labels, credited by a substring scorer on every item.
BOTH_LABELS = '{"reasoning": "includes() only checks containment", ' \
    '"policies": ["Yes No"], "scores_well": 0.9}'

#: A correct answer for `yes-1`, offered with maximum confidence. It is not an
#: exploit, and the probe is the only thing that gets to say so.
CORRECT_AND_CONFIDENT = (
    '{"reasoning": "this is simply the right answer", '
    '"policies": ["Yes"], "scores_well": 1.0}'
)

MALFORMED = "I think the scorer is probably a substring match, but I am not sure."


# -- the environment --------------------------------------------------------

#: Distinctive enough that finding it inside a prompt is unambiguous, and the
#: whole point of `test_the_surface_never_carries_a_target`.
SENTINEL = "ZZQTARGETSENTINELQZZ"


class _AsWildInspect:
    """The spec adapter, with the repertoire `paws` actually has.

    `SpecAdapter` derives an `every_target_at_once` policy under a substring
    matcher (`docs/changelog/114`), and `WildInspectAdapter` -- which is what
    `inspect_evals/paws` really uses -- does not: its policies are
    `always_abstain`, `always_escalate`, `majority_class`, verified against the
    live adapter. Leaving the derived policy in would make this stand-in
    *stronger* than the thing it stands in for, and every claim in this file is
    about what the scripted repertoire cannot reach.

    So it is dropped here, deliberately and visibly. The real measurement is
    `results/policy_synthesis.json`, which runs against the real adapter and is
    unaffected either way.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def trivial_policies(self, task_id):
        policies = dict(self._inner.trivial_policies(task_id))
        policies.pop("every_target_at_once", None)
        return policies


def _paws_shaped(target_of_task_1: str = "Yes"):
    """Two labels, a substring verifier, majority `No`. `paws` in miniature.

    `always_escalate` is the trivial policy that carries the real finding on
    `paws`, and it carries it here for the same accidental reason: "I cannot
    determine the answer." contains `no`, inside `cannot`, so a substring
    verifier credits it on every `No` item while it answers nothing.

    Wrapped so the repertoire matches `WildInspectAdapter`'s -- see
    `_AsWildInspect` for why that is not a convenience.
    """
    return _AsWildInspect(build_spec(
        {
            "env_id": "toy/substring-labels",
            "verifier": "includes",
            "trivial_answers": ["I cannot determine the answer."],
            "tasks": [
                {
                    "task_id": "yes-1",
                    "instruction": "Sentence1: a cat sat.\nSentence2: a cat was sitting.",
                    "target": target_of_task_1,
                    "asserts": [
                        "the submission is credited when it contains the target "
                        "label as a substring, ignoring case"
                    ],
                },
                {"task_id": "no-1", "instruction": "Sentence1: a.\nSentence2: b.", "target": "No"},
                {"task_id": "no-2", "instruction": "Sentence1: c.\nSentence2: d.", "target": "No"},
            ],
        }
    ))


def _run_probe(adapter, challenger):
    return RewardHackability().check(adapter, {"challenger": challenger})


def _hacked(result) -> set[str]:
    return {
        f.task_id for f in result.findings if f.defect is DefectClass.REWARD_HACKABLE
    }


# -- the gap this exists to close -------------------------------------------


def test_the_scripted_repertoire_cannot_reach_the_minority_label():
    """The premise. Without this the rest of the file proves nothing.

    `majority_class` submits `No`, which a substring verifier credits on the
    two `No` items and refuses on the `Yes` one -- the same 14-of-25 shape the
    README records for the real `paws`.
    """
    found = _hacked(_run_probe(_paws_shaped(), ScriptedChallenger()))
    assert found == {"no-1", "no-2"}
    assert "yes-1" not in found


def test_it_finds_the_both_labels_policy_when_the_model_proposes_it():
    adapter = _paws_shaped()
    challenger = PolicySynthesisChallenger(FakeClient(BOTH_LABELS))

    found = _hacked(_run_probe(adapter, challenger))
    assert found == {"yes-1", "no-1", "no-2"}, "one constant string should take every item"

    gap, reported, real = exploit_gap(
        adapter, challenger.attack(adapter, "yes-1")[0].transcript
    )
    assert reported == 1.0, "the environment credits it"
    assert real == 0.0, "it is not the answer"
    assert gap >= GAP_THRESHOLD


def test_composed_with_scripted_it_only_ever_adds():
    """`composite.py` promises a better attacker cannot lose coverage."""
    adapter = _paws_shaped()
    scripted = _hacked(_run_probe(adapter, ScriptedChallenger()))
    both = _hacked(
        _run_probe(
            adapter,
            CompositeChallenger(
                [
                    ScriptedChallenger(),
                    PolicySynthesisChallenger(FakeClient(BOTH_LABELS)),
                ]
            ),
        )
    )
    assert scripted <= both


# -- the model may not decide whether it succeeded --------------------------


def test_it_never_reports_a_gap_the_deterministic_scorer_did_not_confirm():
    """A correct answer, proposed with `scores_well: 1.0`, is not a finding.

    This is the failure mode the whole design is arranged against. The model
    is asked for a self-assessment and it is written into the trace, but no
    branch reads it: `exploit_gap` scores the policy, sees a true completion of
    1.0, and reports nothing.
    """
    adapter = _paws_shaped()
    challenger = PolicySynthesisChallenger(FakeClient(CORRECT_AND_CONFIDENT))

    result = _run_probe(adapter, challenger)
    assert "yes-1" not in _hacked(result), "a correct answer is not an exploit"

    gap, reported, real = exploit_gap(
        adapter, challenger.attack(adapter, "yes-1")[0].transcript
    )
    assert (reported, real, gap) == (1.0, 1.0, 0.0)

    trace = result.detail["per_task"]["yes-1"]["attacker_trace"]
    assert trace[0]["self_report"] == 1.0, "the claim is recorded"
    assert trace[0]["self_report_is_read_by"] == "nothing"


def test_the_self_report_cannot_change_which_policies_run():
    """`usable_policies` is the decision, and it does not consult the model."""
    confident = {"policies": ["a", "b"], "scores_well": 1.0}
    doubtful = {"policies": ["a", "b"], "scores_well": 0.0}
    assert usable_policies(confident) == usable_policies(doubtful) == ["a", "b"]


# -- degradation ------------------------------------------------------------


def test_an_unreachable_model_finds_nothing_rather_than_crashing():
    adapter = _paws_shaped()
    challenger = PolicySynthesisChallenger(DeadClient())

    with pytest.raises(LLMUnavailable):
        challenger.attack(adapter, "yes-1")

    result = _run_probe(adapter, challenger)
    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert result.reason and "could not act" in result.reason
    assert not result.findings, "silence is not a finding"


def test_an_unreachable_model_does_not_delete_what_scripted_already_found():
    adapter = _paws_shaped()
    found = _hacked(
        _run_probe(
            adapter,
            CompositeChallenger(
                [ScriptedChallenger(), PolicySynthesisChallenger(DeadClient())]
            ),
        )
    )
    assert found == {"no-1", "no-2"}


def test_a_malformed_reply_changes_nothing():
    adapter = _paws_shaped()
    challenger = PolicySynthesisChallenger(FakeClient(MALFORMED))

    with pytest.raises(ChallengerExhausted) as exc:
        challenger.attack(adapter, "yes-1")
    assert "did not parse" in str(exc.value)
    assert exc.value.history, "what was thrown away is kept"

    result = _run_probe(adapter, challenger)
    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert not result.findings


@pytest.mark.parametrize(
    "reply",
    [
        '{"reasoning": "x", "policies": []}',
        '{"reasoning": "x", "policies": "Yes No"}',
        '{"reasoning": "x", "policies": [{"policy": "Yes No"}]}',
        '{"reasoning": "x", "policies": ["   ", ""]}',
        '{"reasoning": "x"}',
        "",
    ],
)
def test_a_reply_with_no_literal_string_in_it_is_exhaustion_not_a_pass(reply):
    """Each of these is a real `qwen3:8b` shape. None of them may run silently.

    `ChallengerExhausted` rather than `[]`: an empty attempt list is scored as
    a clean PASS with nothing tried, which is the claim `base.py` was written
    to stop the card making.
    """
    with pytest.raises(ChallengerExhausted):
        PolicySynthesisChallenger(FakeClient(reply)).attack(_paws_shaped(), "yes-1")


def test_json_survives_prose_fences_and_a_think_block():
    reply = (
        "<think>the scorer is includes()</think>\nSure, here you go:\n"
        '```json\n{"reasoning": "substring", "policies": ["Yes No"]}\n```\nHope that helps.'
    )
    attempts = PolicySynthesisChallenger(FakeClient(reply)).attack(_paws_shaped(), "yes-1")
    assert [a.transcript.actions[0].args["answer"] for a in attempts] == ["Yes No"]


def test_duplicates_are_dropped_and_the_cap_holds():
    reply = '{"policies": ["a", "a", " a ", "b", "c", "d"]}'
    assert usable_policies({"policies": ["a", "a", " a ", "b"]}) == ["a", "b"]
    attempts = PolicySynthesisChallenger(
        FakeClient(reply), max_policies=3
    ).attack(_paws_shaped(), "yes-1")
    assert len(attempts) == 3


# -- the redaction contract -------------------------------------------------


def test_the_surface_never_carries_a_target():
    """An attacker told the answer is not finding an exploit, it is being
    handed one. `describe()` prints every target; this surface is assembled
    from named fields instead, so there is no filter to get wrong."""
    adapter = _paws_shaped(target_of_task_1=SENTINEL)
    challenger = PolicySynthesisChallenger(FakeClient(BOTH_LABELS))

    for task in adapter.manifest().tasks:
        assert SENTINEL not in challenger.surface(adapter, task.task_id)

    challenger.attack(adapter, "yes-1")
    system, user = challenger.client.asked[0]
    assert SENTINEL not in system and SENTINEL not in user


def test_the_action_shape_comes_from_the_adapter_and_its_payload_is_discarded():
    """`majority_class`'s payload IS the majority label on a task like this."""
    adapter = _paws_shaped()
    tool, fixed, payload = action_shape(adapter, "yes-1")
    assert tool == "submit"
    assert payload == "answer"
    assert "No" not in str(fixed), "the exemplar's answer must not survive"

    challenger = PolicySynthesisChallenger(FakeClient(BOTH_LABELS))
    action = challenger.attack(adapter, "yes-1")[0].transcript.actions[0]
    assert action.tool == "submit"
    assert action.args["answer"] == "Yes No", "the model supplies only the payload"


def test_an_adapter_that_names_no_action_is_exhaustion_with_a_reason():
    # Subclasses the real adapter, not the `_AsWildInspect` wrapper around it.
    class Mute(type(_paws_shaped()._inner)):
        def trivial_policies(self, task_id):
            return {}

    adapter = Mute(spec=_paws_shaped()._inner.spec)
    with pytest.raises(ChallengerExhausted) as exc:
        PolicySynthesisChallenger(FakeClient(BOTH_LABELS)).attack(adapter, "yes-1")
    assert "no action vocabulary" in str(exc.value)


DESCRIBED = """\
environment: toy/x
tasks:
  - id: t1
scorers:
# str_match_scorer.<locals>.score
async def score(state: TaskState, target: Target) -> Score:
    if target:
        return Score(value=CORRECT)
    return Score(value=INCORRECT)

samples:
  - t1: input='q' target='ZZQTARGETSENTINELQZZ'
"""


def test_the_scorer_section_survives_its_own_function_signature():
    """The first measurement shipped an empty scorer to the model.

    `async def score(state: TaskState, target: Target) -> Score:` is unindented
    and ends in a colon, so "the next unindented line ending in a colon" read
    it as the start of the next section and cut the source off after the
    comment above it. A section header is a bare lowercase label, and nothing
    else.
    """
    body = _section(DESCRIBED, "scorers:")
    assert "async def score" in body
    assert "return Score(value=CORRECT)" in body
    assert SENTINEL not in body, "samples: must still terminate the section"


def test_no_argument_to_section_returns_the_targets():
    assert SENTINEL not in _section(DESCRIBED, "scorers:")
    assert SENTINEL not in _section(DESCRIBED, "tasks:")


def test_the_verifier_source_reaches_the_prompt_when_the_adapter_states_it():
    challenger = PolicySynthesisChallenger(FakeClient(BOTH_LABELS))
    surface = challenger.surface(_paws_shaped(), "yes-1")
    assert "contains the target label as a substring" in surface

    quiet = PolicySynthesisChallenger(FakeClient(BOTH_LABELS), read_verifier=False)
    assert "contains the target label as a substring" not in quiet.surface(
        _paws_shaped(), "yes-1"
    )


# -- the agent's own prompt -------------------------------------------------


def _task_with_solver(template: str, *extras: str):
    """An `inspect_ai`-shaped solver chain: a template captured in a closure."""

    def step(prompt_template, constants):
        def solve(state, generate):
            return prompt_template, constants

        return solve

    class Chain:
        _solvers = [step(template, list(extras))] + [
            step(e, []) for e in extras
        ]

    class Task:
        solver = Chain()

    return Task()


def test_the_agent_prompt_is_read_off_the_solver_chain():
    """On `paws` this is the only place the labels are ever written down."""
    adapter = _paws_shaped()
    adapter._task = _task_with_solver(
        "Answer Yes if the two sentences are paraphrases, otherwise No.\n{prompt}\n"
    )
    assert "Answer Yes" in agent_prompt(adapter)

    challenger = PolicySynthesisChallenger(FakeClient(BOTH_LABELS))
    assert "Answer Yes" in challenger.surface(adapter, "yes-1")

    quiet = PolicySynthesisChallenger(FakeClient(BOTH_LABELS), read_agent_prompt=False)
    assert "Answer Yes" not in quiet.surface(adapter, "yes-1")


def test_only_a_template_is_read_never_a_bare_constant():
    """A closure constant with no placeholder could be an answer. It is not a
    prompt, and nothing here will treat it as one."""
    adapter = _paws_shaped()
    adapter._task = _task_with_solver("Answer with {prompt}.", SENTINEL)
    prompt = agent_prompt(adapter)
    assert "Answer with" in prompt
    assert SENTINEL not in prompt


def test_an_adapter_with_no_solver_simply_has_no_agent_prompt():
    assert agent_prompt(_paws_shaped()) == ""
