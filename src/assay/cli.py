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
from pathlib import Path

from . import audit
from .adapter import close_adapter
from .corpus import entries
from .fixtures import CATALOG, build
from .probes import FAMILIES_NOT_PLANTED_IN_FIXTURES, all_probes


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
    never = sorted(
        {p.family for p in all_probes()} - fired - set(FAMILIES_NOT_PLANTED_IN_FIXTURES)
    )
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


def _auditor_client(args):
    """The backend the Auditor asks, or None to let it choose.

    `--auditor-model` exists because the default order tries ollama first, and
    `results/semantic_gate.json` measures qwen3:8b at 0 of 1 on the one job the
    Auditor has. A flag that silently selects the backend the repo's own
    measurement says cannot do the task is a flag that reports a capability
    nobody has.
    """
    name = getattr(args, "auditor_model", None)
    if not name:
        return None
    from .llm import ClaudeCLIClient, OllamaClient

    return ClaudeCLIClient() if name == "claude" else OllamaClient(name)


def _build_challenger(args):
    """The Challenger the audit runs with, or None for the scripted default.

    Kept out of `_audit` so the import of a model backend only happens when a
    model was actually asked for -- `assay audit` with no flags must not need
    ollama installed, or reachable, or anything at all beyond python.
    """
    choice = getattr(args, "challenger", "scripted")
    if choice == "scripted":
        return None
    from .challenger import PolicySynthesisChallenger, PromptedChallenger
    from .challenger.scripted import ScriptedChallenger
    from .challenger.composite import CompositeChallenger
    from .llm import ClaudeCLIClient, OllamaClient

    kind, _, backend = choice.partition("-")
    if not backend:  # `ollama` / `claude` keep their original meaning
        kind, backend = "prompted", choice
    client = (
        ClaudeCLIClient() if backend == "claude" else OllamaClient(args.challenger_model)
    )
    # Scripted always runs first. A better attacker is not a superset of a
    # worse one -- see `challenger/composite.py` -- so the model arm is added
    # to the fixed repertoire rather than swapped in for it.
    model_arm = (
        PolicySynthesisChallenger(client)
        if kind == "synthesis"
        else PromptedChallenger(client)
    )
    return CompositeChallenger([ScriptedChallenger(), model_arm])


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

    # An environment the reader wrote, audited by path. The README's lead user
    # is "a researcher about to spend a training run on an environment they did
    # not write" -- and until this existed, `assay audit` took only corpus ids,
    # so the one thing that user actually wants to do was reachable from the
    # hosted Space and from Python and not from the tool.
    submitted = Path(args.env)
    if submitted.suffix in {".json", ".yaml", ".yml"} or submitted.exists():
        if not submitted.exists():
            print(f"no such spec file: {submitted}", file=sys.stderr)
            return 2
        from .adapters.spec import build as build_spec

        try:
            adapter = build_spec(submitted.read_text())
        except Exception as exc:  # noqa: BLE001 -- a bad spec is a user error
            print(f"could not read {submitted} as an environment spec:", file=sys.stderr)
            print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
            print(
                "\nA spec is JSON or YAML with `env_id` and a non-empty `tasks` list; "
                "see docs/REPRODUCTION.md and space/examples.json for seven worked ones.",
                file=sys.stderr,
            )
            return 2
        factory = None
    else:
        found = [e for e in entries() if e[0] == args.env]
        if not found:
            print(f"unknown environment: {args.env}", file=sys.stderr)
            print(
                "pass a corpus id, or a path to your own environment spec "
                "(.json/.yaml).",
                file=sys.stderr,
            )
            print("available:", file=sys.stderr)
            for env_id, _, _ in entries():
                print(f"  {env_id}", file=sys.stderr)
            return 2
        env_id, factory, _ = found[0]
        adapter = factory()
    ctx = {"challenger_passes": args.passes}
    auditor = None
    try:
        challenger = _build_challenger(args)
        if challenger is not None:
            ctx["challenger"] = challenger
        if args.auditor:
            from .auditor import Auditor

            auditor = Auditor(_auditor_client(args))
            report = auditor.audit(adapter, ctx)
        else:
            report = audit(adapter, ctx)
    finally:
        close_adapter(adapter)

    for line in _approval_summary(report):
        print(line, file=sys.stderr)

    # Report what the Auditor did even when it did nothing. A run that leaves
    # no trace is indistinguishable from one that never happened, which is the
    # failure mode this tool exists to find in other people's environments.
    for decision in auditor.decisions if auditor else []:
        asked = decision["consulted"] or "no backend"
        print(
            f"auditor: asked {asked} -> {decision['outcome']}: {decision['why']}",
            file=sys.stderr,
        )
        if decision.get("model_said") and decision["outcome"] == "withheld":
            print(
                f"auditor: the model's own label was {decision['model_said']!r}; "
                "the verdict follows the conjunction of label and evidence, "
                "not the label",
                file=sys.stderr,
            )
    if auditor and not auditor.decisions:
        print(
            "auditor: ran, and was not consulted -- the battery flagged nothing "
            "in verifier_integrity, which is the only family it may touch",
            file=sys.stderr,
        )
    for override in auditor.overrides if auditor else []:
        print(
            f"auditor: {override.probe} {override.was} -> {override.now} "
            f"({override.proposed_by}): {override.reason}",
            file=sys.stderr,
        )

    if args.card:
        from .card import to_html, to_markdown

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
    p.add_argument(
        "--challenger",
        choices=[
            "scripted",
            "ollama",
            "claude",
            "synthesis-ollama",
            "synthesis-claude",
        ],
        default="scripted",
        help="which Challenger looks for reward hacks. Scripted is the default and "
             "needs no model, so the shipped verdict stays deterministic; the model "
             "arms propose policies the adapter never declared. `ollama`/`claude` "
             "add the turn-taking attacker, which acts in the environment and reads "
             "back its score; `synthesis-*` add the one that reads the verifier once "
             "and proposes answer strings. Both are composed with scripted, never "
             "substituted for it.",
    )
    p.add_argument("--challenger-model", default="qwen3:8b", metavar="NAME")
    p.add_argument(
        "--auditor-model", metavar="NAME", default=None,
        help="which backend the Auditor asks: an ollama tag, or 'claude' for the "
             "Claude CLI. Worth setting deliberately -- results/semantic_gate.json "
             "measures qwen3:8b at 0 of 1 on the semantic gate and claude-cli at 1 "
             "of 1, so the default backend order will silently pick the weaker one "
             "wherever ollama is running.",
    )
    p.add_argument(
        "--auditor", action="store_true",
        help="read the battery's results with a model before reporting them. It may "
             "only withhold a verifier-integrity defect on an environment that has no "
             "correct answer, never turn one into a pass; every override is printed "
             "with the model that proposed it. Off by default: the headline numbers "
             "are the deterministic ones.",
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
