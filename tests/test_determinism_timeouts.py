"""A repeat the harness abandoned is not a repeat that came back different.

`harbor/broken-gold` reported a spurious `NONDETERMINISM` in 1 of 6 full-corpus
runs, and never on the harbor slice alone — the flake needed the load of a full
run. `HarborAdapter.step` discarded `SandboxResult.timed_out`, so a `docker
exec` that hit the wall clock surfaced as exit code 124 where a healthy repeat
had 0. The determinism probe compares observations across repeats, saw two
different fingerprints, and reported a defect about an environment that had not
misbehaved.

That is the failure this project exists to catch, happening inside a probe:
absence of evidence read as evidence.
"""

from __future__ import annotations

from assay.adapter import NotSupported
from assay.probes.base import REGISTRY
from assay.types import (
    SANDBOX_TIMEOUT,
    Action,
    Capability,
    Manifest,
    Observation,
    ProbeStatus,
    Score,
    StepResult,
    Task,
    Transcript,
)


def _probe():
    return next(p() for p in REGISTRY if p.name == "seed_determinism")


class _FlakyUnderLoad:
    """Deterministic, except the harness gives up on the second repeat."""

    def __init__(self, *, time_out_on: int | None = 2, always: bool = False) -> None:
        # `run_policy` resets too, so the counter advances twice per repeat.
        self.calls = 0
        self.time_out_on = time_out_on
        self.always = always

    def manifest(self) -> Manifest:
        return Manifest(
            env_id="stub/flaky-harness",
            ecosystem="stub",
            version="0",
            tasks=[Task(task_id="t", instruction="do the thing")],
            capabilities=frozenset({Capability.SEEDED_RESET, Capability.LIVE_STEPPING}),
        )

    def reset(self, task_id: str, seed: int = 0) -> Observation:
        self.calls += 1
        return Observation(ok=True, data={"seed": seed})

    def step(self, action: Action) -> StepResult:
        if self.always or self.calls == self.time_out_on:
            return StepResult(
                Observation(
                    ok=False,
                    data={"stdout": "", "exit_code": 124, "timed_out": True},
                    code=SANDBOX_TIMEOUT,
                ),
                done=False,
            )
        return StepResult(
            Observation(ok=True, data={"stdout": "same", "exit_code": 0, "timed_out": False}),
            done=False,
        )

    def gold_actions(self, task_id: str) -> list[Action]:
        raise NotSupported("stub ships no gold trajectory")

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        return {"noop": [Action("run", {"script": "true"})]}


def test_a_timed_out_repeat_is_not_reported_as_nondeterminism():
    result = _probe().run(_FlakyUnderLoad(), {})
    assert result.status is not ProbeStatus.DEFECT, (
        "a sandbox that hit its wall clock was reported as a nondeterministic "
        "environment; that is a false positive on a slow machine"
    )
    assert not result.findings


def test_the_inconclusive_repeat_is_recorded_with_its_reason():
    """Silence is not allowed either — the card has to say why it did not check."""
    result = _probe().run(_FlakyUnderLoad(), {})
    detail = (result.detail or {}).get("per_task", {}).get("t", {})
    assert detail.get("timed_out_repeats"), "the timeout count must survive into the card"
    assert "wall clock" in detail.get("inconclusive", "")


def test_when_nothing_could_be_compared_the_probe_declines():
    """PASS would be a claim the probe did not earn.

    A check that could not run reported as a check that passed is the exact
    failure this project audits environments for.
    """
    result = _probe().run(_FlakyUnderLoad(always=True), {})
    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert "wall clock" in (result.reason or "")


def test_genuine_nondeterminism_is_still_caught():
    """The fix must not buy quiet by disarming the probe."""

    class _ReallyNondeterministic(_FlakyUnderLoad):
        def step(self, action: Action) -> StepResult:
            return StepResult(
                Observation(
                    ok=True,
                    data={"stdout": f"run-{self.calls}", "exit_code": 0, "timed_out": False},
                ),
                done=False,
            )

    result = _probe().run(_ReallyNondeterministic(time_out_on=None), {})
    assert result.status is ProbeStatus.DEFECT
    assert result.findings
