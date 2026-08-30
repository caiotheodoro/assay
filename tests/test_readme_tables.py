"""The start-here table is the first thing anyone reads. It had a duplicate row.

Cheap to prevent and embarrassing to ship, but the reason it is worth a test is
how it got there: a shell command errored partway, applied half its edit, and
was re-run without checking what the first attempt had already done. That is a
process failure rather than a typo, and the same process runs over every
document in this repo.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _table_rows(text: str) -> list[str]:
    rows = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|")]
    return [r for r in rows if not re.fullmatch(r"\|[\s|:-]+\|", r)]


def test_no_readme_table_row_appears_twice():
    rows = _table_rows((ROOT / "README.md").read_text())
    dupes = [row for row, n in Counter(rows).items() if n > 1 and "|" in row]
    assert not dupes, f"duplicated row(s) in README tables: {dupes[:3]}"


def test_every_relative_doc_link_in_the_readme_resolves():
    """A dead link in the first table is worse than a missing one."""
    text = (ROOT / "README.md").read_text()
    targets = re.findall(r"\]\((?!https?:|#)([^)#]+)", text)
    missing = sorted({t for t in targets if not (ROOT / t).exists()})
    assert not missing, f"README links to files that do not exist: {missing}"
