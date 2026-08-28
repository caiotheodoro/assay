"""The Harbor adapter against real task directories, run in real containers.

Harbor is the ecosystem where gold is executable and the verifier is a script
the agent can edit, so these tests cover the two things that makes possible:
a gold-passes check that can actually fail, and an exploit gap measured against
a verifier the agent never reaches.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from assay import audit
from assay.adapters import HarborAdapter
from assay.sandbox import AutoApprove, DockerSandbox, docker_available
from assay.types import Capability, DefectClass, ProbeStatus

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="docker daemon not available"
)

SUITE = Path(__file__).resolve().parents[1] / "src" / "assay" / "fixtures" / "harbor_suite"


@pytest.fixture
def one_task(tmp_path):
    """Isolate a single task directory into its own suite."""

    def _build(name: str) -> HarborAdapter:
        root = tmp_path / f"suite-{name}"
        root.mkdir()
        shutil.copytree(SUITE / name, root / name)
        return HarborAdapter(
            root,
            sandbox=DockerSandbox(AutoApprove("test suite")),
            env_id=f"harbor/{name}",
        )

    return _build


# -- capability honesty -----------------------------------------------------


def test_adapter_refuses_to_claim_an_invertible_spec(one_task):
    """A shell verifier takes no target argument. Claiming otherwise would
    produce a clean-looking inverted-spec result out of nothing."""
    with one_task("healthy") as adapter:
        manifest = adapter.manifest()
        assert not manifest.has(Capability.INVERTIBLE_SPEC)
        assert manifest.has(Capability.GOLD_TRAJECTORY)
        assert manifest.has(Capability.TRUE_COMPLETION)


def test_inverted_spec_probe_reports_not_applicable(one_task):
    with one_task("healthy") as adapter:
        report = audit(adapter)
    probe = [r for r in report.results if r.probe == "inverted_fails"][0]
    assert probe.status is ProbeStatus.NOT_APPLICABLE
    assert probe.reason


# -- the probes that only Harbor makes possible -----------------------------


def test_healthy_task_passes_its_own_gold(one_task):
    with one_task("healthy") as adapter:
        report = audit(adapter)
    assert DefectClass.GOLD_FAILS not in report.detected


def test_rotted_gold_is_caught(one_task):
    """solve.sh writes 41; the tests want 42. Only an executable gold can
    surface this, which is why inspect_ai cannot."""
    with one_task("broken-gold") as adapter:
        report = audit(adapter)
    assert DefectClass.GOLD_FAILS in report.detected


def test_a_verifier_that_always_exits_zero_is_caught(one_task):
    with one_task("vacuous-tests") as adapter:
        report = audit(adapter)
    assert DefectClass.NOOP_PASSES in report.detected
    assert DefectClass.REWARD_HACKABLE in report.detected
    assert report.verdict == "INVALID"


def test_exploit_gap_uses_a_verifier_the_agent_cannot_reach(one_task):
    """The vacuous task reports 1.0 for doing nothing while the independent
    verifier reports 0.0. That difference is the whole measurement."""
    from assay.adapter import run_policy

    with one_task("vacuous-tests") as adapter:
        transcript = run_policy(adapter, "vacuous-tests", [])
        reported = adapter.verify(transcript).reward
        actual = adapter.true_completion(transcript)
    assert reported == 1.0
    assert actual == 0.0


# -- session mechanics ------------------------------------------------------


def test_workspace_is_wiped_between_episodes(one_task):
    from assay.types import Action

    with one_task("healthy") as adapter:
        adapter.reset("healthy")
        adapter.step(Action("run", {"script": "echo leaked > /work/leak.txt\n"}))
        adapter.reset("healthy")
        result = adapter.step(
            Action("run", {"script": "cat /work/leak.txt 2>/dev/null || echo GONE\n"})
        )
    assert "GONE" in result.observation.data["stdout"]


def test_one_container_serves_the_whole_audit(one_task):
    """Starting a container costs seconds; exec costs a fraction of one. If this
    regresses, the reproduction guide gets materially worse."""
    with one_task("healthy") as adapter:
        audit(adapter)
        assert adapter._live is not None
        assert adapter._live.exec_count > 5
