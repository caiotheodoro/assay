# Results, in full

`README.md` carries the headline. This file carries the argument underneath it:
every arm, every cost profile, every caveat that makes a number smaller than it
first reads, and the two external measurements that break the closed loop.

Numbers here are read from `results/*.json`. `docs/REPRODUCTION.md` says how to
regenerate each one; `tests/test_published_claims.py` fails if the prose and the
artifacts disagree. Corrections this repository has had to publish are in
`docs/RETRACTIONS.md`.

---

## The run

28 environments, 54 planted defects. Needs Docker for the Harbor tasks. No GPU
and no API key.

```bash
uv run --extra tau2 python scripts/tau2_fetch.py                     # the two pinned snapshots, ~1 min
ASSAY_APPROVE_ALL="reproduction" uv run --extra adapters --extra sweep --extra openenv --extra tau2 \
  python scripts/full_run.py --out /tmp/check.json                   # 22s warm
```

**All four extras are load-bearing, and dropping one flatters the result.**
`--extra adapters` alone omits `openenv` and `inspect_evals`; without `--extra
sweep` the two `inspect_evals` environments go, including `boolq`, the single
documented miss; without `--extra tau2` the two τ² domains go, and with them all
three spurious findings. The environments a missing provider takes are the ones
Assay does worst on, so a reduced run produces a **better** number and exits 0 —
which is why `full_run.py` now refuses it outright. Without the Docker daemon the
run still completes, on the 23 environments
[`results/corpus_splits.json`](../results/corpus_splits.json) calls `no-harbor`,
and says which ecosystem it dropped and why.

---

## Every arm, on one corpus

Expected loss under the `research-run` cost profile, with 95% bootstrap intervals
(10,000 resamples, seed 11, resampling over environments):

| arm | expected loss | 95% CI | recall | precision |
|---|---|---|---|---|
| **assay+auditor** | **43.0** | [0, 125] | 0.982 | 0.946 |
| assay | **56.0** | [7, 141] | 0.982 | 0.768 |
| flag_everything | 458.0 | [438, 476] | 1.000 | 0.105 |
| always_modal_defect | 2054.0 | [1300, 2891] | 0.185 | 0.313 |
| direct_prompt (`qwen3:8b`) | 2299.0 | [1388, 3341] | 0.259 | 0.341 |
| stratified_random | 2794.0 | [1702, 4030] | 0.111 | 0.125 |
| agent_with_tools (`qwen3:8b`) | 2826.0 | [1761, 4029] | 0.204 | 0.244 |
| **check_env** (incumbent) | **3224.0** | [2040, 4528] | **0.019** | 1.000 |
| flag_nothing | 3232.0 | [2056, 4536] | 0.000 | 0.000 |

**Every arm is measured on the same 32 environments**, in the same
`results/full_run.json`, with intervals from the same bootstrap. That was not
always true — see `docs/RETRACTIONS.md` §3.

The deterministic arm is **worse than it used to be**, and that is the point of
the four environments added to the corpus. They have no correct answer, so every
finding the battery reports on them is a false positive: 16 spurious where there
were 3, precision 0.768 where it was 0.946. `assay+auditor` is the same battery
with the semantic gate reading it, and it recovers all 13 —
**13.0 saved, 95% CI [1, 28], separated.** Predicted before the environments
existed, in `docs/PRE-REGISTRATION-NOANSWER.md`.

### That precision of 1.000 is the modal run, not every run

