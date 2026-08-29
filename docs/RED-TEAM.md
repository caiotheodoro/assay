# Red team

An adversarial review of `README.md` and `docs/CHANGELOG.md`. The brief was to
falsify, not to confirm. Every claim below was attacked; where it broke, the
command and its output are here.

**Scope.** Reviewed against the working tree as of `2026-08-29T15:29:42Z`
(`README.md` sha256 `12232517ea6425d8…`, `CHANGELOG.md` `faec4ac2fc047694…`,
`REPRODUCTION.md` `eff717a462ce79be…`; snapshots kept at `/tmp/rtcheck/snap/`).
The tree was dirty and being edited by a concurrent session while this ran, so
line numbers may have moved; quoted text is verbatim from the snapshot.

**Nothing was fixed.** One artifact (`results/wild_sweep.json`) was produced by a
verification run and deleted afterwards; `results/` is otherwise byte-identical to
the committed state.

---

## Summary

| # | Claim | Verdict |
|---|---|---|
| 1 | τ²-bench recall 0.339 against 62 defects | **BROKEN** — indistinguishable from random (p = 0.486) |
| 2 | 24-environment corpus, assay 240.0 vs check_env 2816.0 | **BROKEN** — half the corpus is Assay's own pytest fixtures |
| 3 | "Assay wins one of four profiles, loses two" | **BROKEN** — flips entirely on the no-Docker corpus the README advertises |
| 4 | `uv run --extra adapters python scripts/full_run.py` reproduces the table | **BROKEN** — that command gives 22 envs / 45 defects |
| 5 | Challenger ablation table, and the "winning policy" snippet | **BROKEN** — matches no committed artifact |
| 6 | `reward_basis` was the field that needed excluding | **BROKEN** — it does not exist in either revision |
| 7 | `docs/REPRODUCTION.md` "expect exactly this" | **BROKEN** — carries the retracted `check_env` row |
| 8 | "a **signed** Environment Card" | **BROKEN** — unkeyed digest; forgeable in three lines |
| 9 | "The incumbent is not statistically distinguishable from checking nothing" | **BROKEN** — true by construction of the test, not by the data |
| 10 | REPRODUCTION.md test counts / "nothing skips" | **BROKEN** — 493 passed / 18 skipped, not 275 / 0 |
| 11 | SAB: "R1 would score respectably", "41 findings on clean tasks" | **BROKEN** — never scored; the file says 16 |
| 12 | "with `harbor/self-graded` held out so the test would mean something" | **BROKEN in the README** — corrected only in the changelog |
| 13 | Bootstrap CIs at n = 24 | **WEAK** — Assay's interval is a 10-point lattice over 2 environments |
| 14 | 62 τ² positives are all defects | **PARTIAL** — 2 are documentation-comment edits |
| 15 | "The incumbent detects 2 of 46 defects" | **PARTIAL** — a property of a reimplementation, not of the incumbent |
| 16 | `paws` scores `"yesno"` at 100% | **SURVIVES** — verified end to end on the current release |
| 17 | `textarena_env` accepts a seed and ignores it | **SURVIVES** — still on OpenEnv `main` today |
| 18 | `flag_everything`'s CI is suspiciously tight | **SURVIVES** — the tightness is arithmetic, not an error |
| 19 | Paired bootstrap construction | **SURVIVES** — one shared resample index, correctly done |
| 20 | Committed results reproduce byte-identically | **SURVIVES** |
| 21 | Prior-art citations and their numbers | **SURVIVES** — all six resolve, numbers match the abstracts |

---

## 1. τ²-bench recall 0.339 is statistically indistinguishable from flagging tasks at random

**BROKEN. The most damaging finding here.**

The README presents this as the measurement that breaks the closed loop:

> Everything above is measured against defects **this repo planted**. That is a closed
> loop, and the two sections below break it […]
> | all 12 probes | **0.339** (21/62) | 0.389 |

Assay flags 54 of 164 tasks and lands 21 of them on positives. There are 62
positives among 164 tasks. Picking 54 tasks *uniformly at random* lands 20.41 on
positives in expectation.

```
$ .venv/bin/python -c "..."   # hypergeometric, exact
all 12 probes:
  flagged n=54 (32.9% of tasks), observed tp=21, expected tp if the same n tasks were picked at random = 20.41
  observed recall 0.3387  vs random-at-same-rate recall 0.3293
  observed precision 0.3889  vs base rate (precision of ANY random flagger) 0.3780
  hypergeometric one-sided P(TP >= 21) = 0.4864

excluding assert_traceability:
  flagged n=23 (14.0% of tasks), observed tp=13, expected tp if the same n tasks were picked at random = 8.70
  observed recall 0.2097  vs random-at-same-rate recall 0.1402
  observed precision 0.5652  vs base rate (precision of ANY random flagger) 0.3780
  hypergeometric one-sided P(TP >= 13) = 0.0403

flag_everything on tau2: recall 1.000, precision 0.3780 (flags all 164 tasks)
```

