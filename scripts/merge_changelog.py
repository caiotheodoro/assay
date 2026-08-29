#!/usr/bin/env python3
"""Merge changelog fragments into docs/CHANGELOG.md.

Fragments live in docs/changelog/NN-slug.md and are concatenated in name order
under the existing table. Keeping them separate is what lets several
workstreams record findings at once without fighting over one file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAGMENTS = ROOT / "docs" / "changelog"
TARGET = ROOT / "docs" / "CHANGELOG.md"
MARKER = "<!-- fragments below; edit docs/changelog/, not here -->"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the merge is stale")
    args = ap.parse_args()

    rows: list[str] = []
    for path in sorted(FRAGMENTS.glob("[0-9]*.md")):
        body = path.read_text().strip()
        if body:
            rows.append(f"<!-- from {path.name} -->\n{body}")

    current = TARGET.read_text()
    head = current.split(MARKER)[0].rstrip()
    merged = head + "\n\n" + MARKER + "\n" + "\n".join(rows) + "\n" if rows else head + "\n"

    if args.check:
        if merged != current:
            print("CHANGELOG.md is stale; run scripts/merge_changelog.py", file=sys.stderr)
            return 1
        print("changelog up to date")
        return 0

    TARGET.write_text(merged)
    print(f"merged {len(rows)} fragment(s) into {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
