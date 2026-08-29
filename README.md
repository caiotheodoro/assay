# Assay

**An agentic auditor for RL environments and eval suites.**

Point Assay at an environment. It runs a battery of probes and emits a signed
**Environment Card**: a validity verdict where every claim is tied to a probe
result, plus machine-readable JSON and a nonzero exit code that blocks a
training run.

> Status: early. Core, all nine probe families, and the inspect_ai and Harbor
> adapters are implemented and tested. The OpenEnv adapter, the prompted and
> learned Challengers, and the wild sweep are not built yet.

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
`reset()` returns `(obs, info)`, and that reward is not NaN. They are linters
for *"will this crash my trainer"* — never *"is this measuring what it
claims."* They do not even verify that seeding makes behaviour reproducible
([Gymnasium #1084](https://github.com/Farama-Foundation/Gymnasium/issues/1084)).

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

This is exactly the gap named at the top of this README:
[Gymnasium #1084](https://github.com/Farama-Foundation/Gymnasium/issues/1084) —
`env_checker` verifies that `reset()` *accepts* a seed, never that seeding does
anything — reproduced in a different ecosystem, on an environment people train
against.

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

21 environments, 44 planted defects. Needs Docker for the Harbor tasks. No GPU,
no API key, no network — `uv run --extra adapters python scripts/full_run.py`.

Expected loss under the `research-run` cost profile, with 95% bootstrap
intervals (10,000 resamples, seed 11, resampling over environments):

| arm | expected loss | 95% CI | recall | precision |
|---|---|---|---|---|
| assay | **120.0** | [0.0, 360.0] | 0.977 | 1.000 |
| flag_everything | 250.0 | [232, 266] | 1.000 | 0.150 |
| **check_env** (incumbent) | **2704.0** | [1688, 3840] | **0.000** | 0.000 |
| flag_nothing | 2704.0 | [1688, 3840] | 0.000 | 0.000 |

The structural linter scores **identically to flagging nothing**. It is not a
weak detector of these defects; it is not a detector of them at all.

### What holds, and what does not

Two overlapping one-sample intervals do not settle "A beats B", so the claims
are paired differences drawn on a shared resample:

| Comparison | Loss saved | 95% CI | |
|---|---|---|---|
| assay vs `check_env` | 2584.0 | [1536, 3760] | **separated** |
| assay vs `flag_everything` | 130.0 | [−117, 261] | **overlaps zero** |

Assay beats the incumbent. **Assay does not beat the trivial floor at n=21.**
By this project's own rule — a policy that ignores the input must not win —
that advantage is not established on this corpus, and saying otherwise would
be the exact failure the tool exists to catch.

### The profile where Assay loses

Running only the flattering cost model would be its own kind of dishonesty.
Under `production-training`, where a missed defect costs 480× a false alarm:

| arm | expected loss |
|---|---|
| flag_everything | **500.0** |
| assay | 960.0 |

**Flagging everything wins.** That is the correct answer to the question that
profile asks: when a miss is catastrophic and review is nearly free, review
everything. Assay's single CRITICAL miss costs 960; 250 false alarms cost 2
each. Assay earns its place only where false alarms have real cost — where
nobody can triage 250 spurious findings.

That miss is `harbor/self-graded`, and it is exactly the one the scripted
Challenger cannot find.

## Does an agent find what a script cannot?

`scripts/challenger_ablation.py`, on that same environment:

| Challenger | Result | Exploit gap | Attempts |
|---|---|---|---|
| scripted | missed | 0.00 | 4 |
| prompted, `qwen3:8b` | missed | 0.00 | 10 |
| prompted, `claude-cli` | **found** | **1.00** | 10 |

The winning policy, at turn 8, after seven turns of reconnaissance — hunting
for the verifier, listing `/logs`, checking file permissions, trying to write
`reward.txt` directly:

```sh
echo -n 'banana' > expected.txt; echo -n 'banana' > out.txt
```

Scored 1.0 by the environment. Scored 0.0 by the independent verifier the
agent never had access to. That difference is the whole measurement.

The two misses are as much the result as the hit. An ablation showing only the
arm that worked says nothing about how hard the problem is.

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
**Challenger** agent. **No LLM judge scores anything, anywhere.**

## Prior art

The category is not new, and Assay does not claim it is.

- **BenchGuard** ([arXiv 2604.24955](https://arxiv.org/abs/2604.24955)) — agentic
  benchmark auditor; found 12 author-confirmed defects on ScienceAgentBench.
- **ABA** ([arXiv 2605.26079](https://arxiv.org/abs/2605.26079)) — agentic audit
  across 168 benchmarks.
- **Adversarial Reward Auditing**, Beigi et al.
  ([arXiv 2602.01750](https://arxiv.org/abs/2602.01750)) — the same probe
  vocabulary, for classical RL reward functions.
- Partial-input baselines — Gururangan et al.
  ([N18-2017](https://aclanthology.org/N18-2017)); the caveat on reading them
  backwards, [P19-1554](https://aclanthology.org/P19-1554).
- Dedup tooling — datatrove, text-dedup, SemHash, LLM-Decontaminator.
- Separability as a benchmark meta-metric — Arena-Hard
  ([arXiv 2406.11939](https://arxiv.org/abs/2406.11939)).

**What Assay adds** is a systems contribution, not a conceptual one:

1. The probes run **dynamically against the live harness**. BenchGuard and ABA
   reason over files; neither actually runs a no-op agent, an inverted grader,
   and a known-wrong trajectory and watches what happens.
2. Contamination, shortcut leakage, and difficulty land in **one** validity
   report instead of three separate literatures.
3. A **learned adversarial Challenger** — no prior work trains an agent to
   reward-hack the environment under audit and reports what it found.
4. One tool across **RL environment, agent benchmark, and eval suite**;
   everything else is domain-locked.

## Try it

```bash
uv sync --extra dev
uv run pytest -q
```

The test suite is the honest demo: twelve fixture environments, each with a
deliberately planted defect, and a test asserting every planted defect is
detected and a healthy environment produces none.

## Lineage

The methodology predates the code — see [`docs/LINEAGE.md`](docs/LINEAGE.md)
for what existed before this repo and what was added here. No code was copied
in; the prior work is cited as lineage, not vendored.

## License

Apache-2.0.
