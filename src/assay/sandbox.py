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
