"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from . import audit
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
    try:
        report = audit(adapter)
    finally:
        close = getattr(adapter, "close", None)
        if close:
            close()

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
    p.set_defaults(func=_audit)

    p = sub.add_parser("list", help="list the audited corpus and its planted defects")
    p.set_defaults(func=_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
