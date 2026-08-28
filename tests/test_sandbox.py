"""The sandbox must actually contain, and must actually refuse.

These tests run real containers. A sandbox verified only by reading its own
argv list is a sandbox nobody has tested.
"""

from __future__ import annotations

import pytest

from assay.sandbox import (
    ApprovalDenied,
    AutoApprove,
    DenyAll,
    DockerSandbox,
    ExecRequest,
    Mount,
    SandboxPolicy,
    docker_available,
)

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="docker daemon not available"
)

IMAGE = "alpine:3.20"


def _req(command: list[str], **policy_kwargs) -> ExecRequest:
    return ExecRequest(
        policy=SandboxPolicy(image=IMAGE, **policy_kwargs),
        command=command,
        workdir="/tmp",
    )


def _box() -> DockerSandbox:
    return DockerSandbox(AutoApprove("test suite"))


# -- approval ---------------------------------------------------------------


def test_nothing_runs_without_approval():
    box = DockerSandbox()  # default DenyAll
    with pytest.raises(ApprovalDenied):
        box.run(_req(["echo", "should not run"]))
    assert box.approvals == []


def test_approval_is_recorded_for_audit():
    box = _box()
    box.run(_req(["true"]))
    assert len(box.approvals) == 1


# -- containment ------------------------------------------------------------


def test_it_can_run_something_at_all():
    result = _box().run(_req(["echo", "hello"]))
    assert result.ok
    assert "hello" in result.stdout


def test_network_is_denied_by_default():
    """The point of the whole exercise: untrusted code cannot phone home."""
    result = _box().run(
        _req(["sh", "-c", "wget -q -T 3 -O - http://example.com || echo BLOCKED"])
    )
    assert "BLOCKED" in result.stdout, result.stdout + result.stderr


def test_root_filesystem_is_read_only():
    result = _box().run(_req(["sh", "-c", "touch /etc/assay-probe || echo READONLY"]))
    assert "READONLY" in result.stdout


def test_tmp_is_writable_so_ordinary_work_still_functions():
    result = _box().run(_req(["sh", "-c", "echo x > /tmp/f && cat /tmp/f"]))
    assert result.ok
    assert "x" in result.stdout


def test_wall_clock_limit_is_enforced():
    result = _box().run(_req(["sleep", "30"], wall_seconds=3))
    assert result.timed_out
    assert not result.ok


def test_filesystem_changes_do_not_survive_the_container():
    box = _box()
    box.run(_req(["sh", "-c", "echo persisted > /tmp/marker"]))
    result = box.run(_req(["sh", "-c", "cat /tmp/marker 2>/dev/null || echo GONE"]))
    assert "GONE" in result.stdout


def test_a_mounted_directory_is_read_only_by_default(tmp_path):
    (tmp_path / "given.txt").write_text("from the host")
    request = ExecRequest(
        policy=SandboxPolicy(image=IMAGE),
        command=["sh", "-c", "cat /work/given.txt && (touch /work/new || echo NOWRITE)"],
        mounts=[Mount(source=tmp_path, target="/work")],
        workdir="/work",
    )
    result = _box().run(request)
    assert "from the host" in result.stdout
    assert "NOWRITE" in result.stdout
    assert not (tmp_path / "new").exists()
