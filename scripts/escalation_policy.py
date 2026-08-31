#!/usr/bin/env python3
"""Produce `results/escalation_policy.json`: where a second attacker is worth paying for.

A model Challenger costs minutes where the scripted one costs about two
seconds, so escalating everywhere is not a design, it is a bill. The policy is
`Auditor.should_escalate`, decided in code with no model call, and this script
runs it over the whole corpus and records the answer and the reason on every
environment -- including the refusals, which are the point.

The artifact this replaces was written by hand and said `n_environments: 26`.
The corpus has been 28 for some time. That is the argument for the script:
a number nothing regenerates is a number that goes stale silently.

    uv run --extra adapters --extra openenv --extra tau2 \
        python scripts/escalation_policy.py

Deterministic and needs no backend.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.auditor import Auditor  # noqa: E402
from assay.corpus import entries, unavailable  # noqa: E402
from assay.runconfig import git_revision  # noqa: E402


def _closing(adapter):
    return adapter if hasattr(adapter, "__enter__") else _NullCtx(adapter)


class _NullCtx:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *exc):
        return False


def _bucket(why: str) -> str:
    """Group a refusal reason without losing which environment gave it."""
    if "already found an exploit" in why:
        return "already found an exploit"
    if "wide enough" in why:
        return "repertoire wide enough"
    if "did not run" in why:
        return "probe did not run"
    if "no reward-hackability result" in why:
        return "no reward-hackability result"
    if "declares no trivial policies" in why:
        return "no declared trivial policies"
    return why


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/escalation_policy.json")
    ap.add_argument("--allow-reduced", action="store_true")
    args = ap.parse_args()

    if unavailable() and not args.allow_reduced:
        raise SystemExit(
            "refusing to report a selectivity rate from a reduced corpus.\n"
            f"missing providers: {sorted(unavailable())}\n"
            "'escalates 12 of 26' is a claim about a corpus; measure it on the "
            "whole one or do not quote it."
        )

    corpus = entries()
    auditor = Auditor()  # no client: should_escalate makes no model call
    rows, refusals = [], {}
    for env_id, factory, _planted in corpus:
        with _closing(factory()) as adapter:
            report = audit(adapter)
            escalate, why = auditor.should_escalate(adapter, report)
        rows.append({"env": env_id, "escalate": escalate, "why": why})
        if not escalate:
            key = _bucket(why)
            refusals[key] = refusals.get(key, 0) + 1
        print(f"  {env_id}: {'escalate' if escalate else 'refuse'} -- {why}", flush=True)

    payload = {
        "what": "When is a second, expensive attacker worth running at all?",
        "why": "A model Challenger costs minutes where the scripted one costs "
               "about two seconds. Escalating everywhere is not a design, it is "
               "a bill. This measures how selective the policy actually is on "
               "the shipped corpus.",
        "policy": "Escalate only where the scripted attacker returned PASS and "
                  "the environment declares fewer than 5 trivial policies, so "
                  "the silence is thin evidence rather than a saturated floor.",
        "harness": "uv run --extra adapters --extra openenv --extra tau2 python "
                   "scripts/escalation_policy.py",
        "assay_revision": git_revision(),
        "model_calls": 0,
        "n_environments": len(rows),
        "escalates": sum(1 for r in rows if r["escalate"]),
        "refuses": sum(1 for r in rows if not r["escalate"]),
        "refusal_reasons": dict(sorted(refusals.items())),
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {out}: {payload['escalates']} escalate, "
          f"{payload['refuses']} refuse, of {payload['n_environments']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
