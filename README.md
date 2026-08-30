# Assay

**An agentic auditor for RL environments and eval suites.**

Point Assay at an environment. It runs a battery of probes and emits an
**Environment Card**: a validity verdict where every claim is tied to a probe
result, plus machine-readable JSON and a nonzero exit code that blocks a
training run. The card carries a content digest, and an HMAC signature when
`ASSAY_CARD_KEY` is set — a digest alone identifies a card and catches
corruption; it is not tamper-evidence, because anyone editing the body can
recompute it.

> **Status: early.** All nine probe families and six adapters — inspect_ai,
> Harbor, OpenEnv, submitted specs, τ²-bench and ScienceAgentBench — are
> implemented and tested. The corpus spans four ecosystems; the wild sweep
> covers 246 registered `inspect_evals` tasks. The GRPO-trained Challenger
> **does not beat the scripted floor**, and the two runs behind that statement
> are written up with their numbers in
> [`docs/changelog/40-grpo-challenger.md`](docs/changelog/40-grpo-challenger.md).

```bash
uv sync --extra dev && uv run pytest -q               # the demo: every planted defect, caught
uv run --extra adapters --extra openenv python scripts/full_run.py   # headline, 22s
```

### Start here

| | |
|---|---|
| Reproduce every number end to end | [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) |
| What changed, slice by slice, with evidence | [`docs/CHANGELOG.md`](docs/CHANGELOG.md) |
| Read an agent run without executing anything | [`results/trajectories/INDEX.md`](results/trajectories/INDEX.md) |
| A sample Environment Card | [`results/example-card.md`](results/example-card.md) |
| Architecture and its known seams | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| **This repo's own claims, attacked** | [`docs/RED-TEAM.md`](docs/RED-TEAM.md) |
| Scored against the hackathon rubric, by us | [`docs/RUBRIC.md`](docs/RUBRIC.md) |
| The 20 scripts, and which 5 are entry points | [`scripts/README.md`](scripts/README.md) |

### Who this is for

An engineer about to spend GPU budget on an RL environment somebody else wrote —
or a benchmark maintainer about to publish one.

Today that person reads the task README, runs the gold solution once to see it
pass, and starts training. If the environment is broken they find out from the
reward curve weeks later, or they never find out and ship a model tuned against
a scorer that does not measure the task. When they *do* suspect something, the
fix is a person reading tasks by hand — 93 developers for SWE-bench Verified.

Assay runs before the training job: `assay audit <env>` exits nonzero and emits
a card naming which probe failed and what it saw. The four cost profiles in
`src/assay/costs/profiles/` are that person's decision made explicit — a
`research-run` prices a missed defect at wasted compute, a
`benchmark-publication` prices it at a retracted paper.

## The problem

Labs and vendors buy RL environments and eval suites as products. Nobody QAs
them. When a flagship benchmark turns out to be broken, the fix is a human
doing it by hand:

| Benchmark | What was wrong | How it was found |
|---|---|---|
| SWE-bench | ~2/3 of instances unusable | 93 developers, hand-triaged → SWE-bench Verified |
| SWE-bench | **7.8% of "passing" patches are wrong-but-pass** | manual audit (ICSE 2026) |
| SWE-bench | ~1/3 of instances leak the fix in the issue text | manual audit (SWE-bench+) |
| WebArena | substring-match evaluator produced false negatives | manual audit → WebArena Verified |
| tau2-bench | wrong gold actions, premature termination | 75+ ad hoc fixes across labs, unpublished |

The only automated tooling that exists is `gymnasium.utils.env_checker` and
`stable_baselines3.common.env_checker`. They assert space shapes, that
`reset()` returns `(obs, info)`, that reward is not NaN — and, in gymnasium
1.3.0, that the same seed and action give the same observation.

