# Pre-registration — registering τ²-bench as two external corpus environments

**Committed before the code that changes any of these numbers.** Same rule as
[`docs/PRE-REGISTRATION.md`](PRE-REGISTRATION.md), which this file follows in shape: check the git
history, this lands in its own commit ahead of `src/assay/_tau2_corpus.py`.

## Why this document exists

Three independent model reviews of this repository deducted on the same fact, and it is true:
**22 of the 26 corpus environments are self-authored or project-controlled, and only 4 are
genuinely third-party** (`results/corpus_splits.json`, `external-envs`). `README.md` already
publishes that split and says the headline is movable by corpus composition. The `external-envs`
row is `n=4`, which the README itself calls "not a measurement — the honest size of the third-party
control this corpus currently has".

τ²-bench is the one source in this repository where **somebody else established the labels**. The
adapter has existed since Slice 26 and drives tau2's own evaluators; what has never existed is a
mapping from tau2's ground truth to `DefectClass`, and `docs/ARCHITECTURE.md:210-232` says so
plainly — tau2's ground truth is task-level *"this record differs between two pinned revisions"*,
not a `frozenset[DefectClass]`, so it registers nothing and is invisible to `corpus.entries()`.

**Building that mapping is the whole of this change, and the mapping is what should be judged.**
An unexplained mapping from someone else's categories onto our taxonomy is label engineering. So
every rule below is derived from the revision diff, stated before the run, and each excluded class
carries a written reason.

## The evidence, and what it can and cannot say

Two pinned revisions, already in `src/assay/tau2_truth.py:38-45`:

- base — `sierra-research/tau2-bench@37199f36924c8896f5e048360691f8476cd89ba1`
- verified — `amazon-agi/tau2-bench-verified@a470e45f2e799286cb87d26b8b30d8ab558a3375`

A task is a labelled positive iff its record differs between them. **62 of 164** do (retail 35 of
114, airline 27 of 50). That rule is a `json.load` and a `==`; anyone can recompute it and nothing
in this repository gets a vote.

Across all 62 positives the diff touches exactly **four** field families, and no others:

| changed leaf path | leaf changes |
|---|---|
| `/evaluation_criteria/actions` | 166 |
| `/user_scenario/instructions/*` | 54 |
| `/evaluation_criteria/nl_assertions` | 15 |
| `/description/purpose` | 9 |

`Tau2Adapter._instruction` concatenates `/user_scenario/instructions/*` and `/description/purpose`
into `Task.instruction` — the human-facing brief. `/evaluation_criteria/*` is the answer key the
scorer grades against. So the diff partitions cleanly into *the brief moved* and *the answer key
moved*, and that partition is already computed and already tested in this repository:
`tau2_truth.mechanical_category`, pinned by
`tests/test_tau2_ground_truth.py::test_mechanical_category_splits_answer_from_instruction`. It is
being reused rather than replaced precisely so that the mapping cannot be accused of having been
shaped to fit an answer.

| `mechanical_category` | rule | retail | airline | total |
|---|---|---|---|---|
| `ground_truth_annotation` | any `/evaluation_criteria` leaf changed | 8 | 12 | **20** |
| `instruction_underspecification` | only instruction leaves changed | 27 | 15 | **42** |

Zero positives are whitespace-only under `re.sub(r"\s+", " ", ...)`, checked before writing this.

## The mapping

### Rule 1 — `instruction_underspecification` → `SPEC_VERIFIER_MISMATCH` (42 tasks)

The third party **rewrote what the solver is told and left the answer key untouched**. There is
only one reason to do that: the brief did not lead to the answer the verifier already required.
That is the definition of family 6 — `types.py` describes `Task.instruction` as the thing
"family 6 compares against what the verifier actually asserts".

Read against the data rather than asserted:

- `retail/0`, `retail/1` — "exchange the mechanical keyboard for **a similar one**" →
  "for **a the same one**". The gold action always required the same item id; the brief said
  "similar".
- `retail/2` — "you want to know how many tshirt options are available" →
  "…, **ask the agent to count them and give you the number**". The criteria required a
  communicated count; the brief did not ask for one.
- `airline/12` — "add 2 checked bags under your name using your Gold membership" →
  "… **even if the upgrade is not possible**". The criteria required the bags unconditionally.