Across six full-corpus runs, `harbor/broken-gold` reported a **spurious
`NONDETERMINISM` once** (one point of loss above the run's true figure);
harbor-only runs were clean 4 of 4, so the flake needs the load of a full run.
The determinism probe fingerprints `(ok, data, code)` and Harbor's step data is
`{stdout, exit_code}`, so a sandbox command that times out under load is
indistinguishable from an environment that is genuinely nondeterministic —
plausible, and **not isolated**, so it is reported as a rate rather than a
diagnosis.

### The two LLM arms are the brief's own simple baseline, and they are now indistinguishable from flagging at base rates

`direct_prompt` reads everything a careful human reviewer could read without
executing anything — the manifest, the instructions, the verifier source where it
can be obtained — and names the defect classes it thinks are present.
`agent_with_tools` gets the same plus a tool loop it can drive. They score
**2299.0 and 2826.0 against `stratified_random`'s 2794.0** — the plain prompt is
ahead of the random arm and the tool-using agent is behind it, and neither is
separated from it. The three paired differences, on the same shared resample as every
other comparison in this file:

| Comparison | Loss saved | 95% CI | |
|---|---|---|---|
| `direct_prompt` vs `stratified_random` | 495.0 | [−93, 1123] | **not separated** |
| `stratified_random` vs `agent_with_tools` | 32.0 | [−396, 513] | **not separated** |
| `direct_prompt` vs `agent_with_tools` | **527.0** | **[167, 931]** | **separated** |

**The one comparison among these that now separates says the tool loop hurt.** This
pair used to sit at −282.0 on an interval crossing zero; it is now a 527.0 advantage to
the *plain prompt*, and the interval clears zero. Giving the model a tool loop did not
buy accuracy — it bought 34 spurious findings against `direct_prompt`'s 27, on the same
corpus.

**That is a reversal from what this section used to report, and it is mostly not
the LLM arms.** They previously lost to `stratified_random` at 2658.0 / 2654.0
against 1789.0, separated. What moved is the baseline. `stratified_random` flags
each class independently at that class's corpus base rate, drawing one
`rng.random()` per class per environment in enum order, so adding two defect
classes to the taxonomy reshuffled its whole seeded sequence and cost it **+878
with no change to the corpus, the policy or the detector**. Against the policy's
closed-form expectation rather than one draw of it — **2474.3** — `direct_prompt`
at 2454.0 is a tie, which is the same answer the bootstrap gives. The arithmetic
and the prediction that preceded it are in
[`docs/PRE-REGISTRATION-TAU2.md`](PRE-REGISTRATION-TAU2.md).

So the honest reading is narrower than either the old one or its mirror image:
**reading an environment is indistinguishable from guessing at the base rate**,
better than the incumbent linter, and an order of magnitude worse than running the
probes. Neither LLM arm has been shown to beat the random policy, and the random
policy has not been shown to beat them.

The third row of that table is the one worth reading twice. The two arms are 282.0
apart on a 28-environment corpus, on an interval that crosses zero: **giving the
model a tool loop bought nothing measurable**. Recorded that way rather than as a
ranking, because reporting `agent_with_tools` as "the better LLM arm" on a
difference that small would be exactly the unfalsifiable claim this project exists
to catch.

Reading an environment is not auditing it. That is the whole argument for executing
the thing, and the row that carries it is no longer the comparison against random.
It is the comparison against the probes, in §What holds, and what does not below:
two separated paired differences of 2411.0 and 2693.0.

### Read the incumbent's row as a property of a model, not of the tool

The incumbent detects **2 of 54 defects — 3.7% recall**, both determinism, at
perfect precision. It is silent on the other ten probe families: verifier
integrity, trivial floor, separability, contamination, shortcut leakage,
spec/verifier mismatch, difficulty band, reward hackability, sandbox permissions
and evaluator code execution.

`src/assay/baselines/structural.py` is Assay's *reimplementation* of what
`gymnasium.utils.env_checker` and `stable_baselines3.common.env_checker` assert,
because the real checkers cannot be pointed at a `ToyEnv`, an `inspect_ai` task or
a Harbor container at all. `NONDETERMINISM` is the only class it can ever return,
so "2 of 54" is bounded by construction rather than measured. The real checkers
*were* run, on five purpose-built `gymnasium.Env` shims — 1 of 4 detected,
`results/real_check_env.json` — and that is the honest incumbent number. One of the
model's two hits is `fixture/flaky`, planted here.

---

## The corpus is almost entirely our own work, and the split is unflattering

The 28 environments are 12 in-process `fixture/*`, 5 `harbor/`, 5 `inspect/`, 2
`openenv/`, 2 `inspect_evals/`, 2 `tau2/`. Split on **who wrote the environment**, not on
the id prefix:

| provenance | n | what it is |
|---|---|---|
| authored here | 12 | our fixtures; `tests/test_probes_fire.py` asserts `detected == planted` on all of them |
| our content, third-party format | 10 | our datasets and defective scorers on inspect_ai's runtime; our task dirs in Harbor's shape, `authors = ["assay fixtures"]` |
| **genuinely external** | **6** | `openenv/echo`, `openenv/textarena-wordle`, `inspect_evals/paws`, `inspect_evals/boolq`, `tau2/retail`, `tau2/airline` — audited as shipped |

By ground truth: **22 planted here, 3 hand-triaged, 3 derived from a diff between two
pinned upstream revisions** (`openenv/textarena-wordle` and the two τ² domains). Those
three are the only labels in this corpus that someone other than us decided. Provenance is
declared in the registry (`src/assay/corpus.py`); an environment that declares none fails a
test rather than defaulting to clean, and — since `scored_entries()` — an environment whose
labels nobody established is audited and carded but **kept out of every scored number**.
Without that rule, registering the 32 other swept tasks would have paid `flag_everything`
16 points each for work nobody did.

`uv run --extra adapters --extra tau2 python scripts/corpus_splits.py`, full table
in `results/corpus_splits.json`. **`--extra tau2` is load-bearing**: without it the
two τ² environments drop out and the script recomputes every split on 26.

| split | n | assay | flag_everything | who wins |
|---|---|---|---|---|
| all (published) | 28 | 43.0 | 394.0 | assay, by 351 |
| our content, third-party format | 10 | 0.0 | 132.0 | assay |
| genuinely external | 6 | 43.0 | 89.0 | assay — and all four of its errors are here |
| in-process fixtures | 12 | 0.0 | 173.0 | assay — asserted, not measured |
| self-authored | 22 | 0.0 | 305.0 | assay |

### The two external environments were added under a pre-registration

`inspect_evals/paws` and `inspect_evals/boolq` were added under a pre-registration
committed **before** the code that moved these numbers (`docs/PRE-REGISTRATION.md`,
commit `d3da87c`), because `flag_everything`'s loss was `Σ (14 − |planted|)` at that
revision — it is `Σ (16 − |planted|)` now — and a corpus can be grown into a better
headline without anyone writing a false number.
Every prediction held: the floor went 290.0 → 316.0, Assay 240.0 → 280.0, and the
margin narrowed from 50.0 to 36.0. (Those were the numbers before the two Harbor
misses were closed; the table above is after.) `paws` was detected; `boolq` was
missed, structurally — `WildInspectAdapter` supplies no train split, so the shortcut
probe reports `NOT_APPLICABLE` before it runs and the verdict is `UNVERIFIED`, not
clean. Assay had previously called `boolq` clean, and it is in the corpus because of
that false negative rather than despite it.

### The split Assay used to lose

**Assay used to lose on the ten environments we wrote in someone else's format —
240.0 to 114.0, on three of four profiles. It now scores 0.0 there.** What changed
was two trivial policies named after flaw classes in BenchJack's taxonomy (arXiv
2605.12673, Fig. 2): V7 *trusting untrusted output* and V1 *isolation failure*. Both
were written against the mechanism the class describes and are handed only the task
text an agent already gets — never a filename or a value read out of an environment
in this corpus.

