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

`EnvAuthor.EXTERNAL` + `LabelSource.EXTERNALLY_DERIVED` — the strongest pair the vocabulary has,
and the first use of `EXTERNALLY_DERIVED` in the registry. `inspect_evals/{paws,boolq}` are
`EXTERNAL` + `HAND_TRIAGED`: external environments whose labels a person here established by
driving upstream's scorer. These are external environments whose labels a *different organisation*
published, in a repository, at a commit.

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
