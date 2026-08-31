#!/usr/bin/env python3
"""Produce `results/na_resolution.json`: can the Auditor rescue a declined probe?

`inspect_evals/boolq` ships one split, so `shortcut_leakage` reports
NOT_APPLICABLE before it runs. The Auditor can name the fields of an item and
cross-fit over a split it synthesizes. This measures whether doing so changes
the verdict, and the answer is the interesting part: it does, and it is still
not a detection.

Run it against more than one backend. Two backends agreeing on the field names
is the only thing that makes the synthesized split evidence rather than one
model's guess.

    uv run --extra adapters --extra sweep \
        python scripts/na_resolution.py --backends claude qwen3:8b

Needs a live backend and `--extra sweep` for inspect_evals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.auditor import Auditor  # noqa: E402
from assay.corpus import entries  # noqa: E402
from assay.runconfig import git_revision  # noqa: E402
from assay.types import ProbeStatus  # noqa: E402

FAMILY = "shortcut_leakage"


def _closing(adapter):
    return adapter if hasattr(adapter, "__enter__") else _NullCtx(adapter)


class _NullCtx:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *exc):
        return False


def _client(name):
    from assay.llm import ClaudeCLIClient, OllamaClient

    return ClaudeCLIClient() if name == "claude" else OllamaClient(name)


def _factory(env_id: str):
    for candidate, factory, _planted in entries():
        if candidate == env_id:
            return factory
    raise SystemExit(
        f"{env_id} is not registered. Registered ids: "
        f"{sorted(e for e, _, _ in entries())}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="inspect_evals/boolq")
    ap.add_argument(
        "--backends", nargs="+", default=["claude", "qwen3:8b"],
        help="every backend to ask for the field decomposition. Agreement "
             "across backends is what makes the split evidence rather than "
             "one model's guess",
    )
    ap.add_argument("--out", default="results/na_resolution.json")
    args = ap.parse_args()

    factory = _factory(args.env)

    with _closing(factory()) as adapter:
        baseline = audit(adapter)
    declined = [
        r for r in baseline.results
        if r.family == FAMILY and r.status is ProbeStatus.NOT_APPLICABLE
    ]
    if not declined:
        raise SystemExit(
            f"{args.env} has no declined {FAMILY} probe, so there is nothing to "
            "resolve. This file exists to record a rescue attempt; if the probe "
            "now runs on its own, delete the artifact rather than faking one."
        )
    before = {"status": declined[0].status.value, "reason": declined[0].reason}
    print(f"battery without auditor: {before['status']} -- {before['reason']}")

    per_backend = {}
    for name in args.backends:
        client = _client(name)
        usable, reason = client.availability()
        if not usable:
            print(f"SKIPPING {name}: {reason}")
            per_backend[name] = {"skipped": reason}
            continue
        auditor = Auditor(client)
        with _closing(factory()) as adapter:
            spec = auditor.decompose(adapter)
            report = auditor.resolve(adapter, audit(adapter))
        resolved = [r for r in report.results if r.family == FAMILY]
        per_backend[name] = {
            "backend": getattr(client, "name", name),
            "model_calls": auditor.calls,
            "decomposition": spec,
            "status": resolved[0].status.value if resolved else None,
            "detail": resolved[0].detail if resolved else None,
        }
        print(f"  {name}: {per_backend[name]['status']}, parts "
              f"{[p.get('name') for p in (spec or {}).get('parts', [])]}")

    ran = {k: v for k, v in per_backend.items() if "skipped" not in v}
    if not ran:
        raise SystemExit("no backend was usable; nothing measured, nothing written")
    part_sets = {
        k: tuple(sorted(p.get("name") for p in (v["decomposition"] or {}).get("parts", [])))
        for k, v in ran.items()
    }
    agree = len(set(part_sets.values())) == 1 and len(part_sets) > 1

    payload = {
        "what": "Can the Auditor resolve a NOT_APPLICABLE by synthesizing the "
                "split the suite never shipped?",
        "env": args.env,
        "probe": f"{FAMILY}/partial_input_baseline",
        "harness": "uv run --extra adapters --extra sweep python "
                   f"scripts/na_resolution.py --backends {' '.join(args.backends)}",
        "assay_revision": git_revision(),
        "battery_without_auditor": before,
        "backends": per_backend,
        "both_backends_agree": agree,
        "agreement_detail": {k: list(v) for k, v in part_sets.items()},
        "corrects": "docs/PRE-REGISTRATION.md attributes this miss to the "
                    "adapter supplying no train split. That is true and it is "
                    "not the binding constraint: the partial-input baseline is "
                    "a dictionary over exact part values and cannot work on "
                    "free-text fields at any n. Supplying the split changes "
                    "NOT_APPLICABLE to PASS, which is a more honest verdict and "
                    "still not a detection.",
        "kept": "The resolver is kept. It is correct, it is cheap, and it fires "
                "wherever part values repeat -- categorical fields, templated "
                "prompts, multiple-choice stems. It does not rescue boolq.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {out}; backends agree on the decomposition: {agree}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