- `airline/15` — "the cheapest **economy** flight" → "the cheapest flight in
  **Economy cabin class (not Basic Economy)**". The gold flight was economy-not-basic.

For all 27 retail cases of this rule the verifier's own NL claims never move at all
(`/evaluation_criteria/nl_assertions` has **zero** retail leaf changes). The brief moved to meet a
stationary verifier. That is the cleanest possible instance of the class.

### Rule 2 — `ground_truth_annotation` → `KNOWN_WRONG_PASSES` (20 tasks)

The **answer key itself was replaced**. The pre-fix verifier therefore accepts, and is guaranteed
to accept, a trajectory a third party has judged wrong — because that trajectory *is* its answer
key. `types.py` files `KNOWN_WRONG_PASSES` under verifier integrity, and `Tau2Adapter`'s own
docstring for `known_wrong_actions` already reaches for the same reading: "a task whose *expected*
actions violate the domain policy is a known-wrong policy that the verifier is guaranteed to
accept, because it is the answer key."

Again, against the data:

- `retail/12` — gold action `return_delivered_order_items` with `payment_method_id:
  paypal_9497703` replaced by `transfer_to_human_agents`. The pre-fix answer key rewarded a refund
  the domain policy forbids.
- `airline/2` — gold action `send_certificate` for $50 deleted, and the NL assertion inverted from
  "Agent should offer a certificate of $50" to "Agent should **not** offer a certificate of $50".
  The pre-fix key rewarded compensation the policy does not allow.
- `retail/18` — `new_item_ids: 8069050545` → `3609437808`. The pre-fix key demanded an exchange
  for an item that could not satisfy the request.

`/evaluation_criteria/nl_assertions` is folded into this rule rather than given its own, because
it is the same claim — the graded answer was wrong — reached through the scorer's prose instead of
its action list. Exactly one positive (`airline/5`) changes `nl_assertions` without changing
`actions`; the other nine change both.

### Environment-level labels

The corpus scores environments, not tasks. Both classes occur in both domains, so:

```
tau2/retail   frozenset({KNOWN_WRONG_PASSES, SPEC_VERIFIER_MISMATCH})
tau2/airline  frozenset({KNOWN_WRONG_PASSES, SPEC_VERIFIER_MISMATCH})
```

**This is coarse and it flatters Assay, so it is said here rather than discovered later.** At task
level, `results/tau2_recall.json` already reports Assay detecting the `ground_truth_annotation`
tasks at 0.875 (retail) / 0.500 (airline) and the `instruction_underspecification` tasks at
**0.185 / 0.200**. An environment-level tick of `SPEC_VERIFIER_MISMATCH` records a class Assay
found *somewhere* in 114 tasks while missing it on 22 of the 27 tasks that carry it. The
environment-level number is the one the corpus scores; the task-level number is the one that is
true, it is already published, and this document is not a reason to stop quoting it.

### Provenance

`EnvAuthor.EXTERNAL` + `LabelSource.EXTERNALLY_DERIVED` — the strongest pair the vocabulary has.
`inspect_evals/{paws,boolq}` are `EXTERNAL` + `HAND_TRIAGED`: external environments whose labels a
person here established by driving upstream's scorer. These are external environments whose labels a
*different organisation* published, in a repository, at a commit.

**Correction, added after `tests/test_published_claims.py` caught it.** This section first said
these were the first use of `EXTERNALLY_DERIVED` in the registry. That is false:
`openenv/textarena-wordle` has carried it since the OpenEnv corpus landed. The surviving
distinction is narrower and worth stating exactly — wordle's label was derived outside Assay but
*decided* here, by reading TextArena's own game state and judging the result a defect; nobody here
decided which τ² tasks are wrong. The gate that caught it is the same shape as the one this
document is written under, and it caught an overclaim in the write-up of a change whose whole
subject is not overclaiming.

## The fourteen classes that are excluded, and why

A mapping is only honest if the exclusions are argued as hard as the inclusions.