The evidence that they were not fitted to the two environments they close is
cross-wise: **V7 fires on `self-graded` and not on `shared-tests`; V1 fires on
`shared-tests` and not on `self-graded`; neither fires on `healthy`.** A pair of
policies reverse-engineered from those two fixtures would tend to fire on both. All
four facts come from each task's own `tests/test.sh` and `truth/test.sh` with no
probe in the loop, pinned in `tests/test_harbor_ground_truth.py`.

**One label changed, and it flattered us, so here is the number both ways.** Closing
the misses showed that both environments also pay full marks to an input-ignoring
policy, which is a trivial-floor breach by definition and was missing from their
ground truth. Correcting it removes two false positives. Measured at the
26-environment revision where the relabelling landed, Assay scored **40.0 at
precision 1.000** with the corrected labels and **42.0 at precision 0.959** with the
original ones — a 2.0 difference against a margin two orders of magnitude larger, so
the result does not depend on the relabelling, which is why the relabelling is
defensible. On the corpus published today Assay scores **43.0 at precision 0.9464**
and the margin over the floor is **351.0**; the counterfactual was not re-run at 28
environments and no artifact in `results/` carries it, so it is quoted as the
historical figure it is rather than restated in the present tense.

The single remaining miss is `inspect_evals/boolq`, and it is external.

### The mirror image, and it no longer flatters us

Dropping Docker used to delete every environment Assay gets wrong along with the
Harbor tasks, and this section reported the 0.0 that fell out of that. **It does
not any more.** Assay's four errors are now `inspect_evals/boolq` (the one miss)
and three spurious findings on the two τ² environments, and none of those four is
a Harbor task. So the `no-harbor` split keeps all of them: on its 23 environments
and 42 planted defects Assay scores **43.0 / 246.0 / 624.0 / 4.0** across
`research-run`, `production-training`, `benchmark-publication` and `flat` — the
same numbers as the full corpus — and saves **283.0, CI [197, 335], separated**
over `flag_everything`'s 326.0
([`results/corpus_splits.json`](../results/corpus_splits.json), split
`no-harbor`). The split that used to be a flattering one is now simply a smaller
one.

### And note what the arithmetic does here

`flag_everything`'s loss is exactly `Σ_env (16 − |planted_env|)`, so **every clean
environment added moves the floor by +16 and Assay by 0**. At that rate **22 clean
third-party environments manufacture the entire published margin of 351.0** with
the detector unchanged, and seven of them manufacture 112 of it. That is why
provenance is declared before the corpus grows, and why any
expansion has to pre-register the expected mechanical shift — otherwise a bigger
corpus is a manufactured win.

