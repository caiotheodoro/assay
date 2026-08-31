"""Command line entry point."""

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
    found = [e for e in entries() if e[0] == args.env]
    if not found:
        print(f"unknown environment: {args.env}", file=sys.stderr)
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

            auditor = Auditor()
            report = auditor.audit(adapter, ctx)
        else:
            report = audit(adapter, ctx)
    finally:
        close_adapter(adapter)

    for override in auditor.overrides if auditor else []:
        print(
            f"auditor: {override.probe} {override.was} -> {override.now} "
            f"({override.proposed_by}): {override.reason}",
            file=sys.stderr,
        )

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
