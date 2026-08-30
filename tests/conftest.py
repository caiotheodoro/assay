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
