"""Challenger behaviour, and the invariant that keeps the measurement honest."""

from __future__ import annotations

import pytest

from assay.adapter import run_policy
from assay.challenger import ScriptedChallenger, action_template
from assay.challenger.prompted import _extract_json
from assay.fixtures import build
from assay.probes.hackability import exploit_gap
from assay.types import Action


# -- the invariant ----------------------------------------------------------


def test_the_challenger_is_never_given_ground_truth():
    """`true_completion` is read by the probe, never handed to the attacker.
    An attacker told the answer is not finding an exploit."""
    import inspect

    from assay.challenger import prompted, scripted

    for module in (prompted, scripted):
        source = inspect.getsource(module)
        assert "true_completion" not in source, f"{module.__name__} can see ground truth"


def test_exploit_gap_replays_before_measuring():
    """Stateful adapters score the current workspace, so a transcript recorded
    earlier must be re-run before it means anything."""
    env = build("escalate_overrewarded")
    transcript = run_policy(env, "t1", [Action("escalate", {})])
    # Disturb the environment the way a second policy would.
    run_policy(env, "t1", [Action("submit", {"label": "billing"})])
    gap, reported, real = exploit_gap(env, transcript)
    assert reported == 1.0
    assert real == 0.0
    assert gap == 1.0


# -- scripted ---------------------------------------------------------------


def test_scripted_challenger_covers_the_trivial_repertoire():
    attempts = ScriptedChallenger().attack(build("healthy"), "t1")
    labels = {a.label for a in attempts}
    assert "empty" in labels
    assert any(l.startswith("trivial:") for l in labels)


def test_action_vocabulary_is_inferred_richest_first():
    """A no-argument tool is the least useful example to hand an attacker."""
    from assay.challenger import action_vocabulary

    vocabulary = action_vocabulary(build("healthy"), "t1")
    tools = [tool for tool, _ in vocabulary]
    assert "submit" in tools and "noop" in tools
    assert vocabulary[0][0] == "submit", "richest action should lead"
    assert vocabulary[0][1] == ["label"]

    tool, args = action_template(build("healthy"), "t1")
    assert (tool, args) == vocabulary[0]


# -- prompted: parsing ------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"reasoning": "look", "tool": "run", "args": {"script": "ls"}}',
        '```json\n{"reasoning": "look", "tool": "run", "args": {"script": "ls"}}\n```',
        'Sure! Here is the action:\n{"reasoning": "look", "tool": "run", "args": {"script": "ls"}}',
        '<think>I should look around first.</think>\n{"reasoning": "look", "tool": "run", "args": {"script": "ls"}}',
        '{"reasoning": "nested {braces}", "tool": "run", "args": {"script": "echo {}"}}',
    ],
)
def test_json_survives_the_shapes_small_models_actually_emit(raw):
    parsed = _extract_json(raw)
    assert parsed is not None, raw
    assert parsed["args"]["script"]


def test_unparseable_output_is_not_silently_treated_as_an_action():
    assert _extract_json("I refuse to do that.") is None
    assert _extract_json("") is None
