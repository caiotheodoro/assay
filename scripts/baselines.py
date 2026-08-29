"""The five trivial policies `criteria.md:52` requires, on every cost profile.

    uv run --extra adapters python scripts/baselines.py

Reads the ground truth out of `results/full_run.json` -- the planted defects,
not anything Assay reported -- and scores every trivial policy against it. The
point of the exercise is the denominator: `normalized_loss` divides by the BEST
policy that ignores its input, so which policies are in that set decides what
"Assay beats the floor" means.

Two of the five were missing until this script existed. Both are now here, and
neither changes the floor on this corpus -- which is a result, published as one,
not a reason to have skipped them.

`stratified_random` is the only stochastic policy in the list, so it gets three
numbers rather than one: the seeded realisation used as the arm, the exact
closed-form expectation, and a Monte-Carlo spread over seeds. Reporting a single
draw of a random baseline is the same error as reporting pass@1 and calling it
pass^k, which this project already has on the record against itself.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.costs import CostProfile, all_profiles  # noqa: E402
from assay.metrics import (  # noqa: E402
    ArmResult,
    Outcome,
    base_rates,
    expected_stratified_loss,
    modal_defect,
    oracle_arm,
    stratified_random_arm,
    stratified_random_setwise_arm,
    trivial_arms,
)
from assay.types import DefectClass  # noqa: E402


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    idx = (len(ordered) - 1) * q
    low, high = int(idx), min(int(idx) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (idx - low)


def monte_carlo(
    ground_truth: dict[str, frozenset[DefectClass]],
    profile: CostProfile,
    builder,
    draws: int,
    seed: int,
) -> dict[str, float]:
    """Spread of a stochastic policy's loss over independent draws."""
    rng = random.Random(seed)
    losses = [
        builder(ground_truth, rng.randrange(1 << 30)).expected_loss(profile)
        for _ in range(draws)
    ]
    return {
        "draws": draws,
        "mean": round(sum(losses) / len(losses), 4),
        "p2.5": round(_percentile(losses, 0.025), 4),
        "p97.5": round(_percentile(losses, 0.975), 4),
        "min": round(min(losses), 4),
        "max": round(max(losses), 4),
        "_losses": losses,
    }


