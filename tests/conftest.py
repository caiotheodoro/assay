"""Session-level guards for the test suite itself.

There was no conftest here, and the absence had a cost: the suite could leak
sandbox containers indefinitely and nothing said so. This machine accumulated
fourteen of them, the oldest running for thirty-three hours, every creating
process long dead -- and a run that leaks is also a run whose teardown can
hang, which is how the suite once finished its last test and never printed a
summary line.

The rule here is reap-then-warn, not reap-then-fail. A leak should be loud on
the first run that causes it, but turning a green suite red for a container
that has already been cleaned up would train people to ignore the signal.
"""

from __future__ import annotations

import subprocess
import warnings

import pytest


@pytest.fixture(autouse=True)
def _the_suite_grants_its_own_approval():
    """The test suite is CI, and CI approves explicitly rather than implicitly.

    Every shipped path now resolves its approver through
    `sandbox.current_approver()`, whose default is a `PromptApprover` that
    refuses when there is no terminal -- which is every pytest run. So the
    suite states its standing approval here, in one place, carrying a reason,
    exactly as `.github/workflows/ci.yml` does with `ASSAY_APPROVE_ALL`.

    The tests that exercise the gate itself override this inside the test, and
    the teardown puts normal resolution back so an override cannot leak into
    the next test.
    """
    from assay.sandbox import AutoApprove, set_approver

    set_approver(AutoApprove("assay test suite, tests/conftest.py"))
    yield
    set_approver(None)


@pytest.fixture(scope="session", autouse=True)
def _sandbox_containers_do_not_outlive_the_suite():
    """Fail loudly-but-not-redly if the suite leaves containers behind.

    Only containers this run created are counted. Orphans that predate the
    session are somebody else's problem and are reported separately rather
    than silently cleaned, because deleting a container a *running* audit
    still owns would be worse than leaking one.
    """
    from assay.sandbox import docker_available, orphaned_sessions, session_containers

    if not docker_available():
        yield
        return

    before = {cid for cid, *_ in session_containers()}
    stale = len(orphaned_sessions())
    if stale:
        warnings.warn(
            f"{stale} orphaned sandbox container(s) existed before this run. "
            "They are not counted against it. Clean them with `assay reap`.",
            stacklevel=1,
        )

    yield

    leaked = [(cid, label) for cid, label in orphaned_sessions() if cid not in before]
    for cid, _ in leaked:
        try:
            subprocess.run(
                ["docker", "rm", "-f", "-v", cid], capture_output=True, timeout=15
            )
        except (OSError, subprocess.SubprocessError):
            pass
    if leaked:
        warnings.warn(
            f"the suite leaked {len(leaked)} sandbox container(s) and they have been "
            f"removed: {[label for _, label in leaked]}. Every session-creating test "
            "should use `with HarborAdapter(...)` or `try/finally: close_adapter(...)`.",
            stacklevel=1,
        )


@pytest.fixture(autouse=True)
def _tmp_path_can_be_mounted_into_a_sandbox(tmp_path):
    """Make `tmp_path` traversable by a container that has dropped every capability.

    `tmp_path` comes from `tempfile.mkdtemp`, which is 0700. The sandbox runs
    with `--cap-drop ALL`, and the capability that goes with it is
    `CAP_DAC_OVERRIDE` -- the one root uses to ignore file modes. A container
    handed a 0700 host directory therefore cannot read it *even as root*, and
    every test that mounts `tmp_path` fails with `Permission denied`.

    Only on Linux. Docker Desktop on macOS presents bind-mounted files as owned
    by the container user and never consults the mode, so the suite was green
    on the only machine it had ever run on while CI was red on every push.
    """
    tmp_path.chmod(0o755)
