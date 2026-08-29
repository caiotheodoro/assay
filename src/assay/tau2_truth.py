"""Ground truth for the tau2 recall measurement, built from two pinned commits.

Assay has so far been scored against defects this repo planted itself. That is
circular: the same author chose both the defect and the probe. This module
supplies the non-circular alternative -- 62 tau-bench tasks that a third party
(amazon-agi, `tau2-bench-verified`) independently judged to be wrong and fixed,
with the fixes documented in FIXES.md against quotes from the domain policy.

Two decisions here are load-bearing.

**The label is the diff, not the prose.** FIXES.md numbers its fixes by a task
index that does not line up with the `id` field in `tasks.json` (see
`docs/changelog/60-tau2-recall.md` for the check that established this). So a
task is a labelled positive iff its record differs between the pre-fix commit
and the verified commit -- a fact anyone can recompute with `json.load` and
`==`. The prose is used only to *categorise* a positive, and only when a fix's
verbatim before/after text can be located in the two task records.

**Neither repository's content is redistributed.** `scripts/tau2_fetch.py`
downloads both snapshots into a gitignored cache. Nothing under `.tau2_cache/`
is committed, and the results file carries task ids and verdicts, never task
text. See `src/assay/publish.py` for the same line drawn elsewhere.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

#: The last commit of `sierra-research/tau2-bench` before `tau2-bench-verified`
#: forked, and therefore the pre-fix task set. Pinned rather than tracking main:
#: main has since moved to tau3 (commit 01e812d1, 2026-03-18) and rewrote both
#: task files, which would silently change every number in this measurement.
BASE_REV = "37199f36924c8896f5e048360691f8476cd89ba1"
BASE_REPO = "sierra-research/tau2-bench"

#: `amazon-agi/tau2-bench-verified` initial commit -- the fixed task set.
VERIFIED_REV = "a470e45f2e799286cb87d26b8b30d8ab558a3375"
VERIFIED_REPO = "amazon-agi/tau2-bench-verified"

DOMAINS = ("retail", "airline")

#: Kept, and it excludes nothing. The original comment here claimed the verified
#: fork "dropped `reward_basis` wholesale", so counting it would label every task
#: a positive. That was never checked and is false: the string occurs zero times
#: in *either* revision of either domain, and recomputing the diff with no
#: exclusion at all still gives 62 positives. The exclusion is therefore a no-op
#: and the 62 does not depend on it. Left in place, correctly described, because
#: the upstream schema could reintroduce the field and a silent reintroduction
#: would be worse than a dead tuple.
SCHEMA_ONLY_FIELDS = (("evaluation_criteria", "reward_basis"),)


def cache_dir() -> Path:
    return Path(os.environ.get("ASSAY_TAU2_CACHE", ".tau2_cache")).resolve()


def tau2_source_root() -> Path:
    """Where `scripts/tau2_fetch.py` unpacks tau2-bench itself.

    Laid out exactly as the upstream repository is, because `tau2` resolves its
    own data directory from `__file__` -- three levels above `src/tau2/utils`.
    Rearranging the tree would silently break `get_environment()`.
    """
    return cache_dir() / "tau2_src"


def verified_dir() -> Path:
    return cache_dir() / "verified"


class Tau2DataMissing(RuntimeError):
    """The pinned snapshots have not been downloaded.

    Carries the command that fixes it. A check that cannot run has to say why,
    and 'why' is more useful when it is also 'how'.
    """


def _read(path: Path) -> Any:
    if not path.exists():
        raise Tau2DataMissing(
            f"{path} is absent. Fetch the two pinned snapshots first:\n"
            "    uv run --extra tau2 python scripts/tau2_fetch.py\n"
            "Neither snapshot is redistributed in this repository."
        )
    return json.loads(path.read_text())


def domain_data_dir(domain: str) -> Path:
    return tau2_source_root() / "data" / "tau2" / "domains" / domain


def tasks_path(domain: str, which: str) -> Path:
    """`which` is 'base' (pre-fix) or 'verified' (post-fix)."""
    if which == "base":
        return domain_data_dir(domain) / "tasks.json"
    if which == "verified":
        return verified_dir() / f"{domain}-tasks.json"
    raise ValueError(f"unknown task set {which!r}; expected 'base' or 'verified'")


def load_tasks(domain: str, which: str, cache: Path | None = None) -> list[dict]:
    return _read(tasks_path(domain, which))


def load_fixes_md(cache: Path | None = None) -> str:
    path = verified_dir() / "FIXES.md"
    if not path.exists():
        raise Tau2DataMissing(
            f"{path} is absent. Run `uv run --extra tau2 python scripts/tau2_fetch.py` first."
        )
    return path.read_text()


# --------------------------------------------------------------------------
# The diff -- this is the label
# --------------------------------------------------------------------------

def _strip_schema_only(task: dict) -> dict:
    task = json.loads(json.dumps(task))
    for path in SCHEMA_ONLY_FIELDS:
        node = task
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return task


def leaf_paths(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten to `{json-pointer-ish path: scalar}` so a diff names the field."""
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, sub in value.items():
            out.update(leaf_paths(sub, f"{prefix}/{key}"))
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            out.update(leaf_paths(sub, f"{prefix}[{i}]"))
    else:
        out[prefix or "/"] = value
    return out