| class | why the diff does not establish it |
|---|---|
| `GOLD_FAILS` | **Deliberately excluded, and it costs us.** The diff establishes that the pre-fix answer key was *wrong*, not that it *fails its own verifier* — a wrong key that executes cleanly and scores 1.0 is the worse defect and is the one the evidence supports. Assay's `gold_passes` probe fires on 4 retail tasks and 2 of those 4 (`retail/64`, `retail/105`) are tasks the third party **did not change**; gold answers the tools refuse also persist *after* the fix (`retail/{18,64,91,105}`). Gold-execution failure is orthogonal to what the revision diff is about, so it stays out and Assay pays for reporting it. |
| `NOOP_PASSES` | Nothing in the diff speaks to whether an empty transcript scores. The evidence points the other way: `results/tau2_recall.json` records `noop_fails` at tp=0/fp=2 on retail and tp=1/fp=6 on airline — 8 of its 9 findings land on tasks the third party inspected and left alone. |
| `NONDETERMINISM` | `seed_determinism` returns PASS on both domains, but that is Assay's claim about Assay. The diff says nothing, so the class is excluded for absence of evidence, not for evidence of absence. |
| `INVERT_PASSES` | tau2 tasks carry no `env_assertions` — all 164 checked — so `invert_spec` raises `NotSupported` and the probe reports NOT_APPLICABLE. There is no negation to substitute. |
| `TRIVIAL_FLOOR_BREACH`, `SEPARABILITY_LOSS` | `trivial_policies` and `graded_policies` both refuse: a degenerate tau2 policy is a conversational refusal only the LLM judge can score, and constructing graded policies would mean inventing the grades the probe exists to check. |
| `CONTAMINATION_EXACT`, `CONTAMINATION_NEARDUP`, `SHORTCUT_LEAK` | tau2 ships one split and no item parts. `train_items` / `eval_items` refuse. |
| `DIFFICULTY_SATURATED`, `DIFFICULTY_IMPOSSIBLE` | Need a solve-rate estimate, which needs a model. |
| `REWARD_HACKABLE` | Needs a completion signal independent of tau2's own scorer; `true_completion` refuses because tau2 does not expose one. |
| `EXCESSIVE_PERMISSIONS` | `Tau2Adapter` declares no `SandboxPosture`, and V8's rule is that an undeclared need is recorded as unchecked, never read as "not needed". |
| `EVALUATOR_RCE` | The adapter hands over no verifier source; tau2's evaluators are tau2's own Python and the scan would be a statement about a file nobody read. |

Two whole tau2 fix categories are excluded by consequence, and both deserve naming:

- **`database_accuracy` (5 positives, recall 0.200).** These are fixtures that disagree with the
  domain database — a wrong price, an item id that is not there. Assay's taxonomy has **no class
  for "the environment's reference data is wrong"**. It is a real defect and it is not in the
  16. Forcing it into `SPEC_VERIFIER_MISMATCH` because both involve a mismatch would be exactly
  the relabelling this file exists to refuse. Its 5 tasks still enter the label set through
  whichever of Rules 1 and 2 their diff satisfies — the *category* is not used as a label, the
  *diff* is — and the gap is recorded here and in `docs/COVERAGE.md`.
- **`nl_assertions` as a scored conjunct.** tau2 grades them with an LLM judge; Assay scores
  nothing with a judge. All 50 airline tasks and 8 retail tasks carry NL assertions that go
  unchecked. `Tau2Adapter.verify` already reports this as coverage rather than as a pass, and
  registering the environment does not change it.

## Baseline, measured before the change

There is a confound and it has to be split out or the result is unreadable.
`docs/changelog/97-dead-zone-probes.md` added `EXCESSIVE_PERMISSIONS` and `EVALUATOR_RCE`, taking
the taxonomy from 14 classes to **16**, and deliberately **did not regenerate any results file**:
"a headline that grows because the taxonomy grew is the thing this repository exists to catch, and
it is not being banked quietly." So `results/full_run.json` as committed is a 14-class artifact.
Regenerating it moves `flag_everything` by +52 *before τ² is added at all*.

Both steps are therefore predicted separately. Column 2 is arithmetic over the committed
`per_env`, not a new measurement.