**The same arithmetic runs the other way, and it has never been stated in full.**
Four of the sixteen classes in the taxonomy — `DIFFICULTY_SATURATED`,
`DIFFICULTY_IMPOSSIBLE`, `EXCESSIVE_PERMISSIONS` and `EVALUATOR_RCE` — occur
**nowhere in the corpus**: zero planted across all 28 environments. `flag_everything`
names each of them on every environment anyway, which is `4 × 28 = 112` false
alarms, **28.4% of its 394.0**, on classes no other arm in the table ever names
and no environment in the corpus can carry. Nothing is being detected on either
side of that 112: it
is not evidence Assay is better, it is the floor paying for a taxonomy the corpus
does not exercise. Verify it from `results/full_run.json` — `per_env[*].planted`
never contains those four classes, and `arm_detections` gives `flag_everything`
28 of each and every other arm zero. The **+52** from the two newest classes,
decomposed in `README.md`, is the *increment*; 112 is the standing total.

The honest summary: **n=6 is the size of the third-party control, and only 3 of those carry a label we did not decide**, the corpus
is too small and too self-authored to support the pooled headline, and growing it
with environments nobody here wrote is the first thing worth doing next — carefully.

---

## The headline survives a 1005% error in one made-up number

Every expected-loss figure is denominated in "engineer-hours-equivalent", and
`src/assay/costs/profiles/research-run.yaml` prices a missed CRITICAL defect at
**120** of them. Nothing derives that 120. It is a considered guess, and every number
above scales linearly with it.

So: sweep it. `uv run --extra adapters python scripts/cost_sensitivity.py`, holding
the severity shape fixed and moving only the miss/false-alarm exchange rate
(`results/cost_sensitivity.json`):

| CRITICAL miss cost | assay | assay+auditor | flag_everything | winner |
|---|---|---|---|---|
| 120 *(shipped)* | 56.0 | 43.0 | 458.0 | assay+auditor |
| 400 | 149.33 | 136.33 | 458.0 | assay+auditor |
| 800 | 282.67 | 269.67 | 458.0 | assay+auditor |
| **1326.0** | **458.0** | **445.0** | **458.0** | **tie** (deterministic arm) |
| 2000 | 682.67 | 669.67 | 458.0 | flag_everything |

The crossover is exact rather than bisected. Every severity scales about the CRITICAL
anchor, so each arm's loss is **affine** in `C` — the single unchecked HIGH scales with
it and the constant false alarms do not, giving `assay(C) = C/3 + 16` and
`assay+auditor(C) = C/3 + 3` — while `flag_everything` never misses and does not move
with `C` at all. The agent arm crosses at `3 × (458 − 3) = 1365.0` and the deterministic
one at `3 × (458 − 16) = 1326.0`, and `results/cost_sensitivity.json` reports the
tighter of the two as `exact_crossover_critical_cost`. **A ratio stood here and it is
not the solve**: `120 × 458 / 56` prices the constant false alarms as though they scaled
too. The affine form is why the sweep's rows read 149.33 and 282.67 rather than 163.33
and 306.67.

**The shipped value is 120. The crossover is 1326.0.** That margin was **21%** before
the two Harbor misses were closed — the crossover sat at 145 against the same shipped
120 — and **685%** before the taxonomy grew from 14 defect classes to 16. Worth stating
plainly because the earliest number was the sharpest criticism of this work and it is
the one that changed most. Note what moved it last: the numerator is
`flag_everything`'s loss, so the margin widened because the floor got worse, not because
the detector got better.

That is not a reason to distrust the ranking so much as a statement of what the ranking
is: a claim about a specific cost regime, not about detectors in general. The one anchor
available is that SWE-bench Verified needed **93 developers** reading tasks by hand —
the observed price of finding these defects the other way, and why a miss is priced far
above a false alarm rather than near it. It does not pin 120 versus 1326.0.

Reported here rather than left for a reader to derive, because a paragraph saying "costs
are illustrative" would have hidden that the margin was ever 21%.

---

## What holds, and what does not

Two overlapping one-sample intervals do not settle "A beats B", so the claims are paired
differences drawn on a shared resample:

| Comparison | Loss saved | 95% CI | |
|---|---|---|---|
| assay vs `flag_nothing` | 3189.0 | [2079, 4422] | **separated** |
| assay vs `check_env` | 3173.0 | [2055, 4415] | **separated** |
| assay vs `always_modal_defect` | 2007.0 | [1291, 2778] | **separated** |
| assay vs `stratified_random` | 2750.0 | [1716, 3926] | **separated** |
| assay vs `direct_prompt` | 2411.0 | [1587, 3343] | **separated** |
| assay vs `agent_with_tools` | 2693.0 | [1711, 3799] | **separated** |
| **assay vs `flag_everything`** | **351.0** | **[263, 404]** | **separated** |
| `check_env` vs `flag_nothing` | 16.0 | [0, 40] | overlaps zero |