_MISSING = object()


def changed_fields(base: dict, verified: dict) -> list[str]:
    a, b = leaf_paths(_strip_schema_only(base)), leaf_paths(_strip_schema_only(verified))
    return sorted(k for k in set(a) | set(b) if a.get(k, _MISSING) != b.get(k, _MISSING))


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------

#: The four categories `tau2-bench-verified`'s README names, plus one this
#: measurement has to add: a task the diff proves was fixed but whose fix could
#: not be located in FIXES.md. Reporting those as if they were categorised
#: would overstate how much of the ground truth is actually labelled.
CATEGORIES = (
    "policy_compliance",
    "database_accuracy",
    "logical_consistency",
    "evaluation_ambiguity",
    "unattributed",
)

#: Matched against a fix's stated rationale, in this order; first hit wins.
#: Deliberately ordered by how specific the evidence is: a quoted policy rule
#: is stronger evidence than the word "clarify".
_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "logical_consistency",
        re.compile(
            r"impossible|identical|same item\b|already (departed|flown|taken off)"
            r"|contradict|cannot be (exchanged|cancelled)|no longer valid",
            re.I,
        ),
    ),
    (
        "database_accuracy",
        re.compile(
            r"in the database|does ?n[o']?t exist|not (found|present) in the"
            r"|match(es|ing)? (the )?(actual )?database|incorrect (item|passenger|payment)"
            r"|wrong (item|id|payment)|is cheaper than|price \$",
            re.I,
        ),
    ),
    (
        "policy_compliance",
        re.compile(
            r"violat|against (the )?policy|policy (states|requires|forbids|only|does not)"
            r"|not allowed|is not permitted|must (either|be|go)|only accepts",
            re.I,
        ),
    ),
    (
        "evaluation_ambiguity",
        re.compile(
            r"ambigu|clarif|explicit|under-?specified|vague|deterministic|emphasis"
            r"|hidden information|fallback|edge case|too restrictive|stricter|score of 0"
            r"|consistent grading|prevent(ing)? (the )?(user|evaluation)",
            re.I,
        ),
    ),
)


def categorise(rationale: str, has_policy_quote: bool) -> str:
    """One category per fix, from the fix's own stated reason.

    `has_policy_quote` promotes a fix that cites a policy rule verbatim: the
    verified repo only attaches a `Policy Reference` block when the change is
    justified by the policy text, which is exactly what `policy_compliance`
    means. It is checked after the two rules whose evidence is stronger still
    -- an identical-item exchange cites a policy quote too, and it is the
    logical impossibility, not the citation, that the fix is about.
    """
    for name, pattern in _CATEGORY_RULES[:2]:
        if pattern.search(rationale):
            return name
    if has_policy_quote:
        return "policy_compliance"
    for name, pattern in _CATEGORY_RULES[2:]:
        if pattern.search(rationale):
            return name
    return "evaluation_ambiguity"