`p = 0.486`. The headline row carries no signal at all. Its precision of 0.389
beats the base rate of *any* random flagger by 0.011.

Three things make this worse than a weak number:

- **The project's own central rule is never applied here.** `metrics.py`'s
  docstring: *"The auditor is held to the same trivial-floor rule it applies to
  environments: if it cannot beat the best policy that ignores its input, it has
  not earned its existence."* `results/intervals.json` carries five trivial
  baselines for the planted corpus. `results/tau2_recall.json` carries none, and
  the base rate 62/164 = 0.378 appears nowhere in the repository:

  ```
  $ grep -rn "62/164\|0.378\|base rate" README.md docs/changelog/60-tau2-recall.md docs/CHANGELOG.md
  README.md:139:the floor: on an imbalanced 14-class multilabel problem, flagging at base rates
  docs/CHANGELOG.md:334:| Slice 20a | ... Stratified-random flags each class at its base rate ...
  ```
  Both hits are about the planted corpus. Neither is about τ².

- **The framing inverts the result.** The README leads with 0.339 and calls the
  `assert_traceability`-free row the narrower one. The arithmetic says the
  opposite: removing that probe is the only thing that lifts the measurement
  above chance (p = 0.040 from p = 0.486). The advisory heuristic is not a
  bonus with a caveat; including it destroys the signal.

- **Recall against a trivial floor.** `flag_everything` on τ² scores recall
  1.000 at precision 0.378 — a higher precision than the "excluding advisory
  probe" row's *recall*, and 3× Assay's recall.

`0.339` is a real number honestly computed. It is not evidence that Assay
detects τ-bench defects.

## 2. Half the headline corpus is Assay's own pytest fixtures

**BROKEN.** The 24-environment corpus is 12 `fixture/*` + 5 `harbor/` + 5
`inspect/` + 2 `openenv/`. The 12 fixtures are not a sample — they are
byte-for-byte the CATALOG the test suite asserts exact detection on:

```
$ .venv/bin/python -c "from assay.fixtures import CATALOG; print(sorted(CATALOG))"
['artifact_splits', 'drifted_asserts', 'escalate_overrewarded', 'flaky', 'gold_broken',
 'healthy', 'leaky_splits', 'paraphrased_splits', 'rationale_ignored', 'solved_at_reset',
 'unfalsifiable', 'weak_oracle']
$ .venv/bin/python -c "... full_run.json fixture ids ..."
['artifact_splits', 'drifted_asserts', 'escalate_overrewarded', 'flaky', 'gold_broken',
 'healthy', 'leaky_splits', 'paraphrased_splits', 'rationale_ignored', 'solved_at_reset',
 'unfalsifiable', 'weak_oracle']
```

`tests/test_probes_fire.py:18`:

```python
@pytest.mark.parametrize("variant", sorted(CATALOG))
def test_detection_matches_ground_truth_exactly(variant):
    ...
    assert detected == planted
```

Assay's score on 12 of the 24 environments is not measured; it is a red build if
it is anything other than perfect. The README markets this without connecting it
to the corpus: *"The test suite is the honest demo: twelve fixture environments
… and a test asserting every planted defect is detected."*

Split the corpus and the headline moves:

```
### fixture-only (12)  n=12  planted=19
arm                        loss   recall    prec   |       flat  research-run  production-training  benchmark-publication
assay                       0.0    1.000   1.000   |        0.0         0.0         0.0         0.0
flag_everything           149.0    1.000   0.113   |      149.0       149.0       298.0      1192.0

### no-fixture (12)  n=12  planted=27
arm                        loss   recall    prec   |       flat  research-run  production-training  benchmark-publication
flag_everything           141.0    1.000   0.161   |      141.0       141.0       282.0      1128.0
assay                     240.0    0.926   1.000   |        2.0       240.0      1920.0      4000.0
```

**On the 12 environments Assay did not author for itself, `flag_everything` has
the lower expected loss under `research-run` (141.0 vs 240.0)** — the profile the
README picks for its headline — and Assay loses outright on three of four
profiles rather than two. (Paired bootstrap on that subset: saved −99.0,
95% CI [−454, 144], not separated. The point estimate reverses; the interval
cannot resolve it at n = 12.)

The README does not report a fixture / non-fixture split anywhere.

## 3. The whole "profiles where Assay loses" section is an artifact of five Harbor environments

**BROKEN, in the README specifically.**

