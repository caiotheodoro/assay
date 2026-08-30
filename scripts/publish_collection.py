#!/usr/bin/env python3
"""Group the published Assay artifacts into one Hugging Face collection.

A collection is the only view that shows the dataset and the model together,
which matters here because the model is a **negative result** and reads as a
failed upload on its own. Next to the corpus it is the ablation row it was
published to make checkable.

Every number in the description is re-derived from `results/` rather than
typed. That rule exists because this repo has already shipped a card quoting a
figure the artifacts had moved past, and a collection is one more place for the
same drift to land.

Dry run by default, like `publish_hf.py`: nothing reaches the Hub without
`--push`. Idempotent -- re-running updates the description and re-adds nothing.

  uv run --extra adapters python scripts/publish_collection.py          # dry run
  uv run --extra adapters python scripts/publish_collection.py --push
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

ACCOUNT = "caiotheodoro"
DATASET_REPO = f"{ACCOUNT}/assay-corpus"
MODEL_REPO = f"{ACCOUNT}/assay-challenger-grpo"
GITHUB = "https://github.com/caiotheodoro/assay"
TAG = "v0.1.0"

TITLE = "Assay: auditing RL environments, with error bars"

#: Every card in this project carries both. A collection is a published surface
#: like any other, so it carries them too.
MANDATORY_DISCLAIMERS = ("synthetic", "not production-validated")


def _load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text())


#: The Hub rejects a longer one outright ("Too big: expected string to have
#: <150 characters"). Found by the API rather than by this script, which is why
#: it is a gate below: a limit discovered at the point of publishing is a limit
#: nothing checked.
DESCRIPTION_LIMIT = 150


def description() -> str:
    """One line, under 150 characters, with the numbers re-derived.

    Shaped like the other collections on this account: the result, then the
    repository. The title already says what the tool is, so the 150 characters
    go to the finding and the address rather than repeating the name.

    The cap forces a choice about which number a reader sees first. It is the
    margin over the trivial floor -- not the corpus size, not the probe count,
    and not the comparison against the incumbent linter, which is the
    flattering one.
    """
    iv = _load("intervals.json")
    floor = iv["arms"]["assay"]["loss_saved_vs"]["flag_everything"]
    lo, hi = floor["ci95"]
    return (
        f"Beats flag-everything by {floor['point']:.1f}, 95% CI [{lo:.0f},{hi:.0f}]. "
        f"Synthetic, not production-validated. Code: {GITHUB}"
    )


#: Same story as the description cap, one API call later: the Hub rejects a
#: longer note ("Too big: expected string to have <500 characters"). Both
#: limits are now gated, because finding a limit by having a publish fail
#: halfway is how the first Space push left the model unattempted.
NOTE_LIMIT = 500

ITEMS = [
    (
        DATASET_REPO,
        "dataset",
        "26 environments, 50 planted defects, an Environment Card for each, "
        "and every arm's per-environment score with 95% intervals.\n\n"
        "The arm that had to be beaten is the floor that flags every "
        "environment unread -- not the incumbent linter, which scores 3056 "
        "loss at 0.040 recall, within half a percent of flagging nothing. "
        "Assay saves 274.0 against the floor, CI [186, 326], separated. For "
        "most of this project's life it did not.\n\n"
        "Third-party content is verdict-only; nothing is redistributed.",
    ),
    (
        MODEL_REPO,
        "model",
        "A negative result, published so the ablation row is checkable.\n\n"
        "Two GRPO runs trained an adversarial Challenger to find reward hacks. "
        "It never beat the scripted repertoire it was meant to improve on, and "
        "the logs say why: 99.7% of rollout groups had zero reward spread, so "
        "there was no gradient. The card leads with that rather than burying "
        "it.\n\n"
        "Alone it reads as a failed upload. Beside the corpus it is the row "
        "that makes the scripted floor's win measurable.",
    ),
]


def gates(desc: str) -> list[tuple[str, bool, str]]:
    """Checked before anything is created, in publish_hf.py's spirit."""
    from huggingface_hub import HfApi

    api = HfApi()
    out: list[tuple[str, bool, str]] = []

    out.append((f"description under {DESCRIPTION_LIMIT} chars",
                len(desc) <= DESCRIPTION_LIMIT, f"{len(desc)} chars"))

    long_notes = [f"{repo} {len(note)}" for repo, _, note in ITEMS
                  if len(note) > NOTE_LIMIT]
    out.append((f"every note under {NOTE_LIMIT} chars", not long_notes,
                ", ".join(long_notes)
                or ", ".join(f"{kind} {len(note)}" for _, kind, note in ITEMS)))

    # Every other collection on this account cites its repository. A reader
    # who finds the collection first should not have to guess where the code is.
    out.append(("description cites the repository", GITHUB in desc, GITHUB))

    missing = [d for d in MANDATORY_DISCLAIMERS if d.lower() not in desc.lower()]
    out.append(("description carries the disclaimers", not missing,
                ", ".join(missing) or f"all {len(MANDATORY_DISCLAIMERS)} present"))

    # A collection of links is worth exactly as much as the links resolving.
    for repo, kind, _ in ITEMS:
        try:
            api.repo_info(repo, repo_type=kind)
            ok, detail = True, f"{kind} exists"
        except Exception as exc:  # noqa: BLE001 - any failure blocks the publish
            ok, detail = False, f"{type(exc).__name__}: {str(exc)[:60]}"
        out.append((f"{kind} resolves", ok, detail))

    # The Space is deliberately absent. Asserted, so that adding it later is a
    # decision someone makes rather than a line that quietly starts passing.
    out.append(("no undeployed artifact listed",
                all(kind != "space" for _, kind, _ in ITEMS),
                "the Space is not deployed and is not linked"))

    # Numbers come from artifacts. If a headline figure is not in the text the
    # derivation broke, and a hardcoded number would not have noticed.
    iv = _load("intervals.json")
    point = f"{iv['arms']['assay']['loss_saved_vs']['flag_everything']['point']:.1f}"
    out.append(("figures derived from results/", point in desc,
                f"margin over the floor {point} present"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--push", action="store_true",
                    help="create or update the collection. Without it, nothing is sent.")
    args = ap.parse_args()

    desc = description()
    print(f"{TITLE}\n{'-' * 78}\n{desc}\n({len(desc)} chars)\n{'-' * 78}")
    for repo, kind, note in ITEMS:
        print(f"\n  {kind:8} {repo}\n           {note[:100]}...")

    print(f"\n{'=' * 78}\nGATES\n{'=' * 78}")
    checks = gates(desc)
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {name:34s}  {detail}")
    if [c for c in checks if not c[1]]:
        print("\ngate(s) failed. Nothing created.")
        return 1

    if not args.push:
        print("\nDry run. Nothing sent. Re-run with --push.")
        return 0

    from huggingface_hub import (
        add_collection_item,
        create_collection,
        get_collection,
        update_collection_metadata,
    )

    collection = create_collection(TITLE, namespace=ACCOUNT, description=desc,
                                   exists_ok=True)
    slug = collection.slug
    # `exists_ok` returns the existing collection untouched, so a re-run has to
    # push the description explicitly or an edited blurb would silently not ship.
    update_collection_metadata(slug, description=desc)

    for repo, kind, note in ITEMS:
        add_collection_item(slug, item_id=repo, item_type=kind, note=note,
                            exists_ok=True)

    # Read it back. Creating and verifying are different claims.
    fresh = get_collection(slug)
    print(f"\nhttps://huggingface.co/collections/{slug}")
    print(f"  title: {fresh.title}")
    print(f"  items: {len(fresh.items)}")
    for item in fresh.items:
        print(f"    {item.item_type:8} {item.item_id}  note={'yes' if item.note else 'NO'}")
    if len(fresh.items) != len(ITEMS):
        print(f"\nexpected {len(ITEMS)} items, the Hub returned {len(fresh.items)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
