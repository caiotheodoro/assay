# Paper v2 plan: artifact reconciliation and prevalence-aware floor (pre-analysis)

2026-11-23. Written and committed before regenerating `results/corpus_splits.json` or
`results/baselines.json` and before computing any prevalence-aware floor figures. No frozen
pre-registration file (`docs/PRE-REGISTRATION*.md`) is edited, no new model or API call is run,
and no existing corpus verdict changes.

## Why

External review of `paper-v1.0` identified two local, zero-spend technical fixes and a framing
revamp:

1. **Artifact discrepancy (`n_missed` vs `n_unchecked`).** `results/full_run.json` and
   `results/gate_reliability.json` record `assay` with `n_missed: 0, n_unchecked: 1`
   (`recall_on_checkable: 1.0`, because `inspect_evals/boolq` ships no train split and
   `partial_input_baseline` returns `NOT_APPLICABLE`), whereas `results/corpus_splits.json` and
   `results/baselines.json` record `assay` with `n_missed: 1, n_unchecked: 0`
   (`recall_on_checkable: 0.9815`) for the same run. Inspection of `scripts/intervals.py:load_arms`
   and `scripts/baselines.py` shows both rebuild `Outcome` for `assay` from
   `full_run.json["per_env"]` without passing `inconclusive=row.get("unchecked", [])`.
   Separately, `assay+auditor` genuinely has `n_missed: 1, n_unchecked: 0` in `full_run.json`
   and `gate_reliability.json` because `Auditor.resolve` synthesises a split for `boolq` and
   re-runs `partial_input_baseline`, which returns `PASS`.
2. **Prevalence-aware floor (post hoc).** `paper-v1.0` compared `assay` against `flag_everything`
   and a restricted floor (`flag_present`, flagging the 12 classes planted in at least one
   environment) and noted in Limitations that a prevalence-aware constant policy would give a
   tighter floor. That policy is deterministic and computable from `results/full_run.json` and
   `src/assay/costs/profiles/*.yaml` with zero new model calls.

## Planned local computations

### A. Reconciliation of `n_unchecked` across downstream artifacts

1. Update `scripts/intervals.py:load_arms` and `scripts/baselines.py` so `Outcome` for `assay`
   reads `inconclusive=frozenset(DefectClass(d) for d in row.get("unchecked", []))`.
2. Regenerate `results/corpus_splits.json` and `results/baselines.json` from the unchanged
   `results/full_run.json`.
3. Expected invariants: `expected_loss`, `recall`, `precision`, `error_count`, and every
   bootstrap confidence interval remain unchanged (since `metrics.py` prices unchecked defects
   identically to missed defects), while `assay` switches from `(n_missed=1, n_unchecked=0)` to
   `(n_missed=0, n_unchecked=1)` wherever `inspect_evals/boolq` is in the split (`all`,
   `external-envs`, `externally-labelled`, `no-harbor`, and all four profiles of `baselines.json`).
4. Add a regression test in `tests/test_published_claims.py` asserting that `full_run.json`,
   `corpus_splits.json`, `baselines.json`, and `gate_reliability.json` agree on `assay`'s
   `(n_missed, n_unchecked, n_spurious, expected_loss)`.

### B. Prevalence-aware floors (post hoc)

Implemented in `scripts/prevalence_floor.py`, writing `results/prevalence_floor.json` from the
unchanged `results/full_run.json` and the four cost profiles (`research-run`,
`production-training`, `benchmark-publication`, `flat`), on both the full corpus (`n=33`) and
the external split (`n=8`). Three input-ignoring constant floors are evaluated alongside
`flag_everything`:

1. **`flag_present` (restricted floor):** flags every defect class planted in at least one
   environment of the evaluated set (`k_d >= 1`), omitting absent classes.
2. **`prevalence_floor` (Bayes-optimal in-sample constant policy, Elkan 2001):** under profile
   miss costs $M_d = \mathrm{cost\_of\_miss}(\mathrm{sev}(d))$ and false-alarm cost $F$, flags
   class $d$ on every environment iff corpus prevalence $p_d = k_d / N > F / (M_d + F)$. By
   construction this achieves the minimum expected loss attainable by any constant
   input-ignoring policy on that set.
3. **`prevalence_floor_loo` (leave-one-out prevalence-aware constant policy):** for each
   environment $e$, computes $p_{d,-e} = (k_d - \mathbb{I}[d \in P_e]) / (N - 1)$ on the other
   $N - 1$ environments and flags class $d$ on $e$ iff $p_{d,-e} > F / (M_d + F)$.

Paired 95% bootstrap intervals for `assay`'s expected-loss saving over each floor are computed
with the exact same environment-resampling routine (`scripts/intervals.py:bootstrap`,
`resamples=10000`, `seed=11`). All prevalence-floor figures are explicitly labelled post hoc in
the artifact and paper, and replace no pre-registered figure.

## Planned paper v2 and design changes

- Revise `paper/assay.tex` to v2: lead with the restricted-floor saving (`285.0`) and report
  `flag_everything` (`474.0`) and the post hoc prevalence-aware floors beside it; remove
  confessional prose, retraction counts from the abstract, and repo housekeeping from the body;
  add generated corpus-composition and 16-defect-class tables; move self-audit / red-CI /
  registration outcomes and deviations into appendices; add verified citations (Kapoor et al.,
  BetterBench); set publication dates to `2026-08-28` (first commit `e2ca9d4`) with revision
  date `2026-11-23` per the owner's dating rule.
- Draft `docs/DESIGN-V2.md` for work requiring new external environments (30+), human labels
  (~15 environments), a single registered external endpoint, and a third-party auditor arm.

## Reversal

If any formula or reading in A or B is found wrong, a later changelog entry corrects it; this
entry is not edited.