| research-run | committed (14 classes) | 16 classes, no τ² | **predicted, +τ²** |
|---|---|---|---|
| corpus size | 26 | 26 | **28** |
| planted defects | 50 | 50 | **54** |
| `assay` | 40.0 | 40.0 | **43.0** |
| `flag_everything` | 314.0 | 366.0 | **394.0** |
| `check_env` | 3056.0 | 3056.0 | **3216.0** |
| `flag_nothing` | 3072.0 | 3072.0 | **3232.0** |
| `always_modal_defect` | 1888.0 | 1888.0 | **2050.0** |
| `stratified_random` | 1789.0 | 2667.0 | **2793.0** |
| margin over floor | 274.0 | 326.0 | **351.0** |
| `assay` normalised | 0.1274 | 0.1093 | **0.1091** |
| `assay` recall | 0.980 | 0.980 | **0.9815** |
| `assay` precision | 1.000 | 1.000 | **0.9464** |
| floor arm | flag_everything | flag_everything | **flag_everything** |

All four profiles, predicted with τ²:

| profile | assay | best trivial arm | margin |
|---|---|---|---|
| `research-run` | 43.0 | 394.0 (`flag_everything`) | +351.0 |
| `flat` | 4.0 | 54.0 (`flag_nothing`) | +50.0 |
| `production-training` | 246.0 | 788.0 (`flag_everything`) | +542.0 |
| `benchmark-publication` | 624.0 | 3152.0 (`flag_everything`) | +2528.0 |

Per environment:

- **`tau2/retail` → detected `{GOLD_FAILS, KNOWN_WRONG_PASSES, NOOP_PASSES,
  SPEC_VERIFIER_MISMATCH}`.** 2 caught, **2 spurious**, 0 missed. Predicted cost **2.0**.
- **`tau2/airline` → detected `{KNOWN_WRONG_PASSES, NOOP_PASSES, SPEC_VERIFIER_MISMATCH}`.**
  2 caught, **1 spurious**, 0 missed. Predicted cost **1.0**.

Both taken from the probe statuses already committed in `results/tau2_recall.json`. The two probe
families added in Slice 34 post-date that file and are predicted **NOT_APPLICABLE** on both domains
for the reasons in the exclusion table.

## The direction is the check, and here it points the wrong way

The previous pre-registration could say "every axis is predicted to get worse for Assay". This one
cannot, and that is the finding.

- **Expected loss gets worse**: 40.0 → 43.0, and `precision` **drops off 1.000 for the first time**
  — 3 spurious findings across 28 environments. The README's "zero false positives anywhere" stops
  being true and has to be rewritten.
- **The margin gets better, and it is arithmetic, not detection**: +25.0, because two environments
  carrying 2 planted classes each hand `flag_everything` `2 × (16 − 2) = 28` free false alarms
  while costing Assay 3. This is precisely the lever `README.md` names and `docs/PRE-REGISTRATION.md`
  was written to guard. **It is not being claimed as a result.** The margin is reported alongside
  the arithmetic that produces it, and the number to read is `external-envs`.
- **Normalised loss is flat to four decimals** (0.1093 → 0.1091, an improvement of 0.0002) because
  numerator and denominator move together. That is luck of the ratio, not a property of the
  detector.

The reason to do this anyway is the `external-envs` split, not the headline: **4 → 6 environments,
3 → 7 planted defects, and for the first time two of them labelled by an outside organisation
rather than hand-triaged here.** Predicted `external-envs` at `research-run`: `assay` 40.0 + 3.0 =
**43.0** against `flag_everything` 53.0 + 28.0 = **81.0**.

## What would falsify the method rather than the prediction

- **Either tau2 environment reporting a class the mapping excludes for a reason other than
  `GOLD_FAILS` or `NOOP_PASSES`** — the exclusion table would then be describing an environment
  that is not the one being audited.
- **Either tau2 environment *missing* `KNOWN_WRONG_PASSES` or `SPEC_VERIFIER_MISMATCH`.** The
  committed recall file says `known_wrong_fails` and `assert_traceability` both fire on both
  domains; if they do not, that file is stale and the recall measurement has to be re-run before
  anything here is believed.
- **`verifier_static_analysis` or `declared_permissions` returning anything but NOT_APPLICABLE** —
  the adapter would be exposing a surface its own refusals say it does not have.