def draw_percentile(losses: list[float], value: float) -> float:
    """Where the fixed-seed realisation sits inside its own policy's spread.

    Worth printing rather than assuming. On this corpus the seed-11 draw of
    `stratified_random` lands BELOW the 2.5th percentile of its own Monte-Carlo
    distribution -- an unusually strong draw for the baseline. It does not move
    any conclusion, because the floor is set by a policy an order of magnitude
    cheaper, but a fixed seed sitting outside its own interval is exactly the
    kind of thing that goes unnoticed when only the point estimate is printed.
    """
    return round(sum(1 for x in losses if x <= value) / len(losses), 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results/full_run.json")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--draws", type=int, default=10000)
    ap.add_argument("--out", default="results/baselines.json")
    args = ap.parse_args()

    payload = json.loads(Path(args.results).read_text())
    truth = {
        env: frozenset(DefectClass(d) for d in row["planted"])
        for env, row in payload["per_env"].items()
    }
    assay = ArmResult(
        "assay",
        [
            Outcome(env, truth[env], frozenset(DefectClass(d) for d in row["assay_detected"]))
            for env, row in payload["per_env"].items()
        ],
    )

    rates = base_rates(truth)
    body: dict = {
        "n_environments": len(truth),
        "n_planted_defects": sum(len(v) for v in truth.values()),
        "n_defect_classes": len(DefectClass),
        "seed": args.seed,
        "monte_carlo_draws": args.draws,
        "source": args.results,
        "policy_mapping": {
            "always_match": "flag_nothing -- predict the modal label ('healthy') everywhere",
            "always_exception": (
                "always_modal_defect -- predict the single most frequently planted "
                "defect class for every environment"
            ),
            "always_escalate": (
                "flag_everything -- every defect class of every environment goes to a "
                "human; zero misses, unbounded review cost"
            ),
            "stratified_random": (
                "flag each defect class independently at its base rate across the corpus"
            ),
            "oracle": "the planted set exactly; loss 0 by construction",
        },
        "base_rates": {d.value: round(p, 4) for d, p in rates.items() if p > 0},
        "base_rates_zero": sorted(d.value for d, p in rates.items() if p == 0),
        "modal_defect": modal_defect(truth).value,
        "prior_is_the_corpus_itself": (
            "Assay has no train/eval split of its corpus, so stratified_random is "
            "handed the exact distribution it is scored against. That makes the floor "
            "harder than one fit on a held-out split would be -- the conservative "
            "direction for any claim that Assay beats it."
        ),
        "profiles": {},
    }

    arms = trivial_arms(truth, seed=args.seed)
    arms["oracle"] = oracle_arm(truth)
    arms["assay"] = assay

    for name, profile in sorted(all_profiles().items()):
        floor_candidates = {
            k: v.expected_loss(profile)
            for k, v in arms.items()
            if k not in ("oracle", "assay")
        }
        best_floor = min(floor_candidates, key=lambda k: floor_candidates[k])
        l_trivial = floor_candidates[best_floor]
        rows = {}
        for arm_name, arm in sorted(arms.items()):
            row = arm.profile_row(profile)
            row["normalized_loss"] = (
                round(arm.expected_loss(profile) / l_trivial, 4) if l_trivial else None
            )
            rows[arm_name] = row
        rows["stratified_random"]["closed_form_expected_loss"] = round(
            expected_stratified_loss(truth, profile), 4
        )
        mc = monte_carlo(truth, profile, stratified_random_arm, args.draws, args.seed)
        losses = mc.pop("_losses")
        mc["seeded_draw_percentile"] = draw_percentile(
            losses, rows["stratified_random"]["expected_loss"]
        )
        rows["stratified_random"]["monte_carlo"] = mc
        setwise = stratified_random_setwise_arm(truth, args.seed)
        rows["stratified_random_setwise"] = setwise.profile_row(profile)
        rows["stratified_random_setwise"]["normalized_loss"] = (
            round(setwise.expected_loss(profile) / l_trivial, 4) if l_trivial else None
        )
        mc_sw = monte_carlo(
            truth, profile, stratified_random_setwise_arm, args.draws, args.seed
        )
        sw_losses = mc_sw.pop("_losses")
        mc_sw["seeded_draw_percentile"] = draw_percentile(
            sw_losses, rows["stratified_random_setwise"]["expected_loss"]
        )
        rows["stratified_random_setwise"]["monte_carlo"] = mc_sw
        rows["stratified_random_setwise"]["note"] = (
            "not an arm in trivial_arms; the robustness check on reading 'sample the "
            "label prior' set-wise instead of per-class"
        )
        body["profiles"][name] = {
            "description": profile.description.strip(),
            "best_trivial_policy": best_floor,
            "L_trivial": round(l_trivial, 4),
            "L_oracle": 0.0,
            "arms": rows,
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2, sort_keys=True))

    print(f"{len(truth)} environments, {body['n_planted_defects']} planted defects, "
          f"{len(DefectClass)} defect classes\n")
    print(f"base rates (the prior stratified_random samples from), modal = "
          f"{body['modal_defect']}:")
    for d, p in sorted(body["base_rates"].items(), key=lambda kv: -kv[1]):
        print(f"  {d:24} {p:.4f}")
    print()
    for name, block in body["profiles"].items():
        print(f"--- {name}   (floor = {block['best_trivial_policy']}, "
              f"L_trivial = {block['L_trivial']:.1f})")
        print(f"    {'policy':28} {'exp.loss':>10} {'norm':>8} {'recall':>7} {'prec':>7}")
        for arm_name, row in sorted(block["arms"].items(), key=lambda kv: kv[1]["expected_loss"]):
            norm = f"{row['normalized_loss']:.3f}" if row["normalized_loss"] is not None else "-"
            print(f"    {arm_name:28} {row['expected_loss']:>10.1f} {norm:>8} "
                  f"{row['recall']:>7.3f} {row['precision']:>7.3f}")
        sr = block["arms"]["stratified_random"]
        print(f"    stratified_random: seeded draw {sr['expected_loss']:.1f} "
              f"(pct {sr['monte_carlo']['seeded_draw_percentile']:.3f} of its own spread), "
              f"closed form {sr['closed_form_expected_loss']:.1f}, "
              f"MC mean {sr['monte_carlo']['mean']:.1f} "
              f"[{sr['monte_carlo']['p2.5']:.1f}, {sr['monte_carlo']['p97.5']:.1f}]")
        print()

    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
