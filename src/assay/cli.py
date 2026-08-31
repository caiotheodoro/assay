"""Command line entry point.

`assay audit` runs third-party code, so it asks first. On a terminal you are
shown the image, the command, every mount, the network state and every resource
cap, and you answer. With no terminal and no explicit standing approval it
refuses and exits 3 -- it does not approve on an absent human's behalf.

Exit codes: 0 clean verdict, 1 any other verdict, 2 bad usage, 3 nothing ran
because nothing was approved.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import audit
from .adapter import close_adapter
from .corpus import entries
from .fixtures import CATALOG, build
from .probes import all_probes


def _selftest(args) -> int:
    failures = []
    for variant, planted in CATALOG.items():
        detected = audit(build(variant)).detected
        if detected != planted:
            failures.append((variant, sorted(d.value for d in planted ^ detected)))
    fired = {
        r.family
        for variant in CATALOG
        for r in audit(build(variant)).results
        if r.findings
    }
    never = sorted({p.family for p in all_probes()} - fired - {"difficulty_band"})
    for variant, diff in failures:
        print(f"MISMATCH {variant}: {diff}", file=sys.stderr)
    if never:
        print(f"NEVER FIRED: {never}", file=sys.stderr)
    if failures or never:
        return 1
    print(f"selftest ok: {len(CATALOG)} fixtures, every family fires")
    return 0


def _approval_summary(report) -> list[str]:
    """One line to stderr saying who let this run, so it is visible without
    writing a card. On stderr and not stdout so `--json` stays pipeable."""
    approvals = list(getattr(report, "approvals", []) or [])
    if not approvals:
        return []
    granted = [a for a in approvals if a.get("granted")]
    refused = len(approvals) - len(granted)
    who = ", ".join(sorted({a["approver"] for a in approvals}))
    if not granted:
        return [
            f"approval: {refused} request(s) put to {who}, none granted — "
            "nothing was executed"
        ]
    unattended = " — ran UNATTENDED" if report.ran_unattended else ""
    outside = sum(1 for a in granted if not a.get("contained"))
    note = f", {outside} of them outside the sandbox" if outside else ""
    return [
        f"approval: {len(granted)} granted, {refused} refused by {who}{note}{unattended}"
    ]


#: Printed instead of running anything when nobody can be asked. Exit code 3,
#: distinct from 2 (bad usage) and 1 (a non-clean verdict), because "the gate
#: held" and "the environment is defective" are not the same answer.
NO_APPROVER = """\
assay audit executes third-party code -- gold solutions, verifier scripts,
adversarial policies -- and it needs approval before it does. There is no
terminal here to ask at, so nothing has been executed.

Run it from a terminal and you will be shown the image, the command, every
mount, the network state and every resource cap before being asked.

To run unattended, say so explicitly:

  assay audit {env} --yes
  ASSAY_APPROVE_ALL="nightly corpus run" assay audit {env}

Either one is recorded on the Environment Card, so a reader can see the audit
ran without a human in the loop."""


def _audit(args) -> int:
    from .sandbox import AutoApprove, PromptApprover, current_approver, set_approver

    if args.yes:
        set_approver(AutoApprove("--yes on the assay command line"))
    # Asked before the corpus is even built. A gate that only fires on the
    # first container start would have already unpacked a fixture tree and
    # opened a Docker session before finding out nobody was there to ask.
    approver = current_approver()
    if isinstance(approver, PromptApprover) and not approver.can_ask():
        print(NO_APPROVER.format(env=args.env), file=sys.stderr)
        return 3

    found = [e for e in entries() if e[0] == args.env]
    if not found:
        print(f"unknown environment: {args.env}", file=sys.stderr)
        print("available:", file=sys.stderr)
        for env_id, _, _ in entries():
            print(f"  {env_id}", file=sys.stderr)
        return 2
    env_id, factory, _ = found[0]
    adapter = factory()
    try:
        report = audit(adapter, {"challenger_passes": args.passes})
    finally:
        close_adapter(adapter)

    for line in _approval_summary(report):
        print(line, file=sys.stderr)

    if args.card:
        from .card import to_html, to_markdown
        from pathlib import Path

        path = Path(args.card)
        render = to_html if path.suffix == ".html" else to_markdown
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(report, signed_by=args.signed_by))
        print(f"wrote {path}")

    if args.json:
        print(report.to_json())
    else:
        print(f"{report.env_id}  [{report.ecosystem}]  verdict: {report.verdict}")
        print(f"coverage: {report.coverage}")
        for finding in report.findings:
            print(f"  {finding.summary()}")
        for result in report.results:
            if result.reason:
                print(f"  - {result.probe}: {result.status.value} ({result.reason})")
    return report.exit_code


def _list(args) -> int:
    for env_id, _, planted in entries():
        print(f"{env_id:34} {sorted(d.value for d in planted) or '-'}")
    return 0


def _reap(args) -> int:
    import subprocess

    from .sandbox import (
        docker_available,
        orphaned_sessions,
        session_containers,
        unlabelled_sessions,
    )

    # "none found" and "could not look" are different answers, and printing the
    # first for the second is the failure this tool exists to flag in
    # environments. Without a daemon `session_containers()` returns an empty
    # list, which read as a clean bill of health.
    if not docker_available():
        print("cannot check: docker is not installed or the daemon is not running")
        return 1

    rows = session_containers()
    if not rows:
        print("no assay sandbox containers running")
        return 0
    for container_id, label, pid, live in rows:
        state = "live" if live else "ORPHANED"
        if pid is None:
            state = "unknown pid"
        print(f"  {container_id}  {label:26} pid={pid}  {state}")

    targets = orphaned_sessions()
    if args.all:
        targets = targets + unlabelled_sessions()
    if not targets:
        print("nothing to remove (use --all to include containers with no recorded pid)")
        return 0
    if args.dry_run:
        print(f"{len(targets)} container(s) would be removed")
        return 1
    for container_id, _ in targets:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, timeout=60)
    print(f"removed {len(targets)} container(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assay", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("selftest", help="verify every probe fires on a known-defective fixture")
    p.set_defaults(func=_selftest)

    p = sub.add_parser("audit", help="audit one environment from the corpus")
    p.add_argument("env")
    p.add_argument("--json", action="store_true")
    p.add_argument("--card", metavar="PATH", help="write an Environment Card (.md or .html)")
    p.add_argument("--signed-by", metavar="NAME", help="record a human reviewer on the card")
    p.add_argument(
        "--yes", "-y", action="store_true",
        help="grant a standing approval for everything this audit executes instead "
             "of being asked for each. This is the escape for CI and scripts, and "
             "it is not free: the Environment Card records that the audit ran "
             "unattended and on whose say-so. ASSAY_APPROVE_ALL=\"<reason>\" in the "
             "environment does the same thing for a process you cannot pass flags to. "
             "Without either, and with no terminal to ask at, assay audit refuses and "
             "exits 3 rather than running anything.",
    )
    p.add_argument(
        "--passes", type=int, default=1, metavar="K",
        help="attack each task K times and report the hit rate. One pass turns a "
             "stochastic attacker into a coin flip reported as a measurement: a PASS "
             "may be a run that happened not to find the exploit. The finding fires "
             "if any pass crosses the threshold; the rate is reported beside it.",
    )
    p.set_defaults(func=_audit)

    p = sub.add_parser("list", help="list the audited corpus and its planted defects")
    p.set_defaults(func=_list)

    p = sub.add_parser(
        "reap", help="remove sandbox containers left behind by a killed or crashed run"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--all", action="store_true", help="also remove containers with no recorded pid"
    )
    p.set_defaults(func=_reap)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