- **`direct_prompt` falling below `stratified_random`.** Predicted `stratified_random` is 2793.0
  and `direct_prompt` was 2658.0 on a 26-environment corpus with 2 fewer misses; the two LLM arms
  are re-sampled from `qwen3:8b` and are the one part of this table that is not arithmetic, so
  they are **not point-predicted**. If the order flips, the README sentence saying the LLM baseline
  does not beat flagging at base rates must flip with it, and so must the assertion in
  `tests/test_published_claims.py`.
- **The corpus miss set changing.** Predicted to stay exactly
  `{"inspect_evals/boolq": ["SHORTCUT_LEAK"]}` — τ² adds spurious findings, not misses. The brief
  that commissioned this work expected that assertion to break; it is predicted **not** to.

Measured results go in `docs/changelog/100-tau2-corpus.md` next to these numbers, whichever way
they come out.

---

# Result — measured 2026-08-31

`ASSAY_APPROVE_ALL=... uv run --extra dev --extra adapters --extra sweep --extra openenv
--extra tau2 python scripts/full_run.py --llm-arms qwen3:8b`, then `scripts/intervals.py
--resamples 10000 --seed 11`, `scripts/corpus_splits.py`, `scripts/cost_sensitivity.py`.

## Every deterministic prediction held exactly. One arithmetic prediction was wrong. One falsification criterion fired.

| research-run | committed (14 classes) | predicted | **measured** |
|---|---|---|---|
| corpus size | 26 | 28 | **28** |
| planted defects | 50 | 54 | **54** |
| `assay` | 40.0 | 43.0 | **43.0** |
| `flag_everything` | 314.0 | 394.0 | **394.0** |
| `check_env` | 3056.0 | 3216.0 | **3216.0** |
| `flag_nothing` | 3072.0 | 3232.0 | **3232.0** |
| `always_modal_defect` | 1888.0 | 2050.0 | **2050.0** |
| `stratified_random` | 1789.0 | 2793.0 | **2793.0** |
| margin over floor | 274.0 | 351.0 | **351.0** |
| `assay` normalised | 0.1274 | 0.1091 | **0.1091** |
| `assay` recall | 0.980 | 0.9815 | **0.9815** |
| `assay` precision | 1.000 | 0.9464 | **0.9464** |
| floor arm | flag_everything | flag_everything | **flag_everything** |

All four profiles, predicted then measured — identical in every cell:

| profile | assay pred / meas | best trivial arm pred / meas |
|---|---|---|
| `research-run` | 43.0 / **43.0** | 394.0 / **394.0** (`flag_everything`) |
| `flat` | 4.0 / **4.0** | 54.0 / **54.0** (`flag_nothing`) |
| `production-training` | 246.0 / **246.0** | 788.0 / **788.0** (`flag_everything`) |
| `benchmark-publication` | 624.0 / **624.0** | 3152.0 / **3152.0** (`flag_everything`) |

Per environment, both exactly as written, including which classes are spurious:

- `tau2/retail` — detected `{GOLD_FAILS, KNOWN_WRONG_PASSES, NOOP_PASSES, SPEC_VERIFIER_MISMATCH}`;
  **2 caught, 2 spurious, 0 missed**, cost 2.0.
- `tau2/airline` — detected `{KNOWN_WRONG_PASSES, NOOP_PASSES, SPEC_VERIFIER_MISMATCH}`;
  **2 caught, 1 spurious, 0 missed**, cost 1.0.

`verifier_static_analysis` and `declared_permissions` both returned **NOT_APPLICABLE** on both
domains, for the predicted reasons (`environment does not expose: VERIFIER_SOURCE` /
`SANDBOX_POSTURE`). The corpus miss set is still exactly
`{"inspect_evals/boolq": ["SHORTCUT_LEAK"]}` — the brief that commissioned this work expected that
assertion in `tests/test_published_claims.py` to break, and it was predicted here not to, and it
did not.

### The prediction that was wrong

