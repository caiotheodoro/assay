"""Family 10 -- does the deployment grant more than the task needs.

BenchJack V8, "excessive permissions" (arXiv 2605.12673, Fig. 2), and the one
class `docs/COVERAGE.md` called "the clearest gap". Everything else in Assay is
a behavioural auditor of scoring: it drives the environment and watches what
comes back. V8 is not behavioural. It is a static property of a deployment, and
until this probe existed Assay read `network_mode` and `environment_mode` only
to *obey* them -- an auditor that faithfully reproduces a permission it should
have been objecting to.

The rule is comparative, never absolute. "Network is enabled" is not a finding;
"network is enabled and the environment declares no step that needs it" is. So
every check here needs two facts, a grant and a stated need, and fires only when
the need is declared and is `False`. An adapter that can state the grant but not
the need leaves the need `None` and the check is reported as *unmade* -- named
in `detail`, counted, and visible on the card.

That asymmetry is deliberate and it costs coverage. The alternative is to infer
the need from the instruction text, and a task whose setup script quietly pulls
a dataset it never mentions would then be reported as over-permissioned for
doing something entirely reasonable. `docs/COVERAGE.md` argues at length that a
probe reporting a defect on a healthy environment costs more than a probe that
declines, and this is the family where the temptation to guess is strongest.

The one absolute check is a writable verifier. A mount the agent can write that
covers the script grading it is not a permission that might be excessive
depending on the task -- it is V1's mechanism, sitting in the manifest where
anyone could have read it.
"""

from __future__ import annotations

import posixpath
from typing import Any

from ..adapter import EnvAdapter
from ..types import (
    Capability,
    DefectClass,
    Finding,
    MountSpec,
    SandboxPosture,
    DEFAULT_SEVERITY,
)
from .base import Probe, register

#: Spellings of "the superuser" that a deployment might use for `user`.
ROOT_NAMES = frozenset({"root", "0", "uid=0", "root:root", "0:0"})


def _covers(mount_target: str, verifier_path: str) -> bool:
    """Does a mount at `mount_target` contain, or sit inside, `verifier_path`.

    Both directions count. A writable `/work` mount covering `/work/tests` is
    the ordinary case; a writable mount of `/work/tests` itself is the same
    grant stated more precisely, and reporting only one of the two would let a
    deployment escape by being specific.

    Paths are normalised as POSIX because that is what a container spells, and
    compared segment-wise so `/workspace` does not read as a parent of
    `/work/tests`.
    """
    a = posixpath.normpath(mount_target or "/")
    b = posixpath.normpath(verifier_path or "/")
    if a == b:
        return True
    return b.startswith(a.rstrip("/") + "/") or a.startswith(b.rstrip("/") + "/")


def writable_verifier_mounts(posture: SandboxPosture) -> list[MountSpec]:
    """Mounts the agent can write that cover a path holding the verifier."""
    if not posture.verifier_paths:
        return []
    return [
        m
        for m in posture.mounts
        if not m.read_only
        and any(_covers(m.target, p) for p in posture.verifier_paths)
    ]


