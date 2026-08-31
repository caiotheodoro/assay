"""Execution sandbox for untrusted environment code.

Assay's whole job is to run third-party environments -- gold solutions, verifier
scripts, adversarial policies -- written by people who are not us. That is a
consequential action, and it gets two things: containment, and a human.

Containment is Docker with the network off, the root filesystem read-only, and
caps on cpu, memory, pids, and wall clock. Note what that costs: an environment
whose setup pulls dependencies at run time will fail here. That is the correct
outcome, not a bug to work around -- an environment that needs the network to
score a trajectory cannot be audited reproducibly.

The human is an approval gate that fails closed, and there are exactly three
approvers.

`DenyAll` is what a bare `DockerSandbox()` gets. It refuses everything, so a
sandbox somebody forgot to configure executes nothing.

`PromptApprover` is what every shipped path resolves to. It prints the image,
the command, every mount, the network state and every resource cap *before* it
asks, because an approval given without seeing the request is not an approval.
With no terminal to ask at it refuses and says how to grant a standing approval
instead; it never approves on an absent human's behalf.

`AutoApprove` is that standing approval, and it has to be asked for out loud --
`assay audit --yes`, or `ASSAY_APPROVE_ALL=<reason>` in the environment for CI
and batch scripts. It carries a reason, and the reason reaches the Environment
Card, so a reader can see the audit ran unattended and on whose say-so.

`current_approver()` is where the three meet and the only place that decides.
Nothing else in this package hard-codes a standing approval of its own. That
sentence used to be false: `_harbor_corpus.py` built every Harbor environment
with `AutoApprove("assay corpus run")`, so the shipped `assay audit
harbor/...` path executed containers under an approval nobody granted at run
time, while the docs advertised a deny-by-default gate.

One thing gets approved here that Docker cannot contain. `InProcessRequest`
covers third-party code Assay runs inside its own interpreter -- inspect_ai
scorers, which are ordinary Python closures and cannot be handed to a container
without rebuilding the ecosystem's runtime inside the image. That is a real
hole in the containment story, it is smaller than the alternative, and it goes
through the same gate and is named on the card rather than going unmentioned.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar, Protocol, TextIO


class SandboxUnavailable(RuntimeError):
    """Docker is not installed or not running."""


class ApprovalDenied(RuntimeError):
    """The approver refused. Nothing was executed."""


#: Environment variable carrying a standing, unattended approval. The value is
#: the reason, because an approval nobody can account for later is the same as
#: no approval. A bare `1` is accepted and recorded as exactly what it is:
#: somebody set a flag and walked away.
APPROVE_ALL_ENV = "ASSAY_APPROVE_ALL"

_FALSEY = {"", "0", "false", "no", "off"}
_BARE_TRUE = {"1", "true", "yes", "on"}


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
class InProcessRequest:
    """Third-party code that will run in *this* interpreter, uncontained.

    There is no image, no `--cap-drop ALL` and no network namespace on this
    path: the code gets the auditor's filesystem, environment variables and
    network. It is a separate type from `ExecRequest` precisely so that an
    approver, a log line or a card can never mistake one for the other.
    """

    #: What is about to run, in one line.
    what: str
    #: Why it is not in a container, in a sentence a reader can argue with.
    why_not_sandboxed: str
    #: The specific third-party callables about to be invoked.
    callables: list[str] = field(default_factory=list)
    #: What saying yes exposes.
    risk: str = (
        "this code runs with the auditor's filesystem, environment variables and "
        "network access; none of the Docker containment applies to it"
    )


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def describe(request: "ExecRequest | InProcessRequest") -> list[str]:
    """Everything an approver has to see before it can honestly answer.

    One function, so the terminal prompt, the Environment Card and the exported
    trajectory cannot describe the same request differently.
    """
    if isinstance(request, InProcessRequest):
        lines = [
            "  UNCONTAINED  this runs inside the Assay process, not in a container",
            f"  what         {request.what}",
            f"  why          {request.why_not_sandboxed}",
            f"  risk         {request.risk}",
        ]
        if request.callables:
            lines.append(f"  code         {', '.join(request.callables)}")
        return lines

    p = request.policy
    lines = [
        f"  image        {p.image}",
        f"  command      {' '.join(request.command)}",
        f"  workdir      {request.workdir}",
        f"  network      {'ON (bridge)' if p.network else 'off (--network none)'}",
        "  capabilities all dropped (--cap-drop ALL, --security-opt no-new-privileges)",
        f"  limits       cpus={p.cpus} memory={p.memory} pids={p.pids} "
        f"wall={p.wall_seconds}s read_only_root={p.read_only_root}",
    ]
    if request.mounts:
        lines += [
            f"  mount        {m.source} -> {m.target} ({'ro' if m.read_only else 'rw'})"
            for m in request.mounts
        ]
    else:
        lines.append("  mount        none")
    return lines


def summarise(request: "ExecRequest | InProcessRequest") -> str:
    """One line for a table cell."""
    if isinstance(request, InProcessRequest):
        return request.what
    return (
        f"`{' '.join(request.command)}` in `{request.policy.image}`, network "
        f"{'ON' if request.policy.network else 'off'}"
    )


# --------------------------------------------------------------------------
# Approval
# --------------------------------------------------------------------------


class Approver(Protocol):
    def __call__(self, request: "ExecRequest | InProcessRequest") -> bool: ...


@dataclass(frozen=True)
class DenyAll:
    """What a `DockerSandbox()` with no approver gets. Refuses everything.

    This is not the approver the shipped CLI resolves to -- `current_approver()`
    is -- and saying otherwise was the bug this file used to have. It is the
    floor underneath every caller who forgot to pass one.
    """

    label: ClassVar[str] = "DenyAll"
    interactive: ClassVar[bool] = False
    reason: ClassVar[str] = "no approver was configured, so nothing was allowed to run"

    def __call__(self, request: "ExecRequest | InProcessRequest") -> bool:
        return False


@dataclass(frozen=True)
class AutoApprove:
    """Explicit standing approval, for CI, batch scripts and tests.

    Carrying a reason is not decoration: an approval nobody can account for
    later is the same as no approval. The reason is carried through to the
    Environment Card, where it is what tells a reader the audit ran unattended.
    """

    reason: str

    interactive: ClassVar[bool] = False

    @property
    def label(self) -> str:
        return f"AutoApprove({self.reason!r})"

    def __call__(self, request: "ExecRequest | InProcessRequest") -> bool:
        return True


#: Printed instead of a prompt when there is nobody to prompt. It names both
#: escapes, because a gate that blocks without saying how to proceed gets
#: routed around rather than answered.
NO_TERMINAL = (
    "refused: there is no terminal here to ask at, and Assay does not approve on "
    "an absent human's behalf. To run unattended, say so explicitly -- `assay "
    f'audit --yes`, or {APPROVE_ALL_ENV}="<reason>" in the environment for CI and '
    "batch scripts. Either one is recorded on the Environment Card as an "
    "unattended run."
)


@dataclass
class PromptApprover:
    """Show the request in full, then ask a human.

    Three answers: `y` for this one request, `n` (the default, and what an
    empty line means) to refuse, `a` to grant a standing approval for the rest
    of this process. `a` exists because one audit starts a dozen containers and
    a gate that asks twelve times gets answered by holding down the y key,
    which is not consent either.

    The standing answer lives on the instance, so it lasts exactly as long as
    the process that was asked and never leaks into another run.

    This class existed once before and was deleted in slice 22e as dead code --
    correctly, at the time: it was never constructed and never wired to a flag.
    It is back, and it is now what `current_approver()` returns by default.
    """

    stream: TextIO | None = None
    #: Injected by tests. Real runs read from the terminal.
    reader: Callable[[str], str] | None = None
    #: Set by answering `a`.
    standing: bool = False

    label: ClassVar[str] = "PromptApprover"
    interactive: ClassVar[bool] = True
    reason: ClassVar[str] = "a human was shown the request and answered at the time"

    def can_ask(self) -> bool:
        """Whether there is anybody to ask. Checked before anything is built."""
        if self.reader is not None:
            return True
        try:
            return bool(sys.stdin is not None and sys.stdin.isatty())
        except (AttributeError, OSError, ValueError):
            return False

    def __call__(self, request: "ExecRequest | InProcessRequest") -> bool:
        if self.standing:
            return True
        out = self.stream or sys.stderr
        print("", file=out)
        print("assay is about to run untrusted third-party code:", file=out)
        for line in describe(request):
            print(line, file=out)
        if not self.can_ask():
            print(f"  {NO_TERMINAL}", file=out, flush=True)
            return False
        # The question goes to the same stream as the description, flushed,
        # rather than riding along as `input()`'s prompt argument. `input()`
        # writes its prompt to stdout, so a caller that had redirected stdout
        # got a process that sat waiting on an answer to a question it had
        # never displayed -- a gate that hangs silently is worse than one that
        # refuses loudly.
        question = "  run it? [y]es / [N]o / yes to [a]ll: "
        print(question, file=out, end="", flush=True)
        try:
            raw = self.reader(question) if self.reader is not None else input()
            answer = raw.strip().lower()
        except (EOFError, KeyboardInterrupt, OSError):
            print("\n  refused: no answer given, so nothing ran", file=out, flush=True)
            return False
        print("", file=out, flush=True)
        if answer in {"a", "all"}:
            self.standing = True
            return True
        return answer in {"y", "yes"}


def approver_record(approver: Approver) -> dict[str, Any]:
    """How an approver describes itself on a card or in a trajectory."""
    return {
        "approver": str(getattr(approver, "label", type(approver).__name__)),
        "interactive": bool(getattr(approver, "interactive", False)),
        "reason": str(getattr(approver, "reason", "")),
    }


_PROCESS_APPROVER: Approver | None = None
_PROMPT: PromptApprover | None = None


def set_approver(approver: Approver | None) -> None:
    """Fix the approver for this process; `None` restores normal resolution.

    The CLI calls this for `--yes`. Tests call it to grant themselves the
    standing approval CI has, and to take it away again when what they are
    testing *is* the gate.
    """
    global _PROCESS_APPROVER, _PROMPT
    _PROCESS_APPROVER = approver
    _PROMPT = None


def approver_from_environment() -> AutoApprove | None:
    """The standing approval a CI job or a batch script leaves in the env."""
    raw = os.environ.get(APPROVE_ALL_ENV, "").strip()
    if raw.lower() in _FALSEY:
        return None
    said = (
        "no reason given" if raw.lower() in _BARE_TRUE else raw
    )
    return AutoApprove(f"unattended, {APPROVE_ALL_ENV} in the environment: {said}")


def current_approver() -> Approver:
    """The approver every shipped path goes through.

    Resolution order, with no fourth branch: whatever `set_approver` was told
    (which is how `--yes` arrives), then a standing approval in the
    environment, then a human at a terminal. With none of those,
    `PromptApprover` finds nobody to ask and refuses.

    The prompt approver is cached so that one `a` answer covers a whole audit
    rather than the first container only.
    """
    global _PROMPT
    if _PROCESS_APPROVER is not None:
        return _PROCESS_APPROVER
    from_env = approver_from_environment()
    if from_env is not None:
        return from_env
    if _PROMPT is None:
        _PROMPT = PromptApprover()
    return _PROMPT


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
        #: Every decision, granted or refused, in the order they were made.
        #: `approvals` holds only what was allowed to run; a card that showed
        #: only those would be a record of the gate opening and never of it
        #: holding, which is the half worth reading.
        self.decisions: list[dict[str, Any]] = []

    def decide(self, request: "ExecRequest | InProcessRequest") -> bool:
        """Put one request to the approver and write down what came back."""
        granted = bool(self.approver(request))
        self.decisions.append(
            {
                **approver_record(self.approver),
                "granted": granted,
                "contained": isinstance(request, ExecRequest),
                "what": summarise(request),
                "detail": describe(request),
            }
        )
        return granted

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
        if not self.decide(request):
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
        if not self.sandbox.decide(request):
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

    #: `docker rm -f` is SIGKILL, not SIGTERM -- there is no grace period to
    #: wait out. If it has not returned in this long the daemon is wedged, and
    #: waiting longer converts a leaked container into a hung test run.
    STOP_TIMEOUT = 15

    def stop(self) -> None:
        """Remove the container. Never raises, never blocks teardown.

        This used to be a 60-second `subprocess.run(..., capture_output=True)`
        with `TimeoutExpired` uncaught, which on a slow daemon meant a full
        minute of total silence and then an exception raised out of a fixture
        finaliser -- a test suite that finished its last test and never printed
        a summary line. Teardown that can hang is worse than teardown that can
        fail, because the failure at least says something.

        `container_id` is cleared *before* the call on purpose. If removal
        fails the container survives, still carrying its `assay-session` and
        `assay-pid` labels, so `assay reap` can find it. A leak that is
        labelled is recoverable; a leak this object still believes it owns is
        not.
        """
        cid, self.container_id = self.container_id, None
        if not cid:
            return
        try:
            subprocess.run(
                ["docker", "rm", "-f", "-v", cid],
                capture_output=True,
                timeout=self.STOP_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            # Deliberately swallowed. The container is now a labelled orphan
            # and `assay reap` is exactly the tool for it.
            pass

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

