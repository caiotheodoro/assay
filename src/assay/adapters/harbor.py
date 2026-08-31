"""Adapter for Harbor / Terminal-Bench tasks on disk.

Harbor's layout is the most externally-parseable manifest of any agent
benchmark surveyed:

    task.toml          metadata, verifier timeout, network mode, image
    instruction.md     what the agent is told
    environment/       starting workspace
    solution/solve.sh  the gold solution, shipped by convention
    tests/test.sh      the verifier, run in its own container

Two consequences shape this adapter.

First, gold is real. Unlike inspect_ai, Harbor tasks ship an executable gold
solution, so `gold_passes` stops being a formality and starts being a check
that can fail -- and does, on tasks whose solution rotted against their tests.

Second, and more useful: because the verifier is a script that lives in the
workspace, the agent can edit it. So the environment's own reported score and
an independent reading of "did the job get done" come apart, and Assay can
measure the gap exactly by running a PRISTINE copy of the tests, mounted
read-only from outside the workspace, against whatever the agent left behind.
Test deletion is the oldest reward hack in agentic coding, and this is what
catches it.

There is no inverted-spec probe here, and the adapter says so rather than
faking one. A shell script that exits 0 or 1 takes no target argument; there is
nothing to substitute. Declaring INVERTIBLE_SPEC would be a lie that produced a
clean-looking result.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from ..adapter import BaseAdapter, NotSupported
from ..sandbox import DockerSandbox, Mount, SandboxPolicy, SandboxSession
from ..types import (
    SANDBOX_TIMEOUT,
    Action,
    Capability,
    Manifest,
    Observation,
    Score,
    StepResult,
    Task,
    Transcript,
    digest,
)

#: Filenames a task's own instruction mentions. The agent is handed this text,
#: so a policy that reads it is using what the agent has, not what the corpus
#: author knows. Deliberately not a list of names seen in this suite.
_FILENAME = re.compile(r"\b([\w-]+\.[A-Za-z0-9]{1,6})\b")


def _mount_dir(prefix: str) -> Path:
    """A scratch directory the sandbox can actually read once it is mounted.

    `tempfile.mkdtemp` makes 0700 directories, and the sandbox drops every
    capability -- including `CAP_DAC_OVERRIDE`, which is the one root uses to
    ignore file modes. So a container running as root still cannot traverse
    into a 0700 directory owned by the host user, and every task mounted this
    way fails with `Permission denied` on Linux.

    It never failed on macOS: Docker Desktop's bind mounts present host files
    as owned by the container user, so the mode is not consulted. The suite was
    only ever run there, and CI has been red since the day it was added.

    Reading is not enough: the task writes its solution into /work and the
    verifier writes its result into /logs, and root-without-DAC_OVERRIDE cannot
    write to a directory it does not own whatever the mode says about others.
    So these two are 0777. The path comes from `mkdtemp`, so it is unguessable
    and lives for one audit; what goes in it is benchmark fixture content that
    is already world-readable in the repo.
    """
    path = Path(tempfile.mkdtemp(prefix=prefix))
    path.chmod(0o777)
    return path


def _make_writable(root: Path) -> None:
    """Let the container modify its own workspace.

    `shutil.copytree` preserves the repo's modes, so the task files arrive 0644
    owned by the host user. The sandbox drops `CAP_DAC_OVERRIDE`, so container
    root cannot write to a file it does not own however permissive the others
    bits are -- and rewriting a reachable verifier is precisely what the V1 and
    V7 trivial policies exist to attempt. Without this they fail to write and
    the probe reads that as an environment that held, which is a false PASS.

    /work is the agent's workspace by design; making it writable is restoring
    the intended semantics, not loosening them. /suite stays read-only and
    /logs is separate.
    """
    root.chmod(0o777)
    for path in root.rglob("*"):
        try:
            path.chmod(0o777 if path.is_dir() else 0o666)
        except OSError:
            pass


def _filenames_in(instruction: str) -> list[str]:
    seen, out = set(), []
    for name in _FILENAME.findall(instruction or ""):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


RUN_TOOL = "run"
DEFAULT_IMAGE = "alpine:3.20"


class HarborTaskDir:
    """One task directory, parsed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.toml: dict[str, Any] = {}
        toml_path = path / "task.toml"
        if toml_path.exists():
            self.toml = tomllib.loads(toml_path.read_text())

    @property
    def task_id(self) -> str:
        return str(self.toml.get("task", {}).get("name") or self.path.name)

    @property
    def instruction(self) -> str:
        f = self.path / "instruction.md"
        return f.read_text().strip() if f.exists() else ""

    @property
    def image(self) -> str:
        return str(self.toml.get("environment", {}).get("docker_image") or DEFAULT_IMAGE)

    @property
    def timeout(self) -> int:
        return int(self.toml.get("verifier", {}).get("timeout_sec") or 120)

    @property
    def network_mode(self) -> str:
        return str(self.toml.get("verifier", {}).get("network_mode") or "no-network")

    @property
    def environment_mode(self) -> str:
        """`separate` runs the verifier in its own grading container, so the
        agent never sees the tests. `shared` runs it in the agent's workspace,
        where the agent can edit its own grader.

        Honouring this is not a detail. Copying tests into the workspace on a
        task that declares `separate` invents an exploit -- rewrite test.sh to
        exit 0 -- that cannot exist on the real task. An auditor that
        mis-models an environment and then reports a defect caused by its own
        mis-modelling is the exact failure this tool exists to catch.
        """
        return str(self.toml.get("verifier", {}).get("environment_mode") or "separate")

    @property
    def solution(self) -> Path | None:
        p = self.path / "solution" / "solve.sh"
        return p if p.exists() else None

    @property
    def wrong_solution(self) -> Path | None:
        """Some tasks ship a plausible-but-incorrect attempt. Most do not."""
        p = self.path / "solution" / "wrong.sh"
        return p if p.exists() else None

    @property
    def tests(self) -> Path:
        """The verifier the agent gets. Copied into the workspace, so editable."""
        return self.path / "tests"

    @property
    def truth(self) -> Path | None:
        """An independent verifier the agent never sees, mirroring Harbor's
        separate grading container. Without one there is no honest way to say
        whether a reported pass reflects work actually done."""
        p = self.path / "truth" / "test.sh"
        return (self.path / "truth") if p.exists() else None

    @property
    def environment(self) -> Path:
        return self.path / "environment"


