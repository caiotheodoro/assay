# Design: Assay v2 evaluation (external corpus expansion, human labels, single endpoint, and third-party auditor arm)

Status: **design, not a registration.** Written 2026-11-23 alongside `paper-v2.0`. Nothing here
is frozen, nothing has been run, no paid API call has been made, and every item marked **owner**
is open. The registration would be `docs/PRE-REGISTRATION-V2.md`, frozen at a signed tag pushed
before the first external audit, human labelling pass, or paid model call, with the owner's own
predictions written in advance.

## Why

`paper-v2.0` established deterministic expected-loss savings on a 33-environment corpus while
leaving four validity limits that cannot be closed locally without new external environments,
independent human annotators, or paid model sampling:

1. **Corpus authorship (25 of 33 author-constructed).** Only 8 of 33 environments are genuinely
   third-party, and only 3 of those 8 carry externally derived labels (5 of 54 planted defects).
   On those 8 environments the saving over `flag_everything` is 76.0 (95% CI [-4, 121], not
   separated), and under `production-training` Assay loses to the floor by 8.0.
2. **Label independence ($\kappa = 0.278$ from a local model).** The only second-rater check
   (`results/label_agreement.json`) used a local `qwen3:8b` model over 24 environments and
   returned Cohen's $\kappa = 0.278$. No independent human has re-labelled the corpus.
3. **Uncorrected second look on $\tau^2$-bench.** On 62 independently confirmed $\tau^2$-bench
   defects, the full 12-probe battery achieved recall 0.339 ($p = 0.486$, chance). Removing the
   advisory `assert_traceability` probe cleared random flagging (recall 0.210, precision 0.565,
   $p = 0.040$), but that exclusion was post hoc and uncorrected for two looks.
4. **No comparative third-party auditor arm.** Assay was compared against `check_env`, constant
   and prevalence-aware floors, and two 8B local LLM baselines (`direct_prompt`,
   `agent_with_tools`), not against a published benchmark auditor (BenchGuard, ABA, or BenchJack)
   or a frontier LLM reader baseline.

## What stays

- The 11 probe families and 16 defect classes frozen before any v2 external environment is
  inspected or audited (no new scripted policies or probe tweaks after inspecting the held-out
  environments).
- The expected-loss scoring rule (`src/assay/metrics.py`), four cost profiles
  (`research-run`, `production-training`, `benchmark-publication`, `flat`), environment-level
  paired bootstrap (10,000 resamples, seed 11), and third-state `NOT_APPLICABLE` / `n_unchecked`
  accounting (priced at full miss cost).
- Reporting all three floors side by side: `flag_everything`, restricted `flag_present`, and
  both in-sample and leave-one-out prevalence-aware floors (`scripts/prevalence_floor.py`).

## What changes

### A. Held-out third-party corpus expansion (target: 30+ external environments)

Grow the genuinely external split from 8 to at least 30 environments sampled from public,
executable evaluation suites not authored here, frozen as a list of pinned repository commits or
package versions before running Assay:

- Candidate sources: `inspect_evals` executable tasks (stratified across coding, QA, reasoning,
  and no-correct-answer/measurement tasks via manifest/scorer inspection rather than task-name
  filtering), additional `OpenEnv` environments, public `Harbor` tasks authored upstream, and
  additional `tau2-bench` domains or verified benchmark forks (e.g., WebArena Verified,
  SWE-bench Verified executable subsets).
- **Strict holdout rule:** Assay's probe code, thresholds, and scripted Challenger repertoire are
  frozen at a signed git tag before any v2 environment is executed. Any adapter needed to expose
  capabilities is reviewed only against the upstream interface, never tuned on probe outputs.
- **Owner:** choose the exact target count (30 vs 40 environments), runtime budget (Docker and
  network requirements), and inclusion/exclusion rule for tasks requiring paid APIs or >10 GB
  images.

### B. Independent human labelling (~15 environments)

Replace the local-model agreement check with blinded human re-labelling on a stratified sample of
at least 15 environments (all 8 existing third-party environments plus 7+ from the v2 external
expansion):

- Two independent annotators (not the author) receive each environment's task specification,
  verifier code, and sample items—without Assay's outputs—and label each of the 16 defect classes
  as `PRESENT`, `ABSENT`, or `UNDETERMINABLE` using a written codebook.
- Report inter-annotator agreement (Cohen's $\kappa$ and Krippendorff's $\alpha$, per-class and
  overall), adjudication protocol for disagreements, and Assay's expected loss scored against the
  adjudicated human ground truth.
- **Owner:** recruit annotators, budget compensation, and freeze the labelling codebook before
  distribution.

### C. One pre-registered primary external endpoint

Eliminate the multiple-looks ambiguity from the $\tau^2$-bench evaluation:

- Register a **single** primary probe configuration (explicitly excluding advisory-only probes
  such as `assert_traceability`, or fixing a single named probe set) and a single primary test
  statistic (exact one-sided hypergeometric $p$ against random flagging at the same flag count,
  plus expected-loss saving over the prevalence-aware floor) on a new independently labelled
  external defect list (e.g., a second verified benchmark diff or held-out $\tau^2$ domain).
- Any secondary configuration or per-category breakdown is explicitly designated exploratory and
  cannot substitute for the primary endpoint.
- **Owner:** select the external defect list and commit the predictions before running.

### D. Third-party auditor arm and frontier LLM reader baseline

Evaluate Assay head-to-head against published auditors on the shared subset of environments where
both tools can execute or parse the benchmark:

- **Published auditor arm:** run at least one of BenchGuard (static LLM cross-check), ABA
  (automated benchmark auditing), or BenchJack (dynamic reward-hacking agent) using its released
  code and default configuration, mapping its output vocabulary onto Assay's 16 defect classes
  (and conversely mapping Assay onto the comparator's taxonomy) via a pre-registered mapping table
  frozen before the run.
- **Frontier LLM reader baseline:** run `direct_prompt` and `agent_with_tools` with a current
  frontier model (replacing or complementing local `qwen3:8b`) and report dollar cost and latency
  alongside expected loss.
- **Semantic gate stability:** re-measure `assay+auditor` across $k \ge 20$ repeated runs on the
  frozen v2 corpus (using the consensus/two-reply path) so mean saving and catastrophic
  false-override rate carry a tight empirical bound.
- **Owner:** approve API spend budget for the third-party auditor, frontier reader baselines, and
  repeated gate runs.

## What the owner decides before a freeze

1. Exact list and pinned versions of the 30+ external environments (A).
2. Human labelling budget, annotators, and codebook sign-off (B).
3. The single pre-registered primary external endpoint and predictions in the owner's words (C).
4. Which third-party auditor(s) and frontier LLM model(s) to fund and run (D).
5. External timestamping/deposit location for the frozen registration (e.g., OSF or Zenodo
   pre-registration deposit) so the registration clock is independent of GitHub commit history.

## Order of work once decided

Freeze detector and scripted repertoire at a signed tag -> draft and externally review
`docs/PRE-REGISTRATION-V2.md` -> deposit and sign-tag the registration -> run blind human
labelling -> execute deterministic Assay, third-party auditor, and frontier LLM arms on the
pinned environments -> publish `results/v2_*.json` and score once without editing the detector.

## Not here

No probe threshold, scripted exploit policy, or taxonomy exclusion is tuned on the v2 external
environments to rescue a failing endpoint.
