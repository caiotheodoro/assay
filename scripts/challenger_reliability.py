#!/usr/bin/env python3
"""How often does the Challenger actually find the exploit?

It found `harbor/self-graded` at turn 8 with gap 1.00, and then missed the same
environment on the next run. A probe backed by a sampled model is not a
deterministic check, and reporting one successful run as "the Challenger finds
this" would be a capability claim the evidence does not support.

So: k independent attempts, report hits/k. This is pass^k rather than pass@1,
for the same reason tau-bench uses it -- a system that succeeds once in five
tries is not a system that succeeds.

**The rate is no longer computed here.** This script used to run a full audit k
times and count how many reports carried the defect, which made it a second
implementation of a number the probe is now responsible for -- and two
implementations of one rate is the "scored by a second implementation" failure
`intervals.py` names. `RewardHackability` takes `challenger_passes` and reports
`hit_rate` in its own detail; this script sets it, reads it back, and writes the
artifact. What it measures is unchanged. Who computes it is not.

Usage:
  uv run --extra adapters python scripts/challenger_reliability.py --k 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.adapters import HarborAdapter  # noqa: E402
from assay.adapters.harbor import stage_suite  # noqa: E402
from assay.challenger import CompositeChallenger, ScriptedChallenger  # noqa: E402
from assay.challenger.prompted import PromptedChallenger  # noqa: E402
from assay.llm import ClaudeCLIClient, OllamaClient  # noqa: E402
from assay.sandbox import AutoApprove, DockerSandbox  # noqa: E402
from assay.types import DefectClass  # noqa: E402

SUITE = Path(__file__).resolve().parents[1] / "src" / "assay" / "fixtures" / "harbor_suite"


def build(task: str) -> HarborAdapter:
    root = stage_suite(SUITE / task, "assay-rel-")
    return HarborAdapter(
        root, sandbox=DockerSandbox(AutoApprove("reliability run")), env_id=f"harbor/{task}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="self-graded")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--model", default="claude")
    ap.add_argument("--out", default="results/challenger_reliability.json")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace an existing artifact, provenance fields included")
    args = ap.parse_args()

    client = ClaudeCLIClient() if args.model == "claude" else OllamaClient(args.model)
    usable, reason = client.availability()
    if not usable:
        print(f"cannot run: {reason}")
        return 1

    out_path = Path(args.out)
    if out_path.exists() and not args.overwrite:
        # The committed artifact carries fields no re-run can reconstruct: why
        # a fifth run was stopped, and a `do_not_backfill` note saying the run
        # config was never captured and must not be filled in from today's
        # defaults. Overwriting them silently would destroy exactly the kind of
        # provenance this repo asks other people to keep.
        existing = json.loads(out_path.read_text())
        unrecoverable = [k for k in ("stopped_early", "run_config") if k in existing]
        print(f"{out_path} already exists and carries {', '.join(unrecoverable)}.")
        print("Re-running would overwrite provenance that cannot be reconstructed.")
        print("Pass --overwrite if you mean to replace it, or --out to write elsewhere.")
        return 1

    challenger = CompositeChallenger(
        [ScriptedChallenger(), PromptedChallenger(client=client, turns=args.turns)]
    )
    started = time.time()
    with build(args.task) as adapter:
        # One audit, k passes inside the probe -- rather than k audits with the
        # rate counted out here.
        report = audit(adapter, {"challenger": challenger, "challenger_passes": args.k})
    probe = [r for r in report.results if r.family == "reward_hackability"][0]
    per_task = next(iter(probe.detail.get("per_task", {}).values()), {})

    hits = per_task.get("hits", 0)
    scored = per_task.get("passes_scored", 0)
    silent = per_task.get("passes_silent", 0)
    attempts = [
        {
            "run": i + 1,
            "found": (entry["best_gap"] or 0.0) >= 0.5,
            "best_gap": entry["best_gap"],
            "policy": entry["policy"],
        }
        for i, entry in enumerate(per_task.get("per_pass", []))
    ]
    print(
        f"  {hits}/{scored} passes found the exploit"
        + (f" ({silent} pass(es) produced nothing)" if silent else "")
        + f"  {time.time() - started:.0f}s"
    )

    body = {
        "task": args.task,
        "challenger": f"scripted+prompted[{client.name}]",
        "k": args.k,
        "turns": args.turns,
        "hits": hits,
        "passes_scored": scored,
        "passes_silent": silent,
        # Read out of the probe, not recomputed here. `scored` rather than
        # `args.k` is the denominator on purpose: a pass in which the attacker
        # produced nothing measured nothing, and counting it as a miss would
        # report an unreachable model as an environment that held.
        "hit_rate": per_task.get("hit_rate"),
        "attempts": attempts,
        "note": (
            "A probe backed by a sampled model is not a deterministic check. Reporting a "
            "single successful run as a capability claim would overstate what the evidence "
            "supports, which is why this is hits/k rather than 'it works'. The rate is "
            "computed by RewardHackability itself (ctx['challenger_passes']); this script "
            "sets k, reads hit_rate back and writes the artifact."
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(body, indent=2))
    rate = per_task.get("hit_rate") or 0.0
    print(f"\n{hits}/{scored} passes found the exploit (hit rate {rate:.0%})")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
