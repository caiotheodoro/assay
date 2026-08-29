"""Near-duplicate audit of the GRPO holdout against the GRPO training set.

    uv run --extra adapters python scripts/train_holdout_dedup.py

`harbor/self-graded` was held out of training from fifteen environments so the
ablation would not be train-on-test, and that holdout was never checked for
near-duplicates -- only for identity, implicitly, by not being in the list.

`hf-publication-specs.md` 11.4 is about exactly this case: train and eval drawn
from the same generator under different seeds, where exact hashing sees nothing
and the templates are the same. Assay's fixtures are a harder version of the
same problem. They are not merely same-generator: they are same-author, written
in one sitting, deliberately sharing the shape "a shell task with a verifier".
If any prompt-level check ought to fire, it is this one.

Parameters are the ones the spec names and `src/assay/minhash.py` already
implements: 5-word shingles, 128 permutations, Jaccard >= 0.8.

Two comparisons, because the answer differs and reporting only one would be a
choice presented as a measurement:

  user_turn    the task-specific half of the prompt. The honest signal.
  full_prompt  system + user, i.e. every token the model actually saw. The
               system preamble is byte-identical across every row, so this
               number is inflated by construction and is reported as a
               control, not as the result.

Needs Docker: five of the sixteen environments are Harbor tasks and their
manifests come from real containers. Without the daemon the Harbor rows drop
out, and the script says so and exits nonzero rather than publishing a number
computed over a corpus that silently shrank.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.adapter import NotSupported  # noqa: E402
from assay.challenger.grpo import MAX_ACTIONS, chat_prompt, prompt_for  # noqa: E402
from assay.minhash import (  # noqa: E402
    estimated_jaccard,
    exact_signature,
    shingles,
    signature,
)
from assay.train.reward import trainable_environments  # noqa: E402

#: The run this audit is about. Both spot-GPU runs used these flags.
TRAIN_ONLY = ["fixture", "harbor"]
HOLDOUT = ["harbor/self-graded"]


def true_jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def collect(pool, max_actions: int) -> tuple[list[dict], dict[str, str]]:
    """One row per (environment, task): the prompt the trainer would build."""
    rows: list[dict] = []
    excluded: dict[str, str] = {}
    for env_id in pool.env_ids():
        adapter = pool.get(env_id)
        for task in adapter.manifest().tasks:
            try:
                system, user = prompt_for(adapter, task.task_id, max_actions)
            except NotSupported as exc:
                excluded[f"{env_id}/{task.task_id}"] = str(exc)
                continue
            full = "\n".join(m["content"] for m in chat_prompt(system, user))
            rows.append(
                {
                    "env_id": env_id,
                    "task_id": task.task_id,
                    "user_turn": user,
                    "full_prompt": full,
                }
            )
    return rows, excluded


def histogram(values: list[float], edges: list[float]) -> dict[str, int]:
    out = {}
    for lo, hi in zip(edges, edges[1:]):
        label = f"[{lo:.1f},{hi:.1f})"
        out[label] = sum(1 for v in values if lo <= v < hi)
    out[f"[{edges[-1]:.1f},1.0]"] = sum(1 for v in values if v >= edges[-1])
    return out


def audit(
    train_rows: list[dict], holdout_rows: list[dict], field: str, *, shingle: int,
    num_perm: int, threshold: float,
) -> dict:
    train_sigs = [(r, signature(r[field], shingle, num_perm)) for r in train_rows]
    train_grams = {id(r): shingles(r[field], shingle) for r, _ in train_sigs}
    train_exact = {}
    for r in train_rows:
        train_exact.setdefault(exact_signature(r[field]), []).append(
            f"{r['env_id']}/{r['task_id']}"
        )

    pairs, nearest, exact_hits = [], [], []
    for h in holdout_rows:
        h_id = f"{h['env_id']}/{h['task_id']}"
        h_sig = signature(h[field], shingle, num_perm)
        h_grams = shingles(h[field], shingle)
        if exact_signature(h[field]) in train_exact:
            exact_hits.append(
                {"holdout": h_id, "train": train_exact[exact_signature(h[field])]}
            )
        best = None
        for r, sig in train_sigs:
            est = estimated_jaccard(h_sig, sig)
            exact_j = true_jaccard(h_grams, train_grams[id(r)])
            row = {
                "holdout": h_id,
                "train": f"{r['env_id']}/{r['task_id']}",
                "minhash_jaccard": round(est, 4),
                "true_jaccard": round(exact_j, 4),
            }
            pairs.append(row)
            if best is None or est > best["minhash_jaccard"]:
                best = row
        if best:
            nearest.append(best)

    over = [p for p in pairs if p["minhash_jaccard"] >= threshold]
    values = [p["minhash_jaccard"] for p in pairs]
    return {
        "field": field,
        "n_pairs": len(pairs),
        "exact_overlap_count": len(exact_hits),
        "exact_overlaps": exact_hits,
        "near_duplicate_count": len(over),
        "near_duplicates": sorted(
            over, key=lambda p: -p["minhash_jaccard"]
        )[:50],
        "max_similarity": round(max(values), 4) if values else None,
        "mean_similarity": round(sum(values) / len(values), 4) if values else None,
        "nearest_neighbour_per_holdout_task": sorted(
            nearest, key=lambda p: -p["minhash_jaccard"]
        ),
        "similarity_histogram": histogram(
            values, [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shingle-size", type=int, default=5)
    ap.add_argument("--num-perm", type=int, default=128)
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--max-actions", type=int, default=MAX_ACTIONS)
    ap.add_argument(
        "--from-run",
        default="results/assay-challenger-r1/run.json",
        help="take the training environment list from this run manifest rather "
        "than from today's corpus. The corpus has grown since both GPU runs "
        "(harbor/shared-tests did not exist yet), and an audit of a set the run "
        "never trained on is an audit of nothing.",
    )
    ap.add_argument("--out", default="results/train_holdout_dedup.json")
    args = ap.parse_args()

    train_sel = trainable_environments(only=TRAIN_ONLY, holdout=HOLDOUT)
    print(train_sel.report(), flush=True)
    hold_sel = trainable_environments(only=["harbor"])

    try:
        train_rows, train_excluded = collect(train_sel.pool, args.max_actions)
        hold_all, hold_excluded = collect(hold_sel.pool, args.max_actions)
    finally:
        train_sel.pool.close()
        hold_sel.pool.close()

    holdout_rows = [r for r in hold_all if r["env_id"] in HOLDOUT]

    run_manifest: dict = {}
    run_path = Path(args.from_run) if args.from_run else None
    if run_path and run_path.exists():
        run_manifest = json.loads(run_path.read_text())
        as_trained = set(run_manifest.get("environments", []))
        drifted = sorted({r["env_id"] for r in train_rows} - as_trained)
        train_rows = [r for r in train_rows if r["env_id"] in as_trained]
        missing = sorted(as_trained - {r["env_id"] for r in train_rows})
        if drifted:
            print(
                f"\nrestricting to the set {run_path} actually trained on; "
                f"dropping {drifted} (added to the corpus after the run)",
                flush=True,
            )
        if missing:
            print(
                f"WARNING: {missing} were trained on but cannot be rebuilt here; "
                "the audit is over a smaller training set than the run used",
                file=sys.stderr,
            )

    if not holdout_rows:
        print(
            "\nFAILED: no holdout prompts could be built. `harbor/self-graded` is a "
            "Harbor task and needs the Docker daemon; a near-duplicate audit over an "
            "empty holdout would report a clean zero for the wrong reason.",
            file=sys.stderr,
        )
        return 1

    trained_envs = sorted({r["env_id"] for r in train_rows})
    body = {
        "what": (
            "near-duplicate audit of the GRPO holdout against the GRPO training set, "
            "per hf-publication-specs.md 11.4"
        ),
        "runs_this_covers": ["results/assay-challenger-r1", "results/assay-challenger-r2"],
        "training_set_taken_from": args.from_run or "today's corpus",
        "prompt_counts_in_the_run": run_manifest.get("prompt_counts", {}),
        "parameters": {
            "shingle_size": args.shingle_size,
            "num_perm": args.num_perm,
            "threshold": args.threshold,
            "max_actions": args.max_actions,
            "implementation": "src/assay/minhash.py",
        },
        "train_environments": trained_envs,
        "n_train_environments": len(trained_envs),
        "n_train_prompts": len(train_rows),
        "holdout_environments": HOLDOUT,
        "n_holdout_prompts": len(holdout_rows),
        "excluded_train": train_excluded,
        "excluded_holdout": hold_excluded,
        "unavailable_ecosystems": train_sel.unavailable,
        "limit": (
            "This bounds prompt-level overlap between this training set and this "
            "holdout. It says nothing about whether Qwen3-1.7B saw similar text in "
            "pretraining, and there is no way to check that from here."
        ),
        "audits": {},
    }
    for field in ("user_turn", "full_prompt"):
        body["audits"][field] = audit(
            train_rows,
            holdout_rows,
            field,
            shingle=args.shingle_size,
            num_perm=args.num_perm,
            threshold=args.threshold,
        )
    body["audits"]["full_prompt"]["note"] = (
        "control, not the result: the system preamble is byte-identical on every "
        "row, so this similarity is inflated by construction"
    )

    # A count of colliding ENVIRONMENTS understates the exposure. Training rows
    # were sampled per environment, so what matters is what fraction of the
    # steps the model spent looking at the holdout's exact prompt.
    exact_env_ids = {
        t.rsplit("/", 1)[0]
        for hit in body["audits"]["user_turn"]["exact_overlaps"]
        for t in hit["train"]
    }
    counts = run_manifest.get("prompt_counts", {})
    if counts:
        colliding = sum(n for env, n in counts.items() if env in exact_env_ids)
        total = sum(counts.values())
        body["holdout_prompt_exposure"] = {
            "colliding_train_environments": sorted(exact_env_ids),
            "colliding_train_rows": colliding,
            "total_train_rows": total,
            "fraction_of_training_rows": round(colliding / total, 4) if total else None,
            "what_this_means": (
                "The holdout held out the ENVIRONMENT -- its verifier, and therefore "
                "the reward -- but not the PROMPT. The prompt the trained Challenger "
                "is given on harbor/self-graded is byte-identical to one it was "
                "optimised against for this fraction of training. Conditioning is "
                "not held out; only the thing being scored is."
            ),
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2, sort_keys=True))

    print(
        f"\n{len(train_rows)} training prompts over {len(trained_envs)} environments"
        f" vs {len(holdout_rows)} holdout prompts"
    )
    for field, block in body["audits"].items():
        print(f"\n--- {field}  ({block['n_pairs']} pairs)")
        print(f"    exact overlap        : {block['exact_overlap_count']}")
        print(
            f"    near-dups (J >= {args.threshold}) : {block['near_duplicate_count']}"
        )
        print(f"    max similarity       : {block['max_similarity']}")
        print(f"    mean similarity      : {block['mean_similarity']}")
        print("    nearest neighbour per holdout task:")
        for row in block["nearest_neighbour_per_holdout_task"]:
            print(
                f"      {row['holdout']:32} -> {row['train']:34} "
                f"minhash {row['minhash_jaccard']:.4f}  true {row['true_jaccard']:.4f}"
            )
        print("    similarity histogram :")
        for label, n in block["similarity_histogram"].items():
            if n:
                print(f"      {label:12} {n}")
    exposure = body.get("holdout_prompt_exposure")
    if exposure:
        print(
            f"\nholdout prompt exposure: {exposure['colliding_train_rows']} of "
            f"{exposure['total_train_rows']} training rows "
            f"({exposure['fraction_of_training_rows']:.1%}) carried a prompt "
            f"byte-identical to the holdout's, via "
            f"{exposure['colliding_train_environments']}"
        )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