#: The other axis, and the one that needs no interpretation at all: did the fix
#: touch the graded answer, or only the words the simulated user says?
MECHANICAL_CATEGORIES = ("ground_truth_annotation", "instruction_underspecification")


def mechanical_category(fields: Iterable[str]) -> str:
    fields = list(fields)
    if any(f.startswith("/evaluation_criteria") for f in fields):
        return "ground_truth_annotation"
    return "instruction_underspecification"


# --------------------------------------------------------------------------
# FIXES.md
# --------------------------------------------------------------------------

@dataclass
class FixRecord:
    domain: str
    title: str
    rationale: str
    policy_quote: str | None
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    category: str = "evaluation_ambiguity"


_BOLD = re.compile(r"\*\*(.*?)\*\*", re.S)
_BEFORE = re.compile(r"^-?\s*\*\*Before:?\*\*:?\s*(.*)$", re.I)
_AFTER = re.compile(r"^-?\s*\*\*After:?\*\*:?\s*(.*)$", re.I)


def _plain(text: str) -> str:
    """Drop the emphasis FIXES.md uses to point at the words it changed.

    The emphasis is editorial: the task files contain no `**`. Leaving it in
    would make every before/after string fail to match the JSON it came from.
    """
    text = _BOLD.sub(r"\1", text).strip()
    text = text.strip("`").strip()
    if text.startswith('"') and text.endswith('"') and len(text) > 1:
        text = text[1:-1]
    return re.sub(r"\s+", " ", text).strip()


def parse_fixes(md: str) -> list[FixRecord]:
    """Split FIXES.md into one record per `### Task:` heading."""
    records: list[FixRecord] = []
    domain = "unknown"
    blocks: list[tuple[str, str, list[str]]] = []
    current: list[str] | None = None
    title = ""
    for line in md.splitlines():
        if line.startswith("## "):
            low = line.lower()
            if "retail" in low:
                domain = "retail"
            elif "airline" in low:
                domain = "airline"
            else:
                domain = "unknown"
        if line.startswith("### "):
            if current is not None:
                blocks.append((domain_at_title, title, current))
            title = line[4:].strip()
            domain_at_title = domain
            current = []
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        blocks.append((domain_at_title, title, current))

    for dom, title, body in blocks:
        before, after, rationale, quote = [], [], [], None
        for line in body:
            m = _BEFORE.match(line.strip())
            if m:
                before.append(_plain(m.group(1)))
                continue
            m = _AFTER.match(line.strip())
            if m:
                after.append(_plain(m.group(1)))
                continue
            stripped = line.strip()
            if stripped.startswith("**Why:**"):
                rationale.append(stripped[len("**Why:**"):])
            elif stripped.startswith("> *"):
                quote = _plain(stripped.lstrip("> "))
            elif rationale and stripped and not stripped.startswith(("**", ">", "-", "#")):
                rationale.append(stripped)
        why = " ".join(rationale).strip()
        records.append(
            FixRecord(
                domain=dom,
                title=title,
                rationale=why,
                policy_quote=quote,
                before=[b for b in before if b],
                after=[a for a in after if a],
                category=categorise(why, quote is not None),
            )
        )
    return records


# Substrings shorter than this match by accident -- half the retail tasks
# contain "you want to return". Long enough to be a fingerprint, short enough
# that most FIXES.md excerpts survive the bar.
_MIN_ANCHOR = 25

#: FIXES.md elides the middle of long instructions with an ellipsis and prefixes
#: pure insertions with "Added:". Both are editorial and neither appears in the
#: task files, so an excerpt has to be cut back to the fragments that were
#: actually quoted before it can be looked for.
_ELLIPSIS = re.compile(r"\.\.\.|\u2026")
_ADDED = re.compile(r"^Added:?\s*", re.I)

