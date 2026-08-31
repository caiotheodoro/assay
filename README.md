# Assay

**An agentic auditor for RL environments and eval suites.**

Point Assay at an environment. It runs a battery of probes and emits an **Environment Card**: a
validity verdict where every claim is tied to a probe result, plus machine-readable JSON and a
nonzero exit code that blocks a training run. The card carries a content digest, and an HMAC
signature when `ASSAY_CARD_KEY` is set — a digest identifies a card and catches corruption, but
it is not tamper-evidence, because anyone editing the body can recompute it. **Assay does not
claim to find more defects than the field. It claims to price them:** a finding is not a result
until you know what missing it costs against what a false alarm costs.

| Arm | Expected loss (`research-run`) | 95% CI |
|---|---|---|
| `flag_nothing` | 3072.0 | [1984, 4288] |
| `check_env` — the incumbent linter | 3056.0 | [1960, 4272] |
| `flag_everything` — **the floor that had to be beaten** | 366.0 | [347, 383] |
| **Assay** | **40.0** | **[0, 120]** |

Assay saves **326.0 against `flag_everything`, 95% CI [238, 378] — separated.**
**Fifty-two of that 326.0 is arithmetic, not detection.** `flag_everything` flags every
class in the taxonomy on every environment, so its loss is
`Σ_env (n_classes − |planted_env|) × false_alarm`. Two classes were added when the V3 and
V8 probes landed, and both have base rate **zero** on this corpus — no environment can
carry them — so the floor rose by `2 × 26 × 1 = 52` while Assay's 40.0 did not move. The
comparable figure against the taxonomy this was originally measured on is **274.0**. A
margin that grows because the taxonomy grew is the thing this repository exists to catch,
and it is not being banked quietly ([`docs/changelog/97-dead-zone-probes.md`](docs/changelog/97-dead-zone-probes.md),
and `test_the_trivial_floor_matches_the_taxonomy_it_was_measured_against` now recomputes
the floor so it cannot drift again). Wins 4 of 4 cost
profiles, separates on 3. 26 environments, 50 planted defects, 10,000 bootstrap resamples over
environments, seed 11. **Read the arms in the right order:** beating `check_env` proves almost
nothing (16.0 saved of `flag_nothing`'s 3072.0, on an interval including zero). The arm that had to
be beaten is `flag_everything` — it catches every defect by construction, and for most of this
project's life Assay did not beat it.

```bash
uv sync --extra dev && uv run pytest -q                              # the demo: every planted defect, caught
uv run --extra adapters --extra openenv python scripts/full_run.py   # the headline, 22s
```

### Start here

| | |
|---|---|
| **Orientation, 100 lines** | [`AGENTS.md`](AGENTS.md) |
| **Every claim, with the file that backs it** | [`docs/FOR_AGENTS.md`](docs/FOR_AGENTS.md) |
| **Every number, with its caveats** | [`docs/RESULTS.md`](docs/RESULTS.md) |
| **Everything this repo published and took back** | [`docs/RETRACTIONS.md`](docs/RETRACTIONS.md) |
| **This repo's own claims, attacked** | [`docs/RED-TEAM.md`](docs/RED-TEAM.md) |
| The method, written to be reused | [`docs/METHOD.md`](docs/METHOD.md) |
| What the tool cannot see, in someone else's vocabulary | [`docs/COVERAGE.md`](docs/COVERAGE.md) |
| Reproduce every number end to end | [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) |
| An agent run and a sample card, read without executing anything | [`results/trajectories/INDEX.md`](results/trajectories/INDEX.md), [`results/example-card.md`](results/example-card.md) |
| Architecture, changelog, self-score | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/CHANGELOG.md`](docs/CHANGELOG.md), [`docs/RUBRIC.md`](docs/RUBRIC.md) |
| **Try it, no install** | [**Hosted demo**](https://huggingface.co/spaces/caiotheodoro/assay-demo) — the probe battery, running in your browser |
| **Published artifacts, all of them** | [**Collection**](https://huggingface.co/collections/caiotheodoro/assay-auditing-rl-environments-with-error-bars-6a946953e05a8669da74ee65) — [code](https://github.com/caiotheodoro/assay), [corpus, cards and arms](https://huggingface.co/datasets/caiotheodoro/assay-corpus), [the GRPO Challenger, **a negative result**](https://huggingface.co/caiotheodoro/assay-challenger-grpo), [the solution video, 4:36](https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4) |

> **An auditor is an eval.** If benchmarks ship unchecked because nobody QAs them, nothing makes
> the QA tool different. So every instrument this tool applies to an environment was turned on the
> tool: **twelve of this repository's published claims broke**, and the self-audit found three real
> behavioural bugs. Every retraction is kept verbatim in
> [`docs/RETRACTIONS.md`](docs/RETRACTIONS.md); the unedited breakage is
> [`docs/RED-TEAM.md`](docs/RED-TEAM.md).

**[Audit an environment in your browser →](https://huggingface.co/spaces/caiotheodoro/assay-demo)**
No signup, no server, nothing uploaded. Paste a spec or load one of seven planted fixtures, press
Audit, and the probe battery runs *in the tab* — CPython under WebAssembly, against the same
vendored package the CLI uses. It boots in about three seconds and audits in milliseconds, and all
seven example cards are rendered into the page ahead of time so it is readable before the runtime
loads and if it never does.

That works because Assay's audit path is pure standard library, which is what the earlier reasoning
here missed: Hugging Face does return HTTP 402 for a Gradio Space on free `cpu-basic`, and a static
Space genuinely cannot serve a *server-side* probe battery — it just does not have to.
`space/app.py`, the Gradio version, still runs locally with `python space/app.py`. The one thing the
browser build refuses is `verifier: "regex"`, because `safe_regex` bounds a submitted pattern in a
subprocess and WebAssembly has none.

### Who this is for

- **The researcher about to spend a training run** on an environment they did not write. They cannot
  read every verifier, and the failure is silent: a policy that learns the verifier instead of the
  task, found from the reward curve weeks later, or never. They run `assay audit`, read the exit code.
- **The maintainer of an eval suite**, who owns tasks other people score against with no cheap way
  to know whether a verifier still means what the task says. They run the battery in CI and diff
  which environments changed status — [`docs/COVERAGE.md`](docs/COVERAGE.md) is written for them, in
  BenchJack's V1–V8 vocabulary rather than ours.
- **The reviewer deciding whether to trust a number.** They get the card: every claim tied to a
  probe, and every probe that could not run named with its reason.

The four cost profiles in `src/assay/costs/profiles/` are that decision made explicit: `research-run`
prices a missed defect at wasted compute, `benchmark-publication` at a retracted paper. **The tool is
not for someone who wants a score.** `flag_everything` gives a score and beats a badly-calibrated
auditor; the cost beliefs where it wins are in
[`results/cost_sensitivity.json`](results/cost_sensitivity.json).

## The problem

Labs and vendors buy RL environments and eval suites as products. Nobody QAs them. When a flagship
benchmark turns out to be broken, the fix is a human doing it by hand:

| Benchmark | What was wrong | How it was found |
|---|---|---|
| SWE-bench | ~2/3 of instances unusable | 93 developers, hand-triaged → SWE-bench Verified |
| SWE-bench | **7.8% of "passing" patches are wrong-but-pass** | manual audit (ICSE 2026) |
| SWE-bench | ~1/3 of instances leak the fix in the issue text | manual audit (SWE-bench+) |
| WebArena | substring-match evaluator produced false negatives | manual audit → WebArena Verified |
| tau2-bench | wrong gold actions, premature termination | 75+ ad hoc fixes across labs, unpublished |

The only automated tooling that exists is `gymnasium.utils.env_checker` and
`stable_baselines3.common.env_checker`. They assert space shapes, that `reset()` returns
`(obs, info)`, that reward is not NaN — and, in gymnasium 1.3.0, that the same seed and action give
the same observation. That last check is real: `scripts/real_check_env.py` runs the tools rather
than a model of them, and stable-baselines3 2.9.0 passes the same environment silently, so the
incumbents differ and the baseline here models the stronger one. On five API-correct environments
carrying four planted defects they catch **one** — determinism — and say nothing about a verifier
that pays full reward at reset, a constant action that beats every other, or a score that comes
apart from the task. Linters for *"will this crash my trainer"*, with one check that is not.

## Two real defects, in software shipping today

Both are now filed upstream — [inspect_evals#2331](https://github.com/UKGovernmentBEIS/inspect_evals/issues/2331) and [OpenEnv#1102](https://github.com/huggingface/OpenEnv/issues/1102) — after a second reader went through both drafts and changed three things in them ([`docs/changelog/106-disclosures-filed.md`](docs/changelog/106-disclosures-filed.md)). No maintainer has replied yet.

The corpus measures Assay against defects this repo planted. These two were not, and both were
verified from the upstream project's own code with Assay out of the loop. Write-ups and drafted
disclosures: [`docs/disclosures/`](docs/disclosures/README.md).

**`inspect_evals` 0.18.0 — `paws` scores a constant string at 100%.** It asks for `Yes` or `No` and
scores with `includes()`, a case-insensitive **substring** test, so `"yesno"` contains both labels
and scores **8000/8000 = 100%**. The looseness is one-sided, which is worse than symmetric: 4464 of
8000 items have the target `No`, so every hedging answer is credited on 56% of the benchmark for
free — the WebArena substring-match failure from the table above, live in a package people train
and publish against.

**`openenv` — `textarena_env` accepts a seed and ignores it.** Six calls to `reset(seed=1234)`
return six different secret Wordle words: `earth, north, south, bread, tight, stage`. The signature
takes `seed`, then calls `self._ta_env.reset(num_players=...)` without it. gymnasium 1.3.0 raises on
exactly this shape; OpenEnv has no equivalent check.

**Assay found one of the two; a human found the other.** It flagged 14 of 25 sampled `paws` items as
`REWARD_HACKABLE` but not the `"yesno"` case — hand triage did — and that split is pinned as a test
so it cannot quietly close in the write-up. `textarena_env` went the other way: the probes found it,
but only after two bugs in Assay's own determinism probe were fixed.

## Measured result

Every arm, profile and caveat is in [`docs/RESULTS.md`](docs/RESULTS.md). Three things there change
how the headline table above should be read.

**1. The two LLM arms are the brief's own simple baseline, and both lose to Assay by more than
2000.** `direct_prompt` reads everything a careful human reviewer could read without executing
anything; `agent_with_tools` gets the same plus a tool loop it can drive. They score **2293.0 and
2656.0** against `stratified_random`'s 2667.0.

**This paragraph used to say they lose to flagging at base rates, and that is no longer true.**
Two things moved it, and neither is the models getting better. Adding two defect classes
(`docs/changelog/97-dead-zone-probes.md`) shifted `stratified_random`'s seeded draw sequence — it
draws one `rng.random()` per class per environment in enum order — so it went 1789.0 → 2667.0 while
flagging the new classes **zero** times. And the LLM arms are non-deterministic and were re-run.
`direct_prompt` now sits 374.0 *better* than stratified random, 95% CI **[-189, 968] — not
separated**, so the honest statement is that neither ordering is established, rather than that the
ordering reversed.

What did separate is the comparison between the two LLM arms, in the direction nobody wants:
`direct_prompt` beats `agent_with_tools` by **363.0, 95% CI [41, 730] — separated.** Giving the
model a tool loop did not buy nothing; on this corpus it measurably **cost** something. Reading an
environment is not auditing it, and neither is poking at it.

**2. Two figures in that table are weaker than they look.** The incumbent's 4.0% recall is a property
of a *model* — `src/assay/baselines/structural.py` reimplements the two checkers, because the real
ones cannot be pointed at a `ToyEnv`, an `inspect_ai` task or a Harbor container at all, and
`NONDETERMINISM` is the only class it can return; run for real on five purpose-built shims they
detect 1 of 4 ([`results/real_check_env.json`](results/real_check_env.json)). And Assay's precision
of 1.000 is the modal run: across six full-corpus runs `harbor/broken-gold` reported a spurious
`NONDETERMINISM` **once**, so it ships as a rate, not a diagnosis.

**3. The corpus is 4 of 26 genuinely third-party, and that is the ceiling on all of it.**
`flag_everything`'s loss is exactly `Σ (14 − |planted|)`, so **every clean environment added moves
the floor by +14 and Assay by 0** — roughly eight would flip the headline with no change to the
detector. Hence provenance declared in the registry before the corpus grows, and the two
`inspect_evals` environments added under a pre-registration committed first
([`docs/PRE-REGISTRATION.md`](docs/PRE-REGISTRATION.md)) whose every prediction held.

| split | n | assay | flag_everything | who wins |
|---|---|---|---|---|
| all (published) | 26 | 40.0 | 366.0 | assay, by 274 |
| our content, third-party format | 10 | 0.0 | 112.0 | assay |
| genuinely external | 4 | 40.0 | 53.0 | assay — but n=4, and the one miss is here |
| in-process fixtures | 12 | 0.0 | 149.0 | assay — asserted, not measured |
| self-authored | 22 | 0.0 | 261.0 | assay |

`uv run --extra adapters python scripts/corpus_splits.py`, full table in
[`results/corpus_splits.json`](results/corpus_splits.json). **n=4 is the real size of the
third-party control**: too small and too self-authored to support the pooled headline, and growing
it with environments nobody here wrote is the first thing worth doing next — carefully.

### What holds, what does not, and what it all rests on

Two overlapping one-sample intervals do not settle "A beats B", so every claim is a paired
difference on a shared resample. Running only the flattering cost model would be its own kind of
dishonesty, so every profile shipped is published, not the one that reads best:

| profile | missed CRITICAL : false alarm | assay | flag_everything | saved | |
|---|---|---|---|---|---|
| `flat` | 1 : 1 | **1.0** | 366.0 | 313.0 | separated, [294, 330] |
| `research-run` | 120 : 1 | **40.0** | 366.0 | 326.0 | separated, [238, 378] |
| `production-training` | 960 : 2 | **240.0** | 628.0 | 388.0 | **not separated**, [−108, 652] |
| `benchmark-publication` | 2000 : 8 | **600.0** | 2512.0 | 1912.0 | separated, [648, 2608] |

**Assay now wins all four and separates on three.** It previously won one and lost two outright. At
`production-training`'s 480:1 ratio, "flag everything and read the cards" is a genuinely good policy
— which is why beating it took closing the misses rather than tuning the metric, and why it still
does not *separate*: winning by 388.0 on an interval crossing zero is a lead, not a result. Against
the other floors the margins are wide and separated (3032.0 over `flag_nothing`, 1749.0 over
`stratified_random`); the six-row table and the interval caveats — including the one whose shape
decides its own answer, and the ten-rung bootstrap lattice a corpus this size actually supports —
are in [`docs/RESULTS.md`](docs/RESULTS.md). **One miss remains across 26 environments and it is
external:** `inspect_evals/boolq`, structurally — no train split, so the shortcut probe reports
`NOT_APPLICABLE` before it runs.

**And the whole ranking rests on one made-up number.** `research-run.yaml` prices a missed CRITICAL
defect at **120** engineer-hours-equivalent; nothing derives that 120, and every figure above scales
linearly with it. So sweep it ([`results/cost_sensitivity.json`](results/cost_sensitivity.json)):

| CRITICAL miss cost | 120 *(shipped)* | 800 | **1098** | 2000 |
|---|---|---|---|---|
| assay | 40.0 | 266.7 | **366.0** | 666.7 |
| flag_everything | 366.0 | 366.0 | **366.0** | 366.0 |
| winner | assay | assay | **tie** | flag_everything |

The crossover is exact, not bisected: Assay's loss is linear in `C` while `flag_everything` never
misses and does not move with `C` at all, so they cross at `120 × 366 / 40 = 1098`. **The shipped
value is 120. The crossover is 1098.** The headline survives a **815% error** in a constant nobody
derives — a margin that was 21% before the two Harbor misses were closed, stated plainly because the
earlier number was the sharpest criticism of this work and the one that changed most. A claim about
a specific cost regime, not about detectors in general.

## Does an agent find what a script cannot?

**Yes, in two places, and the honest history is that the first one did not survive contact
with a better script.** The two that hold are below; the one that did not is kept because it
is the reason the other two were built where they were.

Ten of the eleven probe families are deterministic programs, and the history is the argument for
that design. The `claude-cli` Challenger found a reward-hack exploit class at turn 8 in 262s that a
scripted attacker and `qwen3:8b` both missed:

```sh
echo -n 'banana' > expected.txt; echo -n 'banana' > out.txt
```

It does not forge an answer — it **overwrites the expected answer** so the verifier's comparison is
trivially true. Scored 1.0 by the environment, 0.0 by the independent verifier the agent never had
access to; that difference is the whole measurement. Then the cheapest possible response — writing
the mechanism down as a fixed policy, named after BenchJack's V7 *trusting untrusted output* —
captured it permanently at zero marginal cost, and the scripted Challenger now finds the same gap in
**~2s instead of 262s** with no model in the loop. Good for the tool, bad for the argument that the
agent is load-bearing: an auditor that needs a model in the loop to be reliable is an auditor whose
verdicts cannot be reproduced ([`docs/FOR_AGENTS.md`](docs/FOR_AGENTS.md) has that argument in full,
and what it costs in rubric points).

**How often, though.** One run is not a capability. The composite arm Assay ships was pointed at the
same environment four independent times and found the exploit in **3 of 4**
([`results/challenger_reliability.json`](results/challenger_reliability.json)) — so the number
reported is a rate, and a real audit should run the Challenger more than once. The ablation table,
the reliability run and the GRPO Challenger that **did not beat the scripted floor** are in
[`docs/RESULTS.md`](docs/RESULTS.md); the post-mortem, including the 20% holdout contamination that
makes it weaker than it reads, is
[`docs/changelog/40-grpo-challenger.md`](docs/changelog/40-grpo-challenger.md).
[`results/trajectories/INDEX.md`](results/trajectories/INDEX.md) has one representative run per
agent, readable end to end — failed turns kept, three of the eight Challenger misses, one the
sandbox approval gate **refusing**.

### The exploit a human found, found by an agent

`README.md` records the one place this tool lost to a person: it flagged 14 of 25 sampled
`paws` items and **did not** find the `"yesno"` case — hand triage did — because the scripted
Challenger can only replay policies the adapter *declared*, and none of them names both labels
at once. That split is pinned as a test so it cannot quietly close.

Given the job a fixed repertoire structurally cannot have — **proposing** a policy rather than
replaying one — the Challenger closes it. On the same pinned subsample
([`results/policy_synthesis.json`](results/policy_synthesis.json)):

| arm | detected | beyond the floor |
|---|---|---|
| scripted floor | 14 / 25 | — |
| `claude-cli:sonnet`, sees the verifier | **24 / 25** | **+11** |
| `claude-cli:sonnet`, blind to the verifier | 22 / 25 | +8 |
| `ollama:qwen3:8b` | 0 / 25 | −14 |

The policies it proposed are the point, not the count: `'Yes No'`, `'Yes/No'` and their newline
variants — the both-labels-at-once class, reached from the task text. One run per arm, so
distrust the exact 24 and not the direction; `qwen3:8b` reaching 0 makes this a capability
threshold rather than a property of the design. **Nothing here is scored by a model:**
`self_report` records what the challenger claimed and is used for nothing, and it disagreed with
the deterministic scorer zero times out of 24. The uncomfortable half is that blind scores 22
against 24 — most of the win is reading the task, not defeating the scorer
([`docs/changelog/100-policy-synthesis.md`](docs/changelog/100-policy-synthesis.md)).

### The other agent, and the one judgement no script can make

The Challenger story ends with a script winning. **This one cannot**, and it is the better answer to
the section's question. `docs/COVERAGE.md` records a CRITICAL false positive the battery cannot
avoid: `inspect_evals/personality_BFI` comes back INVALID with 25 × `INVERT_PASSES` — mechanically
correct and semantically wrong, because a personality inventory *has no correct answer* and a format
check is the right design. No probe can see that; it is a question about meaning, not mechanism.

`assay audit --auditor` runs a semantic gate that withholds exactly that verdict. On the 13
environments in [`results/semantic_gate.json`](results/semantic_gate.json) — the 12 that do have a
correct answer, plus the one that does not:

| backend | withheld the false positive | false overrides | wall clock |
|---|---|---|---|
| `claude-cli:sonnet` | **1 of 1** | **0 of 12** | 136.6s |
| `ollama:qwen3:8b` | 0 of 1 | 0 of 12 | 58.5s |

**The interesting half is that the small model could make the observation and could not make the
decision.** The gate is the conjunction of the model's label and its own quoted evidence, because
each alone fails: `qwen3:8b` labels `personality_BFI` as *having* a correct answer in 3 of 3 runs,
immediately after writing a valid contradicting pair into the evidence field; and reading the
verdict off the evidence alone turns **10 of the 12** healthy fixtures into `no_correct_answer`. So
the script owns mechanism and the model owns meaning — this repo's argument, one level down.

It is **off by default and changes none of the numbers above**: the override can only move a
`verifier_integrity` DEFECT to `NOT_APPLICABLE`, never to PASS, never into another family, and each
one prints the model, the text it quoted and the verdict it replaced. Two designs were measured and
rejected first ([`docs/changelog/99-semantic-gate.md`](docs/changelog/99-semantic-gate.md)), and a
second Auditor job — synthesizing a train split for a probe that declined — **works and still does
not rescue `inspect_evals/boolq`**, correcting the pre-registered reason for that miss rather than
the result ([`docs/changelog/102-na-resolution.md`](docs/changelog/102-na-resolution.md)).

## Where Assay sits in the field

Everything above is measured against defects **this repo planted** — a closed loop. Two measurements
break it, scored where possible by other people's code, both in full (with the prior-art comparison)
in [`docs/RESULTS.md`](docs/RESULTS.md).

**τ²-bench — 62 defects an independent team labelled**, built from the diff between two pinned
revisions rather than from the prose. This repo's own trivial-floor rule applies first: the floor is
a flagger picking the same number of tasks at random.

| | recall | precision | vs. flagging at random | one-sided p |
|---|---|---|---|---|
| excluding `assert_traceability` | 0.210 (13/62) | 0.565 | 13 hits vs. 8.70 expected | **0.040** |
| all 12 probes | 0.339 (21/62) | 0.389 | 21 hits vs. 20.41 expected | **0.486** |

**The 0.339 row is chance.** Its precision beats the base rate — the precision of *any* random
flagger — by 0.011. Only the narrower row clears the floor, so the advisory probe is not a bonus with
a caveat: including it **destroys the measurement**. Read the p-values, not the recall
([`results/tau2_recall.json`](results/tau2_recall.json); the test is exact). The split is the result:
**13/20 = 0.65** on ground-truth annotation errors against **8/42 = 0.19** on instruction
under-specification — Assay reads verifiers, and two thirds of what τ-bench needed fixed was not one.

**ScienceAgentBench — 0 of 12, by BenchGuard's own scorer** (`eval/metrics.py` over verdicts from
their `eval/match.py`; nothing here recomputes it). The honest reading is not that Assay finds
instruction defects hard — it is that **Assay could not run at all here, and said so twelve times**:
all 12 probes returned `NOT_APPLICABLE` with a reason, verdict `UNVERIFIED`, because SAB is a static
task-definition set and these probes need an executable environment. The two tools are not
competitors, and the zero says so more plainly than any argument. One thing fell out of running their
scorer: **nine of the twelve defects are already fixed** in the split SAB tells you to use, so any
tool's SAB recall number is uninterpretable without naming the split
([`docs/SCIENCEAGENTBENCH.md`](docs/SCIENCEAGENTBENCH.md)). So the blind spot is measured twice, on
two independently labelled sets: **Assay does not detect instruction defects, because "this
instruction is ambiguous" is a judgement and nothing here scores with a judge.** Published as a
limitation before it was measured; now a number.

## The probes

| Family | Question | A "no" means |
|---|---|---|
| Verifier integrity | Does gold pass? Does no-op fail? Does an **inverted** spec fail? Does a known-wrong policy fail? | the eval cannot fail, or rubber-stamps |
| Trivial floor | Can a policy that ignores the input win? | it is not measuring capability |
| Separability | Can it tell apart policies known to differ? | it is saturated or dead |
| Contamination | Does the train split leak into the eval split? | held-out is not held out |
| Shortcut leakage | Is the answer recoverable from a part of the input? | it measures the artifact, not the task |
| Spec ↔ verifier | Does the verifier check what the instruction asked? | agents fail for following instructions |
| Determinism | Same seed, same result? | every comparison is partly noise |
| Difficulty band | Is the solve rate in a learnable range? | it contributes noise, not learning |
| Reward hackability | Can a policy score well without doing the job? | training on it teaches the exploit |
| Sandbox permissions | Does the deployment grant more than the task needs? | an exploit needs no cleverness, only the manifest |
| Evaluator code execution | Can the verifier be made to run what it is grading? | the agent writes a sentence instead of a solution |

Families 1–8 are deterministic programs. Family 9 is the adversarial **Challenger** — scripted,
prompted, or GRPO-trained. **No model ever scores a probe:** the Challenger only proposes actions,
every one is scored by a program, and the ground truth is held by the probe and never shown to the
attacker. A model can *withhold* a verdict — that is the `--auditor` gate above, off by default,
and it can only turn a DEFECT into `NOT_APPLICABLE`. It can never assert one.

Note the scope on the rest. This is a claim about what Assay *asserts*, not about what exists in
the room: two things it touches do use a judge — τ²-bench's `nl_assertions` (which is why they are
excluded from the τ² measurement) and BenchGuard's `match.py`. Stated as an absolute, "no LLM judge
scores anything, anywhere" was false — [`docs/RETRACTIONS.md`](docs/RETRACTIONS.md) §19.

## Prior art

The category is not new and Assay does not claim it is. Static auditors read a benchmark's files —
**BenchGuard** ([arXiv 2604.24955](https://arxiv.org/abs/2604.24955)), **ABA**
([arXiv 2605.26079](https://arxiv.org/abs/2605.26079)). Dynamic auditors execute it — **BenchJack**
([arXiv 2605.12673](https://arxiv.org/abs/2605.12673)), 219 flaws across 10 agent benchmarks, and
[arXiv 2606.16062](https://arxiv.org/abs/2606.16062), whose gold-sanity gate on SWE-bench Verified
found **28.5% of 49 tasks hackable**. Partial-input baselines, reward-model overoptimization and
separability-as-a-metric are ported, not invented. What Assay adds is the **bundle** — nine families
in one report under one expected-loss metric — plus **pricing rather than counting** defects, and
**absence of evidence reported as loudly as evidence**. Papers, numbers, the head-to-head against
BenchGuard's own scorer and the full novelty claim: [`docs/RESULTS.md`](docs/RESULTS.md); what
predates this repo: [`docs/LINEAGE.md`](docs/LINEAGE.md), cited as lineage and not vendored. An
earlier version of this section mis-cited someone else's paper —
[`docs/RETRACTIONS.md`](docs/RETRACTIONS.md) §16.

## Main failure mode

**A Challenger that could not speak, reported as a Challenger that found nothing.** An agent has more
ways to produce no output than a program does: the model refuses, every reply is unparseable, the
budget runs out mid-plan, the CLI is rate-limited. All of those arrive at the probe as an empty
attempt list, indistinguishable from a genuine "I attacked this environment and it held" — which
means **a card can read `VALID` because the auditor was silent**. That is the single worst thing this
tool can do, because it is the failure the tool exists to catch, happening inside the tool.

Two routes are closed: `ChallengerExhausted(reason, history)` is raised instead of an empty list and
caught in `src/assay/probes/hackability.py`, so the card says `NOT_APPLICABLE` with the reason rather
than staying quiet; and `hackability.py` reads `challenger_passes` from context, so an audit can run
the Challenger more than once. This section described both as open after they had closed —
[`docs/RETRACTIONS.md`](docs/RETRACTIONS.md) §17. What stays open is the shape of the problem: a
silent auditor is indistinguishable from a clean environment unless every route to silence is made to
say so, and only the routes someone has thought of are covered.

## Hot take

**Nobody QAs the benchmark — including the people building the tool that QAs benchmarks.**

The thesis is that the RL environments and eval suites labs buy ship unchecked, and it is right:
`paws` scores the constant string `"yesno"` at 100% on the current release of `inspect_evals`, and
OpenEnv's `textarena_env` accepts a seed and throws it away on `main` today. Then we pointed the
same hostility at this repository and **twelve of its own published claims broke**. The external
recall number was chance (p = 0.486) against a floor the project applies to every environment it
audits and had never applied to itself. Half the corpus proving the headline was the project's own
pytest fixtures, on which a test asserts perfect detection — a passing build wearing a measurement's
clothes. An exploit was published as "the winning policy, scored 1.0" that appears in no run that
succeeded. The Environment Card was described as *signed* and was an unkeyed hash anyone could
recompute.

None of that was dishonesty. It was a fast-moving repo where corrections landed one document
downstream of the one people read — which is exactly how a broken benchmark stays broken. The
uncomfortable conclusion is that **an auditing tool is not exempt from the thing it audits, and the
only defence is to run the audit on yourself and publish what it finds.**
[`docs/RED-TEAM.md`](docs/RED-TEAM.md) is that audit, unedited;
[`docs/RETRACTIONS.md`](docs/RETRACTIONS.md) is every claim it cost. Every probe here is a
deterministic program; the only model in the system is the attacker.

## License

Apache-2.0 — [`LICENSE`](LICENSE).
