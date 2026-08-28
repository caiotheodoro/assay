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
