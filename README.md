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
| `flag_nothing` | 3232.0 | [2128, 4456] |
| `check_env` — the incumbent linter | 3216.0 | [2104, 4448] |
| `flag_everything` — **the floor that had to be beaten** | 394.0 | [375, 411] |
| **Assay** | **43.0** | **[0, 125]** |

Assay saves **351.0 against `flag_everything`, 95% CI [263, 404] — separated.** Wins 4 of 4 cost
profiles and now separates on all 4. 28 environments, 54 planted defects, 10,000 bootstrap resamples
over environments, seed 11. **Read the arms in the right order:** beating `check_env` proves almost
nothing (16.0 saved of `flag_nothing`'s 3232.0, on an interval including zero). The arm that had to
be beaten is `flag_everything` — it catches every defect by construction, and for most of this
project's life Assay did not beat it.

**Two of those numbers moved for reasons that are not detection, and both are in the table above.**
The taxonomy went from 14 defect classes to 16 in
[`docs/changelog/97-dead-zone-probes.md`](docs/changelog/97-dead-zone-probes.md), which hands
`flag_everything` one free false alarm per environment per class and nothing to a truthful detector
— **+52 on its own**, banked here for the first time. And two τ² environments were added under
[`docs/PRE-REGISTRATION-TAU2.md`](docs/PRE-REGISTRATION-TAU2.md), worth another **+28** to the floor
against **+3** to Assay. Of the 351.0, **77.0 is arithmetic and 274.0 is the detector.**

```bash
uv sync --extra dev && uv run pytest -q                              # the demo: every planted defect, caught
uv run --extra tau2 python scripts/tau2_fetch.py                     # the two pinned tau2 snapshots, ~1 min
ASSAY_APPROVE_ALL="reproduction" \
  uv run --extra adapters --extra openenv --extra tau2 python scripts/full_run.py   # the headline
```

**Skip the fetch and you get 26 environments, not 28.** Neither τ² snapshot is redistributed here, so
without them the `tau2` provider reports itself unavailable, the corpus is two environments smaller
and every arm's loss falls — `full_run.py` prints the reason rather than shrinking quietly.

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
| **Published artifacts, all of them** | [**Collection**](https://huggingface.co/collections/caiotheodoro/assay-auditing-rl-environments-with-error-bars-6a946953e05a8669da74ee65) — [code](https://github.com/caiotheodoro/assay), [corpus, cards and arms](https://huggingface.co/datasets/caiotheodoro/assay-corpus), [the GRPO Challenger, **a negative result**](https://huggingface.co/caiotheodoro/assay-challenger-grpo), [the solution video, 4:36](https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4) |

> **An auditor is an eval.** If benchmarks ship unchecked because nobody QAs them, nothing makes
> the QA tool different. So every instrument this tool applies to an environment was turned on the
> tool: **twelve of this repository's published claims broke**, and the self-audit found three real
> behavioural bugs. Every retraction is kept verbatim in
> [`docs/RETRACTIONS.md`](docs/RETRACTIONS.md); the unedited breakage is
> [`docs/RED-TEAM.md`](docs/RED-TEAM.md).

**There is no hosted demo.** `space/app.py` is a finished Gradio app — escapes submitted HTML, 7
tests, 9 pre-publication gates — but Hugging Face returns HTTP 402 for a Gradio Space on free
`cpu-basic`, and a static Space cannot serve a server-side probe battery. Run `python space/app.py`.

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

**1. The two LLM arms are the brief's own simple baseline, and they are now indistinguishable from
flagging at base rates.** `direct_prompt` reads everything a careful human reviewer could read
without executing anything; `agent_with_tools` gets the same plus a tool loop it can drive. They
score **2454.0 and 2736.0** against `stratified_random`'s 2793.0. **That is a reversal and it is
mostly not the LLM arms.** They previously lost to `stratified_random` at 2658.0 / 2654.0 against
1789.0, separated. What moved is the baseline: `stratified_random` flags each class independently at
its corpus base rate, drawing one `rng.random()` per class per environment in enum order, so adding
two defect classes to the taxonomy reshuffled the whole seeded sequence and cost it **+878 with no
change to the corpus, the policy or the detector**. Against the policy's closed-form mean rather
than one draw of it — **2474.3** — `direct_prompt` at 2454.0 is a tie, and the paired bootstrap says
the same: **339.0, 95% CI [−244, 942], not separated.** The two LLM arms land 282.0 apart, far inside
their own intervals: **giving the model a tool loop still bought nothing measurable.**

**2. Two figures in that table are weaker than they look.** The incumbent's 3.7% recall is a property
of a *model* — `src/assay/baselines/structural.py` reimplements the two checkers, because the real
ones cannot be pointed at a `ToyEnv`, an `inspect_ai` task or a Harbor container at all, and
`NONDETERMINISM` is the only class it can return; run for real on five purpose-built shims they
detect 1 of 4 ([`results/real_check_env.json`](results/real_check_env.json)). And **Assay's precision
is no longer 1.000. It is 0.9464**, three spurious findings across 28 environments, all three on the
two τ² environments — `GOLD_FAILS` and `NOOP_PASSES` on retail, `NOOP_PASSES` on airline. Half that
number is real and half is a property of the label: τ² is the only place in the corpus where
`frozenset()` means "an outside revision diff establishes nothing else" rather than "we planted
nothing else", and `Outcome.spurious` cannot tell those apart. Separately, the old 1.000 was already
the modal run: across six full-corpus runs `harbor/broken-gold` reported a spurious `NONDETERMINISM`
**once**.

**3. The corpus is 6 of 28 genuinely third-party, 2 of them externally *labelled*, and that is still
the ceiling on all of it.** `flag_everything`'s loss is exactly `Σ (16 − |planted|)`, so **every
clean environment added moves the floor by +16 and Assay by 0** — roughly seven would flip the
headline with no change to the detector. Hence provenance declared in the registry before the corpus
grows, and every expansion pre-registered first
([`docs/PRE-REGISTRATION.md`](docs/PRE-REGISTRATION.md),
[`docs/PRE-REGISTRATION-TAU2.md`](docs/PRE-REGISTRATION-TAU2.md)).

| split | n | assay | flag_everything | who wins |
|---|---|---|---|---|
| all (published) | 28 | 43.0 | 394.0 | assay, by 351 |
| our content, third-party format | 10 | 0.0 | 132.0 | assay |
| genuinely external | 6 | 43.0 | 89.0 | assay — but n=6, and every error is here |
| in-process fixtures | 12 | 0.0 | 173.0 | assay — asserted, not measured |
| self-authored | 22 | 0.0 | 305.0 | assay |

`uv run --extra adapters --extra tau2 python scripts/corpus_splits.py`, full table in
[`results/corpus_splits.json`](results/corpus_splits.json). **n=6 is the real size of the third-party
control.** It went 4 → 6 by registering τ²-bench's retail and airline domains, whose ground truth
`amazon-agi/tau2-bench-verified` published at a commit. Three of the six now carry
`LabelSource.EXTERNALLY_DERIVED`, and they are not the same kind of evidence:
`openenv/textarena-wordle`'s label was derived outside Assay but *decided* here, by reading
TextArena's own game state; **nobody here decided which τ² tasks are wrong.** The mapping from "this
task record differs between two pinned revisions" onto `DefectClass` is two rules and fourteen
written exclusions, and it is the part worth attacking:
[`docs/PRE-REGISTRATION-TAU2.md`](docs/PRE-REGISTRATION-TAU2.md).

**And read that row's `by 46` with the arithmetic next to it.** Two environments carrying 2 planted
classes each hand `flag_everything` `2 × 14 = 28` free false alarms and cost Assay 3. The margin
widening is not a detection result, and the number that is: **on those 164 tasks, per task, Assay's
recall is 0.339 and does not beat flagging at random** ([`results/tau2_recall.json`](results/tau2_recall.json)).
An environment-level tick records that a class was found *somewhere* in 114 tasks.

### What holds, what does not, and what it all rests on

Two overlapping one-sample intervals do not settle "A beats B", so every claim is a paired
difference on a shared resample. Running only the flattering cost model would be its own kind of
dishonesty, so every profile shipped is published, not the one that reads best:

| profile | missed CRITICAL : false alarm | assay | flag_everything | saved | |
|---|---|---|---|---|---|
| `flat` | 1 : 1 | **4.0** | 394.0 | 390.0 | separated, [371, 408] |
| `research-run` | 120 : 1 | **43.0** | 394.0 | 351.0 | separated, [263, 404] |
| `production-training` | 960 : 2 | **246.0** | 788.0 | 542.0 | separated, [46, 808] |
| `benchmark-publication` | 2000 : 8 | **624.0** | 3152.0 | 2528.0 | separated, [1264, 3232] |

**Assay now wins all four and separates on all four.** It previously won one and lost two outright,
then won four and separated on three. **The row that changed is `production-training`, and it
changed because the floor moved, not because the detector did:** at 16 defect classes rather than 14
`flag_everything` pays 788.0 there instead of 628.0, and a margin that was 388.0 on an interval
crossing zero is 542.0 on one that does not. At that profile's 480:1 ratio "flag everything and read
the cards" is a genuinely good policy, and it is worth being explicit that what pushed Assay clear of
it this time was two probe families being added to the taxonomy. Against the other floors the margins
are wide and separated (3189.0 over `flag_nothing`, 2750.0 over `stratified_random`); the six-row
table and the interval caveats — including the one whose shape decides its own answer, and the
ten-rung bootstrap lattice a corpus this size actually supports — are in
[`docs/RESULTS.md`](docs/RESULTS.md). **One miss remains across 28 environments and it is external:**
`inspect_evals/boolq`, structurally — no train split, so the shortcut probe reports `NOT_APPLICABLE`
before it runs. **Three spurious findings remain and all three are on τ².**

**And the whole ranking rests on one made-up number.** `research-run.yaml` prices a missed CRITICAL
defect at **120** engineer-hours-equivalent; nothing derives that 120, and every figure above scales
linearly with it. So sweep it ([`results/cost_sensitivity.json`](results/cost_sensitivity.json)):

| CRITICAL miss cost | 120 *(shipped)* | 800 | **1099.53** | 2000 |
|---|---|---|---|---|
| assay | 43.0 | 269.7 | **394.0** | 669.7 |
| flag_everything | 394.0 | 394.0 | **394.0** | 394.0 |
| winner | assay | assay | **tie** | flag_everything |

The crossover is exact, not bisected: Assay's loss is linear in `C` while `flag_everything` never
misses and does not move with `C` at all, so they cross at `120 × 394 / 43 = 1099.53`. **The shipped
value is 120. The crossover is 1099.53.** The headline survives a **816% error** in a constant nobody
derives — a margin that was 21% before the two Harbor misses were closed and 685% before the
taxonomy grew, stated plainly because the earliest number was the sharpest criticism of this work and
the one that changed most. Note what moved it this time: the numerator is `flag_everything`, and two
extra defect classes plus two extra environments raised it. **A widening safety margin that comes
from the floor getting worse is not the same evidence as one that comes from the detector getting
better**, and this jump is the first kind. A claim about a specific cost regime, not about detectors
in general.

## Does an agent find what a script cannot?

**It did. Then a better script found it too, and that is the more useful result.**

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