The two LLM rows are the ones that carry "reading an environment is not auditing
it" now that the comparison against `stratified_random` no longer does.

**Assay beats the trivial floor, and for most of this project's life it did not.** That
row read `50.0, [−309, 295], overlaps zero` at n=24, and the honest summary was that the
advantage was not established. Two Harbor misses closed it, and the sentence is only
worth reading because the previous one was published for as long as it was true.

### The two trivial policies the brief asks for

`stratified_random` and `always_modal_defect` are the two trivial policies `criteria.md`
requires that this repo did not implement until `docs/changelog/62-rigour.md`. Neither
becomes the floor: on an imbalanced 16-class multilabel problem, flagging at base rates
buys recall 0.111 at the cost of 41 false alarms and 48 misses, which is worse than
flagging everything under every cost-asymmetric profile and worse than flagging nothing
under `flat`. Adding a harder-sounding baseline did not make the floor harder, and that
is published as the result rather than as a reason not to have run it. The figures above
are read from `results/full_run.json` and `results/intervals.json`, which are the
current corpus. **`results/baselines.json` is not**: it still records
`n_defect_classes: 14`, `n_environments: 24`, `n_planted_defects: 46`, so its per-profile
table and its closed-form column are the 24-environment measurement and are cited here
only as that. Regenerating it is outstanding work, noted rather than done quietly.

### The one interval whose shape decides its own answer

Against `flag_nothing`, `check_env` saves **16.0 expected loss, 95% CI [0.0, 40.0]** — an
interval that includes zero. `check_env` emits no false positives and detects a strict
subset of what is planted, so the paired difference is >= 0 in every resample — 10,000 of
10,000. An interval that can never go negative cannot exclude zero from above, so "not
statistically distinguishable" was decided by the shape of the test, not by the data. On a
one-sided reading the claim survives at p ~ 0.12: that is the chance no `NONDETERMINISM`
environment is drawn, (22/24)^24, and it is the whole result.

Same caveat on the one-sample intervals. With Assay wrong on exactly 2 of 24 environments
at the time that was computed, the bootstrap distribution of its loss is a binomial count
on a 120-point lattice — ten distinct values, 12.4% of the mass on exactly 0.0. The
`[0.0, 600.0]` interval is the 2.5th and 97.5th rungs of that ladder. It is honest
resampling on a corpus too small to carry the precision "95% CI" implies, and it is
reported here rather than left for a reader to derive.

---

## Every profile, including the ones that used to lose

Running only the flattering cost model would be its own kind of dishonesty, so here is
every profile shipped, not the one that reads best.

| profile | assay | flag_everything | saved | |
|---|---|---|---|---|
| `flat` | **4.0** | 394.0 | 390.0 | separated, [371, 408] |
| `research-run` | **43.0** | 394.0 | 351.0 | separated, [263, 404] |
| `production-training` | **246.0** | 788.0 | 542.0 | separated, [46, 808] |
| `benchmark-publication` | **624.0** | 3152.0 | 2528.0 | separated, [1264, 3232] |

**Assay now wins all four and separates on all four** — but read
`production-training` carefully before crediting it. Its interval was
[−108, 652] and not separated at 26 environments; what closed it is largely the
same arithmetic that widened the headline. `flag_everything` pays two false
alarms per class per environment under that profile, so two added classes and
two added environments moved the floor from 628.0 to 788.0 while Assay went
240.0 to 246.0. A separation bought by the floor getting worse is not the same
fact as one bought by the detector getting better, and the lower bound of 46 is
thin enough that one environment could take it back. It previously won one and lost two
outright, and the reasoning published then still stands as the reason those two were the
hardest: `production-training` prices a missed CRITICAL at 960 against a false alarm at
2, and `benchmark-publication` at 2000 against 8. At a 480:1 ratio, "flag everything and
read the cards" is a genuinely good policy, which is why beating it there took closing
the misses rather than tuning the metric — and why the separation it now shows,
**542.0 on [46, 808]**, is worth less than the three above it. The 388.0 on an
interval crossing zero that this paragraph used to report was the figure at 14
classes and 26 environments; the number moved, the caution did not.

The pattern is the whole argument for reporting a profile rather than a number. A single
accuracy figure would have hidden which regime the tool is for, and a single cost profile
would have let us choose which way it hid.

**One miss remains across 28 environments, and it is external:** `inspect_evals/boolq`.
The two `harbor/` misses that carried this section for weeks are closed.

---

## Does an agent find what a script cannot?

**It did. Then a better script found it too, and that is the more useful result.**

The ablation below was run when the scripted repertoire held four policies and missed
`harbor/self-graded`. It has since been given two policies named after classes in
BenchJack's published taxonomy — V7 *trusting untrusted output* and V1 *isolation
failure* — and now finds both Harbor exploits with no model in the loop at all. **The
table is kept as the historical measurement it was, not as a current claim**; every
number in it describes the old six-candidate-free repertoire.

