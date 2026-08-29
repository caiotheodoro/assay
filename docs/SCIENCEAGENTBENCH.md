# ScienceAgentBench — what Assay can and cannot check

## Status

Two of the three defect families BenchGuard reports are **out of reach for Assay by design**,
and the third needs one manual download. Both facts are results, not excuses.

Assay has now been scored against BenchGuard's 12 confirmed defects **using BenchGuard's own
scorer**. The number is **0/12 recall**. See `docs/changelog/61-benchguard-recall.md` for the
run, and `results/sab_benchguard/` for the artefacts.

## What was tried and rejected

`scripts/sab_metadata_probe.py` tests whether instruction defects fall out of the metadata
ScienceAgentBench publishes per task. They do not:

| Rule | INST recall | Fires on | Precision |
|---|---|---|---|
| output path the instruction never names | 5/7 | **61 / 102** | 0.08 |
| input file absent from the dataset tree | 0/7 | 0 / 102 | — |

Measured only against BenchGuard's 12 known-defective tasks, the first rule reads as a
success. Measured against the whole benchmark it flags 60% of it — the flag-everything
trivial policy in disguise, caught by Assay's own trivial-floor rule.

Both numbers reproduce on both published splits (`scripts/sab_benchguard_recall.py
--arm rejected-r1`): rule R1 fires on **61 of 102** either way, and hits 5 of the 12 gold
tasks (26, 31, 34, 35, 67).

**Conclusion: Assay structurally cannot find instruction defects.** "This instruction is
ambiguous" and "this requirement is infeasible" are judgements, and Assay scores nothing
with a judge. Assay and BenchGuard find **disjoint** classes of defect — instruction quality
needs judgement, verifier defects need execution — and neither subsumes the other.

## Two splits, and why the choice changes what a recall number means

SAB publishes two 102-task splits, and the difference is load-bearing:

| Split | File | Gold defects still present |
|---|---|---|
| `original` | `ScienceAgentBench.csv` | 11 present, 1 differs by a typo |
| `verified` | `data/verified-00000-of-00001.parquet` | **3 present, 9 already fixed** |

SAB released `verified` on 2026/04/30 "to mitigate false negatives in evaluation", and that
split already carries BenchGuard's corrected wording for nine of the twelve tasks (12, 26,
29, 31, 32, 34, 35, 67, 92). Only 9, 21 and 78 still contain the defect.

**A detector scored against `verified` is being asked to find text that is no longer there.**
`scripts/sab_benchguard_recall.py` measures this per task rather than assuming it, and
records it under `gold_defect_presence` in every result file. The scoring run defaults to
`--split original` for that reason.

The one `differs_from_both` case is task 34: the CSV reads `extracterd` where BenchGuard's
gold transcription reads `extracted`. A typo, not a third variant.

## BenchGuard's own categories differ from the ones this repo guessed

`scripts/sab_metadata_probe.py` hand-labelled the 12 defects as 7 INST / 4 GT / 1 EVAL. The
machine-readable gold (`eval/data/gold/sab_gold.json`) labels them by `change_type`:

| change_type | count | tasks |
|---|---|---|
| `instruction` | 9 | 9, 12, 26, 29, 31, 34, 35, 67, 92 |
| `file` | 2 | 21, 78 |
| `both` | 1 | 32 |

So the instruction-defect share is **10 of 12**, not 7. The hand labels were a guess; the
gold file is the source of truth and nothing here should be read against the old split.

