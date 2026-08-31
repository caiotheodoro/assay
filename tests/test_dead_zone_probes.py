"""The two families added to close `docs/COVERAGE.md`'s V8 and V3 rows.

Every probe here gets the same pair of tests the rest of the battery gets: it
must fire on a planted instance, and it must stay silent on a healthy one. The
second half is the one that matters. `docs/COVERAGE.md` argues that a probe
reporting a defect on a healthy environment costs a reader the tool's
credibility in a way no amount of NOT_APPLICABLE discipline elsewhere repairs,
and both of these families judge a manifest rather than a behaviour -- which is
exactly the shape that reports on its own assumptions if nobody checks.

The adapters below are built for these tests and are deliberately NOT added to
`assay.fixtures.CATALOG`. That catalogue is a scored corpus, and an environment
added to it changes a published number; a fixture that exists to exercise a
probe belongs next to the probe's tests.
"""

from __future__ import annotations

import textwrap

import pytest

from assay import audit
from assay.adapter import BaseAdapter, NotSupported
from assay.fixtures import CATALOG, build
from assay.probes import FAMILIES_NOT_PLANTED_IN_FIXTURES, families
from assay.probes.evaluator import VerifierStaticAnalysis, execution_sinks
from assay.probes.permissions import DeclaredPermissions, excessive_grants
from assay.types import (
    Capability,
    DefectClass,
    Manifest,
    MountSpec,
    ProbeStatus,
    SandboxPosture,
    Severity,
    Task,
)


# --------------------------------------------------------------------------
# Adapters. One knob each, so a failure names the thing that moved.
# --------------------------------------------------------------------------


class PostureEnv(BaseAdapter):
    """An environment that declares a deployment and nothing else.

    Nothing here runs. That is the point of family 10: it is the only probe in
    the battery that can audit an environment which cannot be executed at all.
    """

    def __init__(self, posture: SandboxPosture | None, *, declare: bool = True) -> None:
        self._posture = posture
        self._declare = declare

    def manifest(self) -> Manifest:
        caps = {Capability.SANDBOX_POSTURE} if self._declare else set()
        return Manifest(
            env_id="posture/test",
            ecosystem="fixture",
            version="0",
            source="tests",
            capabilities=frozenset(caps),
            tasks=[Task(task_id="t1", instruction="do the job")],
        )

    def sandbox_posture(self, task_id: str) -> SandboxPosture:
        if self._posture is None:
            raise NotSupported("this environment declares no posture")
        return self._posture


class VerifierSourceEnv(BaseAdapter):
    """An environment that hands out its verifier's source."""

    def __init__(self, source: str | None, *, declare: bool = True, n_tasks: int = 1) -> None:
        self._source = source
        self._declare = declare
        self._n = n_tasks

    def manifest(self) -> Manifest:
        caps = {Capability.VERIFIER_SOURCE} if self._declare else set()
        return Manifest(
            env_id="verifier/test",
            ecosystem="fixture",
            version="0",
            source="tests",
            capabilities=frozenset(caps),
            tasks=[
                Task(task_id=f"t{i}", instruction="do the job") for i in range(1, self._n + 1)
            ],
        )

    def verifier_source(self, task_id: str) -> str:
        if self._source is None:
            raise NotSupported("no verifier source here")
        return self._source


CLEAN_POSTURE = SandboxPosture(
    network_enabled=False,
    network_required=False,
    read_only_root=True,
    user="1000",
    root_required=False,
    mounts=(
        MountSpec("/tmp/work", "/work", read_only=False),
        MountSpec("/suite/tests", "/suite/tests", read_only=True),
    ),
    verifier_paths=("/suite/tests",),
    declared_by="tests/task.toml",
)

HEALTHY_VERIFIER = textwrap.dedent(
    """
    import re
    import subprocess

    def score(submission: str, target: str) -> float:
        if not re.fullmatch(r"[A-Za-z ]+", submission):
            return 0.0
        result = subprocess.run(["diff", submission, target], capture_output=True)
        return 1.0 if result.returncode == 0 else 0.0
    """
)


# --------------------------------------------------------------------------
# V8 -- excessive permissions: the rule table
# --------------------------------------------------------------------------


