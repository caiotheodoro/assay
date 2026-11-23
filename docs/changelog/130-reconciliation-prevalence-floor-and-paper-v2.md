# Artifact reconciliation, post hoc prevalence-aware floor, paper v2, and next-study design

2026-11-23. Executes the pre-analysis plan committed in
`docs/changelog/129-paper-v2-preanalysis-plan.md` (`48ee192`). No frozen pre-registration file
(`docs/PRE-REGISTRATION*.md`) changed, no new model or API call ran, and no pre-registered verdict
changed.

## A. Artifact reconciliation (`n_missed` vs `n_unchecked`)

- **Root cause.** `scripts/intervals.py:load_arms` and `scripts/baselines.py` rebuilt `Outcome` for
  `assay` from `results/full_run.json["per_env"]` without passing
  `inconclusive=frozenset(DefectClass(d) for d in row.get("unchecked", []))`. As a result,
  `results/corpus_splits.json` and `results/baselines.json` recorded `assay` with `n_missed: 1,
  n_unchecked: 0, recall_on_checkable: 0.9815` (and `0.8571` on `external-envs`), whereas
  `results/full_run.json` and `results/gate_reliability.json` recorded `n_missed: 0, n_unchecked: 1,
  recall_on_checkable: 1.0`. Meanwhile, `assay+auditor` genuinely carries `n_missed: 1,
  n_unchecked: 0` in `full_run.json` and `gate_reliability.json` because `Auditor.resolve`
  synthesises a split for `inspect_evals/boolq` and re-runs `partial_input_baseline`, which returns
  `PASS` (verified in `full_run.json:arm_logs.assay+auditor.overrides[2]`).
- **Fix and verification.** Both loaders now pass `row.get("unchecked", [])` into `Outcome`.
  Regenerating `results/corpus_splits.json` and `results/baselines.json` changed only `n_missed`,
  `n_unchecked`, and `recall_on_checkable` (`0 / 1 / 1.0`); every `expected_loss`, `recall`,
  `precision`, `error_count`, and bootstrap interval was bit-for-bit unchanged.
  `tests/test_published_claims.py::test_downstream_artifacts_agree_on_assay_missed_and_unchecked`
  locks all five artifacts together so they cannot drift again.

## B. Post hoc restricted and prevalence-aware constant floors (`results/prevalence_floor.json`)

Computed by `scripts/prevalence_floor.py` from `results/full_run.json` and the four cost profiles
(10,000 paired environment bootstrap resamples, seed 11; all figures post hoc):

| profile (all 33 envs) | `assay` | `flag_everything` | `flag_present` (restr.) | `prevalence_floor` | saved vs restr. [95% CI] | saved vs prev. [95% CI] |
|---|---:|---:|---:|---:|---|---|
| `research-run` | 57.0 | 474.0 | 342.0 | 327.0 | 285.0 [198, 339] | 270.0 [176, 336] |
| `production-training` | 274.0 | 948.0 | 684.0 | 684.0 | 410.0 [-84, 678] (not sep.) | 410.0 [-84, 678] (not sep.) |
| `benchmark-publication` | 736.0 | 3792.0 | 2736.0 | 2688.0 | 2000.0 [744, 2712] | 1952.0 [588, 2832] |
| `flat` | 18.0 | 474.0 | 342.0 | 54.0 | 324.0 [303, 343] | 36.0 [9, 64] |

- On `research-run`, `prevalence_floor` flags 11 classes (omitting the 4 absent classes and
  `NONDETERMINISM`, whose prevalence $2/33$ is below $1/9$); `prevalence_floor_loo` scores 367.0
  (Assay saves 310.0 [195, 429], separated) because `CONTAMINATION_NEARDUP` occurs once.
- Removing the 4 absent classes reveals that bootstrap separation on `production-training`
  depended on the unrestricted floor: against both `flag_present` and `prevalence_floor`, Assay
  saves 410.0 with a 95% CI crossing zero ([-84, 678]). Against `prevalence_floor_loo` (1004.0),
  Assay saves 730.0 [28, 1434] (separated).
- On the 8 genuinely external environments (`research-run`), only 5 classes occur: oracle-prior
  in-sample `prevalence_floor` scores 33.0 (Assay loses by 12.0, [-92, 33]), while
  `prevalence_floor_loo` scores 201.0 (Assay saves 156.0 [24, 399]).
- Verified by `tests/test_published_claims.py::test_prevalence_floor_artifact_matches_elkan_rule`.

## C. Paper v2 (`paper/assay.tex`, `paper/assay.pdf`)

- **Title.** *Pricing Defects in Evaluation Environments by Expected Loss: A Probe Battery
  Evaluated Against Trivial and Prevalence-Aware Floors* (removing *"and Twelve of Its Own Claims
  That Broke"*).
- **Framing and structure.** Abstract leads with expected loss 57.0 and the restricted-floor saving
  285.0 ([198, 339]) beside `flag_everything` (474.0) and post hoc `prevalence_floor` (327.0,
  saving 270.0), with no confessional prose and no retraction counts. Introduction adds four
  contribution bullets. Method adds generated tables for all 16 defect classes across 11 families
  (`tab_classes.tex`) and corpus composition (`tab_corpus.tex`). External scope (8 external envs
  76.0 [-4, 121]; $\tau^2$ full-battery recall 0.339, $p=0.486$) is stated cleanly once in Results
  and once in Limitations. Pre-registration outcomes and deviations move to Appendix A
  (`tab_registrations.tex`); internal red-team table (`tab_redteam.tex`), retraction count, and
  hygiene checks move to Appendix B. Compiled to 14 pages with zero errors or undefined references.
- **Citations added** (verified against sources): Kapoor et al. (2024/2025, *AI Agents That
  Matter*, arXiv:2407.01502, TMLR 2025) and Reuel et al. (2024, *BetterBench*, NeurIPS 2024,
  arXiv:2411.12990). Both arXiv IDs added to `.zenodo.json`.
- **Dates (per owner's dating rule recorded in `lacuna` D114).** First repository commit was
  `2026-08-28` (`e2ca9d4`). `CITATION.cff` `date-released` and `.zenodo.json` `publication_date`
  are set to `2026-08-28` (with `.zenodo.json` `version: "paper-v2.0"` and `notes` stating work
  begun 28 August 2026, first paper compiled and deposited 23 November 2026, and this revision
  `paper-v2.0` of 23 November 2026); `paper/assay.tex` carries `First version 28 August 2026; this
  version 23 November 2026`. Nothing is pushed to GitHub or uploaded to Zenodo by this entry.

## D. Next-study design (`docs/DESIGN-V2.md`)

Drafted (not frozen, not run) for items requiring new external environments (30+), blind human
labelling (~15 environments), a single pre-registered external endpoint, and a third-party auditor
arm (BenchGuard/ABA/BenchJack) plus frontier LLM reader baselines.

## Reversal

If any figure or reading here is found wrong, a later changelog entry corrects it; this entry is
not edited.