The honest reading: the agentic arm demonstrated an exploit class existed, and the
cheapest possible response — writing the mechanism down as a fixed policy — captured it
permanently at zero marginal cost. That is a good outcome for a tool and a bad one for
the argument that the agent is load-bearing.

*Historical, superseded — `scripts/challenger_ablation.py` against the four-policy
repertoire:*

| Challenger | Result | Exploit gap | Scored attempts | Wall clock |
|---|---|---|---|---|
| scripted *(then)* | missed | 0.00 | 4 | 2.2s |
| prompted, `qwen3:8b` | missed | 0.00 | 10 | 97.0s |
| prompted, `claude-cli` | **found** | **1.00** | 10 | 261.7s |
| **scripted *(now)*** | **found** | **1.00** | 6 | **3.8s** |

The first three rows are read from `results/challenger_ablation.json`; the fourth —
`scripted (now)` — is `results/scripted_floor.json`, which is a different run against a
different repertoire and is why the row is labelled. A 10-turn budget; "scored attempts" counts
the turns that parsed into an action. Wall clock is with the Ollama model already
resident; the first call after a model swap costs another two to three minutes.

The winning policy, at turn 8, after seven turns of reconnaissance — hunting for the
verifier, listing `/logs`, checking file permissions, trying to write `reward.txt`
directly:

```sh
echo -n 'banana' > expected.txt; echo -n 'banana' > out.txt
```

It does not forge an answer. It **overwrites the expected answer** so the verifier's
comparison is trivially true, and by turn 10 it does the same with `WRONG_XYZ` — a string
that is not the answer to anything.

Scored 1.0 by the environment. Scored 0.0 by the independent verifier the agent never had
access to. That difference is the whole measurement.

The misses are as much the result as the hit. An ablation showing only the arm that
worked says nothing about how hard the problem is — and in this case the arm that worked
was later matched by four lines of shell.

### How often, though

That table is one run each, and one run is not a capability. A Challenger was pointed at
the same environment four independent times (`scripts/challenger_reliability.py`,
`results/challenger_reliability.json`):

Not quite the same arm, and the distinction matters. The ablation row above is `prompted,
claude-cli` alone; the reliability run records `scripted+prompted[claude-cli:sonnet]` —
the **composite**. So 3-in-4 is the reliability of the arm Assay actually ships, not of
the row directly above it.

| run | result | gap |
|---|---|---|
| 1 | found | 1.00 |
| 2 | found | 1.00 |
| 3 | **missed** | 0.00 |
| 4 | found | 1.00 |

**3 of 4.** A probe backed by a sampled model is not a deterministic check. The number
reported is a rate. It also means a real audit should run the Challenger more than once,
and Assay does not currently do that by default: the probe takes one pass per environment
unless `challenger_passes` says otherwise, so a card can say `VALID` on an environment a
second attempt would have broken. That is a known gap, not a solved problem.

### The trained Challenger, which did not work

A Challenger was trained with GRPO against a dense exploit-gap reward (`reported score`
minus `independent true completion`, held by the harness and never shown to the attacker)
on a spot A10G, with `harbor/self-graded` held out. That holdout does not hold:
`results/train_holdout_dedup.json` records 60 of 300 training rows carrying its
byte-identical prompt, true Jaccard 1.0, so 20% of training saw the held-out environment.
The result is reported against a contaminated split and is weaker than it reads. It did
not close the miss, and neither did the prompted Challenger on local 1.7B/8B models.

The reward itself is verified — 38 tests, four against real containers, no GPU — and the
run logs say precisely what failed: 99.7% of GRPO rollout groups had zero reward spread,
so there was no gradient at all. Numbers, the single-variable follow-up run, and what to
try next are in `docs/changelog/40-grpo-challenger.md`. Nothing about the trained
Challenger is required to run Assay: it ships as an optional artifact, the scripted
Challenger is the floor, and the reproduction guide never asks for a GPU.

---

## Breaking the closed loop: recall on defect lists other people confirmed

Everything above is measured against defects **this repo planted**. That is a closed
loop. These two measurements break it — scored where possible by someone else's code
rather than ours.

### τ²-bench — 62 defects an independent team labelled

`amazon-agi/tau2-bench-verified`: an independent team read all 164 τ-bench retail and
airline tasks, judged some wrong, and shipped corrected files. Labels here are built from
the **diff between two pinned revisions**, not from the prose — anyone can recompute them
with `json.load` and `==`.