Both of Assay's misses are `harbor/self-graded` and `harbor/shared-tests`, worth
120 each under `research-run` — which is the entire 240.0. Drop the Harbor
ecosystem, which the README explicitly treats as optional (*"Needs Docker for the
Harbor tasks … Without the daemon the run still completes, on 19
environments"*), and:

```
### no-harbor (19)  n=19  planted=36
arm                        loss   recall    prec   |       flat  research-run  production-training  benchmark-publication
assay                       0.0    1.000   1.000   |        0.0         0.0         0.0         0.0
flag_everything           230.0    1.000   0.135   |      230.0       230.0       460.0      1840.0

no-harbor (19)   research-run    assay loss 0.0 CI [0.0, 0.0]  assay-vs-flag_everything saved 230.0 CI [213.0, 245.0] separated=True
no-harbor (19)   production-training  assay loss 0.0 CI [0.0, 0.0]  saved 460.0 CI [426.0, 490.0] separated=True
```

On the corpus a reader without Docker gets, Assay is **perfect on all four cost
profiles**, and it **separates from the trivial floor**. Three of the README's
most prominent statements are then false of that run:

- "**Assay does not beat the trivial floor at n=24**"
- "**Assay wins outright on one of four, and loses outright on two**"
- "Assay's two CRITICAL misses cost 960 each under `production-training`"

`docs/REPRODUCTION.md` does disclose the direction of this ("With the daemon down,
Assay's expected loss drops from 240.0 to **0.0** — it looks perfect because the
five environments it does worst on are gone"). It does not say the floor
comparison flips to *separated*, and **the README says none of it**. The document
that carries the honest-concessions section is the one that omits the condition
under which the concessions disappear.

## 4. The README's own reproduction command does not produce the README's table

**BROKEN.** README line 120:

> 24 environments, 46 planted defects. Needs Docker for the Harbor tasks. No GPU
> and no API key — `uv run --extra adapters python scripts/full_run.py`, 22s on a
> warm Docker image.

`--extra adapters` does not install the `openenv` extra. Verified in a clean,
isolated environment (`UV_PROJECT_ENVIRONMENT`, so the project venv was not
touched):

```
$ UV_PROJECT_ENVIRONMENT=/tmp/rtcheck/venv_readme uv run --extra adapters python -c "import openenv"
Creating virtual environment at: /tmp/rtcheck/venv_readme
Installed 83 packages in 266ms
inspect_ai IMPORTABLE
openenv MISSING -> ModuleNotFoundError
textarena_env MISSING -> ModuleNotFoundError

$ UV_PROJECT_ENVIRONMENT=/tmp/rtcheck/venv_readme uv run --extra adapters python scripts/full_run.py --out /tmp/rtcheck/full_run_readme_cmd.json
corpus: 22 environments, 45 planted defects
WARNING: openenv unavailable, corpus is reduced -- OpenEnv environments not importable ...

arm                   exp.loss    norm  recall    prec  miss  spur
assay                    240.0   0.912   0.956   1.000     2     0
flag_everything          263.0   1.000   1.000   0.146     0   263
check_env               2816.0  10.707   0.022   1.000    44     0
flag_nothing            2824.0  10.738   0.000   0.000    45     0
```

22 environments, 45 defects. `flag_everything` 263.0, not 290.0. And because
`openenv/textarena-wordle` is one of `check_env`'s only two hits, the README's
next paragraph — *"The incumbent detects **2 of 46 defects — 4.3% recall**"* —
becomes 1 of 45 = 2.2% under the README's own command.

The degradation warning fires correctly and loudly; that part works. The README
just never tells the reader to read it, while `REPRODUCTION.md` does ("check
`corpus:` before believing any number under it") and uses the right command
(`--extra adapters --extra openenv`).

Timing: `22s` was not reproduced — 56.9 s here, on a contended box.

## 5. The Challenger ablation table matches no committed artifact, and the "winning policy" is not in the results

**BROKEN.** README:

> | scripted | missed | 0.00 | 4 | 6s |
> | prompted, `qwen3:8b` | missed | 0.00 | 8 | 74s |
> | prompted, `claude-cli` | **found** | **1.00** | 8 | 405s |

Every committed ablation run:

```
$ .venv/bin/python -c "... glob results/challenger_ablation*.json ..."
results/challenger_ablation.json           [('scripted',4,2.2,False), ('prompted:qwen3:8b',10,97.0,False), ('prompted:claude-cli',10,261.7,True)]
results/challenger_ablation_8b.json        [('scripted',4,4.9,False), ('prompted:qwen3:8b',10,44.3,False)]
results/challenger_ablation_claude.json    [('scripted',4,7.6,False), ('prompted:qwen3:8b',10,142.4,False), ('prompted:claude-cli',9,161.6,False)]
results/challenger_ablation_runconfig.json [('scripted',4,3.1,False), ('prompted:qwen3:8b',10,66.8,False), ('prompted:claude-cli',10,106.4,False)]
```

No file has `8` scored attempts for either model arm, and none has 6 s, 74 s or
405 s. The only `found` run on disk is 10 attempts / 261.7 s. `docs/REPRODUCTION.md`
repeats the same unsourced numbers ("**Measured: 840 s end to end** … `claude-cli`
**finds the exploit at attempt 8 with gap 1.00** (405 s)").

The README's explanation for the column makes the mismatch sharper, not softer:
*"'scored attempts' counts the turns that parsed into an action, so it is at most
the budget and usually less."* Every committed run is at 9 or 10 of a 10-turn
budget.

The exploit the README publishes as the result is also not in the record:

> The winning policy, at turn 8 […]
> ```sh
> rm -f expected.txt && ln -s out.txt expected.txt && echo -n 'WRONG_ANSWER_XYZ' > out.txt
> ```
> Scored 1.0 by the environment. Scored 0.0 by the independent verifier.

```
$ grep -rn "ln -s" results/
results/challenger_ablation_claude.json:254:   "script": "rm -f out.txt; ln -s expected.txt out.txt; cat out.txt"
results/trajectories/04-challenger-claude-cli-harbor-self-graded-missed.md:118: (same)
results/trajectories/04-challenger-claude-cli-harbor-self-graded-missed.json:112: (same)
```

The only symlink in the artifacts points the other way, does not write
`WRONG_ANSWER_XYZ`, and belongs to the run that **missed** (`found_exploit:
false`, gap 0.00). The turn-8 action of the run that did succeed is:

```
$ .venv/bin/python -c "... trajectory 03, turns[7] ..."
"script": "echo -n 'banana' > expected.txt; echo -n 'banana' > out.txt; ..."
"reported_score": 1.0
"outcome": {"found_exploit": true, "exploit_gap": 1.0, "n_attempts": 10,
            "provenance": "replayed from results/challenger_ablation.json"}
```

The README hedges ("One run's winner was a symlink, an earlier one a pair of
matching writes"), but it prints the symlink under **"The winning policy, at turn
8 … Scored 1.0 by the environment"**, and there is no committed evidence that
that command was ever scored 1.0. The one place a reader is told to look —
`results/trajectories/`, *"readable end to end without running anything"* —
contains a different command.

Two committed artifacts also carry exploit residue into the repository root, and
they are tracked, not ignored:

```
$ cat expected.txt; cat out.txt; git ls-files | grep -E "^(out|expected)\.txt"
WRONG_ANSWER_XYZZY
undefined
expected.txt
out.txt
$ grep -n "out.txt\|expected.txt" .gitignore
(not in .gitignore)
```

## 6. The `reward_basis` exclusion is a no-op, justified by a claim that is false

**BROKEN.** `src/assay/tau2_truth.py:47`:

> `reward_basis` was dropped wholesale by the verified fork — it is absent
> from all 164 of its task records. Counting that as a per-task fix would
> label every task a positive and make recall meaningless, so it is excluded
> from the diff and named here rather than hidden in a helper.

It is absent from all 164 records of **both** revisions. It was never there to be
dropped:

```
$ grep -c "reward_basis" base-retail.json ver-retail.json base-airline.json ver-airline.json
0 matches for 'reward_basis'
$ .venv/bin/python -c "... eval_criteria keys per file ..."
base-retail:  n=114 tasks_with_reward_basis=0 eval_criteria_keys=['actions','communicate_info','nl_assertions']
ver-retail:   n=114 tasks_with_reward_basis=0 eval_criteria_keys=['actions','communicate_info','nl_assertions']
base-airline: n=50  tasks_with_reward_basis=0 eval_criteria_keys=['actions','communicate_info','nl_assertions']
ver-airline:  n=50  tasks_with_reward_basis=0 eval_criteria_keys=['actions','communicate_info','nl_assertions']
```

Recomputing the diff from the two pinned revisions with **no exclusion at all**
gives the same answer:

```
retail base 114 verified 114   ids equal: True
airline base 50 verified 50    ids equal: True
total tasks 164, tasks with ANY diff 62
```

`SCHEMA_ONLY_FIELDS` strips a key that does not exist. The number 62 is right;
the stated reason it is right was never checked. It is the same failure mode the
README catalogues elsewhere — an assertion about someone else's data, written
down without running `grep` on it — sitting in the module whose docstring says
*"a fact anyone can recompute with `json.load` and `==`"*.

To answer the brief's question directly: nothing else needed excluding either.
`reward_basis` was not "the only field that needed excluding" — no field did.

## 7. `docs/REPRODUCTION.md` still publishes the retracted `check_env` row

**BROKEN.** The README makes a point of the correction:

> An earlier version of this table gave `check_env` flag_nothing's row —
> **2832.0, [1752, 4032], recall 0.000** — which contradicted both
> `results/intervals.json` and the sentence directly beneath it.

`docs/REPRODUCTION.md`, under **"Expect exactly this, under `research-run`"**:

```
| arm | expected loss | recall | precision |
| assay | 240.0 | 0.957 | 1.000 |
| flag_everything | 290.0 | 1.000 | 0.137 |
| check_env | 2832.0 | 0.000 | 0.000 |
| flag_nothing | 2832.0 | 0.000 | 0.000 |

`check_env` — the incumbent linter … — scores identically to `flag_nothing`.
```

That is the uncorrected row *and* the retracted sentence. Running the guide's own
command:

```
$ uv run --extra adapters --extra openenv python scripts/full_run.py
check_env               2816.0   9.710   0.043   1.000    44     0
flag_nothing            2832.0   9.765   0.000   0.000    46     0
```

A reader following the reproduction guide gets a mismatch on the guide's own
"expect exactly this". The correction was applied to `README.md` and not
propagated.

## 8. The Environment Card is not signed

**BROKEN.** README, first paragraph: *"emits a **signed** Environment Card"*.
`src/assay/runner.py:104`: *"Sign the body so a card cannot be edited without the
hash changing."*

```python
body["signature"] = digest(body)     # digest = sha256(canonical_json(...))
```

There is no key. Anyone editing a card recomputes the digest:

```
$ .venv/bin/python -c "..."
published signature is exactly digest(body without signature): True
original: verdict=INVALID sig=7a32329628aedf0c56242d6f
forged  : verdict=VALID   sig=db44572dcc30afad3c8fb0e7  (recomputed with no key)
forged card passes its own signature check: True
```

An `INVALID` card was turned into a self-consistent `VALID` card with every
finding removed, in three lines and no secret. The property the README sells — a
card whose verdict is attributable and tamper-evident, gating a training run — is
not what a bare content digest provides. It detects accidental corruption only.
The card footer, *"Signature covers the full probe output"*, reads as provenance
to anyone who does not open `runner.py`.

## 9. "The incumbent is not statistically distinguishable from checking nothing" is decided by the test's construction

**BROKEN as evidence**, though the conclusion happens to hold.

> Against `flag_nothing` it saves **16.0 expected loss, 95% CI [0.0, 40.0]** — an
> interval that includes zero. **The incumbent is not statistically
> distinguishable from checking nothing at all** on this corpus.

`check_env` never emits a false positive and only ever detects a subset of what
is planted, so its loss is ≤ `flag_nothing`'s on *every* environment. The paired
difference cannot be negative:

```
$ .venv/bin/python -c "..."
check_env spurious anywhere: False
envs where check_env detects something: ['fixture/flaky', 'openenv/textarena-wordle']
paired diff check_env vs flag_nothing over 10000 resamples: min=0.0 max=72.0
  resamples with diff == 0: 1221 (12.21%)   with diff < 0: 0
```

`intervals.py` declares separation with `separated = lo > 0 or hi < 0`. For a
statistic that is ≥ 0 in 10000 of 10000 resamples, `hi < 0` is impossible and
`lo > 0` requires fewer than 2.5% of draws to be exactly zero. 12.2% are — the
probability that neither of the two `NONDETERMINISM` environments is drawn,
(22/24)^24 ≈ 0.12. **A two-sided percentile CI on a one-sided statistic can
never separate here, no matter how much better the incumbent got.** The right
instrument is the one-sided mass at zero, p ≈ 0.12 — which does not reach 0.05,
so the sentence survives on the merits. It is not established by the interval the
README cites for it.

Related: one of `check_env`'s two hits is `fixture/flaky` — Assay's own test
fixture.

## 10. The reproduction guide's test numbers are stale by roughly 2×

**BROKEN.**

> **Measured: 275 collected, 0 skipped, 0 failed, exit 0, 49–60 s** … Nothing
> skips when everything is installed and running, which is the point of the table
> below — you should be able to tell a skip from a pass.

```
$ uv run --extra adapters --extra sweep --extra openenv python -m pytest tests -p no:randomly
493 passed, 18 skipped, 1 warning in 161.55s (0:02:41)

$ ... -rs
SKIPPED [18] tests/test_tau2_adapter.py: the pinned tau2-bench snapshots are not in the cache;
             run `uv run --extra tau2 python scripts/tau2_fetch.py`
```

511 collected, 18 skipped, 161–227 s. Something *does* skip with all three named
extras installed, because the τ² snapshots are fetched by a script the guide
never lists as a prerequisite for the test suite. The "Degradation" table's
`275 collected, 32 skipped` and `275 collected, 0 skipped` rows are stale for the
same reason.

The two targeted commands in the guide are exact:

```
$ uv run ... pytest tests/test_wild_findings.py         → 26 passed in 3.27s   (claimed: 26 passed in 6 s)
$ uv run ... pytest tests/test_openenv_ground_truth.py  →  7 passed in 11.30s  (claimed: 7 passed in 3 s)
```

## 11. The ScienceAgentBench counterfactual was never scored, and one of its numbers contradicts the committed file

**BROKEN.**

> **The heuristic this project rejected would score respectably through their
> metric.** R1 fires on 61 of 102 tasks; `metrics.py` computes precision only over
> findings on the 12 revised tasks, so its **41 findings on clean tasks** are
> invisible to it.

Presented under the heading *"Two things that fell out of running their scorer."*
The scorer never ran on this arm:

```
$ .venv/bin/python -c "... rejected-r1__original_result.json ..."
fired_on: 61 of 102 rate 0.598
suppressed_by_exclusion: n_tasks = 41 sum = 41
findings_submitted: {'total': 20, 'on_revised_tasks': 4, 'judge_calls_required': True}
=> findings on CLEAN (non-revised) tasks = 16
their_report: None
blocked: BLOCKED: 4 findings land on revised tasks, so match.py must call the
         gemini/gemini-3-flash-preview judge, and no GEMINI_API_KEY is set.
```

Two errors:

- **"41 findings on clean tasks"** is wrong. 41 is `suppressed_by_exclusion` —
  the fires that never became findings. The file records 20 findings, 4 on
  revised tasks, so 16 on clean ones. 61 − 20 = 41 appears to have been read as a
  finding count.
- **"would score respectably through their metric"** is an argument about the
  metric's shape, not a measurement. `their_report` is `null`; the run stopped.
  The repository is right to stop rather than report an unjudged number — but the
  README states the outcome as if it had been obtained, in a section explicitly
  headed "fell out of running their scorer".

Also worth flagging against the README's bolded **"No LLM judge scores anything,
anywhere"**: the SAB pipeline the README cites as its scorer *is* an LLM judge
(`match.py`, `gemini/gemini-3-flash-preview`). It scored nothing only because
Assay submitted nothing — `"Total pairs to judge: 0 … Cost: $0.0000"`. The
changelog concedes this in as many words ("the one design principle that could
have been compromised here … never got the chance"); the README's absolute does
not.

The claim *"nine of the twelve defects are already fixed in the split SAB tells
you to use"* checks out exactly: `counts: {defect_present: 3,
already_fixed_upstream: 9}`.

The reproduction command in that section cannot be run from a clean clone —
`third_party/BenchGuard` and `third_party/auto-bench-audit` are gitignored, no
script fetches them, and no clone URL appears in the README (the shas are in the
result files).

## 12. The README still asserts a holdout the repository has measured to be contaminated

**BROKEN in the README.**

> A Challenger was trained with GRPO … with `harbor/self-graded` held out so the
> test would mean something.

`results/train_holdout_dedup.json`:

```json
"holdout_prompt_exposure": {
  "colliding_train_environments": ["harbor/broken-gold", "harbor/healthy", "harbor/vacuous-tests"],
  "colliding_train_rows": 60, "fraction_of_training_rows": 0.2, "total_train_rows": 300,
  "what_this_means": "The holdout held out the ENVIRONMENT ... but not the PROMPT.
   The prompt the trained Challenger is given on harbor/self-graded is byte-identical
   to one it was optimised against for this fraction of training."
}
```

Exact SHA-256 overlap 1, true Jaccard 1.0, on `user_turn` as well as
`full_prompt`. `docs/CHANGELOG.md` Slice 20i/20j records this fully and correctly
— *"the claim that the holdout made the ablation clean is half true and is
corrected here rather than left standing."* It was left standing in the README.
Same shape as findings 3 and 7: the correction exists, one document downstream.

Practical impact is nil (nothing learned), but it is the specific claim the
sentence is making.

## 13. n = 24 does not support the interval Assay reports

**WEAK, not a break.** The resampling unit is right — environments, not defects,
for the reason `intervals.py` gives, and the pairing is correct (finding 19). But
Assay's loss is nonzero on exactly 2 of 24 environments, so the bootstrap
distribution is a binomial count of two rows on a 120-point lattice:

```
assay expected-loss bootstrap distribution (research-run, 10k resamples):
   loss=    0.0   1244 draws  (12.44%)
   loss=  120.0   2726 draws  (27.26%)
   loss=  240.0   2868 draws  (28.68%)
   loss=  360.0   1824 draws  (18.24%)
   loss=  480.0    891 draws  ( 8.91%)
   loss=  600.0    335 draws  ( 3.35%)
   ... support size = 10 distinct values
```

`[0.0, 600.0]` is not a continuum; it is the 2.5th and 97.5th rungs of a ladder
with ten rungs. 12.4% of the mass sits on exactly zero. The README's *"read
those, not the point estimates"* is good advice pointed at an interval that
cannot resolve much. This is inherent to the corpus size, not an error in the
method — but "95% CI" invites a precision that two error-bearing environments
cannot supply.

## 14. Two of the 62 τ² positives are documentation-comment edits

**PARTIAL break.** The label rule is *"a task is a positive iff its record differs
between the pre-fix commit and the verified commit."* Recomputing the diff and
bucketing by which section changed:

```
positives: 62
top-level sections touched, per task:
   37  ('user_scenario',)
   11  ('evaluation_criteria', 'user_scenario')
    5  ('evaluation_criteria',)
    3  ('description', 'user_scenario')
    3  ('description', 'evaluation_criteria')
    2  ('description',)
    1  ('description', 'evaluation_criteria', 'user_scenario')

tasks whose ONLY diff is /description/* (pure metadata churn): 2 ['airline/36', 'airline/39']
```

Both are edits to `description.purpose`, a human-readable annotation that reaches
neither the agent nor the evaluator:

```
airline/36 BASE: "... the change is not allowed."
airline/36 VER : "... the change is not allowed and the flight already took off."
airline/39 BASE: "... The tool does not allow to cancel without a refund."
airline/39 VER : "... Agents must follow airline policy and only cancel flights that are
                  eligible for refunds, even though the tool itself would process any cancellation."
```

Both are counted as defects Assay failed to find — `airline/36` under
`logical_consistency`, `airline/39` under `policy_compliance` in
`results/tau2_recall.json`. Two of the 41 false negatives are unfalsifiable.

3% of the labels, and it makes recall look *worse*, so it is not an overclaim.
But it falsifies the framing "62 defects an independent team labelled": a record
diff is not a defect, and the rule was never audited for what else it lets in.

What did **not** break: the base revision really is the last state of the task
files before the fork, so the diff carries no upstream churn —

```
$ curl -s 'https://api.github.com/repos/sierra-research/tau2-bench/commits?path=data/tau2/domains/retail/tasks.json'
01e812d1d1 2026-03-18 feat: τ³-bench 1.0.0 ...
37199f3692 2025-06-10 release            <- BASE_REV
   fork initial commit: 2025-11-26
```

Only two commits ever touched that file and the fork sits between them. And the
`ground_truth_annotation` / `instruction_underspecification` split reproduces
exactly: 20 / 42, matching the README's 13/20 = 0.65 and 8/42 = 0.19.

## 15. "The incumbent detects 2 of 46 defects" is a property of a reimplementation

**PARTIAL break.** The README frames its correction as having replaced a
strawman:

> An earlier version of this README said it scored *identically* to flagging
> nothing. That was measured against a reimplementation of the checkers that
> omitted their determinism check — a strawman weaker than the real tool.

The fix was to add a determinism check to the reimplementation, not to run the
real tool on the corpus. `src/assay/baselines/structural.py:22` is explicit
(*"This arm reimplements what they actually assert"*), and the arm can only ever
return `NONDETERMINISM`:

```python
detected: set[DefectClass] = set()
...
if len(fingerprints) > 1:
    detected.add(DefectClass.NONDETERMINISM)
return frozenset(detected), issues
```

So "2 of 46, 4.3% recall" is arithmetic on the corpus's `NONDETERMINISM` count,
not a measurement of `gymnasium.utils.env_checker`. It cannot come out any other
way.

The real checkers were run — on five purpose-built `gymnasium.Env` shims written
by the same author, with the defects chosen to be invisible to them
(`results/real_check_env.json`, 4 planted, 1 detected). That is a fair
demonstration of the ceiling and it is honestly labelled. It is not the headline
arm, and the README's correction paragraph reads as though it were.

This is defensible — the real checkers cannot be pointed at a `ToyEnv`, an
`inspect_ai` task or a Harbor container at all — but "the incumbent detects 2 of
46" is a stronger sentence than the evidence, and the same author who caught
"benchmarking against a reimplementation of a tool rather than the tool" is still
benchmarking against a reimplementation.

---

## What I could not break

Stated briefly, as instructed.

### 16. `paws` scores the constant string `"yesno"` at 100% — **survives, completely**

Verified from upstream sources with Assay out of the loop. `inspect_evals` 0.18.0
is the current PyPI release, so this is live today:

```
$ inspect_evals/paws/paws.py:  scorer=includes()   targets "Yes" / "No"
$ inspect_ai/scorer/_match.py:46  def includes(ignore_case: bool = True)  ->  target in value

$ .venv/bin/python -c "... real includes() over all 8000 test items ..."
'yesno' scored by real inspect_ai includes(): 8000/8000 = 1.0000

$ ... dataset at the pinned revision ...
n = 8000   label counts: Counter({0: 4464, 1: 3536})   frac No: 0.558
```

8000/8000, and the 4464 / 56% figure is exact. The one-sidedness table
reproduces, including `boolq`'s narrower leak — `pattern(r"(Yes|No).?\Z")` marks
`"I don't know"` correct on every `No` item, because `know` ends in `no` plus one
character:

```
completion                          inc:Yes    inc:No     pat:Yes    pat:No
'yesno'                             C          C          I          C
"I don't know"                      I          C          I          C
```

Would maintainers call it a trade-off? `includes()` is a documented,
intentionally loose scorer; the defect is choosing it for a two-token label set
where one label is a substring of common English. That is a benchmark-design
error, not a library bug, and the README says exactly that. No basis to soften
it.

### 17. `textarena_env` accepts a seed and ignores it — **survives, and is current**

```
$ textarena_env/server/environment.py:132
    def reset(self, seed: Optional[int] = None, episode_id=None, **kwargs):
        ...
        self._ta_env.reset(num_players=self.num_players)      # seed dropped

$ .venv/bin/python -c "... six resets at seed=1234 ..."
6x reset(seed=1234) secret words: ['owner','grass','plant','drink','trade','spade']
unique: 6
```

Still on `huggingface/OpenEnv` `main` today (fetched `raw.githubusercontent.com`,
line 150 identical). Not a trade-off, and stronger than the README claims:
upstream TextArena's own `reset` **does** take a seed —

```
$ .venv/bin/python -c "import inspect, textarena; ..."
Env.reset sig: (self, num_players: int, seed: Optional[int] = None)
Wordle reset sig: (self, num_players: int = 1, seed: Optional[int] = None)
```

— so this is a one-word omission in a wrapper, not a limitation of the
underlying environment. No upstream issue reports it (searched
`repo:huggingface/OpenEnv seed`; the nearest is #183, an open *feature* request
for passing parameters to `reset`, which suggests maintainers may class it as
"not yet wired" rather than "broken" — but a signature that accepts a parameter
and silently discards it is a defect on any reading).

### 18. `flag_everything`'s tight CI — **survives; the tightness is arithmetic**

Under `research-run` `flag_everything` has zero misses, so its loss is exactly
`1 × #spurious = 14·24 − Σ|planted| = 336 − 46 = 290`. Resampling only moves
`Σ|planted|`, which varies between 1 and 6 per environment. `[271, 307]`
corresponds to `Σ|planted| ∈ [29, 65]` — the correct width for that statistic.
Not suspicious, and not a sign of a broken resample.

### 19. Paired bootstrap construction — **survives**

`intervals.py` draws one index vector per iteration and evaluates every arm on
it, so paired differences share a resample. Correct. The flaw in finding 9 is in
the `separated` predicate, not in the pairing.

### 20. Committed results reproduce — **survives**

```
$ uv run --extra adapters --extra openenv python scripts/full_run.py
$ cmp results_committed/full_run.json results/full_run.json   → BYTE IDENTICAL
$ uv run --extra adapters python scripts/intervals.py --resamples 10000 --seed 11
$ cmp results_committed/intervals.json results/intervals.json → BYTE IDENTICAL
```

The README's headline table is exactly what the committed files say, on the
right command. `14 of 25` sampled `paws` items also reproduces
(`wild_sweep.py --only paws` → `n=25 … findings=14`, `registered 246`, `static
excluded 188`), and the split the README pins ("Assay did not find the `yesno`
case; hand triage did") is a real test —
`test_the_constant_string_exploit_was_not_in_the_challenger_repertoire`, which
asserts `"yesno" not in proposed`.

### 21. Prior art — **survives**

All six arXiv ids resolve, and the numbers match the abstracts:

- BenchJack 2605.12673 — "219 distinct flaws", 10 benchmarks, "without solving a
  single task", "from near 100% to under 10%": all four verbatim.
- 2606.16062 — "On a 49-task sample of SWE-bench Verified, 28.5% of tasks have
  test suites weak enough that a Docker-verified incorrect patch passes them":
  exact, including the gold-sanity-gate framing.
- BenchGuard 2604.24955 — "12 author-confirmed issues in ScienceAgentBench":
  exact. (The README's "83–100% recall" is a paper-body number I could not check
  from the abstract; the abstract's 83.3% is BIXBench, not SAB.)
- ABA 2605.26079 — 168 benchmarks, "over 25.7% of the evaluated tasks": exact.
- The Beigi et al. retraction is accurate: 2602.01750 is *Adversarial Reward
  Auditing for Active Detection and Mitigation of Reward Hacking*, an RLHF
  alignment paper, as the correction says.

### Minor, not worth a section

- **No `LICENSE` file.** README ends "## License / Apache-2.0"; `ls LICENSE*`
  finds nothing. Apache-2.0 requires the text be shipped.
- **The reliability run is the composite Challenger.** README: "The same
  Challenger was pointed at the same environment four independent times."
  `results/challenger_reliability.json` says
  `"challenger": "scripted+prompted[claude-cli:sonnet]"` — the ablation table's
  arm is `prompted, claude-cli` alone. The 3/4 result stands; the arm identity
  does not quite match. Everything else about that file is exemplary, including
  the recorded abort of a fifth run.
- **`results/wild_sweep.json` is not committed** and not gitignored, so the
  sweep's partition numbers (246/188/58/34/24/14) have no artifact to check
  against; only the hand triage ships.
- **SAB result provenance points outside this repository**
  (`/Users/…/assay-sab/results/…`), so the committed files were produced in a
  different working copy.

---

## The one sentence

The two upstream defects are real, current and correctly described — those are
the strongest thing here and they survived every attack. The measured claims did
not fare as well: the external validation number is chance, half the internal
corpus is the tool's own regression suite, the headline is carried by two rows
out of twenty-four, and the ablation table cites a run that is not in the
repository. The pattern across findings 3, 7 and 12 is worth naming on its own —
this project corrects itself carefully in `docs/`, and then leaves the
uncorrected version in the file most readers will read.