def test_a_clean_posture_produces_no_grant_findings():
    hits, _unchecked = excessive_grants(CLEAN_POSTURE)
    assert hits == [], hits


def test_network_granted_for_a_task_that_declares_no_network_step_fires():
    hits, _ = excessive_grants(
        CLEAN_POSTURE.__class__(
            **{**CLEAN_POSTURE.__dict__, "network_enabled": True, "network_required": False}
        )
    )
    assert [h["rule"] for h in hits] == ["network_not_needed"]


def test_network_granted_and_needed_is_not_a_finding():
    """The comparison is grant-against-need. A task that fetches something has
    to be allowed to fetch it, and reporting that would make the probe an
    objection to networked benchmarks rather than to unnecessary permissions."""
    hits, _ = excessive_grants(
        SandboxPosture(
            network_enabled=True,
            network_required=True,
            read_only_root=True,
            declared_by="tests",
        )
    )
    assert hits == []


def test_network_granted_with_no_declared_need_is_recorded_as_unchecked_not_flagged():
    """The fail-closed direction. An adapter that cannot say whether the task
    needs network must not have that read as 'it does not', because the probe
    would then object to every environment whose adapter is merely thin."""
    hits, unchecked = excessive_grants(
        SandboxPosture(network_enabled=True, read_only_root=True, declared_by="tests")
    )
    assert hits == []
    assert any(u.startswith("network:") for u in unchecked)


def test_a_writable_mount_covering_the_verifier_fires():
    posture = SandboxPosture(
        read_only_root=True,
        mounts=(MountSpec("/tmp/work", "/work", read_only=False),),
        verifier_paths=("/work/tests",),
        declared_by="tests/task.toml",
    )
    hits, _ = excessive_grants(posture)
    assert [h["rule"] for h in hits] == ["writable_verifier_mount"]
    assert hits[0]["declared"]["target"] == "/work"


def test_a_writable_mount_of_the_verifier_directory_itself_fires():
    """Stated precisely rather than as a parent, which is the same grant. Only
    matching the containing mount would let a deployment escape by being exact."""
    posture = SandboxPosture(
        read_only_root=True,
        mounts=(MountSpec("/tmp/t", "/work/tests", read_only=False),),
        verifier_paths=("/work/tests",),
        declared_by="tests",
    )
    hits, _ = excessive_grants(posture)
    assert [h["rule"] for h in hits] == ["writable_verifier_mount"]


def test_a_read_only_verifier_mount_is_not_a_finding():
    posture = SandboxPosture(
        read_only_root=True,
        mounts=(
            MountSpec("/tmp/work", "/work", read_only=False),
            MountSpec("/suite", "/suite", read_only=True),
        ),
        verifier_paths=("/suite/tests",),
        declared_by="tests",
    )
    assert excessive_grants(posture)[0] == []


def test_a_sibling_path_is_not_read_as_containing_the_verifier():
    """`/workspace` is not a parent of `/work/tests`. Comparing on a raw string
    prefix says it is, and that is a false alarm with no way for a reader to
    tell it from a real one."""
    posture = SandboxPosture(
        read_only_root=True,
        mounts=(MountSpec("/tmp/w", "/workspace", read_only=False),),
        verifier_paths=("/work/tests",),
        declared_by="tests",
    )
    assert excessive_grants(posture)[0] == []


def test_a_writable_root_filesystem_fires():
    hits, _ = excessive_grants(
        SandboxPosture(read_only_root=False, declared_by="tests/task.toml")
    )
    assert [h["rule"] for h in hits] == ["writable_root_filesystem"]


def test_root_is_only_a_finding_when_the_task_declares_it_does_not_need_root():
    granted = SandboxPosture(
        read_only_root=True, user="root", root_required=False, declared_by="tests"
    )
    assert [h["rule"] for h in excessive_grants(granted)[0]] == ["root_not_needed"]

    needed = SandboxPosture(
        read_only_root=True, user="root", root_required=True, declared_by="tests"
    )
    assert excessive_grants(needed)[0] == []

    undeclared = SandboxPosture(read_only_root=True, user="root", declared_by="tests")
    assert excessive_grants(undeclared)[0] == []


# --------------------------------------------------------------------------
# V8 -- through the probe
# --------------------------------------------------------------------------