Also worth recording: that gold file carries `"human_verified": false` and a
`created_with_model` field. The *defects* are author-confirmed (BenchGuard's paper); this
particular JSON encoding of them is model-generated from `eval/data/raw/sab_upted.md`.

## Which of the 12 are reachable without executing anything

Nine of Assay's twelve registered probes are gated on a capability the metadata cannot
supply; the rest need a rollout or the eval script. Measured, not asserted — this table is
the `arm_detail.probes` block of `results/sab_benchguard/assay__original_result.json`:

| Probe | Status | Blocked on |
|---|---|---|
| `gold_passes`, `inverted_fails`, `known_wrong_fails`, `noop_fails` | NOT_APPLICABLE | `SEPARABLE_VERIFIER` (+ gold trajectory / invertible spec / known-wrong) |
| `trivial_floor`, `separability` | NOT_APPLICABLE | `TRIVIAL_POLICIES` / `GRADED_POLICIES` + `SEPARABLE_VERIFIER` |
| `train_eval_leak`, `partial_input_baseline` | NOT_APPLICABLE | `SPLITS` — SAB has no train split at all |
| `seed_determinism` | NOT_APPLICABLE | `SEEDED_RESET` |
| `challenger` | NOT_APPLICABLE | `TRUE_COMPLETION` + `SEPARABLE_VERIFIER` |
| `difficulty_band` | NOT_APPLICABLE | no solve-rate estimate; needs a rollout sampler |
| `assert_traceability` | NOT_APPLICABLE | the gated archive (this is the one the download unlocks) |

**So: none of the 12 gold defects is reachable without execution.** Not 7-of-12, not
2-of-12 — zero. The two `file` defects (21, 78) and the `both` defect (32) would need the
gold programs *and* a Docker run; the nine `instruction` defects need a judge Assay does not
have. The audit verdict is `UNVERIFIED`, which is the correct answer and not the same as
"clean".

## The manual step, if you want the execution probes

The GT and EVAL defects need SAB's gold programs and eval scripts. Those are not on the Hub;
they are in a password-protected archive behind a SharePoint link that requires a browser
session, so this cannot be scripted end to end.

1. Open the benchmark artifacts link in
   [the ScienceAgentBench README](https://github.com/OSU-NLP-Group/ScienceAgentBench)
   (`benchmark_verified.zip`).
2. Unzip with the password `scienceagentbench`.
3. Place the result at `third_party/ScienceAgentBench/benchmark/`.

Then the SAB adapter can drive its Docker execute-and-diff harness the way the Harbor
adapter drives `tests/test.sh`.

**The fetch was retried on 2026-08-29 and is still blocked.** Both `?download=1` forms of
the share link return HTTP 200 with `Content-Type: text/html` after redirecting to
`login.microsoftonline.com/.../oauth2/authorize` — a sign-in page, not the archive. The
password is not the obstacle; an authenticated browser session is.

Passing `--benchmark-root` to the adapter with an `eval_programs/` directory present unlocks
`verifier_asserts` (family 6) as a static read, no Docker. Execution capabilities are still
never declared — see the adapter docstring.

**Redistribution:** the upstream README says plainly *"Please DO NOT redistribute the
unzipped data files online."* Nothing from that archive goes into `caiotheodoro/assay-corpus`
or any other published artifact. Only derived per-task verdicts — which contain no benchmark
content — may be published. `third_party/` is gitignored for the same reason, and the
committed result files have BenchGuard's gold wording redacted down to a sha256.

## A conflict worth stating

Some ScienceAgentBench tasks (the data-visualization ones) are scored by an LLM judge
(`gpt4_visual_judge.py`). Assay's probes assume the verifier is a deterministic function of
the transcript. Against a judge, `inverted_fails` and `known_wrong_fails` are not measuring
verifier integrity — they are measuring a model's mood on the day.

Those tasks must be excluded from any execution audit, with the reason recorded per task,
rather than quietly scored. An environment Assay cannot honestly probe is reported as
`NOT_APPLICABLE`, which is the whole design.

Confirmed upstream: SAB's README states *"A valid OpenAI API key is required since our
evaluation leverages GPT-4o to judge output visualizations."* The judge runs at
`temperature=0.2` with `n=3`, so it is not a deterministic function of the transcript.

The exclusion criterion is **declared `output_fname` is an image**, which is public and
checkable. On that criterion **65 of 102** tasks are excluded, including gold tasks
**9, 31 and 32**. This is a proxy: the eval scripts that import the judge are inside the
gated archive, so the exact set is only confirmable against `benchmark/eval_programs/`.

Excluding a task suppresses findings, never the denominator — BenchGuard's `metrics.py`
scores all 12 gold issues regardless, so the exclusion can only ever lower Assay's recall.