**`external-envs` `flag_everything`: predicted 81.0, measured 89.0.** The split is right — 4 → **6**
environments, 3 → **7** planted defects, `assay` **43.0** as predicted — but the floor figure was
computed by adding τ²'s 28 to the *committed* 53.0, which is a 14-class number. At 16 classes the
four pre-existing external environments are worth `4 × 16 − 3 = 61`, not 53, so the correct
arithmetic is `61 + 28 = 89`. A pre-registration whose whole subject is a 14→16 confound made the
14→16 mistake in one of its own rows. Left in place above rather than corrected in situ, because
editing a prediction after the measurement is the thing pre-registration exists to prevent.

### The falsification criterion that fired

> **`direct_prompt` falling below `stratified_random`.** … If the order flips, the README sentence
> saying the LLM baseline does not beat flagging at base rates must flip with it, and so must the
> assertion in `tests/test_published_claims.py`.

It flipped, and for both LLM arms: `direct_prompt` **2454.0** and `agent_with_tools` **2736.0**
against `stratified_random` **2793.0**. It was 2658.0 / 2654.0 against 1789.0.

**It is mostly not the LLM arms moving.** Decomposed:

| | 26 envs, 14 classes | 26 envs, 16 classes | 28 envs, 16 classes |
|---|---|---|---|
| `stratified_random`, seeded draw | 1789.0 | 2667.0 | **2793.0** |
| `stratified_random`, closed-form `E[loss]` | — | 2298.3 | **2474.3** |
| `direct_prompt` | 2658.0 | *(re-sampled)* | **2454.0** |

`stratified_random` flags each class independently at its corpus base rate and draws one
`rng.random()` per class per environment in enum order, so adding two classes to the taxonomy
reshuffles the entire seeded sequence: **+878 with no change to the corpus, the policy or the
detector.** `docs/changelog/97-dead-zone-probes.md` recorded that at the time and did not regenerate
any results file; this is the first run that banks it.

So the honest statement is neither the old one nor its negation. Against the *policy's actual mean*
rather than one draw of it, `direct_prompt` at 2454.0 and `stratified_random` at 2474.3 are a tie,
and the paired bootstrap agrees: **339.0, 95% CI [−244, 942] — not separated**
(`results/intervals.json`). The old claim was "the LLM arms lose to flagging at base rates,
separated, 869.0 [201, 1627]". The new one is that they are indistinguishable from it. Both the
README sentence and the test assertion are rewritten to say that.

## What the reviewer found that the pre-registration got wrong

The mapping was sent to a fresh context with the spec and the artifacts and no access to this
document's reasoning. Four findings survived checking, and all four are recorded rather than
quietly fixed.

**1. The `SPEC_VERIFIER_MISMATCH` tick is earned by a probe that is below chance on retail, and
every worked example above is a task Assay misses.** `assert_traceability` alone on retail is
precision **0.2143** against a base rate of 35/114 = **0.3070**. `retail/{0,1,2}` and
`airline/{12,15}` — the five fixes this document uses to argue the rule — are *all* in
`results/tau2_recall.json`'s missed lists, while all three of the answer-key examples
(`retail/{12,18}`, `airline/2`) are detected. The environment-level union erases that split: 5 of 27
retail brief-only tasks detected reads as one green tick. **The label is sound; the `caught` is
doing work the evidence does not support**, and the per-task figure (0.185 / 0.200) is the one that
is true.

**2. The exclusion table's price was stated one-sided.** The document said `GOLD_FAILS` is
"excluded, and it costs us" — 3.0 points. It did not state the other side. Summing
`DEFAULT_SEVERITY` over the fourteen excluded classes gives **752 per environment**; had all
fourteen been claimed on both, Assay would have missed all but the three it reports, for
**1384 points** under `research-run`, and the margin would be **−1384 rather than +25**. So the
fourteen paragraphs are worth roughly **460× more to Assay in avoided misses than the 3.0 they
cost**. That is the number a reader should be given first.

**3. …and the reason it is nevertheless not the adversarial optimum is arithmetic, not sentiment.**
For one environment, moving a class the detector *already reports* from excluded to planted lowers
`flag_everything`'s loss by exactly one `false_alarm` and Assay's spurious count by exactly one.
**The margin is invariant.** Checked: labelling both domains with everything Assay reports gives
`(16−4) + (16−3) = 25` for the floor and 0.0 for Assay — margin **25**, identical to the registered
mapping's `28 − 3 = 25`. Moving in a class the detector does *not* report costs the margin
`false_alarm + miss`. So inclusion buys nothing and exclusion is the only lever — which is exactly
why the fourteen reasons carry the weight, and why two of them were rewritten below.