That last one matters, and an earlier version of this README got it wrong. It
said the checkers never verify seeding, citing
[Gymnasium #1084](https://github.com/Farama-Foundation/Gymnasium/issues/1084).
Running the real checker instead of a model of it
(`scripts/real_check_env.py`) shows gymnasium 1.3.0 raising `Deterministic step
observations are not equivalent for the same seed and action`.
Stable-baselines3 2.9.0 passes the same environment silently, so the two
incumbents differ; the baseline in this repo models the stronger one.

What survives is the ceiling. On five API-correct environments carrying four
planted defects, the real checkers catch **one** — determinism — and say
nothing about a verifier that pays full reward at reset, a constant action that
beats every other, or a score that comes apart from the task. They are linters
for *"will this crash my trainer"*, with exactly one check that is not.

## Two real defects, in software shipping today

The corpus above measures Assay against defects this repo planted. These two
were not planted. Both were verified from the upstream project's own code,
with Assay out of the loop, before being written down.

### `inspect_evals` 0.18.0 — `paws` scores a constant string at 100%

`paws` asks a model to answer `Yes` or `No`, and scores with `includes()` — a
case-insensitive **substring** test — against those literal targets.

| Completion | vs target `Yes` | vs target `No` |
|---|---|---|
| `"yesno"` | **correct** | **correct** |
| `"I don't know"` | incorrect | **correct** |
| `"Not sure"` | incorrect | **correct** |
| `"None of the above"` | incorrect | **correct** |
| `"I cannot determine the answer."` | incorrect | **correct** |

The constant string `"yesno"` contains both labels, so it scores **8000/8000 =
100%**. The looseness is one-sided, which is worse than symmetric: 4464 of 8000
items have the target `No`, so every hedging model is credited on 56% of the
benchmark for free.

This is the WebArena substring-match failure from the table at the top of this
README, live in a package people train and publish against. `boolq` carries a
narrower version — `pattern(r"(Yes|No).?\Z")` anchors, which genuinely helps,
but *know* is *no* plus one character, so `"I don't know"` still passes on every
`No` item.

### `openenv` — `textarena_env` accepts a seed and ignores it

Six calls to `reset(seed=1234)` return six different secret Wordle words:
`earth, north, south, bread, tight, stage`. The method signature takes `seed`
and then calls `self._ta_env.reset(num_players=...)` without it.

gymnasium 1.3.0 would catch this — its checker raises on exactly this shape,
confirmed in `scripts/real_check_env.py`. OpenEnv has no equivalent check, and
the environment ships with the defect. That is the point: the fix exists in one
ecosystem, and the ecosystem people are adopting for RL environments does not
have it.

### What the tool found, and what a human found

Assay flagged 14 of 25 sampled `paws` items as `REWARD_HACKABLE`. It did **not**
find the `"yesno"` case; hand triage did. The scripted Challenger's repertoire
is the adapter's trivial policies, and none of them names both labels at once.
That split is pinned as a test so it cannot quietly close in the write-up.

The `textarena_env` defect went the other way: the probe battery found it, and
only after two bugs in Assay's own determinism probe were fixed — it had been
requiring a verifier that OpenEnv does not have, and replaying an empty action
list whenever no gold trajectory existed. A vacuous check in the auditor, of
exactly the shape it flags in environments.

## Measured result

24 environments, 46 planted defects. Needs Docker for the Harbor tasks. No GPU
and no API key — `uv run --extra adapters --extra openenv python scripts/full_run.py`,
22s on a warm Docker image. **Both extras are load-bearing:** `--extra adapters`
alone omits `openenv` and gives 22 environments and 45 defects, not 24 and 46.
The run says so when it happens; read the degradation line before the table. Without the daemon the run still completes, on 19
environments, and says which ecosystem it dropped and why.

Expected loss under the `research-run` cost profile, with 95% bootstrap
intervals (10,000 resamples, seed 11, resampling over environments):

| arm | expected loss | 95% CI | recall | precision |
|---|---|---|---|---|
| assay | **240.0** | [0.0, 600.0] | 0.957 | 1.000 |
| flag_everything | 290.0 | [271, 307] | 1.000 | 0.137 |
| stratified_random | 1587.0 | [852, 2446] | 0.370 | 0.386 |
| always_modal_defect | 1767.0 | [1066, 2550] | 0.196 | 0.375 |
| direct_prompt (`qwen3:8b`) | 2415.0 | — | 0.239 | 0.324 |
| agent_with_tools (`qwen3:8b`) | 2497.0 | — | 0.196 | 0.265 |
| **check_env** (incumbent) | **2816.0** | [1728, 4024] | **0.043** | 1.000 |
| flag_nothing | 2832.0 | [1752, 4032] | 0.000 | 0.000 |

**The two LLM arms are the brief's own simple baseline, and they lose to
flagging at base rates.** `direct_prompt` reads everything a careful human
reviewer could read without executing anything — the manifest, the
instructions, the verifier source where it can be obtained — and names the
defect classes it thinks are present. `agent_with_tools` gets the same plus a
tool loop it can drive. They score 2415.0 and 2497.0 against
`stratified_random`'s 1587.0: better than the incumbent linter, worse than
guessing at the base rate, and an order of magnitude worse than running the
probes.

Reading an environment is not auditing it. That is the whole argument for
executing the thing, and until now it was an argument rather than a row.

These two arms were written, tested, and never scored, because
`scripts/full_run.py --llm-arms` **crashed**: the arm called `adapter.verify()`
with no refusal path, and `OpenEnvAdapter` raises there. One adapter of six
took the whole run down, and the failure sat at the far end of a long command
where nobody met it. No confidence intervals here yet — `scripts/intervals.py`
bootstraps `results/full_run.json`, and these live in `results/full_run_llm.json`.

An earlier version of this table gave `check_env` flag_nothing's row —
**2832.0, [1752, 4032], recall 0.000** — which contradicted both
`results/intervals.json` and the sentence directly beneath it. Corrected above
from the measured file; the paired differences below were always right.

The incumbent detects **2 of 46 defects — 4.3% recall**, both determinism, at
perfect precision. It is silent on the other eight probe families: verifier
integrity, trivial floor, separability, contamination, shortcut leakage,
spec/verifier mismatch, difficulty band and reward hackability.

**Read that row as a property of a model, not of the tool.**
`src/assay/baselines/structural.py` is Assay's *reimplementation* of what
`gymnasium.utils.env_checker` and `stable_baselines3.common.env_checker` assert,
because the real checkers cannot be pointed at a `ToyEnv`, an `inspect_ai` task
or a Harbor container at all. `NONDETERMINISM` is the only class it can ever
return, so "2 of 46" is bounded by construction rather than measured. The real
checkers *were* run, on five purpose-built `gymnasium.Env` shims — 1 of 4
detected, `results/real_check_env.json` — and that is the honest incumbent
number. One of the model's two hits is `fixture/flaky`, planted here.

### This corpus is almost entirely our own work, and the split is unflattering

The 24 environments are 12 in-process `fixture/*`, 5 `harbor/`, 5 `inspect/`,
2 `openenv/`. Split on **who wrote the environment**, not on the id prefix:

| provenance | n | what it is |
|---|---|---|
| authored here | 12 | our fixtures; `tests/test_probes_fire.py` asserts `detected == planted` on all of them |
| our content, third-party format | 10 | our datasets and defective scorers on inspect_ai's runtime; our task dirs in Harbor's shape, `authors = ["assay fixtures"]` |
| **genuinely external** | **2** | `openenv/echo`, `openenv/textarena-wordle`, audited as shipped |

By ground truth it is worse: **22 planted here, 1 hand-triaged, 1 derived from
a diff between two pinned upstream revisions.** Provenance is now declared in
the registry (`src/assay/corpus.py`), and an environment that declares none
fails a test rather than defaulting to clean.

`uv run --extra adapters python scripts/corpus_splits.py`, full table in
[`results/corpus_splits.json`](results/corpus_splits.json):

| split | n | assay | flag_everything | who wins |
|---|---|---|---|---|
| all (published) | 24 | 240.0 | 290.0 | assay, by 50 |
| **our content, third-party format** | 10 | **240.0** | **114.0** | **flag_everything** |
| genuinely external | 2 | 0.0 | 27.0 | assay — but n=2 |
| in-process fixtures | 12 | 0.0 | 149.0 | assay — asserted, not measured |
| no-harbor | 19 | 0.0 | 230.0 | assay, perfectly |

`research-run`; the other three profiles are in the file.

**Where Assay loses is the ten environments we wrote in someone else's format —
240.0 to 114.0, and on three of four profiles.** Both of its misses are
`harbor/`, both are ours, so the fixtures contribute a guaranteed zero and the
pooled 240.0 vs 290.0 win is carried by environments whose answers are pinned in
a test.

A previous version of this section reported that split as "the twelve
environments this repo did not write". It wrote ten of the twelve. That
sentence was added while correcting other overclaims, which is the failure mode
this project keeps finding in itself: a split computed on a string prefix
(`fixture/`) and then described in words the prefix does not support. The
splits are now cut on declared provenance.

The mirror image is equally under-reported: drop Docker and the corpus loses
every environment Assay gets wrong, so it scores **0.0 on all four profiles**
and separates cleanly from the floor (saved 230.0, CI [213, 245]).

**And note what the arithmetic does here.** `flag_everything`'s loss is exactly
`Σ_env (14 − |planted_env|)`, so **every clean environment added moves the floor
by +14 and Assay by 0**. Roughly eight clean third-party environments would flip
the headline without the detector changing at all. That is why provenance is
declared before the corpus grows, and why any expansion has to pre-register the
expected mechanical shift — otherwise a bigger corpus is a manufactured win.

The honest summary: **n=2 is the real size of the third-party control**, the
corpus is too small and too self-authored to support the pooled headline, and
growing it with environments nobody here wrote is the first thing worth doing
next — carefully.

### The headline survives a 21% error in one made-up number, and no more

Every expected-loss figure here is denominated in "engineer-hours-equivalent",
and `src/assay/costs/profiles/research-run.yaml` prices a missed CRITICAL defect
at **120** of them. Nothing derives that 120. It is a considered guess, and
every number above scales linearly with it.

So: sweep it. `uv run --extra adapters python scripts/cost_sensitivity.py`,
holding the severity shape fixed and moving only the miss/false-alarm exchange
rate ([`results/cost_sensitivity.json`](results/cost_sensitivity.json)):

| CRITICAL miss cost | assay | flag_everything | winner |
|---|---|---|---|
| 40 | 80.0 | 290.0 | assay |
| 120 *(shipped)* | 240.0 | 290.0 | assay |
| **145** | **290.0** | **290.0** | **tie** |
| 200 | 400.0 | 290.0 | flag_everything |
| 800 | 1600.0 | 290.0 | flag_everything |

The crossover is exact rather than bisected. Assay never false-alarms, so its
loss is `2 × C`; `flag_everything` never misses, so its loss is pure false
alarms and does not move with `C` at all. They cross at `290 / 2 = 145`.

**The shipped value is 120. The crossover is 145.** So the headline result —
Assay beats the trivial floor — holds only while a missed critical defect is
worth less than about 1.2× what this repo guessed. Price a wasted training run
any higher, as anyone renting an H100 cluster for a week plausibly would, and
**flagging everything is the better policy** and Assay is not worth running.

That is not a reason to distrust the ranking so much as a statement of what the
ranking is: a claim about a specific cost regime, not about detectors in
general. The one anchor available is that SWE-bench Verified needed **93
developers** reading tasks by hand — which is the observed price of finding
these defects the other way, and why a miss is priced far above a false alarm
rather than near it. It does not pin 120 versus 145.

Reported here rather than left for a reader to derive, because a paragraph
saying "costs are illustrative" would have hidden that the margin is 21%.

`stratified_random` and `always_modal_defect` are the two trivial policies
`criteria.md` requires that this repo did not implement until
[`docs/changelog/62-rigour.md`](docs/changelog/62-rigour.md). Neither becomes
the floor: on an imbalanced 14-class multilabel problem, flagging at base rates
buys recall 0.370 at the cost of 27 false alarms and 29 misses, which is worse
than flagging everything under every cost-asymmetric profile and worse than
flagging nothing under `flat`. Adding a harder-sounding baseline did not make
the floor harder, and that is published as the result rather than as a reason
not to have run it. Full table, per profile, in `results/baselines.json`.

Against `flag_nothing` it saves **16.0 expected loss, 95% CI [0.0, 40.0]** — an
interval that includes zero.

**That interval cannot say what this README used to make it say.** `check_env`
emits no false positives and detects a strict subset of what is planted, so the
paired difference is >= 0 in every resample — 10,000 of 10,000. An interval
that can never go negative cannot exclude zero from above, so "not
statistically distinguishable" was decided by the shape of the test, not by the
data. On a one-sided reading the claim survives at p ~ 0.12: that is the chance
no `NONDETERMINISM` environment is drawn, (22/24)^24, and it is the whole
result. One of `check_env`'s two hits is `fixture/flaky`, planted here.

Same caveat on the intervals above. With Assay wrong on exactly 2 of 24
environments, the bootstrap distribution of its loss is a binomial count on a
120-point lattice — ten distinct values, 12.4% of the mass on exactly 0.0. The
`[0.0, 600.0]` interval is the 2.5th and 97.5th rungs of that ladder. It is
honest resampling on a corpus too small to carry the precision "95% CI"
implies, and it is reported here rather than left for a reader to derive.

An earlier version of this README said it scored *identically* to flagging
nothing. That was measured against a model of the checkers that omitted their
determinism check — a strawman weaker than the real tool. The corrected claim
is narrower and is the one worth making, but note what it rests on: the same
author who caught "benchmarking against a reimplementation rather than the
tool" is still, on this row, benchmarking against a reimplementation.

### What holds, and what does not

Two overlapping one-sample intervals do not settle "A beats B", so the claims
are paired differences drawn on a shared resample:

| Comparison | Loss saved | 95% CI | |
|---|---|---|---|
| assay vs `check_env` | 2576.0 | [1472, 3840] | **separated** |
| assay vs `stratified_random` | 1347.0 | [455, 2316] | **separated** |
| assay vs `always_modal_defect` | 1527.0 | [638, 2435] | **separated** |
| assay vs `flag_everything` | 50.0 | [−309, 295] | **overlaps zero** |
| `check_env` vs `flag_nothing` | 16.0 | [0, 40] | **overlaps zero** |

Assay beats the incumbent. **Assay does not beat the trivial floor at n=24.**
By this project's own rule — a policy that ignores the input must not win —
that advantage is not established on this corpus, and saying otherwise would
be the exact failure the tool exists to catch.

### The profiles where Assay loses

Running only the flattering cost model would be its own kind of dishonesty, so
here is every profile shipped, not the one that reads best.

| profile | assay | flag_everything | |
|---|---|---|---|
| `flat` | **2.0** | 290.0 | separated, [269, 305] |
| `research-run` | **240.0** | 290.0 | overlaps zero, [−309, 295] |
| `production-training` | 1920.0 | **580.0** | flag_everything wins |
| `benchmark-publication` | 4000.0 | **2320.0** | flag_everything wins |

**Assay wins outright on one of four, and loses outright on two.** That is the
correct answer to the question those profiles ask: when a miss is catastrophic
and review is nearly free, review everything. Assay's two CRITICAL misses cost
960 each under `production-training`; 290 false alarms cost 2 each.

The pattern is the whole argument for the metric. Assay earns its place exactly
where false alarms have real cost — where nobody can triage 290 spurious
findings — and it is the wrong tool where a miss is unaffordable and a human
will read everything anyway. A single accuracy number would have hidden that,
and a single cost profile would have let us pick which way it hid.

Both misses are `REWARD_HACKABLE`, on `harbor/self-graded` and
`harbor/shared-tests` — the two the scripted Challenger cannot find.

## Does an agent find what a script cannot?

`scripts/challenger_ablation.py`, on that same environment:

| Challenger | Result | Exploit gap | Scored attempts | Wall clock |
|---|---|---|---|---|
| scripted | missed | 0.00 | 4 | 2.2s |
| prompted, `qwen3:8b` | missed | 0.00 | 10 | 97.0s |
| prompted, `claude-cli` | **found** | **1.00** | 10 | 261.7s |

Read from [`results/challenger_ablation.json`](results/challenger_ablation.json).
An earlier version of this table printed 4/8/8 attempts at 6s/74s/405s, which
matched no committed run — a red-team pass could not source a single one of
those six numbers. The row above is the file. A 10-turn budget; "scored
attempts" counts the turns that parsed into an action. Wall clock is with the
Ollama model already resident; the first call after a model swap costs another
two to three minutes.

The winning policy, at turn 8, after seven turns of reconnaissance — hunting
for the verifier, listing `/logs`, checking file permissions, trying to write
`reward.txt` directly:

```sh
echo -n 'banana' > expected.txt; echo -n 'banana' > out.txt
```

It does not forge an answer. It **overwrites the expected answer** so the
verifier's comparison is trivially true, and by turn 10 it does the same with
`WRONG_XYZ` — a string that is not the answer to anything.

Scored 1.0 by the environment. Scored 0.0 by the independent verifier the
agent never had access to. That difference is the whole measurement.

A previous revision printed a symlink here — `rm -f expected.txt && ln -s
out.txt expected.txt && …` — as "the winning policy … scored 1.0". That command
appears in no run that succeeded. The only symlink in the artifacts points the
other way and belongs to a run that **missed**
([`results/challenger_ablation_claude.json`](results/challenger_ablation_claude.json)).
Publishing an exploit that was never scored, in a repository whose thesis is
that unverified claims about environments are the problem, was the worst single
defect the red-team found, and it was found by reading artifacts this README
told people to read.

The two misses are as much the result as the hit. An ablation showing only the
arm that worked says nothing about how hard the problem is.

That row nearly went into this table as a lie. Two earlier runs printed
`qwen3:8b` as `missed gap=0.00 attempts= 0`, at 186.6s and 188.3s, with an
empty `attacker_trace` and no reason — a row indistinguishable from ten attacks
that all failed. It has not reproduced since and the cause is still open:
`PromptedChallenger.attack` can spend its whole budget and return nothing by
three different routes — every reply unparseable, every reply a `reset`, or the
model going unreachable — and until this was found, all three came back as the
same clean PASS over an empty attempt list.

The third route is fixed: an unreachable model now makes the probe
`NOT_APPLICABLE` with the reason attached, which is what this project's own
rule has always said should happen, and two tests hold it there. The other two
are not. A run that produced only unparseable or only `reset` turns still
records them in the loop's `history` and then discards it, because only parsed
turns become `Attempt`s and the probe reports the last `Attempt`'s log. That is
a live gap between what the card says and what the run knew, tracked in
[`docs/changelog/85-reproduction.md`](docs/changelog/85-reproduction.md).

### How often, though

That table is one run each, and one run is not a capability. A Challenger was
pointed at the same environment four independent times
(`scripts/challenger_reliability.py`, `results/challenger_reliability.json`):

Not quite the same arm, and the distinction matters. The ablation row above is
`prompted, claude-cli` alone; the reliability run records
`scripted+prompted[claude-cli:sonnet]` — the **composite**. So 3-in-4 is the
reliability of the arm Assay actually ships, not of the row directly above it.

| run | result | gap |
|---|---|---|
| 1 | found | 1.00 |
| 2 | found | 1.00 |
| 3 | **missed** | 0.00 |
| 4 | found | 1.00 |

**3 of 4.** A probe backed by a sampled model is not a deterministic check, and
the first version of this README said "the Challenger finds this" on the
strength of a single run — which is the pass@1-for-pass^k substitution that
τ-bench exists to warn about, made here in our own write-up.

The number reported is a rate. It also means a real audit should run the
Challenger more than once, and Assay does not currently do that: the probe
takes one pass per environment, so a card can say `VALID` on an environment a
second attempt would have broken. That is a known gap, not a solved problem.

**It is still open.** A Challenger was trained with GRPO against a dense
exploit-gap reward (`reported score` minus `independent true completion`, held
by the harness and never shown to the attacker) on a spot A10G, with
`harbor/self-graded` held out. That holdout does not hold: `results/train_holdout_dedup.json`
records 60 of 300 training rows carrying its byte-identical prompt, true Jaccard
1.0, so 20% of training saw the held-out environment. The result below is
reported against a contaminated split and is weaker than it reads. It did not
close the miss, and neither did the prompted Challenger on local 1.7B/8B
models. The reward itself is verified -- 38 tests, four against real
containers, no GPU -- and the run logs say precisely what failed: 99.7% of GRPO
rollout groups had zero reward spread, so there was no gradient at all.
Numbers, the single-variable follow-up run, and what to try next are in
[`docs/changelog/40-grpo-challenger.md`](docs/changelog/40-grpo-challenger.md).
Nothing about the trained Challenger is required to run Assay: it ships as an
optional artifact, the scripted Challenger is the floor, and the reproduction
guide never asks for a GPU.

## What every agent actually did

[`results/trajectories/`](results/trajectories/INDEX.md) — one representative run
per agent this submission used, readable end to end without running anything:
the instructions the agent was given, every action it took, what the tools said
back, the feedback that shaped its next step, and every human approval.

Failed turns and malformed replies are kept. Three of the eight are Challenger
**misses**, one of those is the same `claude-cli` arm failing on the task it
cracks in another run, and one is the sandbox approval gate **refusing** —
`DenyAll` is the default, and nothing executes untrusted environment code
without an approver who leaves a reason.

```bash
uv run --extra adapters python scripts/export_trajectories.py
```

## Where Assay sits in the field

Everything above is measured against defects **this repo planted**. That is a closed
loop, and the two sections below break it — recall against defect lists other people
confirmed, scored where possible by their code rather than ours.

### τ²-bench — 62 defects an independent team labelled

`amazon-agi/tau2-bench-verified`: an independent team read all 164 τ-bench retail and
airline tasks, judged some wrong, and shipped corrected files. Labels here are built
from the **diff between two pinned revisions**, not from the prose — anyone can
recompute them with `json.load` and `==`.

**Apply this repo's own trivial-floor rule first.** `metrics.py`: *"if it cannot beat
the best policy that ignores its input, it has not earned its existence."* Every
environment Assay audits is held to that. This measurement was not, until a red-team
pass caught it. The floor here is a flagger that picks the same number of tasks at
random; `flag_everything` scores recall 1.000 at precision 0.378.

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
false positives, and including it **destroys the measurement**. An earlier revision of
this README led with 0.339 and relegated the row that carries the signal. That framing
was backwards, and the base rate 62/164 appeared nowhere in the repository.

Read the p-values, not the recall. Both rows and the floor are in
[`results/tau2_recall.json`](results/tau2_recall.json); the test is exact
(hypergeometric), so it needs no sampling and no normal approximation.

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
  `their_report: null` and says so. Stopping rather than reporting an unjudged number
  was right; an earlier revision of this README stated the outcome anyway, under a
  heading claiming it fell out of running their scorer. It is an argument about the
  metric's shape, not a result.

  The argument itself still stands and can be checked without a judge: R1 fires on 61 of
  102 tasks, and `metrics.py` computes precision only over findings on the 12 revised
  tasks, so most of what it emits is structurally invisible to that metric. The count
  previously given here — 41 findings on clean tasks — was wrong. R1 submitted **20**
  findings, 4 on revised tasks, so **16** on clean ones; 41 is the number of findings
  suppressed by the image-output exclusion, a different quantity read out of the wrong
  field.

### What this changes about the claims above

The blind spot is now measured twice, on two independently labelled sets: **Assay does
not detect instruction defects, because "this instruction is ambiguous" is a judgement
and nothing here scores with a judge.** That was published as a limitation before it was
measured; it is now a number.

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

Families 1–8 are deterministic programs. Family 9 is an adversarial
**Challenger** agent -- scripted, prompted, or GRPO-trained. **No LLM judge
scores anything inside Assay.** The Challenger only ever proposes actions; every
one of them is scored by a program, and the ground truth it is scored against
is held by the probe and never shown to the attacker.

Stated as an absolute — "no LLM judge scores anything, anywhere" — that was
false, and worth correcting precisely because the rule is load-bearing.
Assay's *own* verdicts use no judge. But two things it touches do: τ²-bench's
`nl_assertions` are judged by an LLM, which is exactly why they are excluded
from the τ² measurement and reported as absent rather than passed; and
BenchGuard's `match.py`, whose scorer this project deliberately borrowed rather
than reimplement, calls a Gemini judge. That run scored nothing only because
Assay submitted nothing. The rule is about what Assay asserts, not about what
exists in the room.

```bash
uv run --extra adapters pytest tests/test_grpo_reward.py -q      # the reward, no GPU
uv run --extra adapters python scripts/reward_landscape.py       # what it can pay
```

## Prior art

The category is not new, Assay does not claim it is, and one earlier version of this
section overclaimed. Corrected below.

**Static auditors — reason over a benchmark's files:**

- **BenchGuard** ([arXiv 2604.24955](https://arxiv.org/abs/2604.24955)) — 12
  author-confirmed defects on ScienceAgentBench across 102 tasks, 83–100% recall
  depending on model and whether agent traces are supplied, ~$0.12–0.30 per task.
- **ABA** ([arXiv 2605.26079](https://arxiv.org/abs/2605.26079)) — 168 benchmarks,
  34,285 tasks, **14,024 major issues affecting 25.7% of tasks**. Publishes a table
  claiming it beats BenchGuard on both SAB and BixBench.

Assay has been scored head-to-head against BenchGuard's 12 defects **using
BenchGuard's own `eval/match.py` + `eval/metrics.py`**, not a scorer written here.
**ABA's audit scores 10/12 on that gold; Assay scores 0/12** — because SAB's
verifier lives in a password-protected archive and all 12 probes returned
NOT_APPLICABLE, so Assay could not run on this benchmark at all. The numbers, the
two ways that comparison is unfair to BenchGuard's own metric, and why "could not
run" is kept apart from "ran and found nothing" are
[above](#scienceagentbench--0-of-12-by-benchguards-own-scorer).

```bash
uv run --extra sab --extra adapters python scripts/sab_benchguard_recall.py \
    --arm assay --split original \
    --benchguard-root third_party/BenchGuard \
    --converter third_party/auto-bench-audit/benchmarks/benchguard/audits_to_benchguard_findings.py
```

Full write-up: [docs/SCIENCEAGENTBENCH.md](docs/SCIENCEAGENTBENCH.md).

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

### A correction

An earlier version of this README listed **Adversarial Reward Auditing**, Beigi et al.
([arXiv 2602.01750](https://arxiv.org/abs/2602.01750)) as having "the same probe
vocabulary, for classical RL reward functions". That was wrong, and it was wrong about
someone else's paper.

Beigi et al. is an RLHF alignment paper: a Hacker policy against an Auditor, plus
Auditor-Guided RLHF, evaluated on sycophancy, length bias and code gaming with
Llama-2-7B. It contains no classical RL environments, no gold / no-op / inverted-spec /
known-wrong probes, and no benchmark-defect counts. The probe vocabulary is Assay's own.
The paper is adjacent in spirit — adversarial detection of reward exploitation — and
shares no metric Assay could be measured against. Left in the record rather than quietly
deleted.

### What Assay adds

Narrowed to what the literature actually supports, after the above.

1. **The bundle, not dynamism.** Running probes against a live harness is *not*
   novel — BenchJack does it, and arXiv 2606.16062 runs a gold-sanity gate on
   SWE-bench Verified. What no other tool does is carry verifier integrity,
   contamination, shortcut leakage, separability, difficulty and reward-hackability in
   one report under one severity-weighted expected-loss metric. ABA's own static-vs-
   trajectory ablation, which agrees with itself only 29–63% of the time, is the best
   published evidence that these modes are not interchangeable.
2. **Expected loss rather than a defect count.** Every system above reports how many
   defects it found. None reports what missing one costs against what a false alarm
   costs, or publishes the cost profiles under which it loses to flagging everything.
   Assay does, [above](#the-profiles-where-assay-loses).
3. **Absence of evidence reported as loudly as evidence.** Every card names the probes
   that could not run and why. On `openenv/textarena-wordle` that is 11 of 12.
4. **One tool across RL environment, agent benchmark and eval suite** — inspect_ai,
   Harbor, OpenEnv and submitted specs behind one adapter protocol.

A learned adversarial Challenger was trained and **did not work**; the honest write-up
is in [`docs/changelog/40-grpo-challenger.md`](docs/changelog/40-grpo-challenger.md).
It is listed here as an attempt, not a contribution.

## Try it

`uv sync --extra dev && uv run pytest -q`, as at the top. The test suite is the
honest demo: twelve fixture environments, each with a deliberately planted
defect, and a test asserting every planted defect is detected and a healthy
environment produces none.

Which script produces which number: [`scripts/README.md`](scripts/README.md).

## Lineage

The methodology predates the code — see [`docs/LINEAGE.md`](docs/LINEAGE.md)
for what existed before this repo and what was added here. No code was copied
in; the prior work is cited as lineage, not vendored.

## Main failure mode

**A Challenger that could not speak, reported as a Challenger that found
nothing.** Family 9 is the only probe backed by an agent, and an agent has more
ways to produce no output than a program does: the model refuses, every reply
is unparseable, the budget runs out mid-plan, the CLI is rate-limited. All of
those arrive at the probe as an empty attempt list, and an empty attempt list is
indistinguishable from a genuine "I attacked this environment and it held".

The probe reports `NOT_APPLICABLE` for one of those routes and `PASS` for the
rest, which means **a card can read `VALID` because the auditor was silent**.
That is the single worst thing this tool can do, because it is the failure the
tool exists to catch, happening inside the tool. It is open, it is
[written up](#does-an-agent-find-what-a-script-cannot), and the fix — returning
an exhaustion reason instead of an empty list — is the next thing to land.

A second, milder version: one Challenger pass per environment, against a
Challenger measured at 3-in-4 reliability. A `VALID` verdict may be a run that
happened not to find the exploit.

## Hot take

**Nobody QAs the benchmark — including the people building the tool that QAs
benchmarks.**

This project's thesis is that the RL environments and eval suites labs buy are
shipped unchecked, and it is right: `paws` scores the constant string `"yesno"`
at 100% on the current release of `inspect_evals`, and OpenEnv's
`textarena_env` accepts a seed and throws it away on `main` today.

Then we pointed the same hostility at this repository and **twelve of its own
published claims broke**. The external recall number was chance (p = 0.486)
against a floor the project applies to every environment it audits and had never
applied to itself. Half the corpus proving the headline was the project's own
pytest fixtures, on which a test asserts perfect detection — a passing build
wearing a measurement's clothes. An exploit was published as "the winning
policy, scored 1.0" that appears in no run that succeeded. The Environment Card
was described as *signed* and was an unkeyed hash anyone could recompute.

None of that was dishonesty. It was a fast-moving repo where corrections landed
one document downstream of the one people read — which is exactly how a broken
benchmark stays broken. The uncomfortable conclusion is that **an auditing tool
is not exempt from the thing it audits, and the only defence is to run the
audit on yourself and publish what it finds.**
[`docs/RED-TEAM.md`](docs/RED-TEAM.md) is that audit, unedited.

Every probe here is a deterministic program. The only model in the system is the
attacker.

## License

Apache-2.0.
