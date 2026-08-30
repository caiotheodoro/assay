# scripts/

Twenty files, but only five of them are things a reader runs. The rest generate
one figure each, or exist because a rejected experiment is still evidence.

Everything here writes into `results/`. Nothing here is imported by
`src/assay/` — the package does not depend on this directory.

## The five entry points

Run in this order to rebuild every number in the README from scratch. Only the
first needs anything unusual (Docker, for the Harbor tasks), and it degrades to
19 environments without it rather than failing.

| | Script | Writes | What it is |
|---|---|---|---|
| 1 | `full_run.py` | `results/full_run.json` | Every arm over the audited corpus. The measurement the other four read. ~22s, no GPU, no API key. |
| 2 | `intervals.py` | `results/intervals*.json` | Bootstrap CIs and paired differences — the "what holds, and what does not" table. |
| 3 | `baselines.py` | `results/baselines.json` | The five trivial policies on all four cost profiles, including the two Assay loses. |
| 4 | `real_check_env.py` | `results/real_check_env.json` | Runs the *actual* gymnasium and stable-baselines3 checkers. The incumbent number rests on this, not on a reimplementation of them. |
| 5 | `export_trajectories.py` | `results/trajectories/` | One readable run per agent, misses included. Read this if you only read one thing. |

```bash
uv run --extra adapters python scripts/full_run.py
uv run --extra adapters python scripts/intervals.py --resamples 10000 --seed 11
uv run --extra adapters python scripts/baselines.py
uv run --extra gym python scripts/real_check_env.py
uv run --extra adapters python scripts/export_trajectories.py
```

## Everything else

Implementation details of one section of the README, or of one document in
`docs/`. Grouped by what they support.

**Does an agent beat the script?** (README § *Does an agent find what a script cannot?*)

- `challenger_ablation.py` — scripted vs prompted vs `claude-cli` on `harbor/self-graded`.
- `challenger_reliability.py` — the same arm four times, because one run is not a capability.
- `publish_collection.py` — groups the published artifacts into one Hugging Face
  collection. Dry run by default; every figure in the blurb is re-derived from
  `results/` and both Hub length limits are gated rather than discovered on upload.
- `challenger_calibration.py` — whether the Challenger's own `solves_the_task` self-report can be trusted.

**Against defects this repo did not plant** (README § *Where Assay sits in the field*)

- `tau2_fetch.py` — downloads the two pinned τ²-bench snapshots. Run before `tau2_recall.py`.
- `tau2_recall.py` — recall against the 62 defects an independent team confirmed.
- `sab_benchguard_recall.py` — scores Assay through *BenchGuard's* `eval/match.py` and `eval/metrics.py`. Deliberately computes no recall itself.
- `sab_metadata_probe.py` — a rejected experiment, kept because the rejection is the finding.

**The trained Challenger, which did not work** (`docs/changelog/40-grpo-challenger.md`)

- `reward_landscape.py` — what the exploit-gap reward pays per environment, before any training.
- `env_health_report.py` — the environment-health block; where the "99.7% of groups had zero reward spread" number comes from.
- `train_holdout_dedup.py` — near-duplicate audit of the GRPO holdout against its training set.

**Label quality**

- `second_labelling.py` — a blinded second pass over the planted-defect corpus.
- `label_agreement.py` — Cohen's κ between that and the repo's hand labels. Run `second_labelling.py` first.

**The wild sweep** (README § *Two real defects*)

- `wild_sweep.py` — sweeps the published `inspect_evals` registry. Where `paws` was found.

**Repo plumbing**

- `merge_changelog.py` — merges `docs/changelog/NN-*.md` into `docs/CHANGELOG.md`. `--check` fails if the merge is stale; run it after editing any fragment.
- `publish_hf.py` — stages and gates the Hugging Face artifacts. Uploads nothing without an explicit flag.
