"""The trajectory export, end to end.

The invariant under test throughout: a trajectory that shows only the turns
that worked is a highlight reel. Failed turns, malformed replies and refused
approvals all have to survive to disk.
"""

from __future__ import annotations

import json

from assay.trajectory import AgentTrajectory, Turn


def test_a_trajectory_states_what_it_demonstrates():
    traj = AgentTrajectory(
        agent="scripted",
        role="challenger",
        environment="harbor/self-graded",
        task_id="self-graded",
        shows="the fixed repertoire misses the exploit",
    )
    assert traj.to_dict()["shows"] == "the fixed repertoire misses the exploit"
    assert "the fixed repertoire misses the exploit" in traj.to_markdown()


# -- the scripted Challenger ------------------------------------------------

from assay.challenger import ScriptedChallenger  # noqa: E402
from assay.fixtures import build  # noqa: E402


def test_the_scripted_challenger_leaves_a_trace():
    """The floor arm needs a trajectory too. An arm with no record is an arm a
    reader has to take on trust."""
    attempts = ScriptedChallenger().attack(build("healthy"), "t1")
    assert attempts
    last = attempts[-1].log
    assert len(last) == len(attempts), "the last attempt carries the whole run"
    assert {row["policy"] for row in last} == {a.label for a in attempts}
    first = last[0]
    assert first["turn"] == 1
    assert "action" in first and "observation" in first
    assert "no model in the loop" in first["reasoning"]


def test_each_scripted_attempt_carries_history_up_to_itself():
    attempts = ScriptedChallenger().attack(build("healthy"), "t1")
    assert [len(a.log) for a in attempts] == list(range(1, len(attempts) + 1))


def test_the_scripted_log_records_no_score_the_attacker_never_saw():
    """The probe scores these attempts. Recording a score in the attacker's own
    log would put knowledge in the record that the attacker did not have."""
    for attempt in ScriptedChallenger().attack(build("healthy"), "t1"):
        for row in attempt.log:
            assert "reported" not in row
            assert "true" not in row