#: Several fixes change nothing but an item id, and quote it as
#: `new_item_ids: ["8069050545"]`. The id is a better fingerprint than any
#: prose, so it is pulled out as an anchor in its own right.
_ITEM_ID = re.compile(r'"(\d{10})"')


def _anchors(strings: Iterable[str]) -> list[str]:
    """Every substring of an excerpt that could plausibly appear in a task."""
    out: list[str] = []
    for raw in strings:
        text = _ADDED.sub("", raw).strip().strip('"').strip()
        out.extend(f'"{i}"' for i in _ITEM_ID.findall(raw))
        for fragment in _ELLIPSIS.split(text):
            fragment = fragment.strip().strip('"').strip()
            if len(fragment) >= _MIN_ANCHOR:
                out.append(fragment)
    return out


def _haystack(task: dict) -> str:
    return re.sub(r"\s+", " ", json.dumps(task, ensure_ascii=False))


def attach_fixes(
    records: list[FixRecord],
    base: dict[str, dict],
    verified: dict[str, dict],
    changed: dict[str, list[str]],
) -> dict[str, list[FixRecord]]:
    """Attach each FIXES.md record to the task ids it demonstrably describes.

    The test is exact and one-directional: a record attaches to a changed task
    only if some `Before:` excerpt appears verbatim in that task's *pre-fix*
    record and the matching `After:` excerpt appears verbatim in its *post-fix*
    record. Anything weaker -- persona names, the fix's own task numbering --
    was tried and produced attachments that the diff contradicted.
    """
    out: dict[str, list[FixRecord]] = {tid: [] for tid in changed}
    base_text = {tid: _haystack(base[tid]) for tid in changed}
    ver_text = {tid: _haystack(verified[tid]) for tid in changed}
    for rec in records:
        befores, afters = _anchors(rec.before), _anchors(rec.after)
        if not befores or not afters:
            continue
        for tid in changed:
            hit_before = any(b in base_text[tid] for b in befores)
            hit_after = any(a in ver_text[tid] for a in afters)
            if hit_before and hit_after:
                out[tid].append(rec)
    return out


# --------------------------------------------------------------------------
# The assembled label set
# --------------------------------------------------------------------------

@dataclass
class TaskLabel:
    domain: str
    task_id: str
    defective: bool
    changed_fields: list[str] = field(default_factory=list)
    category: str = "clean"
    mechanical: str = "clean"
    fix_titles: list[str] = field(default_factory=list)


def ground_truth(domain: str, cache: Path | None = None) -> dict[str, TaskLabel]:
    cache = cache or cache_dir()
    base = {t["id"]: t for t in load_tasks(domain, "base", cache)}
    verified = {t["id"]: t for t in load_tasks(domain, "verified", cache)}
    shared = [tid for tid in base if tid in verified]

    changed: dict[str, list[str]] = {}
    for tid in shared:
        fields = changed_fields(base[tid], verified[tid])
        if fields:
            changed[tid] = fields

    records = [r for r in parse_fixes(load_fixes_md(cache)) if r.domain == domain]
    attached = attach_fixes(records, base, verified, changed)

    labels: dict[str, TaskLabel] = {}
    for tid in shared:
        if tid not in changed:
            labels[tid] = TaskLabel(domain=domain, task_id=tid, defective=False)
            continue
        recs = attached[tid]
        category = _reduce_categories([r.category for r in recs]) if recs else "unattributed"
        labels[tid] = TaskLabel(
            domain=domain,
            task_id=tid,
            defective=True,
            changed_fields=changed[tid],
            category=category,
            mechanical=mechanical_category(changed[tid]),
            fix_titles=[r.title for r in recs],
        )
    return labels


def _reduce_categories(names: list[str]) -> str:
    """A task can attract several fixes. Report the most consequential one.

    Order is the same judgement as `categorise`: a task whose gold answer was
    logically impossible is not an 'ambiguity' case just because a second,
    cosmetic fix landed on it too.
    """
    for name in ("logical_consistency", "database_accuracy", "policy_compliance"):
        if name in names:
            return name
    return "evaluation_ambiguity"