**4. Two exclusion reasons used the wrong standard of evidence.** Fixed in
`tau2_truth.EXCLUDED_DEFECT_CLASSES`, in this commit's parent:

- `NOOP_PASSES` said "8 of its 9 findings land on tasks the third party left alone", which is
  evidence of absence — the same move the `NONDETERMINISM` row two lines below explicitly refuses.
  The real reason was found by checking: `Tau2Adapter.verify` scores two of tau2's three conjuncts
  and drops the LLM-judged `nl_assertions`, so on the **9** tasks whose gold action list is empty
  after `_gold()` — `retail/{24,57}`, `airline/{0,10,26,28,31,34,46}`, verified against the
  snapshots — an empty transcript scores 1.0 by construction. Those nine are exactly `noop_fails`'
  nine findings. The probe is measuring our missing conjunct, not tau2's environment.
- `GOLD_FAILS` argued only from `retail/{64,105}` being untouched, and said nothing about
  `retail/{18,91}`, which are positives whose pre-fix gold *also* fails. Both readings are true
  there. The reason now says so, and says the thing that actually exculpates the exclusion:
  **claiming `GOLD_FAILS` would turn a spurious into a caught and save Assay a point.**

The same check turned up a **live defect in `Tau2Adapter.known_wrong_actions`**, whose docstring
claimed "a clean task cannot produce a finding here by accident". It can: on those same 9 no-gold
tasks the probe is handed `[]`, scores an empty transcript, and reports `KNOWN_WRONG_PASSES` on a
task with no policy violation — **2 of retail's 6 and 6 of airline's 13 `known_wrong_fails`
findings, and the whole of that probe's false-positive column on both domains.** The docstring now
states this instead of denying it. It is **not** fixed here: the fix is a probe-contract change and
doing it inside a corpus-label change would move a published recall measurement for an unrelated
reason. The environment-level `KNOWN_WRONG_PASSES` tick survives it — 4 genuine retail and 6 genuine
airline findings remain — but `results/tau2_recall.json`'s `by_probe` and `each_probe_alone` tables
are partly this artifact and should be read knowing it.

## The direction, restated against the measurement

- **Expected loss got worse and precision left 1.000**: 40.0 → 43.0, precision 1.000 → **0.9464**,
  three spurious findings across 28 environments. The README's "zero false positives anywhere" is
  gone.
- **And the precision drop is not comparable to the number it replaces.** These are the only two
  environments in the corpus with an **open-world** label. Everywhere else `frozenset()` means "we
  planted nothing else"; here it means "the revision diff establishes nothing else", and the fork's
  own paper says more τ² tasks are under-specified than it changed. `Outcome.spurious` cannot
  represent that, so part of the 0.9464 is the label being a lower bound rather than Assay being
  wrong. Stated in both directions because either alone is misleading.
- **The margin got better, and it is arithmetic**: +25.0 on two environments, because each one hands
  `flag_everything` `16 − 2 = 14` free false alarms. Reported next to the arithmetic that produces
  it and not claimed as detection.
- **What was actually bought**: `external-envs` 4 → **6** environments and 3 → **7** planted
  defects, and the first two entries in the registry carrying `LabelSource.EXTERNALLY_DERIVED` — a
  label an outside organisation published at a commit, rather than one a person here worked out by
  driving upstream's scorer.

## Considered and not done

**Registering four environments instead of two** — `tau2/retail:answer-key` (8 tasks),
`tau2/retail:brief-only` (27), and the airline pair — each with a single-class label. The adapter
already takes `task_ids` and `task_defect_classes` already returns per-task labels, so it is cheap,
and it would fix finding 1: `SPEC_VERIFIER_MISMATCH` could only be `caught` if the probe fired
*inside* the brief-only tasks. Declined for now because it hands `flag_everything` `4 × 15 = 60`
of free floor instead of 28, which is the corpus-inflation lever this document exists to guard, and
doing it in the same change that introduces the mapping would make the two effects impossible to
separate. It is the right next step and it needs its own pre-registration.