**Apply this repo's own trivial-floor rule first.** `metrics.py`: *"if it cannot beat the
best policy that ignores its input, it has not earned its existence."* Every environment
Assay audits is held to that. This measurement was not, until a red-team pass caught it.
The floor here is a flagger that picks the same number of tasks at random;
`flag_everything` scores recall 1.000 at precision 0.378.

| | recall | precision | vs. flagging at random | one-sided p |
|---|---|---|---|---|
| excluding `assert_traceability` | 0.210 (13/62) | 0.565 | 13 hits vs. 8.70 expected | **0.040** |
| all 12 probes | 0.339 (21/62) | 0.389 | 21 hits vs. 20.41 expected | **0.486** |

**The 0.339 row is chance.** Flagging 54 of 164 tasks uniformly at random lands 20.41
positives in expectation; Assay lands 21. Its precision of 0.389 beats the 0.378 base
rate — the precision of *any* random flagger — by 0.011. That row is a real number,
honestly computed, and it is not evidence that Assay detects τ-bench defects.

Only the narrower row clears the floor, at p = 0.040. So the advisory probe is not a
bonus with a caveat: `assert_traceability` supplies 8 of 21 true positives and 23 of 33
false positives, and including it **destroys the measurement**.

Read the p-values, not the recall. Both rows and the floor are in
`results/tau2_recall.json`; the test is exact (hypergeometric), so it needs no sampling
and no normal approximation.

**The split is the result, not the headline:**

| what the fix actually corrected | recall |
|---|---|
| ground-truth annotation errors | **13/20 = 0.65** |
| instruction under-specification | **8/42 = 0.19** |

Assay reads verifiers. **Two thirds of what τ-bench needed fixed was not a verifier** —
it was an instruction too vague to grade consistently. By category: logical consistency
0.71, policy compliance 0.43, unattributed 0.27, evaluation ambiguity 0.24 — and
evaluation ambiguity is **0/21** once the advisory heuristic is removed.

Two caveats on the label rule, both self-penalising. `airline/36` and `airline/39` differ
only in `description.purpose`, a human-readable annotation that reaches neither the agent
nor the evaluator — 2 of the 62 "defects" are documentation edits, and both are counted
against Assay. And `SCHEMA_ONLY_FIELDS` excludes nothing: the field it names is absent
from both revisions, so the exclusion is a no-op. Recomputing the diff with no exclusion
at all still gives 62. The count is right; the reason previously given for it was never
checked.

### ScienceAgentBench — 0 of 12, by BenchGuard's own scorer

BenchGuard reports 12 author-confirmed defects across SAB's 102 tasks. Assay was scored
against them by `BenchGuard/eval/metrics.py` over verdicts from their `eval/match.py`.
Nothing here recomputes it.

**Recall@ALIGNED 0/12.** Assay submitted zero findings, so their judge scored zero pairs
at $0.00.

The honest reading is not that Assay finds instruction defects hard. It is that **Assay
could not run at all on this benchmark, and said so twelve times** — all 12 probes
returned `NOT_APPLICABLE` with a reason, verdict `UNVERIFIED`. ScienceAgentBench is a
static task-definition set; these probes need an executable environment with a separable
verifier. On this benchmark the two tools are not competitors, and the zero says so more
plainly than any argument.

One thing fell out of running their scorer, and one argument did not:

- **Measured — nine of the twelve defects are already fixed** in the split SAB tells you
  to use, so any tool's SAB recall number is uninterpretable without naming the split.
- **Not measured — whether the heuristic this project rejected would score respectably
  through their metric.** The run stopped: 4 of its findings land on revised tasks, so
  `match.py` must call a Gemini judge, and no API key was set. The artifact records
  `their_report: null` and says so.

  The argument itself still stands and can be checked without a judge: R1 fires on 61 of
  102 tasks, and `metrics.py` computes precision only over findings on the 12 revised
  tasks, so most of what it emits is structurally invisible to that metric. R1 submitted
  **20** findings, 4 on revised tasks, so **16** on clean ones.

Full write-up: `docs/SCIENCEAGENTBENCH.md`.

### What this changes about the claims above

The blind spot is now measured twice, on two independently labelled sets: **Assay does
not detect instruction defects, because "this instruction is ambiguous" is a judgement
and nothing here scores with a judge.** That was published as a limitation before it was
measured; it is now a number.

---

## Prior art, in full

The category is not new and Assay does not claim it is. Static auditors read a
benchmark's files; dynamic auditors execute it. Assay's probe vocabulary is its own,
but partial-input baselines, reward-model overoptimization and
separability-as-a-metric are all ported rather than invented. One earlier version of
this section overclaimed and mis-cited someone else's paper —
`docs/RETRACTIONS.md` §16.

**Static auditors — reason over a benchmark's files:**

