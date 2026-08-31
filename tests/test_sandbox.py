"""The sandbox must actually contain, and must actually refuse.

These tests run real containers. A sandbox verified only by reading its own
argv list is a sandbox nobody has tested.

The gate tests used to be skipped wholesale when Docker was absent, because the
module carried one `pytestmark`. That hid the half of the gate that has nothing
to do with Docker -- the in-process approval in front of third-party
`inspect_ai` scorers -- from CI, which is exactly where Docker is absent and
`inspect_ai` is installed. The marker is now applied per test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assay.sandbox import (
    ApprovalDenied,
    AutoApprove,
    DenyAll,
    DockerSandbox,
    ExecRequest,
    InProcessRequest,
    Mount,
    PromptApprover,
    SandboxPolicy,
    current_approver,
    docker_available,
    set_approver,
)

needs_docker = pytest.mark.skipif(
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


@needs_docker
def test_nothing_runs_without_approval():
    """Three ways in, one gate, and it holds on all three.

    The first assertion is the one this test always made. The other two are the
    two paths a judge found running without a gate at all: `assay audit
    harbor/...` built its sandbox with `AutoApprove("assay corpus run")` baked
    in, and the `inspect_ai` adapter never asked anybody before executing a
    third-party scorer in this very interpreter.
    """
    # 1. the sandbox itself, with no approver configured
    box = DockerSandbox()  # default DenyAll
    with pytest.raises(ApprovalDenied):
        box.run(_req(["echo", "should not run"]))
    assert box.approvals == []
    assert box.decisions and box.decisions[0]["granted"] is False

    # 2. the shipped corpus path. `entries()` is what `assay audit` calls, and
    # the factory has to pick up the refusing approver rather than one of its
    # own.
    from assay.corpus import entries

    set_approver(DenyAll())
    harbor = [e for e in entries() if e[0] == "harbor/self-graded"]
    assert harbor, "harbor/self-graded is not in the corpus; nothing was tested"
    adapter = harbor[0][1]()
    try:
        with pytest.raises(ApprovalDenied):
            adapter.reset(adapter.manifest().tasks[0].task_id)
        assert adapter.sandbox.approvals == []
        assert [d["granted"] for d in adapter.approval_log()] == [False]
    finally:
        adapter.close()

    # 3. the inspect_ai adapter, which runs somebody else's Python in *this*
    # process and is therefore the one place the container guarantees do not
    # reach at all.
    _assert_the_inspect_scorer_needs_approval()


def _assert_the_inspect_scorer_needs_approval() -> None:
    pytest.importorskip("inspect_ai")
    from assay._inspect_corpus import build_inspect_environments
    from assay.adapters.inspect_ai_adapter import InspectAdapter
    from assay.types import Action, Transcript

    _env_id, factory, _ = build_inspect_environments(InspectAdapter)[0]
    adapter = factory()
    task_id = adapter.manifest().tasks[0].task_id
    transcript = Transcript(
        task_id=task_id, seed=0, actions=[Action("submit", {"answer": "x"})]
    )

    set_approver(DenyAll())
    with pytest.raises(ApprovalDenied):
        adapter.verify(transcript)
    assert [d["granted"] for d in adapter.approval_log()] == [False]
    assert adapter.approval_log()[0]["contained"] is False, (
        "an in-process scorer call must never be recorded as contained"
    )

    # And the request the approver was handed has to say what it is asking for.
    request = adapter.scoring_request()
    assert isinstance(request, InProcessRequest)
    assert request.callables, "the approver was not told which scorers would run"
    assert "network" in request.risk


def test_the_inspect_scorer_gate_holds_without_docker():
    """The same assertion as part 3 above, reachable on a machine with no
    Docker -- which is every CI runner this repo has."""
    _assert_the_inspect_scorer_needs_approval()


def test_the_default_approver_asks_a_human_and_refuses_when_there_is_none(monkeypatch):
    """`current_approver()` is the only place that decides, and with nothing
    configured it is a prompt -- not a standing yes.

    `ASSAY_APPROVE_ALL` is deleted rather than assumed absent. It is the
    documented way to run unattended, so it is set in CI and in every
    reproduction command, and a test asserting the *default* must not quietly
    pass or fail on whether the shell it inherited had it.
    """
    monkeypatch.delenv("ASSAY_APPROVE_ALL", raising=False)
    set_approver(None)
    assert isinstance(current_approver(), PromptApprover)

    # An empty answer is a no. The default has to be the safe one, because the
    # answer people give a prompt they did not read is the default.
    assert PromptApprover(reader=lambda prompt: "")(_req(["echo", "hi"])) is False
    assert PromptApprover(reader=lambda prompt: "n")(_req(["echo", "hi"])) is False
    assert PromptApprover(reader=lambda prompt: "y")(_req(["echo", "hi"])) is True

    # `a` is a standing yes for the rest of this process and nothing wider.
    once = PromptApprover(reader=lambda prompt: "a")
    assert once(_req(["echo", "hi"])) is True
    assert once.standing is True
    assert PromptApprover(reader=lambda prompt: "").standing is False

    # No reader and no terminal: refuse, and never fall through to a yes.
    class _NotATty:
        def isatty(self):
            return False

    import sys as _sys

    real, _sys.stdin = _sys.stdin, _NotATty()
    try:
        blind = PromptApprover()
        assert blind.can_ask() is False
        assert blind(_req(["echo", "hi"])) is False
    finally:
        _sys.stdin = real


def test_an_environment_standing_approval_is_explicit_and_carries_its_reason(monkeypatch):
    """The escape CI and `scripts/full_run.py` use. It has to be legible on a
    card afterwards, so the reason travels with it."""
    from assay.sandbox import APPROVE_ALL_ENV, AutoApprove as _AutoApprove
    from assay.sandbox import approver_from_environment

    set_approver(None)
    monkeypatch.delenv(APPROVE_ALL_ENV, raising=False)
    assert approver_from_environment() is None

    monkeypatch.setenv(APPROVE_ALL_ENV, "ci: nightly corpus run")
    approver = approver_from_environment()
    assert isinstance(approver, _AutoApprove)
    assert "ci: nightly corpus run" in approver.reason
    assert approver.interactive is False
    assert current_approver() is not None
    assert current_approver()(_req(["echo", "hi"])) is True

    monkeypatch.setenv(APPROVE_ALL_ENV, "0")
    assert approver_from_environment() is None


def test_what_the_approver_is_shown_before_it_answers():
    """A yes given without seeing the request is not a yes."""
    from assay.sandbox import describe

    shown = "\n".join(
        describe(
            ExecRequest(
                policy=SandboxPolicy(image=IMAGE, network=False),
                command=["sh", "-c", "cat /work/expected.txt"],
                mounts=[Mount(source=Path("/tmp"), target="/work")],
            )
        )
    )
    for expected in (IMAGE, "cat /work/expected.txt", "--network none", "cpus=", "memory=",
                     "wall=", "cap-drop ALL", "/tmp -> /work"):
        assert expected in shown, f"the approver was never shown {expected!r}"


@needs_docker
def test_approval_is_recorded_for_audit():
    box = _box()
    box.run(_req(["true"]))
    assert len(box.approvals) == 1


# -- containment ------------------------------------------------------------


@needs_docker
def test_it_can_run_something_at_all():
    result = _box().run(_req(["echo", "hello"]))
    assert result.ok
    assert "hello" in result.stdout


@needs_docker
def test_network_is_denied_by_default():
    """The point of the whole exercise: untrusted code cannot phone home."""
    result = _box().run(
        _req(["sh", "-c", "wget -q -T 3 -O - http://example.com || echo BLOCKED"])
    )
    assert "BLOCKED" in result.stdout, result.stdout + result.stderr


@needs_docker
def test_root_filesystem_is_read_only():
    result = _box().run(_req(["sh", "-c", "touch /etc/assay-probe || echo READONLY"]))
    assert "READONLY" in result.stdout


@needs_docker
def test_tmp_is_writable_so_ordinary_work_still_functions():
    result = _box().run(_req(["sh", "-c", "echo x > /tmp/f && cat /tmp/f"]))
    assert result.ok
    assert "x" in result.stdout


@needs_docker
def test_wall_clock_limit_is_enforced():
    result = _box().run(_req(["sleep", "30"], wall_seconds=3))
    assert result.timed_out
    assert not result.ok


@needs_docker
def test_filesystem_changes_do_not_survive_the_container():
    box = _box()
    box.run(_req(["sh", "-c", "echo persisted > /tmp/marker"]))
    result = box.run(_req(["sh", "-c", "cat /tmp/marker 2>/dev/null || echo GONE"]))
    assert "GONE" in result.stdout


@needs_docker
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


def test_reap_says_it_could_not_look_rather_than_finding_nothing(monkeypatch, capsys):
    """`assay reap` with no daemon used to print "no assay sandbox containers
    running" and exit 0 -- absence of evidence dressed up as evidence of
    absence, which is exactly what the probes flag in environments."""
    from assay import cli

    monkeypatch.setattr("assay.sandbox.docker_available", lambda: False)
    code = cli.main(["reap", "--dry-run"])
    out = capsys.readouterr().out
    assert code != 0
    assert "cannot check" in out
    assert "daemon is not running" in out
