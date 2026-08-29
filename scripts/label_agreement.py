"""Cohen's kappa between the repo's hand labels and a blinded second labelling.

    uv run --extra adapters python scripts/second_labelling.py --runs 3
    uv run --extra adapters python scripts/label_agreement.py

Reads `results/second_labelling.json`, which is produced by a model that never
saw the existing labels, and scores it against `assay.corpus.ground_truth()`.
Pure arithmetic: no model is called here.

Three numbers, and the third is the one that stops the first two being
over-read:

  kappa(A, B)   the headline. Rater A is the repo's catalogue; rater B is the
                second labelling, pooled by majority across its independent runs.
  kappa(B_i, B_j)  the rater-noise floor. A sampled labeller disagrees with
                itself, and kappa(A, B) cannot be interpreted without knowing by
                how much. If B agrees with A about as well as it agrees with
                itself, the disagreement is the rater, not the labels.
  the disagreements themselves, listed. Per the brief: where the two labellings
                differ, the difference IS the finding.

Ground truth is NOT edited to match. Retro-fitting the corpus to a second
opinion would invalidate every published number and would be the exact move this
project forbids -- "never adjust ground truth to match what a tool reported".
Disagreements are published and adjudicated in prose; any label that turns out
to be genuinely wrong is a separate, deliberate change with its own re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.agreement import compare, interpret  # noqa: E402
from assay.corpus import ground_truth  # noqa: E402
from assay.runconfig import git_revision  # noqa: E402
from assay.types import DefectClass  # noqa: E402


def as_labelling(raw: dict[str, list[str]]) -> dict[str, frozenset[DefectClass]]:
    return {
        env: frozenset(DefectClass(name) for name in names)
        for env, names in raw.items()
    }


def majority(runs: list[dict[str, list[str]]]) -> dict[str, frozenset[DefectClass]]:
    """Pool the independent runs cell by cell: a class is labelled if it is
    labelled in strictly more than half the runs that covered that environment.

    Pooling by majority rather than union or intersection because both of those
    are biased by k: a union gets more defect-happy the more runs you do, an
    intersection gets more conservative, and neither converges on what the rater
    believes.
    """
    envs = sorted({env for run in runs for env in run})
    out = {}
    for env in envs:
        covering = [run[env] for run in runs if env in run]
        counts = Counter(name for names in covering for name in names)
        out[env] = frozenset(
            DefectClass(name)
            for name, n in counts.items()
            if n * 2 > len(covering)
        )
    return out


def load_family(path: Path) -> tuple[str, list[dict[str, list[str]]], dict]:
    payload = json.loads(path.read_text())
    runs = [run["labels"] for run in payload["runs"]]
    name = payload.get("rater", {}).get("config", {}).get("client") or path.stem
    return name, runs, payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--labelling",
        nargs="*",
        default=[
            "results/second_labelling.json",
            "results/second_labelling_qwen.json",
        ],
        help="one or more second-labelling files, each from a different rater "
        "family. Two families are better than one: correlated error between two "
        "runs of the same model is not independent evidence, and "
        "eval-methodology.md B2 says to judge from a different model family.",
    )
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="results/label_agreement.json")
    args = ap.parse_args()

    families: dict[str, list[dict[str, list[str]]]] = {}
    missing_files: list[str] = []
    for name in args.labelling:
        path = Path(name)
        if not path.exists():
            missing_files.append(name)
            continue
        family, runs, _payload = load_family(path)
        if runs:
            families[family] = runs
    if not families:
        print(
            f"FAILED: none of {args.labelling} is present. Run "
            "scripts/second_labelling.py first -- it needs a model, and a kappa "
            "computed against a labelling that does not exist would be a number "
            "about nothing.",
            file=sys.stderr,
        )
        return 1
    if missing_files:
        print(
            f"NOTE: {missing_files} not present; the panel is smaller than intended "
            "and that is recorded in the output rather than left implicit.",
            file=sys.stderr,
        )

    # The primary rater is the first family that was actually produced, so the
    # headline number does not silently change identity when one file is absent.
    primary = next(iter(families))
    runs = families[primary]

    rater_a = ground_truth()
    rater_b = majority(runs)
    shared = sorted(set(rater_a) & set(rater_b))
    rater_a = {env: rater_a[env] for env in shared}
    rater_b = {env: rater_b[env] for env in shared}

    headline = compare(rater_a, rater_b, resamples=args.resamples, seed=args.seed)

    # The rater against itself. Without this, kappa(A, B) cannot be read: a low
    # value might mean the labels are unreliable, or just that B is noisy.
    self_pairs = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            a_i = as_labelling(runs[i])
            b_j = as_labelling(runs[j])
            common = sorted(set(a_i) & set(b_j))
            block = compare(
                {e: a_i[e] for e in common},
                {e: b_j[e] for e in common},
                resamples=0,
                seed=args.seed,
            )
            self_pairs.append(
                {
                    "runs": [i + 1, j + 1],
                    "cohen_kappa": block["cohen_kappa"],
                    "percent_agreement": block["percent_agreement"],
                    "n_environments_exact_set_match": block["n_environments_exact_set_match"],
                    "n_environments": block["n_environments"],
                }
            )
    self_kappas = [p["cohen_kappa"] for p in self_pairs if p["cohen_kappa"] is not None]
    self_mean = round(sum(self_kappas) / len(self_kappas), 4) if self_kappas else None

    # Per-run against A, so a single bad run cannot hide inside the majority.
    per_run = []
    for i, run in enumerate(runs, start=1):
        b_i = as_labelling(run)
        common = sorted(set(rater_a) & set(b_i))
        block = compare(
            {e: rater_a[e] for e in common},
            {e: b_i[e] for e in common},
            resamples=0,
            seed=args.seed,
        )
        per_run.append(
            {
                "run": i,
                "cohen_kappa": block["cohen_kappa"],
                "percent_agreement": block["percent_agreement"],
                "n_environments_exact_set_match": block["n_environments_exact_set_match"],
                "n_environments": block["n_environments"],
                "n_disagreements": len(block["disagreements"]),
            }
        )

    # Every family against the catalogue, and against each other. Two runs of
    # one model share its blind spots; two model families do not, so a
    # disagreement both families make is evidence about the label and a
    # disagreement only one makes is evidence about the rater.
    panel: dict[str, dict] = {}
    for family, family_runs in families.items():
        b = majority(family_runs)
        common = sorted(set(rater_a) & set(b))
        block = compare(
            {e: rater_a[e] for e in common},
            {e: b[e] for e in common},
            resamples=args.resamples if family == primary else 0,
            seed=args.seed,
        )
        panel[family] = {
            "n_runs": len(family_runs),
            "cohen_kappa": block["cohen_kappa"],
            "interpretation": block["interpretation"],
            "percent_agreement": block["percent_agreement"],
            "bootstrap": block["bootstrap"],
            "n_environments_exact_set_match": block["n_environments_exact_set_match"],
            "n_environments": block["n_environments"],
            "disagreements": block["disagreements"],
        }

    cross_family = None
    if len(families) > 1:
        names = list(families)
        first, second = majority(families[names[0]]), majority(families[names[1]])
        common = sorted(set(first) & set(second))
        cross = compare(
            {e: first[e] for e in common},
            {e: second[e] for e in common},
            resamples=0,
            seed=args.seed,
        )
        cross_family = {
            "families": names[:2],
            "cohen_kappa": cross["cohen_kappa"],
            "interpretation": cross["interpretation"],
            "n_environments_exact_set_match": cross["n_environments_exact_set_match"],
            "n_environments": cross["n_environments"],
            "why": (
                "two independent readers from different model families agreeing "
                "with each other and disagreeing with the catalogue in the same "
                "place is evidence about the label. One family disagreeing alone "
                "is evidence about that rater."
            ),
        }

    body = {
        "spec": "eval-methodology.md:64 -- measure inter-rater agreement (Cohen's "
                "kappa) before trusting human labels",
        "rater_a": "assay.corpus.ground_truth() -- the repo's hand labels",
        "rater_b": (
            f"blinded second labelling by {primary}, majority over {len(runs)} "
            "independent runs; see results/second_labelling*.json for what the "
            "rater is and is not"
        ),
        "rater_families": sorted(families),
        "labelling_files_missing": missing_files,
        "panel": panel,
        "cross_family": cross_family,
        "assay_revision": git_revision(),
        "ground_truth_was_not_edited": (
            "Retro-fitting the corpus to a second opinion would invalidate every "
            "published number and is the move this project forbids. Disagreements "
            "are published, not resolved by overwriting."
        ),
        "agreement": headline,
        "rater_b_against_itself": {
            "pairs": self_pairs,
            "mean_kappa": self_mean,
            "interpretation": interpret(self_mean),
            "why": (
                "a sampled labeller disagrees with itself. kappa(A, B) cannot be "
                "read without this: if B agrees with A about as well as it agrees "
                "with itself, the disagreement is rater noise, not evidence about "
                "the labels."
            ),
        },
        "per_run_against_rater_a": per_run,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2))

    a = headline
    print(f"{a['n_environments']} environments x {len(DefectClass)} classes "
          f"= {a['n_cells']} cells\n")
    print(f"  percent agreement     : {a['percent_agreement']:.4f}   "
          f"(high by construction -- most cells are 'not planted' under both)")
    print(f"  Cohen's kappa         : {a['cohen_kappa']}  ({a['interpretation']})")
    bs = a["bootstrap"]
    print(f"  95% CI (env bootstrap): [{bs['ci95'][0]}, {bs['ci95'][1]}]")
    print(f"  exact set match       : {a['n_environments_exact_set_match']} of "
          f"{a['n_environments']} environments")
    print(f"  mean Jaccard          : {a['mean_jaccard']}")
    c = a["confusion"]
    print(f"  confusion             : both_yes={c['both_yes']} both_no={c['both_no']} "
          f"a_only={c['a_only']} b_only={c['b_only']}")
    print(f"\n  rater B vs itself     : mean kappa {self_mean} ({interpret(self_mean)})")
    for p in self_pairs:
        print(f"    runs {p['runs']}: kappa {p['cohen_kappa']}, "
              f"{p['n_environments_exact_set_match']}/{p['n_environments']} exact")
    print("\n  per run against rater A:")
    for r in per_run:
        print(f"    run {r['run']}: kappa {r['cohen_kappa']}, "
              f"{r['n_environments_exact_set_match']}/{r['n_environments']} exact, "
              f"{r['n_disagreements']} disagreements")

    print("\n  panel -- each rater family against the catalogue:")
    for family, blk in panel.items():
        print(f"    {family:26} kappa {str(blk['cohen_kappa']):>8} "
              f"({blk['interpretation']}), "
              f"{blk['n_environments_exact_set_match']}/{blk['n_environments']} exact, "
              f"{len(blk['disagreements'])} disagreements")
    if cross_family:
        print(f"\n  cross-family {cross_family['families']}: "
              f"kappa {cross_family['cohen_kappa']} "
              f"({cross_family['interpretation']}), "
              f"{cross_family['n_environments_exact_set_match']}/"
              f"{cross_family['n_environments']} exact")

    print("\n  per class (kappa, prevalence A / B, cells where only one rater said yes):")
    for name, row in a["per_class"].items():
        print(f"    {name:24} k={str(row['kappa']):>8}  "
              f"prev {row['prevalence_rater_a']:.3f}/{row['prevalence_rater_b']:.3f}  "
              f"a_only={row['a_only']:2} b_only={row['b_only']:2}")

    print(f"\n  DISAGREEMENTS ({len(a['disagreements'])} environments):")
    for row in a["disagreements"]:
        print(f"    {row['env_id']}")
        print(f"      rater A only: {row['a_only'] or '-'}")
        print(f"      rater B only: {row['b_only'] or '-'}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