- **BenchGuard** ([arXiv 2604.24955](https://arxiv.org/abs/2604.24955)) — 12
  author-confirmed defects on ScienceAgentBench across 102 tasks, 83–100% recall
  depending on model and whether agent traces are supplied, ~$0.12–0.30 per task.
- **ABA** ([arXiv 2605.26079](https://arxiv.org/abs/2605.26079)) — 168 benchmarks,
  34,285 tasks, **14,024 major issues affecting 25.7% of tasks**. Publishes a table
  claiming it beats BenchGuard on both SAB and BixBench.

Assay has been scored head-to-head against BenchGuard's 12 defects **using
BenchGuard's own `eval/match.py` + `eval/metrics.py`**, not a scorer written here.
**ABA's audit scores 10/12 on that gold; Assay scores 0/12** — because SAB's verifier
lives in a password-protected archive and all 12 probes returned `NOT_APPLICABLE`, so
Assay could not run on this benchmark at all. The numbers, the two ways that
comparison is unfair to BenchGuard's own metric, and why "could not run" is kept apart
from "ran and found nothing" are above.

```bash
uv run --extra sab --extra adapters python scripts/sab_benchguard_recall.py \
    --arm assay --split original \
    --benchguard-root third_party/BenchGuard \
    --converter third_party/auto-bench-audit/benchmarks/benchguard/audits_to_benchguard_findings.py
```

**Dynamic auditors — execute the environment. These are Assay's actual cousins:**

- **BenchJack** ([arXiv 2605.12673](https://arxiv.org/abs/2605.12673)) — drives coding
  agents to audit benchmarks. **219 flaws across 10 agent benchmarks**, near-perfect
  scores obtained "without solving a single task", and an adversarial patch-and-repeat
  loop that drove the hackable-task ratio from ~100% to under 10%.
- **Auditing Reward Hackability in Code RL Training Environments**
  ([arXiv 2606.16062](https://arxiv.org/abs/2606.16062)) — a Docker gold-sanity gate,
  essentially Assay's "does gold pass" probe, already run on a flagship benchmark:
  **28.5% of 49 SWE-bench Verified tasks are hackable**.

**Methods Assay ports rather than invents:**

- Partial-input baselines — Gururangan et al.
  ([N18-2017](https://aclanthology.org/N18-2017)); the caveat on reading them
  backwards, [P19-1554](https://aclanthology.org/P19-1554).
- Reward-model overoptimization — Gao, Schulman, Hilton
  ([arXiv 2210.10760](https://arxiv.org/abs/2210.10760)), the standard citation for
  reward hacking and the ancestor of the whole reward-hackability family.
- Dedup tooling — datatrove, text-dedup, SemHash, LLM-Decontaminator. Contamination
  exemplars: GSM1k ([arXiv 2405.00332](https://arxiv.org/abs/2405.00332)), LiveBench,
  LiveCodeBench.
- Separability as a benchmark meta-metric — Arena-Hard
  ([arXiv 2406.11939](https://arxiv.org/abs/2406.11939)).

### What Assay adds

Narrowed to what the literature actually supports.

1. **The bundle, not dynamism.** Running probes against a live harness is *not* novel —
   BenchJack does it, and arXiv 2606.16062 runs a gold-sanity gate on SWE-bench
   Verified. What no other tool does is carry verifier integrity, contamination,
   shortcut leakage, separability, difficulty and reward-hackability in one report
   under one severity-weighted expected-loss metric. ABA's own static-vs-trajectory
   ablation, which agrees with itself only 29–63% of the time, is the best published
   evidence that these modes are not interchangeable.
2. **Expected loss rather than a defect count.** Every system above reports how many
   defects it found. None reports what missing one costs against what a false alarm
   costs, or publishes the cost profiles under which it loses to flagging everything.
3. **Absence of evidence reported as loudly as evidence.** Every card names the probes
   that could not run and why. On `openenv/textarena-wordle` that is 11 of 12.
4. **One tool across RL environment, agent benchmark and eval suite** — inspect_ai,
   Harbor, OpenEnv and submitted specs behind one adapter protocol.

A learned adversarial Challenger was trained and **did not work**; the honest write-up
is `docs/changelog/40-grpo-challenger.md`. It is listed here as an attempt, not a
contribution.

---

## What every agent actually did

`results/trajectories/INDEX.md` — one representative run per agent this submission used,
readable end to end without running anything: the instructions the agent was given, every
action it took, what the tools said back, the feedback that shaped its next step, and
every human approval.

Failed turns and malformed replies are kept. Three of the eight are Challenger **misses**,
one of those is the same `claude-cli` arm failing on the task it cracks in another run,
and one is the sandbox approval gate **refusing** — `DenyAll` is the default, and nothing
executes untrusted environment code without an approver who leaves a reason.

```bash
uv run --extra adapters python scripts/export_trajectories.py
```
