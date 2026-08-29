"""Assemble the publishable artifact, and refuse to publish what is not ours.

What ships: the environments this repo wrote (the toy fixtures and the Harbor
suite), their planted-defect ground truth, and the Environment Cards Assay
produced for them.

What does not, and why the check is code rather than a note:

  - ScienceAgentBench's archive. Upstream asks plainly that the unzipped files
    not be redistributed.
  - inspect_evals and OpenEnv content. Those are other people's benchmarks and
    environments; auditing them does not make them ours to republish.

Findings ABOUT third-party software are a different matter and do ship: a
verdict says `paws` scores a constant string at 100%, and carries no benchmark
content to redistribute. The line is between a claim and a copy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .corpus import entries
from .runner import audit
from .types import canonical_json, digest

#: Ecosystems this repo authored, and may therefore publish in full.
OURS = {"fixture", "harbor"}

#: Ecosystems whose environments belong to someone else. Verdicts about them
#: may ship; their content may not.
THEIRS = {"inspect_ai", "openenv", "scienceagentbench"}


class RedistributionRefused(RuntimeError):
    """A payload contained content from an ecosystem we do not own."""


@dataclass
class Payload:
    rows: list[dict[str, Any]] = field(default_factory=list)
    cards: dict[str, str] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)

    def signature(self) -> str:
        return digest({"rows": self.rows, "cards": sorted(self.cards)})


def _ecosystem(env_id: str) -> str:
    """Fallback only. The adapter's own manifest is authoritative -- an env id
    prefix is a display label and the two have already drifted once
    (`inspect/...` ids under the `inspect_ai` provider)."""
    return env_id.split("/", 1)[0]


def build(include_third_party_verdicts: bool = True) -> Payload:
    from .card import to_markdown

    payload = Payload()
    for env_id, factory, planted in entries():
        adapter = factory()
        try:
            report = audit(adapter)
            # From the manifest, not the id prefix.
            eco = report.ecosystem or _ecosystem(env_id)
        finally:
            close = getattr(adapter, "close", None)
            if close:
                close()

        row = {
            "env_id": env_id,
            "ecosystem": eco,
            "verdict": report.verdict,
            "detected": sorted(d.value for d in report.detected),
            "coverage": report.coverage,
        }
        if eco in OURS:
            # Ours: ship the labels and the full card.
            row["planted_defects"] = sorted(d.value for d in planted)
            row["content_included"] = True
            payload.cards[env_id] = to_markdown(report)
        else:
            if not include_third_party_verdicts:
                payload.excluded[env_id] = f"{eco} content is not ours to republish"
                continue
            # Theirs: the verdict travels, the environment does not.
            row["planted_defects"] = None
            row["content_included"] = False
            row["note"] = (
                f"verdict only; {eco} environments are not redistributed here. "
                "Reproduce by installing the upstream package and running "
                "scripts/full_run.py."
            )
        payload.rows.append(row)
    return payload


def verify_no_redistribution(payload: Payload) -> None:
    """Fail closed. A published artifact is not something to fix afterwards."""
    for row in payload.rows:
        eco = row["ecosystem"]
        if eco in THEIRS and row.get("content_included"):
            raise RedistributionRefused(
                f"{row['env_id']}: {eco} content marked for inclusion"
            )
        if eco not in OURS and eco not in THEIRS:
            raise RedistributionRefused(
                f"{row['env_id']}: ecosystem {eco!r} is not classified as ours or "
                "theirs; classify it before publishing rather than guessing"
            )
    by_id = {row["env_id"]: row["ecosystem"] for row in payload.rows}
    for env_id in payload.cards:
        eco = by_id.get(env_id, _ecosystem(env_id))
        if eco not in OURS:
            raise RedistributionRefused(f"{env_id}: card for an ecosystem we do not own")


def write(payload: Payload, out: Path) -> Path:
    verify_no_redistribution(payload)
    out.mkdir(parents=True, exist_ok=True)
    (out / "corpus.jsonl").write_text(
        "\n".join(canonical_json(r) for r in payload.rows) + "\n"
    )
    cards = out / "cards"
    cards.mkdir(exist_ok=True)
    for env_id, card in payload.cards.items():
        (cards / f"{env_id.replace('/', '__')}.md").write_text(card)
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "n_rows": len(payload.rows),
                "n_cards": len(payload.cards),
                "ours": sorted(OURS),
                "verdict_only": sorted(THEIRS),
                "excluded": payload.excluded,
                "signature": payload.signature(),
            },
            indent=2,
        )
    )
    return out
