#!/usr/bin/env python3
"""Post hoc prevalence-aware and restricted constant floors on all cost profiles.

Reads the unchanged `results/full_run.json` and evaluates three tighter
input-ignoring constant policies alongside `flag_everything`, on both the full
corpus (n=33) and the genuinely external split (n=8):

1. `flag_present` (restricted floor): flags every defect class planted in at
   least one environment of the evaluated set (`k_d >= 1`), omitting classes
   that never occur there.
2. `prevalence_floor` (in-sample Bayes-optimal constant policy, Elkan 2001):
   under profile miss costs M_d and false-alarm cost F, flags class d on every
   environment iff corpus prevalence p_d = k_d / N > F / (M_d + F). Achieves
   the minimum expected loss attainable by any constant (input-ignoring) policy
   on that set.
3. `prevalence_floor_loo` (leave-one-out prevalence-aware constant policy):
   for each environment e, estimates p_{d,-e} = (k_d - I[d in P_e]) / (N - 1)
   from the other N - 1 environments and flags class d on e iff
   p_{d,-e} > F / (M_d + F).

Paired 95% bootstrap intervals for `assay`'s loss saved over each floor use the
same environment-resampling routine as `scripts/intervals.py` (10,000 resamples,
seed 11).

Pre-analysis specification: `docs/changelog/129-paper-v2-preanalysis-plan.md`.
All figures here are post hoc and replace no pre-registered result.

Usage:
  uv run --extra adapters --extra sweep --extra openenv --extra tau2 \
      python scripts/prevalence_floor.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from assay.corpus import EnvAuthor, provenance  # noqa: E402
from assay.costs import CostProfile, load  # noqa: E402
from assay.metrics import ArmResult, Outcome  # noqa: E402
from assay.types import DEFAULT_SEVERITY, DefectClass, Severity  # noqa: E402
from intervals import bootstrap, load_arms  # noqa: E402

PROFILES = ["research-run", "production-training", "benchmark-publication", "flat"]


def _revision() -> dict[str, object]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def _threshold(miss_cost: float, false_alarm: float) -> float:
    return false_alarm / (miss_cost + false_alarm)


def _should_flag(p: float, miss_cost: float, false_alarm: float) -> bool:
    """Flag class d iff expected miss cost strictly exceeds expected false-alarm cost."""
    return p * miss_cost > (1.0 - p) * false_alarm


def build_floor_arms(
    truth: dict[str, frozenset[DefectClass]],
    profile: CostProfile,
) -> tuple[dict[str, ArmResult], dict[str, object]]:
    """Construct `flag_everything`, `flag_present`, `prevalence_floor`, and LOO."""
    envs = sorted(truth)
    n = len(envs)
    counts = {d: sum(1 for e in envs if d in truth[e]) for d in DefectClass}
    present = frozenset(d for d, k in counts.items() if k >= 1)

    in_sample_flagged = frozenset(
        d
        for d in DefectClass
        if n > 0 and _should_flag(counts[d] / n, profile.cost_of_miss(DEFAULT_SEVERITY[d]), profile.false_alarm)
    )

    everything = frozenset(DefectClass)
    arms = {
        "flag_everything": ArmResult(
            "flag_everything",
            [Outcome(e, truth[e], everything) for e in envs],
        ),
        "flag_present": ArmResult(
            "flag_present",
            [Outcome(e, truth[e], present) for e in envs],
        ),
        "prevalence_floor": ArmResult(
            "prevalence_floor",
            [Outcome(e, truth[e], in_sample_flagged) for e in envs],
        ),
    }

    loo_outcomes: list[Outcome] = []
    for e in envs:
        flagged_e = frozenset(
            d
            for d in DefectClass
            if n > 1
            and _should_flag(
                (counts[d] - (1 if d in truth[e] else 0)) / (n - 1),
                profile.cost_of_miss(DEFAULT_SEVERITY[d]),
                profile.false_alarm,
            )
        )
        loo_outcomes.append(Outcome(e, truth[e], flagged_e))
    arms["prevalence_floor_loo"] = ArmResult("prevalence_floor_loo", loo_outcomes)

    meta = {
        "thresholds_by_severity": {
            sev.value: round(_threshold(profile.cost_of_miss(sev), profile.false_alarm), 6)
            for sev in Severity
        },
        "n_present_classes": len(present),
        "present_classes": sorted(d.value for d in present),
        "prevalence_floor_flagged_classes": sorted(d.value for d in in_sample_flagged),
        "prevalence_floor_n_flagged_classes": len(in_sample_flagged),
    }
    return arms, meta


def evaluate_subset(
    payload: dict,
    keep,
    resamples: int,
    seed: int,
) -> dict[str, object]:
    loaded_arms, truth = load_arms(payload, keep)
    # Keep deterministic env ordering matching `build_floor_arms`.
    assay_by_env = {o.env_id: o for o in loaded_arms["assay"].outcomes}
    envs = sorted(truth)
    assay_arm = ArmResult("assay", [assay_by_env[e] for e in envs])

    out_profiles: dict[str, object] = {}
    for pname in PROFILES:
        profile = load(pname)
        floor_arms, meta = build_floor_arms(truth, profile)
        combined = {"assay": assay_arm, **floor_arms}
        boot = bootstrap(combined, profile, resamples, seed)
        out_profiles[pname] = {
            **meta,
            "arms": {
                name: {
                    **arm.profile_row(profile),
                    "ci95": boot[name]["expected_loss"]["ci95"],
                }
                for name, arm in combined.items()
            },
            "assay_saved_vs": {
                other: boot["assay"]["loss_saved_vs"][other]
                for other in ("flag_everything", "flag_present", "prevalence_floor", "prevalence_floor_loo")
            },
        }
    return {
        "n_environments": len(truth),
        "n_planted": sum(len(v) for v in truth.values()),
        "environments": envs,
        "profiles": out_profiles,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default="results/full_run.json")
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="results/prevalence_floor.json")
    args = ap.parse_args()

    payload = json.loads((ROOT / args.results).read_text())
    prov = provenance()

    all_block = evaluate_subset(payload, None, args.resamples, args.seed)
    ext_block = evaluate_subset(
        payload,
        lambda e: e in prov and prov[e].env_author is EnvAuthor.EXTERNAL,
        args.resamples,
        args.seed,
    )

    body = {
        "measurement": "post hoc restricted and prevalence-aware constant floors",
        "post_hoc": True,
        "preanalysis_plan": "docs/changelog/129-paper-v2-preanalysis-plan.md",
        "harness": (
            "uv run --extra adapters --extra sweep --extra openenv --extra tau2 "
            "python scripts/prevalence_floor.py"
        ),
        "assay_revision": _revision(),
        "source": args.results,
        "resamples": args.resamples,
        "seed": args.seed,
        "resampling_unit": "environment",
        "n_environments": all_block["n_environments"],
        "n_planted_defects": all_block["n_planted"],
        "n_defect_classes": len(DefectClass),
        "splits": {
            "all": all_block,
            "external-envs": ext_block,
        },
    }

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(body, indent=2) + "\n")
    print(f"wrote {args.out}\n")
    for split_name, block in body["splits"].items():
        print(f"=== {split_name} (n={block['n_environments']}, planted={block['n_planted']}) ===")
        for pname in PROFILES:
            p = block["profiles"][pname]
            a = p["arms"]["assay"]["expected_loss"]
            fe = p["arms"]["flag_everything"]["expected_loss"]
            fp = p["arms"]["flag_present"]["expected_loss"]
            pf = p["arms"]["prevalence_floor"]["expected_loss"]
            loo = p["arms"]["prevalence_floor_loo"]["expected_loss"]
            sv_fp = p["assay_saved_vs"]["flag_present"]
            sv_pf = p["assay_saved_vs"]["prevalence_floor"]
            sv_loo = p["assay_saved_vs"]["prevalence_floor_loo"]
            print(
                f"  {pname:22s} assay={a:6.1f} | fe={fe:6.1f} | "
                f"present={fp:6.1f} (saved {sv_fp['point']:6.1f} {sv_fp['ci95']} sep={sv_fp['separated']}) | "
                f"prev={pf:6.1f} (saved {sv_pf['point']:6.1f} {sv_pf['ci95']} sep={sv_pf['separated']}) | "
                f"loo={loo:6.1f} (saved {sv_loo['point']:6.1f} {sv_loo['ci95']} sep={sv_loo['separated']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