def excessive_grants(posture: SandboxPosture) -> tuple[list[dict[str, Any]], list[str]]:
    """(findings-worth of grants, checks that could not be made).

    Split out from the probe so the rule table can be exercised directly, with
    no adapter and no audit in the way. Every entry carries the `rule` that
    produced it and the `declared` grant it read, because a permissions finding
    a reader cannot check against the deployment's own manifest is an assertion,
    not evidence.
    """
    hits: list[dict[str, Any]] = []
    unchecked: list[str] = []

    # -- network -----------------------------------------------------------
    if posture.network_enabled is None:
        unchecked.append("network: the deployment declares no network setting")
    elif posture.network_required is None:
        unchecked.append(
            "network: granted, but the environment does not declare whether any "
            "step needs it, and it is not inferred from the instruction"
        )
    elif posture.network_enabled and not posture.network_required:
        hits.append(
            {
                "rule": "network_not_needed",
                "declared": {"network_enabled": True, "network_required": False},
                "note": "the task is granted network access and declares no step "
                "that uses it; an agent can reach a reference solution, an "
                "answer key, or a machine that will run one for it",
            }
        )

    # -- a verifier the agent can write ------------------------------------
    writable = writable_verifier_mounts(posture)
    if not posture.verifier_paths:
        unchecked.append(
            "verifier reachability: the deployment names no path holding the "
            "verifier, so no mount can be checked against it"
        )
    for mount in writable:
        hits.append(
            {
                "rule": "writable_verifier_mount",
                "declared": {
                    "source": mount.source,
                    "target": mount.target,
                    "read_only": False,
                },
                "verifier_paths": list(posture.verifier_paths),
                "note": "the agent is granted write access to a path holding the "
                "verifier it is graded by; the evaluator trusts a file its "
                "subject can edit",
            }
        )

    # -- writable root filesystem ------------------------------------------
    if posture.read_only_root is None:
        unchecked.append("root filesystem: the deployment declares no read-only setting")
    elif not posture.read_only_root:
        hits.append(
            {
                "rule": "writable_root_filesystem",
                "declared": {"read_only_root": False},
                "note": "the whole container filesystem is writable. A task needing "
                "a writable workspace can be given one as a mount; a writable root "
                "additionally lets the agent edit the interpreter, the shell and "
                "anything else the verifier will later run",
            }
        )

    # -- superuser ---------------------------------------------------------
    if posture.user is None:
        unchecked.append("user: the deployment does not expose the uid it runs as")
    elif posture.root_required is None:
        unchecked.append(
            "user: exposed, but the environment does not declare whether the task "
            "needs root"
        )
    elif posture.user.strip().lower() in ROOT_NAMES and not posture.root_required:
        hits.append(
            {
                "rule": "root_not_needed",
                "declared": {"user": posture.user, "root_required": False},
                "note": "the task runs as root and declares no step that needs it",
            }
        )

    return hits, unchecked


@register
class DeclaredPermissions(Probe):
    """Judge the manifest, not the behaviour.

    This is the only family here that reports without driving the environment
    at all, which is why it is also the only one that can run on an environment
    nothing can execute. It requires exactly one capability, and an adapter that
    withholds it gets NOT_APPLICABLE naming it -- there is no partial mode where
    the probe assumes a posture it was not handed.
    """

    family = "sandbox_permissions"
    name = "declared_permissions"
    requires = (Capability.SANDBOX_POSTURE,)

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        findings: list[Finding] = []
        detail: dict[str, Any] = {}
        empty: list[str] = []

        for task in adapter.manifest().tasks:
            posture = adapter.sandbox_posture(task.task_id)
            if posture.is_empty():
                # Declaring the capability and then handing back nothing is not
                # a clean bill. Recorded per task so a card reader can see the
                # difference between "checked, granted nothing extra" and
                # "there was nothing to check".
                empty.append(task.task_id)
                detail[task.task_id] = {
                    "declared_by": posture.declared_by,
                    "posture": "empty -- the adapter declared SANDBOX_POSTURE and "
                    "returned no grants to judge",
                }
                continue

            hits, unchecked = excessive_grants(posture)
            detail[task.task_id] = {
                "declared_by": posture.declared_by,
                "network_enabled": posture.network_enabled,
                "network_required": posture.network_required,
                "read_only_root": posture.read_only_root,
                "user": posture.user,
                "n_mounts": len(posture.mounts),
                "writable_mounts": [m.target for m in posture.mounts if not m.read_only],
                "verifier_paths": list(posture.verifier_paths),
                "n_excessive": len(hits),
                # As loud as the findings. A card that says "no excessive
                # permissions" while three of the four checks never ran is
                # making a claim it did not earn.
                "checks_not_made": unchecked,
            }
            for hit in hits:
                findings.append(
                    Finding(
                        defect=DefectClass.EXCESSIVE_PERMISSIONS,
                        severity=DEFAULT_SEVERITY[DefectClass.EXCESSIVE_PERMISSIONS],
                        task_id=task.task_id,
                        evidence={**hit, "declared_by": posture.declared_by},
                    )
                )

        if not detail:
            return self.na("environment declares no tasks to read a posture from")
        if len(empty) == len(detail):
            return self.na(
                "every task returned an empty posture, so no permission could be "
                f"compared against a need: {', '.join(sorted(empty))}",
                per_task=detail,
            )
        return self.defects(findings, per_task=detail)
