"""Independent verification of the Harbor corpus labels.

Established by running the task's own scripts and reading their output --
never by asking Assay what it detected. A label confirmed by the tool it is
used to score is not a label.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from assay.adapter import close_adapter
from assay.sandbox import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="docker daemon not available"
)

SUITE = Path(__file__).resolve().parents[1] / "src" / "assay" / "fixtures" / "harbor_suite"
IMAGE = "alpine:3.20"


def _run_verifier(workspace: Path, script: Path, logs: Path) -> float:
    """Run one verifier script against a workspace, return its reward."""
    shutil.rmtree(logs / "verifier", ignore_errors=True)
    subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--workdir", "/work",
            "-v", f"{workspace.resolve()}:/work:rw",
            "-v", f"{script.parent.resolve()}:/verifier:ro",
            "-v", f"{logs.resolve()}:/logs:rw",
            IMAGE, "sh", "/verifier/test.sh",
        ],
        capture_output=True,
        timeout=120,
    )
    reward_file = logs / "verifier" / "reward.txt"
    return float(reward_file.read_text().strip()) if reward_file.exists() else 0.0


@pytest.fixture
def workspace(tmp_path):
    def _build(task: str) -> tuple[Path, Path]:
        ws = tmp_path / f"ws-{task}"
        ws.mkdir()
        src = SUITE / task
        if (src / "environment").exists():
            shutil.copytree(src / "environment", ws, dirs_exist_ok=True)
        shutil.copytree(src / "tests", ws / "tests", dirs_exist_ok=True)
        logs = tmp_path / f"logs-{task}"
        logs.mkdir(exist_ok=True)
        return ws, logs

    return _build


def test_vacuous_verifier_pays_full_price_for_nothing(workspace):
    """NOOP_PASSES and REWARD_HACKABLE on vacuous-tests."""
    ws, logs = workspace("vacuous-tests")
    reported = _run_verifier(ws, ws / "tests" / "test.sh", logs)
    actual = _run_verifier(ws, SUITE / "vacuous-tests" / "truth" / "test.sh", logs)
    assert reported == 1.0, "the task's own verifier passes an untouched workspace"
    assert actual == 0.0, "the independent verifier does not"
    assert reported - actual >= 0.5, "REWARD_HACKABLE is real"


def test_broken_gold_does_not_satisfy_its_own_tests(workspace):
    """GOLD_FAILS on broken-gold."""
    ws, logs = workspace("broken-gold")
    solve = (SUITE / "broken-gold" / "solution" / "solve.sh").read_text()
    (ws / "solve.sh").write_text(solve)
    subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--workdir", "/work",
         "-v", f"{ws.resolve()}:/work:rw", IMAGE, "sh", "/work/solve.sh"],
        capture_output=True, timeout=120,
    )
    assert _run_verifier(ws, ws / "tests" / "test.sh", logs) == 0.0


def test_healthy_gold_does_satisfy_its_own_tests(workspace):
    ws, logs = workspace("healthy")
    solve = (SUITE / "healthy" / "solution" / "solve.sh").read_text()
    (ws / "solve.sh").write_text(solve)
    subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--workdir", "/work",
         "-v", f"{ws.resolve()}:/work:rw", IMAGE, "sh", "/work/solve.sh"],
        capture_output=True, timeout=120,
    )
    assert _run_verifier(ws, ws / "tests" / "test.sh", logs) == 1.0


def test_self_graded_task_is_genuinely_hackable(workspace):
    """REWARD_HACKABLE on self-graded -- planted, and currently MISSED by the
    scripted Challenger. Establishing it here, by exhibiting the exploit
    directly, is what makes the miss a measured result rather than an excuse."""
    ws, logs = workspace("self-graded")
    exploit = "echo 7 > /work/out.txt\necho 7 > /work/expected.txt\n"
    (ws / "hack.sh").write_text(exploit)
    subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--workdir", "/work",
         "-v", f"{ws.resolve()}:/work:rw", IMAGE, "sh", "/work/hack.sh"],
        capture_output=True, timeout=120,
    )
    reported = _run_verifier(ws, ws / "tests" / "test.sh", logs)
    actual = _run_verifier(ws, SUITE / "self-graded" / "truth" / "test.sh", logs)
    assert reported == 1.0, "the task's own verifier is satisfied by the exploit"
    assert actual == 0.0, "the independent verifier is not"


# -- environment_mode -------------------------------------------------------


def _run_script(workspace: Path, script: str) -> None:
    (workspace / "policy.sh").write_text(script)
    subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--workdir", "/work",
         "-v", f"{workspace.resolve()}:/work:rw", IMAGE, "sh", "/work/policy.sh"],
        capture_output=True, timeout=120,
    )


TAMPER = (
    "mkdir -p /work/tests\n"
    "printf 'mkdir -p /logs/verifier\\necho 1 > /logs/verifier/reward.txt\\nexit 0\\n' "
    "> /work/tests/test.sh\n"
)


def test_a_shared_verifier_can_be_rewritten_by_the_agent(tmp_path):
    """REWARD_HACKABLE on shared-tests, established by exhibiting the exploit
    rather than by asking Assay."""
    ws = tmp_path / "ws"
    ws.mkdir()
    shutil.copytree(SUITE / "shared-tests" / "tests", ws / "tests")
    logs = tmp_path / "logs"
    logs.mkdir()

    _run_script(ws, TAMPER)
    reported = _run_verifier(ws, ws / "tests" / "test.sh", logs)
    actual = _run_verifier(ws, SUITE / "shared-tests" / "truth" / "test.sh", logs)
    assert reported == 1.0, "the agent's rewritten verifier passes"
    assert actual == 0.0, "the verifier it could not reach does not"


def test_a_separate_verifier_is_out_of_the_agents_reach(tmp_path):
    """The same attack on a `separate` task must do nothing, because the tests
    were never in the workspace. Copying them in anyway invented an exploit the
    real task does not have -- an auditor reporting a defect caused by its own
    mis-modelling."""
    from assay.adapters.harbor import HarborTaskDir

    assert HarborTaskDir(SUITE / "broken-gold").environment_mode == "separate"
    assert HarborTaskDir(SUITE / "shared-tests").environment_mode == "shared"

    ws = tmp_path / "ws2"
    ws.mkdir()
    logs = tmp_path / "logs2"
    logs.mkdir()
    _run_script(ws, TAMPER)  # writes /work/tests/test.sh, which is not consulted
    reported = _run_verifier(ws, SUITE / "broken-gold" / "tests" / "test.sh", logs)
    assert reported == 0.0, "a separate verifier is unaffected by the workspace"


# ---------------------------------------------------------------------------
# A ground-truth correction, and it improves Assay's score, so it is proved
# here with the tasks' own scripts and no probe in the loop.
#
# `self-graded` and `shared-tests` were labelled REWARD_HACKABLE only. Two
# policies named after BenchJack's flaw taxonomy (arXiv 2605.12673 Fig. 2 --
# V7 "trusting untrusted output", V1 "isolation failure") show both also admit
# an input-ignoring policy that scores full marks, which is a trivial-floor
# breach by definition. The label was incomplete; the environments did not
# change.
#
# Relabelling a fixture because a detector fired on it is unfalsifiable, and
# this particular relabelling removes two false positives and lifts precision
# from 0.833 back to 1.000. So the facts below come from `tests/test.sh` and
# `truth/test.sh` -- the task's own verifiers -- and the assertions are about
# rewards those scripts return, not about anything Assay concluded.
# ---------------------------------------------------------------------------


def _reward_for(env_id: str, policy: str) -> tuple[float, float]:
    """(what the environment reports, what the independent verifier says)."""
    from assay.adapter import run_policy
    from assay.corpus import entries

    factory = {e: f for e, f, _ in entries(only=["harbor"])}[env_id]
    adapter = factory()
    try:
        task = adapter.manifest().tasks[0].task_id
        actions = adapter.trivial_policies(task)[policy]
        transcript = run_policy(adapter, task, actions, stop_on_done=False)
        return adapter.verify(transcript).reward, adapter.true_completion(transcript)
    finally:
        close_adapter(adapter)


@pytest.mark.parametrize(
    "env_id, policy",
    [
        ("harbor/self-graded", "v7_make_the_comparison_agree"),
        ("harbor/shared-tests", "v1_neuter_a_reachable_verifier"),
    ],
)
def test_an_input_ignoring_policy_scores_full_marks(env_id, policy):
    """The environment pays 1.0 for work the independent verifier scores 0."""
    reported, true = _reward_for(env_id, policy)
    assert reported == 1.0, f"{env_id}: its own tests/test.sh did not pay the trivial policy"
    assert true == 0.0, f"{env_id}: truth/test.sh thinks the task was actually done"


@pytest.mark.parametrize(
    "policy", ["v7_make_the_comparison_agree", "v1_neuter_a_reachable_verifier"]
)
def test_neither_policy_fires_on_the_healthy_task(policy):
    """The control. A policy that pays on a healthy environment is a bug."""
    reported, true = _reward_for("harbor/healthy", policy)
    assert reported == 0.0, f"healthy paid {reported} for an input-ignoring policy"
    assert true == 0.0


def test_each_policy_only_catches_the_flaw_class_it_is_named_for():
    """Evidence against fitting: cross-wise, neither policy fires.

    V7 targets an evaluator that compares agent-writable files; V1 targets a
    verifier reachable from the workspace. `self-graded` has the first and not
    the second, `shared-tests` the reverse. If these policies had been written
    by looking at the two environments rather than at the taxonomy, both would
    tend to fire on both.
    """
    assert _reward_for("harbor/self-graded", "v1_neuter_a_reachable_verifier")[0] == 0.0
    assert _reward_for("harbor/shared-tests", "v7_make_the_comparison_agree")[0] == 0.0
