# Pre-registration — adding two external environments

**Committed before the code that changes any of these numbers.** That is the only thing
that makes it a pre-registration rather than a description. Check the git history: this
file lands in its own commit, ahead of `src/assay/_inspect_evals_corpus.py`.

## Why this document exists

`README.md` already states the hazard: `flag_everything`'s loss is exactly
`Σ_env (14 − |planted_env|)`, so **every clean environment added moves the trivial floor
by `14 × false_alarm` and a perfect detector by 0**. It commits, in prose, to
pre-registering the expected shift before growing the corpus. Nothing in the code or the
test suite enforced that commitment. This file is the first time it is honoured.

Two things make the hazard worse than the README says:

1. **The lever is profile-dependent and much stronger than the quoted figure.** A clean
   environment is worth `+14` under `research-run`, `+28` under `production-training`,
   and **`+112` under `benchmark-publication`** — 8× the number the README quotes, on the
   profile a benchmark author would actually use.
2. **`normalized_loss` divides by `min(trivial_arms)`** (`src/assay/metrics.py:163`), so
   corpus growth improves the *normalised* number almost unconditionally. Simulated
   against the shipped corpus: adding 100 clean environments takes Assay from
   **0.828 to 0.142 with no change to the detector at all.** `stratified_random` degrades
   toward `flag_nothing` almost immediately; `always_modal_defect` costs only +1 per clean
   environment and becomes the binding floor at k ≈ 114. That crossover is the only thing
   in the codebase resembling a guard, and it is accidental — a side effect of `min()`.

## Baseline, measured before the change

`results/full_run.json`, 24 environments, 46 planted defects.

| arm | research-run | normalised |
|---|---|---|
| assay | 240.0 | 0.828 |
| flag_everything | 290.0 | 1.000 |
| stratified_random | 1587.0 | 5.472 |
| always_modal_defect | 1767.0 | 6.093 |
| check_env | 2816.0 | 9.710 |
| flag_nothing | 2832.0 | 9.766 |

Floor by profile: `flag_everything` at 290.0 (`research-run`), 580.0
(`production-training`), 2320.0 (`benchmark-publication`); `flag_nothing` at 46.0 (`flat`).

## What is being added, and why it cannot be cherry-picked

Two environments, both third-party, both labelled from **upstream's own scorers with Assay
out of the loop**, both already pinned by 16 tests in `tests/test_wild_findings.py` that
predate this decision:

| env | planted | established by |
|---|---|---|
| `inspect_evals/paws` | `REWARD_HACKABLE` | `inspect_ai`'s own `includes()`; the constant `"yesno"` scores 8000/8000 |
| `inspect_evals/boolq` | `SHORTCUT_LEAK` | `inspect_ai`'s own `pattern()`; `"I don't know"` credited on every `No` item |

`paws` is **not** labelled `NONDETERMINISM` despite its unseeded shuffle being real and
execution-confirmed, because the corpus entry pins `shuffle=False` for reproducibility.
Scoring Assay against a defect we deliberately removed would be planting and then deleting
it. That finding stays in `results/wild_sweep_triage.json`.

The other 32 swept tasks are registered `UNAUDITED` and **excluded from every scored
number**. "Assay reported no defect" is Assay's claim, not established truth, and an
unaudited environment carrying `frozenset()` would hand the floor 14 points each — ~448
under `research-run`, ~3,584 under `benchmark-publication` — for work nobody did.

## Predictions

Stated now. Any of these being wrong is itself the result.

| | baseline | **predicted** |
|---|---|---|
| corpus size | 24 | 26 |
| planted defects | 46 | 48 |
| `flag_everything` (research-run) | 290.0 | **316.0** |
| `assay` (research-run) | 240.0 | **280.0** |
| margin over floor | 50.0 | **36.0** |
| `assay` normalised | 0.828 | **0.886** |
| floor arm (research-run) | flag_everything | flag_everything |

Per-environment:

- **`paws` / `REWARD_HACKABLE` → detected.** The wild sweep already reported it on 14 of
  25 sampled items at `exploit_gap = 1.0`. Predicted cost: **0**.
- **`boolq` / `SHORTCUT_LEAK` → missed, structurally.** `WildInspectAdapter` supplies no
  train split, so `SPLITS` is undeclared and the shortcut probe reports `NOT_APPLICABLE`
  before it runs. A miss because the probe *cannot execute* is a coverage gap rather than
  bad luck, and it is the most useful thing these two environments add. Predicted cost:
  **40** (`DEFAULT_SEVERITY[SHORTCUT_LEAK]` is HIGH; note the hand triage judged this
  finding MEDIUM — the class default governs scoring and the disagreement is recorded
  rather than resolved silently).

All four profiles:

| profile | assay | floor | margin |
|---|---|---|---|
| research-run | 280.0 | 316.0 | **+36.0** |
| flat | 3.0 | 48.0 | +45.0 |
| production-training | 2160.0 | 632.0 | **−1528.0** |
| benchmark-publication | 4600.0 | 2528.0 | **−2072.0** |

## The direction is the check

**Every axis is predicted to get worse for Assay.** The margin narrows from 50.0 to 36.0,
normalised loss rises from 0.828 to 0.886, and the two profiles Assay already loses on it
loses by more. An expansion that *widened* the margin would need its arithmetic explained
before anyone should believe it; this one does not, and that asymmetry is the point of
writing the numbers down first.

## What would falsify the method rather than the prediction

- `boolq`'s `SHORTCUT_LEAK` being **detected** — that would mean the shortcut probe ran
  without a train split, and the coverage story here is wrong.
- The floor arm changing at n=26 — it should not; `always_modal_defect` does not become
  binding until roughly k = 114.
- Any arm other than `assay` moving differently than `Σ (14 − |planted|)` predicts.
- `results/full_run.json` failing to reproduce byte-identically on a re-run, which would
  mean the `shuffle=False` pinning did not take and the corpus is no longer deterministic.

Measured results go in `docs/changelog/77-external-corpus.md` next to these numbers,
whichever way they come out.