def test_permissions_probe_fires_on_a_planted_environment():
    posture = SandboxPosture(
        network_enabled=True,
        network_required=False,
        read_only_root=False,
        user="root",
        root_required=False,
        mounts=(MountSpec("/tmp/work", "/work", read_only=False),),
        verifier_paths=("/work/tests",),
        declared_by="fixtures/over-permissioned/task.toml",
    )
    result = DeclaredPermissions().run(PostureEnv(posture))
    assert result.status is ProbeStatus.DEFECT
    assert {f.defect for f in result.findings} == {DefectClass.EXCESSIVE_PERMISSIONS}
    assert {f.severity for f in result.findings} == {Severity.HIGH}
    assert {f.evidence["rule"] for f in result.findings} == {
        "network_not_needed",
        "writable_verifier_mount",
        "writable_root_filesystem",
        "root_not_needed",
    }
    # Every finding says where the claim can be checked.
    assert all(
        f.evidence["declared_by"] == "fixtures/over-permissioned/task.toml"
        for f in result.findings
    )


def test_permissions_probe_is_silent_on_a_healthy_environment():
    result = DeclaredPermissions().run(PostureEnv(CLEAN_POSTURE))
    assert result.status is ProbeStatus.PASS, result.findings


def test_permissions_probe_declines_when_the_capability_is_withheld():
    result = DeclaredPermissions().run(PostureEnv(CLEAN_POSTURE, declare=False))
    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert "SANDBOX_POSTURE" in (result.reason or "")


def test_permissions_probe_declines_rather_than_passing_on_an_empty_posture():
    """An adapter that declares the capability and returns nothing has not
    cleared the environment. PASS would be the 'a check that could not run
    reported as a check that passed' failure this repository exists to find."""
    result = DeclaredPermissions().run(PostureEnv(SandboxPosture(declared_by="tests")))
    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert "empty posture" in (result.reason or "")


def test_a_healthy_pass_still_records_which_checks_could_not_be_made():
    """A clean bill next to three unmade checks is a different statement from a
    clean bill, and the card has to be able to tell them apart."""
    partial = SandboxPosture(network_enabled=False, declared_by="tests")
    result = DeclaredPermissions().run(PostureEnv(partial))
    assert result.status is ProbeStatus.PASS
    unchecked = result.detail["per_task"]["t1"]["checks_not_made"]
    assert any(u.startswith("root filesystem:") for u in unchecked)
    assert any(u.startswith("user:") for u in unchecked)


# --------------------------------------------------------------------------
# V3 -- evaluator RCE: the sink table
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("def s(x):\n    return eval(x)\n", "eval"),
        ("def s(x):\n    exec(x)\n", "exec"),
        ("def s(x):\n    return compile(x, '<s>', 'eval')\n", "compile"),
        ("import os\ndef s(x):\n    os.system(x)\n", "os.system"),
        ("import os\ndef s(x):\n    return os.popen(x).read()\n", "os.popen"),
        ("import pickle\ndef s(p):\n    return pickle.load(open(p, 'rb'))\n", "pickle.load"),
        ("import marshal\ndef s(b):\n    return marshal.loads(b)\n", "marshal.loads"),
        ("import yaml\ndef s(t):\n    return yaml.unsafe_load(t)\n", "yaml.unsafe_load"),
        ("import torch\ndef s(p):\n    return torch.load(p)\n", "torch.load"),
    ],
)
def test_every_named_sink_is_found(source, expected):
    assert [s["call"] for s in execution_sinks(source)] == [expected]


def test_subprocess_is_only_a_sink_with_shell_true():
    safe = "import subprocess\ndef s(a):\n    subprocess.run(['diff', a])\n"
    unsafe = "import subprocess\ndef s(a):\n    subprocess.run('diff ' + a, shell=True)\n"
    assert execution_sinks(safe) == []
    assert [s["call"] for s in execution_sinks(unsafe)] == ["subprocess.run"]


def test_yaml_load_is_judged_on_its_loader():
    bare = "import yaml\ndef s(t):\n    return yaml.load(t)\n"
    kw = "import yaml\ndef s(t):\n    return yaml.load(t, Loader=yaml.SafeLoader)\n"
    positional = "import yaml\ndef s(t):\n    return yaml.load(t, yaml.SafeLoader)\n"
    unsafe_kw = "import yaml\ndef s(t):\n    return yaml.load(t, Loader=yaml.Loader)\n"
    assert [s["call"] for s in execution_sinks(bare)] == ["yaml.load"]
    assert execution_sinks(kw) == []
    assert execution_sinks(positional) == []
    assert [s["call"] for s in execution_sinks(unsafe_kw)] == ["yaml.load"]


