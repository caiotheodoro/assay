# Reproduction guide

Written for someone starting from a clean machine. Every command below is one
you run; every number the project claims comes from one of them.

Every timing, download size and disk figure in this guide was measured, not
estimated, by cloning the repository into an empty directory and running the
commands in order against a cold `uv` cache and a cold Hugging Face cache. The
machine was an Apple M5, 10 cores, 16 GB, macOS 26.5.2, `uv` 0.11.32, Docker
Engine 29.2.1. Timings on a slower link or a busier machine will be larger;
the ones here are what a quiet laptop actually did, and where the same command
was measured twice under load both numbers are given.

## What you need

| | Required for | Notes |
|---|---|---|
| Python ≥ 3.11 + [uv](https://docs.astral.sh/uv/) | everything | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | the Harbor quarter of the corpus | Desktop or Engine; the daemon must be running |
| Network | installing, and the wild sweep | one 793 MB install, then 1.1 GB of datasets only if you run the sweep |
| [Ollama](https://ollama.com) + a small model | the prompted Challenger only | `ollama pull qwen3:8b` |
| Claude CLI | the strongest Challenger arm only | optional; the headline needs no model |

**No GPU. No API key for the headline result.** Resolution was checked under
both 3.12 and 3.13; the lockfile is committed, so the versions the two defect
write-ups were found against are the versions you get.

Two things the guide used to claim that are not quite true, stated here rather
than buried:

- **The audit itself makes one network call.** Auditing
  `openenv/textarena-wordle` asks NLTK for its `words` corpus (3.1 MB, into
  `$HOME/nltk_data`, once). Blocking it changes nothing — the run completes and
  every headline number is identical — but the old "no network at audit time"
  was too strong. The *sandbox* still runs with networking disabled, which is
  the part that matters.
- **No test needs Ollama.** With `brew services stop ollama` the suite still
  passes with nothing skipped. (The count quoted here was 275 collected, measured
  before the suite grew to 593; the *claim* — that nothing is
  model-gated — was re-checked, the number was not.) The model path is exercised by
  `scripts/challenger_ablation.py`, not by pytest, and that is where you see it
  degrade.

If a runtime is missing the run still completes on a reduced corpus and says so,
per ecosystem, with the reason — in the console and in `runtime_availability` /
`unavailable` in the results JSON. A corpus that shrank because Docker was not
running would make every arm look better than it is. Verified by stopping the
daemon; see [Degradation](#degradation-checked-by-turning-things-off).

## Setup

```bash
git clone https://github.com/caiotheodoro/assay.git && cd assay
uv sync --extra dev --extra adapters --extra sweep --extra openenv
```

> The tree is public at [https://github.com/caiotheodoro/assay](https://github.com/caiotheodoro/assay). Every number below was
> measured on a local checkout of it.

**Measured, cold cache: 52 s, 759 MB downloaded, 566 MB venv, 351 packages.**
Re-running against a warm cache is 2 s. `uv.lock` is committed, so this installs
from the lockfile rather than re-resolving — the same versions every time,
`inspect-ai` 0.3.260, `inspect_evals` 0.18.0, `textarena` 0.7.4, `openenv`
0.3.1. Without the lockfile the same command took 79 s and resolved 353
packages, which is how the missing pin was found.

Dependency groups are separate on purpose: `adapters` (inspect_ai), `sweep`
(inspect_evals), `openenv` (also pinned to a git revision, because the two
environments are not on PyPI at all), `train` (GRPO, needs a GPU).

The smaller install in the README works too, and says what it is missing:

```bash
uv sync --extra dev && uv run pytest -q
```

**Measured: 200 collected, 33 skipped, 0 failed, exit 0, 38 s** — measured
against the pre-doubling suite; treat the count as stale and the skip *reasons*
as current. The skips
name the `openenv` extra and the revision it pins, or `inspect_ai`. Two whole
suites (`test_sweep`, `test_wild_findings`) are not collected at all, because
their `importorskip` is at module scope.

## The headline comparison

```bash
ASSAY_APPROVE_ALL="reproduction run" uv run --extra adapters --extra openenv python scripts/full_run.py
uv run --extra adapters python scripts/intervals.py --resamples 10000 --seed 11
```

**Measured: 15–39 s and about 1 s** on an idle machine, 33–44 s for
`full_run.py` with other work contending for the Docker daemon. Most of it is
container startup. `--extra sweep` is not needed here — it is for the wild sweep
below — and leaving it out gives a byte-identical `results/full_run.json`,
checked by diffing the two.

Re-running these two commands on a clean clone reproduces **every deterministic
arm** of the committed `results/*.json` with no diff at all — verified from a fresh
tree: all six of `assay`, `check_env`, `flag_everything`, `flag_nothing`,
`always_modal_defect` and `stratified_random` came back identical. The two LLM
baseline arms, `agent_with_tools` and `direct_prompt`, are **not** regenerated by the
bare command: they need `--llm-arms qwen3:8b` and a live Ollama daemon, so a plain
re-run writes a `full_run.json` with those two arms absent rather than an identical
file. That is the check that caught them being
three environments out of date.

26 environments across five ecosystems: 12 fixture, 5 harbor, 5 inspect, 2
openenv, 2 inspect_evals, **50 planted defects**. `intervals.py` adds 95%
bootstrap CIs and paired differences; read those, not the point estimates.

Expect exactly this, under `research-run`:

| arm | expected loss | recall | precision |
|---|---|---|---|
| assay | 40.0 | 0.980 | 1.000 |
| flag_everything | 314.0 | 1.000 | 0.137 |
| stratified_random | 1789.0 | 0.360 | 0.383 |
| always_modal_defect | 1888.0 | 0.200 | 0.385 |
| check_env | 3056.0 | 0.040 | 1.000 |
| flag_nothing | 3072.0 | 0.000 | 0.000 |

Exactly **one** environment is missed corpus-wide — `inspect_evals/boolq`,
`SHORTCUT_LEAK` — and there are zero false positives. If you see two Harbor
misses instead, you are on a revision before the taxonomy-derived policies
landed; see `docs/changelog/79-taxonomy-policies.md`.

`check_env` — a model of what `gymnasium.utils.env_checker` and
`stable_baselines3.common.env_checker` actually assert — detects 2 of 50, both
`NONDETERMINISM`, which is the only class it can return. It does not score
identically to `flag_nothing`; an earlier revision of this guide said so and
was wrong, because the model omitted the determinism check that gymnasium
1.3.0 does perform. One of its two hits is `fixture/flaky`, planted here.

The gap to `flag_nothing` is 16.0 of 3072.0. Whether that counts as
"distinguishable" is not settled by the interval the README quotes: `check_env`
emits no false positives and detects a subset of what is planted, so the paired
difference is >= 0 by construction and the CI can never exclude zero from
above. On a one-sided reading it is p ~ 0.13 -- the chance neither
`NONDETERMINISM` environment is drawn, (24/26)^26.

Expect also that Assay **does** separate from `flag_everything` — paired
difference **274.0, 95% CI [186, 326]** — and that it now wins all four cost
profiles, separating on three. Under `--profile production-training` it wins
240.0 to 628.0 but the interval crosses zero, so that one is a lead rather than
a result. An earlier revision of this guide told you to expect the opposite on
both counts; it was correct when written, and closing the two Harbor misses is
what changed it.

## The agent trajectories

```bash
uv run --extra adapters python scripts/export_trajectories.py --model qwen3:8b
```

Writes `results/trajectories/` — eight runs, JSON and markdown, plus an index.
Five are live on this machine (Docker plus `ollama pull qwen3:8b`); two replay
committed Claude CLI ablation runs, so they reproduce with no CLI installed;
one is the sandbox approval gate.

Arms whose runtime is missing skip with a reason and are listed in `INDEX.md`
rather than dropped, in the same way as every other comparison here. The
committed artefacts are asserted by `tests/test_trajectory_export.py`, which
checks the files on disk rather than only the code that writes them.

## The two defects in shipping software

Neither needs Assay to verify — that is the point of how they are written.
Neither touches the Hugging Face Hub either: both run offline against the
installed packages.

```bash
# paws: a constant string scores 100%
uv run --extra adapters --extra sweep pytest tests/test_wild_findings.py -q

# textarena_env: reset(seed=...) does nothing
uv run --extra adapters --extra openenv pytest tests/test_openenv_ground_truth.py -q
```

**Measured: 26 passed in 6 s, and 7 passed in 3 s.**

## The wild sweep

This is what `--extra sweep` is installed for, and the only step in this guide
that costs real download.

```bash
# one task, the one the README write-up is about
uv run --extra adapters --extra sweep python scripts/wild_sweep.py --only paws

# the whole registry
uv run --extra adapters --extra sweep python scripts/wild_sweep.py
```

**Measured, cold Hugging Face cache:**

| | wall clock | downloaded |
|---|---|---|
| `--only paws` | 10–22 s | 26 MB |
| full sweep | 415 s | 1.1 GB |

The full sweep partitions the registry rather than reporting only what it
found: 246 tasks registered, 188 statically excluded, 58 attempted, of which 34
swept and 24 excluded at runtime with a reason each — missing optional
dependency, gated dataset, multi-target samples the adapter would score wrongly,
an unreplayable solver chain. 14 candidate findings, all `REWARD_HACKABLE`, all
on `paws`.

## Tests

The snapshot fetch is a real prerequisite, so it goes first. `.tau2_cache/` is not
committed, and `uv sync` will not put it there:

```bash
uv run --extra tau2 python scripts/tau2_fetch.py
uv run --extra adapters --extra sweep --extra openenv --extra tau2 pytest -q
```

**Measured: 594 passed, 0 skipped, 0 failed, exit 0, 82 s** with Docker and
Ollama up. An earlier revision of this guide claimed 275 collected; the suite has
roughly doubled since and that number was never re-measured.

**`--extra tau2` is load-bearing on the test line too**, and this guide previously
omitted it there. Without the snapshots `tests/test_tau2_adapter.py` skips (18 skips,
measured); without the extra it *fails*, on `No module named 'loguru'`. Both were
verified from a fresh tree with no `.venv`: the command above gives 594 passed, 0
failed, exit 0 in 87 s, and dropping `--extra tau2` from it gives 7 failures.

So "nothing skips when everything is installed and running" is true only once the
snapshots are on disk and the extra is on the command.

Three suites carry more weight than the rest:

- `tests/test_probes_fire.py` — every planted defect detected **exactly**, not
  merely detected. A recall-only assertion passes for a probe that flags
  everything.
- `tests/test_corpus_ground_truth.py`, `tests/test_harbor_ground_truth.py`,
  `tests/test_openenv_ground_truth.py` — every corpus label established by
  running the environment's own scorer or scripts, never by asking Assay what
  it found. A label confirmed by the tool it scores is not a label.
- `tests/test_exploit_gap_replay.py` — a multi-step exploit must be replayed in
  full. This existed because it was not, and a real finding came back as zero.

## Degradation, checked by turning things off

Not asserted. Each row below was produced by actually stopping the thing —
but the pytest counts in it were measured before the suite doubled, and carry
the same stale 275 as above. The failure *modes* are what this table is for and
those were observed; treat the collected/skipped counts as needing a re-run.

| What was stopped | How | Result |
|---|---|---|
| Docker daemon | `docker desktop stop` | pytest: **275 collected, 32 skipped, 0 failed, exit 0, 17 s** — count stale (pre-doubling); every skip reads `docker daemon not available`, which is the row's actual claim |
| Docker daemon | as above | `full_run.py`: **corpus 21 / 38 defects**, `WARNING: harbor unavailable ... docker daemon not running`, `unavailable: {harbor: ...}` in the JSON, exit 0 |
| Docker daemon | as above | `assay reap --dry-run`: prints `cannot check: docker is not installed or the daemon is not running` and exits 1, rather than reporting a clean nothing |
| `docker` binary | removed from `PATH` | identical skips, exit 0 — the other branch of the same check |
| Ollama | `brew services stop ollama` | pytest: **275 collected, 0 skipped, 0 failed, 53 s** — count stale (pre-doubling); the claim that nothing in the suite is model-gated holds |
| Ollama | as above | `challenger_ablation.py --models qwen3:8b`: `SKIPPING qwen3:8b: ollama daemon unreachable at http://localhost:11434: <urlopen error [Errno 61] Connection refused>`, scripted arm still runs, exit 0 |

The Docker row used to be the one worth reading twice, and it is worth reading
for a different reason now. It once dropped Assay's expected loss from 240.0 to
**0.0** — a perfect score bought by deleting the five environments it did worst
on. Measured today: **corpus 21 / 38 defects, expected loss 40.0, unchanged.**
The degradation no longer flatters, because the one environment Assay misses is
`inspect_evals/boolq` and Docker has nothing to do with it.

That is a better state and it does not retire the warning. A corpus that shrinks
for an environmental reason can still make an arm look better than it is; it
happens not to here, this week, with these misses. Check `corpus:` before
believing any number printed under it.

## Auditing a single environment

```bash
uv run --extra adapters --extra sweep --extra openenv assay list
uv run --extra adapters assay audit inspect/always-correct        # asks before it runs the scorer
uv run --extra adapters assay audit harbor/self-graded --card card.html   # asks before it starts a container
uv run --extra adapters assay audit harbor/self-graded --yes              # or say yes up front, unattended
uv run --extra adapters assay reap --dry-run    # leftover sandbox containers
```

Exit code is 0 only for `VALID`. `UNVERIFIED` — some probe could not run —
exits nonzero like any other non-clean verdict. In practice **every environment
in the shipped corpus exits nonzero**, the healthy ones included: with no
solve-rate estimate and no machine-readable scorer assertions, four probes come
back `NOT_APPLICABLE` and the verdict is `UNVERIFIED`. Do not wrap these in
`set -e` expecting a clean run. No defects found is not the same as no defects.

**Exit 3 is different and it is not a verdict.** `assay audit` executes
third-party code and asks first, showing the image, the command, every mount,
the network state and every resource cap before it does. With no terminal to
ask at and no explicit standing approval it refuses, prints how to grant one,
and exits **3** with nothing run — distinct from 1 so a script can tell "the
environment is defective" from "the gate held". The escapes are `--yes` on the
command line and `ASSAY_APPROVE_ALL="<reason>"` in the environment, the latter
for processes you cannot pass a flag to, such as `scripts/full_run.py` and CI.
Both are recorded on the Environment Card as an unattended run, carrying the
reason. Background in `docs/changelog/98-approval-gate.md`.

`assay reap --dry-run` exits **1** when there is something to remove and 0 when
there is not, so it can gate a CI step.

Containers are cleaned up by the run that made them. **Measured:** after
`scripts/full_run.py` exits, and after `pytest` exits, zero containers carry
that run's `assay-pid` label.

That claim used to name `full_run.py` only, and was **false of the test
suite**, which is where most container-creating code actually runs. It was
contradicted for thirty-three hours by `docker ps`: fourteen orphans, every
creating pid dead. The cause was `SandboxSession.stop()` waiting 60 s on
`docker rm -f` with `TimeoutExpired` uncaught, so teardown could hang and then
raise out of a fixture finaliser, and `EnvPool.close()` aborting its loop on
the first exception. Both fixed, and the claim is now **enforced by
`tests/conftest.py`** rather than asserted: a session fixture removes and warns
about any orphan the run itself created. Containers that existed before the run
are reported separately and deliberately not touched — deleting a container a
live audit still owns would be worse than leaking one. `reap` is for the case where a run was killed: killing a process
mid-session leaves its container behind, `assay reap --dry-run` lists it as
`ORPHANED`, `assay reap` removes exactly it, and containers belonging to other
live pids are left alone.

## The Challenger ablation

```bash
uv run --extra adapters python scripts/challenger_ablation.py --models qwen3:8b --claude
```

**Measured, from `results/challenger_ablation.json`:** scripted misses
(4 attempts, 2.2 s), `qwen3:8b` misses (10 attempts, 97.0 s), `claude-cli`
**finds the exploit with gap 1.00** (10 attempts, 261.7 s). The misses are as
much the result as the hit.

An earlier revision of this guide gave 840 s end to end, 6 s and 405 s, and
"attempt 8" — none of which appear in any committed run. These numbers are read
back out of the artifact; run the command and compare against the file, not
against this paragraph.

This arm is model-gated and non-deterministic. A rerun will not reproduce
261.7 s and need not reproduce `found` at all; what should reproduce is the
shape — the scripted arm loses, and a prompted agent that finds the exploit
does it by overwriting `expected.txt` rather than by answering correctly.

Arms that cannot run are printed as skipped with a reason and recorded in the
results JSON. An arm missing from a comparison is a result about the run, not
about the method — and a challenger that could not speak is reported as
`NOT_APPLICABLE`, never as an arm that found nothing. That last sentence was
not true when this guide was first written; see
[`docs/changelog/85-reproduction.md`](changelog/85-reproduction.md) for what a
silent zero looked like and what still is not covered.

`--grpo-base` is the control worth having: the same one-shot prompt on an
*untrained* model. If that arm finds the exploit too, the prompt format found
it and the training did not.

```bash
uv run --extra adapters python scripts/challenger_ablation.py --task self-graded \
    --grpo-adapter checkpoints/grpo/final --grpo-base qwen3:1.7b
```

Note that Ollama load time dominates a cold arm: the same `qwen3:8b` arm takes
74 s with the model resident and around 190 s when it has to be loaded first.

## What is not automated, and why

- **ScienceAgentBench gold programs** sit behind a password-protected archive
  requiring a browser session. See `docs/SCIENCEAGENTBENCH.md` for the manual
  step and the exact drop path. Upstream asks that the unzipped files not be
  redistributed, so nothing from it enters any published artifact.
- **The GRPO-trained Challenger** needs a GPU. It is deliberately ablatable:
  the scripted Challenger works without it and nothing else here requires it.

## The trained Challenger (optional, and the only part that wants a GPU)

Everything above runs without one. This section is the exception, and it is
built so that skipping it costs you an arm in one table and nothing else.

**Without a GPU** you can still check the whole reward, which is the part that
decides whether training would mean anything:

```bash
uv run --extra adapters pytest tests/test_grpo_reward.py tests/test_grpo_challenger.py -q
uv run --extra adapters python scripts/reward_landscape.py --holdout harbor/self-graded
```

The first proves the exploit-gap reward on the fixtures — an honest solve pays
zero, a planted hack pays the full gap, an unparseable completion pays less
than any policy that ran. Four of those tests replay real Docker containers.

The second prints what the reward can pay per environment before any model
exists. Read `prompts_with_signal` and `fraction_flat`: GRPO learns from
variance within a rollout group, so an environment where every candidate
policy scores the same contributes exactly zero gradient no matter how long it
is trained on. A corpus that is flat here was never going to teach, and that is
a different finding from an optimiser that failed. It is what predicted the
negative result before any GPU was bought: 39 prompts, 19 with signal, 51.3%
flat.

**With a GPU**, or with AWS credentials:

```bash
# wiring gate: CPU, tiny model, two steps, no GPU and no Docker needed
uv run --extra train --extra adapters python -m assay.train.run --smoke

# the real run, on one A10G
uv run --extra train --extra adapters python -m assay.train.run \
    --model Qwen/Qwen3-1.7B --steps 300 --group-size 8 \
    --only fixture harbor --holdout harbor/self-graded

# or launch it on a spot g5.xlarge; DRY=1 prices it and launches nothing
DRY=1 ./cloud/aws_spot_train.sh
```

Read [`docs/changelog/40-grpo-challenger.md`](changelog/40-grpo-challenger.md)
first, because both runs failed to learn and the reason is worth knowing before
spending the money. `harbor/self-graded` is held out of training on purpose. It
is the ablation target, and training on it and then reporting that the trained
Challenger cracks it would be train-on-test.

## Costs

Everything above is free apart from optional model calls. Measured, in order:

| Step | Wall clock | Network | Disk |
|---|---|---|---|
| `uv sync` with all four extras | 52 s | 759 MB | 566 MB venv |
| `scripts/full_run.py` | 15–39 s | none | — |
| `scripts/intervals.py` | < 1 s | none | — |
| the two defect suites | 9 s | none | — |
| `pytest`, all extras | 49–60 s | none | — |
| `wild_sweep.py --only paws` | 10–22 s | 26 MB | 26 MB |
| `wild_sweep.py`, full registry | 415 s | 1.1 GB | 1.1 GB |
| `challenger_ablation.py --models qwen3:8b --claude` | 840 s | model-dependent | — |

Roughly **3 minutes and 760 MB** to install and reproduce the headline, the two
defects and the whole test suite. Every figure in this table was re-measured
against a second clean clone of this branch, cold cache, after all the fixes
below landed; `results/full_run.json` and `results/intervals.json` came back
byte-identical to the committed ones. Add 7 minutes and 1.1 GB for the full wild
sweep, and 14 minutes for the Challenger ablation.

Container startup dominates the audit at roughly four seconds each, which is why
the sandbox holds one container open per suite rather than starting one per
command.

The one exception to "free" is `cloud/aws_spot_train.sh`. A spot `g5.xlarge` in
`us-east-1` was $0.46/hr at the time of writing and a 300-step run is roughly
an hour including model download — about **$0.50**. Nothing else in this guide
needs it, and the trained adapter is an optional artifact rather than a
dependency. That price was not re-checked for this pass and is the only
unverified number left in this file.
