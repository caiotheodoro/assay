"""Execution sandbox for untrusted environment code.

Assay's whole job is to run third-party environments -- gold solutions, verifier
scripts, adversarial policies -- written by people who are not us. That is a
consequential action, and it gets two things: containment, and a human.

Containment is Docker with the network off, the root filesystem read-only, and
caps on cpu, memory, pids, and wall clock. Note what that costs: an environment
whose setup pulls dependencies at run time will fail here. That is the correct
outcome, not a bug to work around -- an environment that needs the network to
score a trajectory cannot be audited reproducibly.

The human is an approval gate that fails closed. Nothing executes until an
approver says so. `AutoApprove` exists for tests and CI and has to be passed
explicitly, so approval is always a decision somebody made.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


class SandboxUnavailable(RuntimeError):
    """Docker is not installed or not running."""


class ApprovalDenied(RuntimeError):
    """The approver refused. Nothing was executed."""


# --------------------------------------------------------------------------
# Approval
# --------------------------------------------------------------------------


class Approver(Protocol):
    def __call__(self, request: "ExecRequest") -> bool: ...


@dataclass(frozen=True)
class DenyAll:
    """The default. An unattended Assay executes nothing."""

    def __call__(self, request: "ExecRequest") -> bool:
        return False


@dataclass(frozen=True)
class AutoApprove:
    """Explicit standing approval, for CI and tests.

    Carrying a reason is not decoration: an approval nobody can account for
    later is the same as no approval.
    """

    reason: str

    def __call__(self, request: "ExecRequest") -> bool:
        return True


@dataclass(frozen=True)
class PromptApprover:
    """Ask a human on the terminal, once per distinct request."""

    def __call__(self, request: "ExecRequest") -> bool:
        print("\n--- Assay wants to execute untrusted environment code ---")
        print(f"  image   : {request.policy.image}")
        print(f"  command : {' '.join(request.command)}")
        print(f"  mounts  : {[str(m.source) for m in request.mounts]}")
        print(f"  network : {'ON' if request.policy.network else 'off'}")
        print(f"  limits  : {request.policy.cpus} cpu, {request.policy.memory}, "
              f"{request.policy.pids} pids, {request.policy.wall_seconds}s")
        return input("approve? [y/N] ").strip().lower() in {"y", "yes"}


# --------------------------------------------------------------------------
# Policy and requests
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Mount:
    source: Path
    target: str
    read_only: bool = True


@dataclass(frozen=True)
class SandboxPolicy:
    image: str
    network: bool = False
    cpus: float = 1.0
    memory: str = "512m"
    pids: int = 128
    wall_seconds: int = 120
    read_only_root: bool = True
    #: Writable scratch, so a read-only root does not break ordinary work.
    tmpfs: str = "/tmp"


@dataclass(frozen=True)
class ExecRequest:
    policy: SandboxPolicy
    command: list[str]
    mounts: list[Mount] = field(default_factory=list)
    workdir: str = "/work"


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                timeout=10,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


class DockerSandbox:
    def __init__(self, approver: Approver | None = None) -> None:
        self.approver: Approver = approver or DenyAll()
        self.approvals: list[ExecRequest] = []

    def _argv(self, request: ExecRequest) -> list[str]:
        p = request.policy
        argv = [
            "docker", "run", "--rm",
            "--network", "bridge" if p.network else "none",
            "--cpus", str(p.cpus),
            "--memory", p.memory,
            "--pids-limit", str(p.pids),
            "--workdir", request.workdir,
            # Drop every capability; nothing here needs one.
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
        ]
        if p.read_only_root:
            argv += ["--read-only", "--tmpfs", f"{p.tmpfs}:rw,exec,size=64m"]
        for mount in request.mounts:
            mode = "ro" if mount.read_only else "rw"
            argv += ["-v", f"{mount.source.resolve()}:{mount.target}:{mode}"]
        argv += [p.image, *request.command]
        return argv

    def run(self, request: ExecRequest) -> SandboxResult:
        if not docker_available():
            raise SandboxUnavailable("docker is not installed or the daemon is not running")
        if not self.approver(request):
            raise ApprovalDenied(
                f"execution of {' '.join(request.command)!r} in {request.policy.image} "
                "was not approved; nothing ran"
            )
        self.approvals.append(request)
        try:
            proc = subprocess.run(
                self._argv(request),
                capture_output=True,
                text=True,
                timeout=request.policy.wall_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                exit_code=124,
                stdout=(exc.stdout or b"").decode(errors="replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or ""),
                stderr="wall-clock limit exceeded",
                timed_out=True,
            )
        return SandboxResult(proc.returncode, proc.stdout, proc.stderr)


# --------------------------------------------------------------------------
# Persistent sessions
# --------------------------------------------------------------------------


class SandboxSession:
    """A container held open across many commands.

    Starting a container costs about four seconds on Docker Desktop. A full
    probe battery replays a dozen policies, so paying that per command puts the
    audit into the minutes and makes the reproduction guide a worse promise.
    `docker exec` into a container that is already running costs roughly a
    fifth of a second.

    Isolation is unchanged -- same network, capability, filesystem, and
    resource policy, applied once at creation. What is traded is isolation
    *between episodes inside one session*: they share a filesystem namespace,
    separated by directory rather than by container. Each episode gets its own
    subdirectory under the session root and runs with that as its working
    directory. For policies Assay itself constructs this is safe; a session is
    never shared across two different environments under audit.
    """

    def __init__(
        self,
        sandbox: "DockerSandbox",
        policy: SandboxPolicy,
        mounts: list[Mount],
        *,
        label: str = "assay",
    ) -> None:
        self.sandbox = sandbox
        self.policy = policy
        self.mounts = mounts
        self.label = label
        self.container_id: str | None = None
        self.exec_count = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "SandboxSession":
        if not docker_available():
            raise SandboxUnavailable("docker is not installed or the daemon is not running")
        request = ExecRequest(
            policy=self.policy,
            command=["sh", "-c", "while :; do sleep 3600; done"],
            mounts=self.mounts,
        )
        if not self.sandbox.approver(request):
            raise ApprovalDenied(
                f"opening a sandbox session in {self.policy.image} was not approved; "
                "nothing ran"
            )
        self.sandbox.approvals.append(request)

        argv = self.sandbox._argv(request)
        # `--rm` cannot be combined with detached reuse; drop it and remove
        # explicitly in stop(), so a crash never leaves a container behind
        # silently -- it leaves one named for this label.
        argv = [a for a in argv if a != "--rm"]
        argv.insert(2, "-d")
        argv.insert(3, "--label")
        argv.insert(4, f"assay-session={self.label}")
        # The creating pid, so a later reap can tell a live session from a
        # container left behind by a process that is gone.
        argv.insert(5, "--label")
        argv.insert(6, f"assay-pid={os.getpid()}")
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise SandboxUnavailable(f"could not start session container: {proc.stderr.strip()}")
        self.container_id = proc.stdout.strip()
        return self

    def stop(self) -> None:
        if self.container_id:
            subprocess.run(
                ["docker", "rm", "-f", self.container_id],
                capture_output=True,
                timeout=60,
            )
            self.container_id = None

    def __enter__(self) -> "SandboxSession":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- execution ---------------------------------------------------------

    def exec(self, command: list[str], workdir: str = "/work") -> SandboxResult:
        if not self.container_id:
            raise SandboxUnavailable("session is not running; call start() first")
        self.exec_count += 1
        try:
            proc = subprocess.run(
                ["docker", "exec", "--workdir", workdir, self.container_id, *command],
                capture_output=True,
                text=True,
                timeout=self.policy.wall_seconds,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(124, "", "wall-clock limit exceeded", timed_out=True)
        return SandboxResult(proc.returncode, proc.stdout, proc.stderr)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def session_containers() -> list[tuple[str, str, int | None, bool]]:
    """Every Assay session container: (id, label, creating pid, still live)."""
    if not docker_available():
        return []
    proc = subprocess.run(
        [
            "docker", "ps", "--filter", "label=assay-session",
            # .Labels is a comma-joined string in ps templates, not a map --
            # `index` on it silently yields nothing and every container
            # disappears from the listing.
            "--format", '{{.ID}}\t{{.Label "assay-session"}}\t{{.Label "assay-pid"}}',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    rows = []
    for line in proc.stdout.strip().splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        container_id = parts[0]
        label = parts[1] if len(parts) > 1 else ""
        pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        # No pid label means the container predates pid labelling. Unknown, so
        # treated as live: reaping something that might be in use is worse than
        # leaving it for an explicit --all.
        live = _pid_alive(pid) if pid is not None else True
        rows.append((container_id, label, pid, live))
    return rows


def orphaned_sessions() -> list[tuple[str, str]]:
    """Containers whose creating process is gone.

    A session is removed in stop(), but a killed or crashed process never gets
    there. Liveness is decided by whether the creating pid still exists -- an
    earlier version reaped by label alone, which would have torn down a running
    audit to tidy up after a dead one.
    """
    return [
        (container_id, label)
        for container_id, label, _pid, live in session_containers()
        if not live
    ]


def unlabelled_sessions() -> list[tuple[str, str]]:
    """Session containers with no creating pid recorded, so liveness is
    unknown. Removed only when explicitly asked for."""
    return [
        (container_id, label)
        for container_id, label, pid, _live in session_containers()
        if pid is None
    ]


def reap_sessions() -> int:
    """Remove every orphaned session container. Returns how many."""
    orphans = orphaned_sessions()
    for container_id, _ in orphans:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, timeout=60)
    return len(orphans)
