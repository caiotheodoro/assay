"""Modes on everything the sandbox mounts, checked without a container.

The sandbox runs `--cap-drop ALL`, which takes `CAP_DAC_OVERRIDE` away from
container root, so file modes are enforced against it like anyone else. Docker
Desktop on macOS never consults those modes -- it presents bind-mounted files as
owned by the container user -- so on the machine this repo is developed on, a
directory the container cannot possibly read looks fine. Three separate
permission bugs shipped that way, and each was found by CI on Linux afterwards.

These tests need no daemon: they assert the modes directly, so they fail on the
laptop where the consequence is invisible.
"""

from __future__ import annotations

import shutil
import stat

from assay._harbor_corpus import SUITE
from assay.adapters.harbor import HarborAdapter, _mount_dir, stage_suite


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_a_staged_suite_can_be_read_by_a_process_that_does_not_own_it():
    """`/suite` is where the verifier lives. `mkdtemp` is 0700, so container
    root could not open `/suite/<task>/tests/test.sh`, and the adapter scored
    the failure to open as the environment scoring zero."""
    root = stage_suite(SUITE / "healthy", "assay-test-suite-")
    try:
        assert _mode(root) & 0o005 == 0o005, f"{root} is {oct(_mode(root))}"
        for path in root.rglob("*"):
            need = 0o005 if path.is_dir() else 0o004
            assert _mode(path) & need == need, f"{path} is {oct(_mode(path))}"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_scratch_mounts_can_be_written_by_a_process_that_does_not_own_them():
    """/work takes the agent's solution and /logs takes the verifier's reward.
    Readable is not enough for either."""
    for prefix in ("assay-test-work-", "assay-test-logs-"):
        path = _mount_dir(prefix)
        try:
            assert _mode(path) & 0o007 == 0o007, f"{path} is {oct(_mode(path))}"
        finally:
            shutil.rmtree(path, ignore_errors=True)


class _StubSession:
    """Stands in for the container, and refuses to be the one that cleans up."""

    def exec(self, command, workdir="/work"):
        raise AssertionError(
            f"asked the container to run {command}: the host should be able to "
            "empty a directory it created itself"
        )


def test_the_verifier_log_dir_is_left_where_the_host_can_empty_it(tmp_path):
    """Unlink permission comes from the directory, not the file. When the
    container creates /logs/verifier, the reward file it writes there is
    root-owned in a root-owned directory and the host cannot remove it --
    so `_parse_reward` reads the previous episode's score as this one's."""
    adapter = HarborAdapter.__new__(HarborAdapter)
    adapter._logs_host = tmp_path
    (tmp_path / "verifier").mkdir()
    (tmp_path / "verifier" / "reward.txt").write_text("1")

    adapter._clear_verifier_logs(_StubSession())

    assert (tmp_path / "verifier").is_dir(), "left ready for the next verifier"
    assert not (tmp_path / "verifier" / "reward.txt").exists()
    assert _mode(tmp_path / "verifier") & 0o007 == 0o007