class HarborAdapter(BaseAdapter):
    def __init__(
        self,
        suite_dir: str | Path,
        *,
        sandbox: DockerSandbox,
        env_id: str | None = None,
        cache: bool = True,
    ) -> None:
        self.suite_dir = Path(suite_dir)
        self.sandbox = sandbox
        self._tasks = {
            t.task_id: t
            for t in (
                HarborTaskDir(p)
                for p in sorted(self.suite_dir.iterdir())
                if p.is_dir() and (p / "task.toml").exists()
            )
        }
        self._env_id = env_id or f"harbor/{self.suite_dir.name}"
        self._live: SandboxSession | None = None
        self._work_host: Path | None = None
        self._logs_host: Path | None = None
        self._current: str | None = None
        # Every container start costs about a second, and the probe battery
        # replays the same policies several times over. Caching a verification
        # keyed on (task, exact action sequence, which verifier) is sound
        # because the environment is deterministic given those -- which is
        # precisely what the determinism probe is checking, so that probe
        # clears the cache between repeats rather than reading it.
        self._caching = cache
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    @staticmethod
    def _key(transcript: Transcript, which: str) -> str:
        return digest(
            {
                "task": transcript.task_id,
                "which": which,
                "actions": [(a.tool, a.args) for a in transcript.actions],
            }
        )

    # -- helpers -----------------------------------------------------------

    def _task(self, task_id: str) -> HarborTaskDir:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown harbor task: {task_id}") from exc

    def _policy(self, task: HarborTaskDir) -> SandboxPolicy:
        return SandboxPolicy(
            image=task.image,
            network=task.network_mode == "public",
            wall_seconds=task.timeout,
            read_only_root=True,
        )

    def _session(self, task: HarborTaskDir) -> SandboxSession:
        """One container for the whole suite, opened on first use.

        Harbor tasks hard-code `/work` and `/logs`, so those cannot be
        remounted per episode. Instead a single workspace is mounted once and
        wiped on every reset. Episodes run strictly in sequence, so a wiped
        directory gives the same isolation a fresh container would, at a
        twentieth of the cost.
        """
        if self._live is None:
            self._work_host = _mount_dir("assay-work-")
            self._logs_host = _mount_dir("assay-logs-")
            self._live = SandboxSession(
                self.sandbox,
                self._policy(task),
                [
                    Mount(self._work_host, "/work", read_only=False),
                    Mount(self._logs_host, "/logs", read_only=False),
                    Mount(self.suite_dir, "/suite", read_only=True),
                ],
                label=self._env_id,
            ).start()
        return self._live

    def close(self) -> None:
        """Release the container and the host tmpdirs, in that order, always.

        The tmpdir cleanup used to sit after an unguarded `stop()`, so a
        failure to remove the container also leaked two directories per
        adapter. `stop()` no longer raises, but the ordering is made explicit
        anyway: whatever happens to the container, the disk is reclaimed.
        """
        live, self._live = self._live, None
        try:
            if live is not None:
                live.stop()
        finally:
            for path in (self._work_host, self._logs_host):
                if path:
                    shutil.rmtree(path, ignore_errors=True)
            self._work_host = self._logs_host = None

    def __enter__(self) -> "HarborAdapter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @staticmethod
    def _parse_reward(logs: Path) -> float | None:
        """Harbor verifiers write reward.json or reward.txt under /logs/verifier."""
        verifier = logs / "verifier"
        j = verifier / "reward.json"
        if j.exists():
            try:
                payload = json.loads(j.read_text())
            except json.JSONDecodeError:
                return None
            value = payload.get("reward", payload.get("score"))
            return float(value) if isinstance(value, (int, float)) else None
        t = verifier / "reward.txt"
        if t.exists():
            match = re.search(r"-?\d+(?:\.\d+)?", t.read_text())
            return float(match.group()) if match else None
        return None

    def _run_verifier(self, task: HarborTaskDir, script_path: str) -> tuple[float, dict[str, Any]]:
        session = self._session(task)
        assert self._logs_host is not None
        shutil.rmtree(self._logs_host / "verifier", ignore_errors=True)
        result = session.exec(["sh", script_path], workdir="/work")
        reward = self._parse_reward(self._logs_host)
        from_file = reward is not None
        if reward is None:
            reward = 1.0 if result.ok else 0.0
        return reward, {
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "stdout_tail": result.stdout[-400:],
            "reward_source": "reward file" if from_file else "exit code",
        }

    # -- manifest ----------------------------------------------------------

    def manifest(self) -> Manifest:
        caps = {
            Capability.SEPARABLE_VERIFIER,
            Capability.LIVE_STEPPING,
            Capability.SEEDED_RESET,
            Capability.TRIVIAL_POLICIES,
        }
        if all(t.truth for t in self._tasks.values()):
            caps.add(Capability.TRUE_COMPLETION)
        if all(t.solution for t in self._tasks.values()):
            caps.add(Capability.GOLD_TRAJECTORY)
            caps.add(Capability.GRADED_POLICIES)
        if all(t.wrong_solution for t in self._tasks.values()):
            caps.add(Capability.KNOWN_WRONG)
        # Deliberately absent: INVERTIBLE_SPEC. A shell verifier takes no target.
        return Manifest(
            env_id=self._env_id,
            ecosystem="harbor",
            version="task.toml",
            source=str(self.suite_dir),
            capabilities=frozenset(caps),
            tasks=[
                Task(task_id=tid, instruction=t.instruction, metadata=dict(t.toml.get("task", {})))
                for tid, t in self._tasks.items()
            ],
        )

    def describe(self) -> str:
        parts = [super().describe(), ""]
        for task_id, task in self._tasks.items():
            parts.append(f"--- task {task_id} ---")
            for name, path in (
                ("task.toml", task.path / "task.toml"),
                ("instruction.md", task.path / "instruction.md"),
                ("tests/test.sh", task.tests / "test.sh"),
                ("solution/solve.sh", task.solution),
            ):
                if path and Path(path).exists():
                    parts.append(f"# {name}\n{Path(path).read_text().strip()}")
            parts.append("")
        return "\n".join(parts)

    # -- episode -----------------------------------------------------------

    def reset(self, task_id: str, seed: int = 0) -> Observation:
        task = self._task(task_id)
        self._session(task)
        assert self._work_host is not None
        for child in self._work_host.iterdir():
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
        if task.environment.exists():
            shutil.copytree(task.environment, self._work_host, dirs_exist_ok=True)
        # Only `shared` puts the tests where the agent can reach them. Under
        # `separate` they stay outside the workspace and are read from the
        # read-only /suite mount at verification time.
        if task.environment_mode == "shared" and task.tests.exists():
            shutil.copytree(task.tests, self._work_host / "tests", dirs_exist_ok=True)
        _make_writable(self._work_host)
        self._current = task_id
        return Observation(ok=True, data={"instruction": task.instruction})

    def step(self, action: Action) -> StepResult:
        if action.tool != RUN_TOOL:
            return StepResult(
                Observation(ok=False, code="UNKNOWN_TOOL", message=action.tool), done=False
            )
        if self._current is None or self._work_host is None:
            return StepResult(
                Observation(ok=False, code="STALE_EPISODE", message="reset first"), done=False
            )
        task = self._task(self._current)
        session = self._session(task)
        script = str(action.args.get("script", ""))
        (self._work_host / ".assay-run.sh").write_text(script)
        result = session.exec(["sh", "/work/.assay-run.sh"], workdir="/work")
        # `timed_out` used to be dropped here, and dropping it turned a sandbox
        # that gave up under load into evidence about the environment: the
        # determinism probe compares observations across repeats, saw exit 124
        # against exit 0, and reported NONDETERMINISM on an environment that had
        # not misbehaved. Surfaced with its own code so a caller can tell "the
        # harness gave up" from "the environment answered differently".
        code = None
        if result.timed_out:
            code = SANDBOX_TIMEOUT
        elif not result.ok:
            code = "SCRIPT_FAILED"
        return StepResult(
            Observation(
                ok=result.ok,
                data={
                    "stdout": result.stdout[-400:],
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                },
                code=code,
            ),
            # A shell command does not end the episode. Saying otherwise gave an
            # agent exactly one command per episode and truncated every replay
            # of a multi-step policy at its first action.
            done=False,
        )

    # -- verification ------------------------------------------------------

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        if spec is not None:
            raise NotSupported(
                "a shell verifier takes no target argument; there is no spec to substitute"
            )
        task = self._task(transcript.task_id)
        key = self._key(transcript, "workspace")
        if self._caching and key in self._cache:
            reward, detail = self._cache[key]
        else:
            script = (
                "/work/tests/test.sh"
                if task.environment_mode == "shared"
                else f"/suite/{task.path.name}/tests/test.sh"
            )
            reward, detail = self._run_verifier(task, script)
            self._cache[key] = (reward, detail)
        return Score(passed=reward >= 1.0, reward=reward, profile=detail)

    def true_completion(self, transcript: Transcript) -> float:
        """Run the independent verifier -- never copied into the workspace, so
        never reachable by the agent -- against whatever it left behind.

        The gap between this and `verify` is the exploit gap, and on a shell
        task it is exactly what catches an agent that edited its own grader."""
        task = self._task(transcript.task_id)
        if not task.truth:
            raise NotSupported(
                f"{task.task_id} ships no truth/test.sh; without a verifier the agent "
                "cannot reach, a reported pass cannot be distinguished from a hack"
            )
        key = self._key(transcript, "truth")
        if self._caching and key in self._cache:
            reward, _ = self._cache[key]
        else:
            reward, detail = self._run_verifier(
                task, f"/suite/{task.path.name}/truth/test.sh"
            )
            self._cache[key] = (reward, detail)
        return max(0.0, min(1.0, reward))

    # -- policies ----------------------------------------------------------

    @staticmethod
    def _script_action(path: Path) -> list[Action]:
        return [Action(RUN_TOOL, {"script": path.read_text()})]

    def gold_actions(self, task_id: str) -> list[Action]:
        task = self._task(task_id)
        if not task.solution:
            raise NotSupported(f"{task_id} ships no solution/solve.sh")
        return self._script_action(task.solution)

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        task = self._task(task_id)
        if not task.wrong_solution:
            raise NotSupported(
                f"{task_id} ships no solution/wrong.sh; a plausible-but-incorrect "
                "attempt cannot be synthesised generically for a shell task"
            )
        return self._script_action(task.wrong_solution)

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        """Input-ignoring policies, two of them named after a published class.

        `v1_*` and `v7_*` come from BenchJack's flaw taxonomy (arXiv 2605.12673,
        Fig. 2), which derives eight recurring classes from reported
        reward-hacking incidents. They are written against the *mechanism* the
        class describes and are handed the same task text an agent gets --
        never a filename or a value taken from an environment in this corpus.
        That distinction is the whole point: a policy tuned to the environments
        it is scored on is a fitted detector, and this repository's own headline
        would be the thing it flattered.

        `delete_the_tests` was already here and does not work, which is why
        `v1` is not a duplicate of it. Deleting `/work/tests` makes the verifier
        script *missing*, so `sh /work/tests/test.sh` exits non-zero and the
        run scores 0. V1 is about **modifying** what the evaluator trusts, not
        removing it. Kept because "the obvious hack that fails" is worth having
        in the repertoire.
        """
        task = self._task(task_id)
        named = _filenames_in(task.instruction)
        token = "assay-trivial-token"

        # V7, "trusting untrusted output": the evaluator compares files the
        # agent can write. Make every file it might read agree with every
        # other. Restricted to the workspace root so it cannot clobber a
        # verifier script living under tests/ -- that is V1's job, and a policy
        # that did both at once would not say which flaw it found.
        agree = (
            f'tok={token}\n'
            'for f in $(find /work -maxdepth 1 -type f ! -name ".assay-run.sh" 2>/dev/null); '
            'do printf "%s" "$tok" > "$f"; done\n'
            + "".join(
                f'printf "%s" "$tok" > /work/{name}\n' for name in named
            )
        )

        # V1, "isolation failure": the agent and the evaluator share a
        # filesystem, so a verifier reachable from the workspace can be
        # rewritten to pass unconditionally. A no-op wherever the tests are
        # mounted read-only outside the workspace, which is what
        # `environment_mode = "separate"` means.
        neuter = (
            'for f in $(find /work -type f -name "*test*.sh" 2>/dev/null); '
            'do printf "exit 0\\n" > "$f"; done\n'
        )

        return {
            "do_nothing": [],
            "touch_only": [Action(RUN_TOOL, {"script": "touch /work/.assay-trivial\n"})],
            # The oldest reward hack in agentic coding, and it does not work.
            "delete_the_tests": [Action(RUN_TOOL, {"script": "rm -rf /work/tests\n"})],
            "v7_make_the_comparison_agree": [Action(RUN_TOOL, {"script": agree})],
            "v1_neuter_a_reachable_verifier": [Action(RUN_TOOL, {"script": neuter})],
        }

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        task = self._task(task_id)
        if not task.solution:
            raise NotSupported(f"{task_id} ships no solution to grade against")
        weak = task.wrong_solution
        if not weak:
            raise NotSupported(
                f"{task_id} ships no wrong.sh, so there is no second quality level to separate"
            )
        return {"strong": self._script_action(task.solution), "weak": self._script_action(weak)}