def test_safe_load_is_not_a_sink():
    assert execution_sinks("import yaml\ndef s(t):\n    return yaml.safe_load(t)\n") == []


def test_the_from_import_spelling_of_a_sink_is_resolved():
    """`from os import system` is the same call. A scanner that only matches the
    dotted spelling misses the one somebody wrote deliberately."""
    source = "from os import system\ndef s(x):\n    system(x)\n"
    assert [s["call"] for s in execution_sinks(source)] == ["os.system"]


def test_the_builtins_module_spelling_of_a_builtin_is_resolved():
    source = "from builtins import eval as ev\ndef s(x):\n    return ev(x)\n"
    assert [s["call"] for s in execution_sinks(source)] == ["builtins.eval"]


def test_a_project_function_that_merely_shares_a_builtin_name_is_not_flagged():
    """`mycompiler.compile` is not `compile`. Matching on the last segment of
    any import would report the name rather than the call, and a false alarm a
    reader cannot distinguish from a real one is the expensive kind."""
    source = "from mycompiler import compile\ndef s(x):\n    return compile(x)\n"
    assert execution_sinks(source) == []


def test_an_aliased_import_is_resolved():
    source = "import yaml as y\ndef s(t):\n    return y.load(t)\n"
    found = execution_sinks(source)
    assert [s["call"] for s in found] == ["yaml.load"]
    assert found[0]["spelled"] == "y.load"


def test_a_sink_reports_the_line_it_is_on():
    source = "def s(x):\n    y = 1\n    return eval(x)\n"
    assert execution_sinks(source)[0]["line"] == 3


def test_a_healthy_verifier_has_no_sinks():
    assert execution_sinks(HEALTHY_VERIFIER) == []


# --------------------------------------------------------------------------
# V3 -- through the probe
# --------------------------------------------------------------------------


def test_evaluator_probe_fires_on_a_planted_verifier():
    source = textwrap.dedent(
        """
        def score(submission, target):
            # The grader offers to run the thing it is grading.
            return float(eval(submission))
        """
    )
    result = VerifierStaticAnalysis().run(VerifierSourceEnv(source))
    assert result.status is ProbeStatus.DEFECT
    finding = result.findings[0]
    assert finding.defect is DefectClass.EVALUATOR_RCE
    assert finding.severity is Severity.CRITICAL
    assert [s["call"] for s in finding.evidence["sinks"]] == ["eval"]


def test_evaluator_probe_is_silent_on_a_healthy_verifier():
    result = VerifierStaticAnalysis().run(VerifierSourceEnv(HEALTHY_VERIFIER))
    assert result.status is ProbeStatus.PASS, result.findings


def test_evaluator_probe_declines_when_the_capability_is_withheld():
    result = VerifierStaticAnalysis().run(VerifierSourceEnv(HEALTHY_VERIFIER, declare=False))
    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert "VERIFIER_SOURCE" in (result.reason or "")


def test_a_shell_verifier_is_declined_not_passed():
    """Harbor grades with `tests/test.sh`. Unparseable is unexamined, and this
    probe adds no second parser to find out which -- reporting PASS would be a
    clean bill issued over a file nobody read."""
    result = VerifierStaticAnalysis().run(VerifierSourceEnv("#!/bin/sh\nexit 0\n"))
    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert "not parseable as Python" in (result.reason or "")


def test_one_verifier_shared_by_many_tasks_is_one_finding():
    """A suite with a hundred samples and one scorer has one defect, not a
    hundred. The card is read by a person."""
    source = "def score(s, t):\n    return float(eval(s))\n"
    result = VerifierStaticAnalysis().run(VerifierSourceEnv(source, n_tasks=25))
    assert len(result.findings) == 1
    assert result.findings[0].evidence["n_tasks_sharing_this_verifier"] == 25


def test_a_clean_result_says_what_it_does_not_prove():
    result = VerifierStaticAnalysis().run(VerifierSourceEnv(HEALTHY_VERIFIER))
    assert "not evidence of safety" in result.detail["asymmetry"]


