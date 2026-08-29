"""Assemble the publishable artifact, and refuse to publish what is not ours.

What ships: the environments this repo wrote (the toy fixtures and the Harbor
suite), their planted-defect ground truth, and the Environment Cards Assay
produced for them.

What does not, and why the check is code rather than a note:

  - ScienceAgentBench's archive. Upstream asks plainly that the unzipped files
    not be redistributed.
  - inspect_evals and OpenEnv content. Those are other people's benchmarks and
    environments; auditing them does not make them ours to republish.
  - tau2-bench and tau2-bench-verified. MIT and Apache-2.0 respectively, so
    redistribution would in fact be permitted -- and it still does not happen,
    because the line here is ownership rather than licence, and carving out the
    one benchmark that happens to be permissive would make the rule a
    negotiation. `scripts/tau2_fetch.py` downloads both into a gitignored
    cache; `results/tau2_recall.json` carries task ids and verdicts and not a
    line of task text.

Findings ABOUT third-party software are a different matter and do ship: a
verdict says `paws` scores a constant string at 100%, and carries no benchmark
content to redistribute. The line is between a claim and a copy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapter import close_adapter
from .corpus import entries
from .runner import audit
from .types import canonical_json, digest

#: Ecosystems this repo authored, and may therefore publish in full.
OURS = {"fixture", "harbor"}

#: Ecosystems whose environments belong to someone else. Verdicts about them
#: may ship; their content may not.
THEIRS = {"inspect_ai", "openenv", "scienceagentbench", "tau2"}


class RedistributionRefused(RuntimeError):
    """A payload contained content from an ecosystem we do not own."""


#: Probe detail keys that are safe to carry for a third-party environment.
#: A probe's `detail` is where measurements live -- counts, rates, parameters --
#: but for the contamination probe it also sits next to the item ids and texts
#: it compared, so the allowlist is by key rather than by exclusion. Anything
#: not named here is dropped for THEIRS, on the principle that a new probe
#: adding a new detail key must not silently start publishing someone's data.
THIRD_PARTY_DETAIL_KEYS = {
    "n_train",
    "n_eval",
    "exact_overlap",
    "near_dup_count",
    "near_dup_rate",
    "params",
    "bounds",
}


@dataclass
class Payload:
    rows: list[dict[str, Any]] = field(default_factory=list)
    cards: dict[str, str] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)
    #: Per-environment probe outcomes. For OURS this is the signed report body.
    #: For THEIRS it is status + reason + allowlisted detail only -- enough to
    #: publish which probes could not run and why, which is the part a reader
    #: needs most, without carrying a line of anyone's benchmark.
    probes: dict[str, dict[str, Any]] = field(default_factory=dict)

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
            close_adapter(adapter)

        row = {
            "env_id": env_id,
            "ecosystem": eco,
            "verdict": report.verdict,
            "detected": sorted(d.value for d in report.detected),
            "coverage": report.coverage,
        }
        if eco in OURS:
            # Ours: ship the labels, the full card, and the signed report body.
            row["planted_defects"] = sorted(d.value for d in planted)
            row["content_included"] = True
            payload.cards[env_id] = to_markdown(report)
            payload.probes[env_id] = report.to_dict()
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
            payload.probes[env_id] = _redacted_probes(report)
        payload.rows.append(row)
    return payload


def _redacted_probes(report) -> dict[str, Any]:
    """Which probes ran, and why the rest did not. No findings, no evidence.

    Absence of evidence is the part of a card that must never be dropped, and
    it is also the part that carries no benchmark content -- "this probe could
    not run because the environment exposes no train split" is a fact about
    the environment, not a copy of it. So it ships even for THEIRS, while the
    findings, which quote task ids and item text, do not.
    """
    return {
        "env_id": report.env_id,
        "ecosystem": report.ecosystem,
        "env_version": report.env_version,
        "verdict": report.verdict,
        "coverage": report.coverage,
        "content_included": False,
        "probes": [
            {
                "family": r.family,
                "probe": r.probe,
                "status": r.status.value,
                "reason": r.reason,
                "n_findings": len(r.findings),
                "detail": {
                    k: v for k, v in r.detail.items() if k in THIRD_PARTY_DETAIL_KEYS
                },
            }
            for r in report.results
        ],
    }


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

    for env_id, body in payload.probes.items():
        eco = by_id.get(env_id, _ecosystem(env_id))
        if eco in OURS:
            continue
        # A third-party probe body carries no findings and no unlisted detail
        # keys. Checked here rather than trusted from `_redacted_probes`,
        # because the caller can construct a Payload by hand and the guard is
        # the last thing that runs before bytes leave the machine.
        if body.get("content_included"):
            raise RedistributionRefused(f"{env_id}: probe body marked for inclusion")
        for probe in body.get("probes", []):
            if probe.get("findings"):
                raise RedistributionRefused(
                    f"{env_id}: probe {probe.get('probe')!r} carries findings for an "
                    "ecosystem we do not own; findings quote task ids and item text"
                )
            stray = set(probe.get("detail", {})) - THIRD_PARTY_DETAIL_KEYS
            if stray:
                raise RedistributionRefused(
                    f"{env_id}: probe {probe.get('probe')!r} carries detail keys "
                    f"{sorted(stray)} that are not on the third-party allowlist; add "
                    "them deliberately or drop them, but do not publish by default"
                )


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
    if payload.probes:
        (out / "probes.jsonl").write_text(
            "\n".join(
                canonical_json(payload.probes[k]) for k in sorted(payload.probes)
            )
            + "\n"
        )
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