# --------------------------------------------------------------------------
# Neither family may disturb what was already there
# --------------------------------------------------------------------------


@pytest.mark.parametrize("variant", sorted(CATALOG))
def test_neither_new_family_finds_anything_on_a_toy_fixture(variant):
    """The property that keeps the scored corpus where it was.

    Both families RUN here -- the fixture declares a posture and hands over its
    verifier's source, which is what keeps `healthy` at full coverage -- and
    neither may report. `test_detection_matches_ground_truth_exactly` would
    catch a finding on all twelve as well, but only as a set mismatch buried in
    a diff; this names the two families so a regression says which one moved.
    """
    results = {
        r.family: r
        for r in audit(build(variant)).results
        if r.family in ("sandbox_permissions", "evaluator_code_execution")
    }
    assert set(results) == {"sandbox_permissions", "evaluator_code_execution"}
    for family, result in results.items():
        assert result.status is ProbeStatus.PASS, (family, result.status, result.reason)
        assert not result.findings


def test_the_toy_fixture_hands_over_its_real_verifier_not_a_description():
    """If `verifier_source` returned prose about the verifier, the static scan
    would be reading this repository's opinion of `ToyEnv.verify` rather than
    `ToyEnv.verify`. Pinned because that substitution is invisible in a passing
    test suite."""
    source = build("healthy").verifier_source("t1")
    assert "def verify(" in source
    assert "LABEL_CREDIT" in source
    assert execution_sinks(source) == []


def test_the_inspect_corpus_scans_clean_and_still_scans():
    """`inspect_ai` is the one ecosystem that can feed family 11 today, and the
    reason the corpus numbers did not move is that all five of its environments
    are genuinely clean -- not that the probe declined on them. A test that only
    asserted the numbers held would pass equally well if the probe never ran."""
    pytest.importorskip("inspect_ai")
    from assay._inspect_corpus import build_inspect_environments
    from assay.adapters.inspect_ai_adapter import InspectAdapter

    for env_id, factory, _planted in build_inspect_environments(InspectAdapter):
        adapter = factory()
        assert adapter.manifest().has(Capability.VERIFIER_SOURCE), env_id
        result = VerifierStaticAnalysis().run(adapter)
        assert result.status is ProbeStatus.PASS, (env_id, result.status, result.findings)


def test_a_planted_inspect_scorer_is_caught_through_the_real_adapter():
    """The path that matters: a scorer written the way one actually is, read
    through `InspectAdapter`, with no hand-written source string in between."""
    pytest.importorskip("inspect_ai")
    from inspect_ai import Task as InspectTask
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
    from inspect_ai.solver import TaskState

    from assay.adapters.inspect_ai_adapter import InspectAdapter

    @scorer(metrics=[accuracy()])
    def arithmetic_by_eval():
        """The plausible version: 'the answer is an expression, so evaluate it'."""

        async def score(state: TaskState, target: Target) -> Score:
            submitted = eval(state.output.completion)  # noqa: S307
            return Score(value=CORRECT if submitted == eval(target.text) else INCORRECT)

        return score

    task = InspectTask(
        dataset=MemoryDataset([Sample(input="2+2", target="4", id="a")]),
        scorer=arithmetic_by_eval(),
    )
    result = VerifierStaticAnalysis().run(InspectAdapter(task, env_id="inspect/eval-scorer"))
    assert result.status is ProbeStatus.DEFECT
    assert result.findings[0].defect is DefectClass.EVALUATOR_RCE
    assert [s["call"] for s in result.findings[0].evidence["sinks"]] == ["eval", "eval"]


def test_the_two_new_families_are_registered():
    assert {"sandbox_permissions", "evaluator_code_execution"} <= set(families())


def test_every_fixture_unreachable_family_is_a_real_family():
    """The exclusion list is a claim about the fixtures. A stale entry in it
    silently excuses a family that no longer exists, or misspells one that
    does, and either way the 'every family fires' check stops checking."""
    assert set(FAMILIES_NOT_PLANTED_IN_FIXTURES) <= set(families())
    assert all(reason.strip() for reason in FAMILIES_NOT_PLANTED_IN_FIXTURES.values())
