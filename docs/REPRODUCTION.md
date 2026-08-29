# Reproduction guide

Written for someone starting from a clean machine. Every command below is one
you run; every number the project claims comes from one of them.

## What you need

| | Required for | Notes |
|---|---|---|
| Python ≥ 3.11 + [uv](https://docs.astral.sh/uv/) | everything | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | the Harbor half of the corpus | Desktop or Engine; the daemon must be running |
| [Ollama](https://ollama.com) + a small model | the prompted Challenger and the difficulty probe | `ollama pull qwen3:1.7b` |

**No GPU. No API key. No network at audit time** — the sandbox runs with
networking disabled, which is the point.

If Docker or Ollama is missing, the run still completes on a reduced corpus and
says so explicitly in its output and in `runtime_availability` in the results
JSON. A shrunken corpus must never be mistaken for a clean one.

## Setup

```bash
git clone <repo> && cd assay
uv sync --extra dev --extra adapters
```

## The headline comparison

```bash
uv run --extra adapters python scripts/full_run.py
```

Writes `results/full_run.json` and prints a table. Roughly two minutes with
Docker running, most of it container startup.

Expected shape of the result: `check_env` — the incumbent structural linter,
reimplementing what `gymnasium.utils.env_checker` and
`stable_baselines3.common.env_checker` actually assert — scores identically to
`flag_nothing`. Assay scores well below the trivial floor, with a small number
of honest misses listed per environment.

Select a different cost model with `--profile`:

```bash
uv run --extra adapters python scripts/full_run.py --profile benchmark-publication
```

Available: `research-run`, `production-training`, `benchmark-publication`, and
`flat`. The flat profile is not a scenario — it is the theorem test, and it is
wired as a test rather than reported as a result.

## Tests

```bash
uv run --extra adapters pytest -q
```

Container-backed tests skip cleanly when Docker is absent; model-backed tests
skip when Ollama is absent. Neither silently passes.

Two suites carry more weight than the rest:

- `tests/test_probes_fire.py` — every planted defect is detected **exactly**,
  not merely detected. A recall-only assertion would pass for a probe that
  flags everything.
- `tests/test_corpus_ground_truth.py` and `tests/test_harbor_ground_truth.py` —
  every corpus label is established by running the environment's own scorer or
  scripts, never by asking Assay what it found. A label confirmed by the tool
  it is used to score is not a label.

## Auditing a single environment

```bash
uv run --extra adapters assay list
uv run --extra adapters assay audit inspect/always-correct
uv run --extra adapters assay audit harbor/self-graded --json
```

Exit code is 0 only for `VALID`. `UNVERIFIED` — meaning some probe could not
run — exits nonzero like any other non-clean verdict. No defects found is not
the same as no defects.

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
a different finding from an optimiser that failed.

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

`harbor/self-graded` is held out of training on purpose. It is the ablation
target, and training on it and then reporting that the trained Challenger
cracks it would be train-on-test.

## The Challenger ablation

```bash
uv run --extra adapters python scripts/challenger_ablation.py --task self-graded
uv run --extra adapters python scripts/challenger_ablation.py --task self-graded \
    --grpo-adapter checkpoints/grpo/final --grpo-base qwen3:1.7b
```

Arms that cannot run are printed as skipped with a reason and recorded in the
results JSON. An arm missing from a comparison is a result about the run, not
about the method — and a challenger that could not speak is reported as
`NOT_APPLICABLE`, never as an arm that found nothing.

`--grpo-base` is the control worth having: the same one-shot prompt on an
*untrained* model. If that arm finds the exploit too, the prompt format found
it and the training did not.

## Costs

Everything above is free except the training run. Compute is one laptop; the
models are local. The only resource worth noting is time: container startup
dominates, at roughly four seconds per container on Docker Desktop, which is
why the sandbox holds one container open per suite instead of starting one per
command.

The exception is `cloud/aws_spot_train.sh`. A spot `g5.xlarge` in `us-east-1`
was $0.46/hr at the time of writing and a 300-step run is roughly an hour
including model download, so about **$0.50**. Nothing else in this guide needs
it, and the trained adapter is an optional artifact rather than a dependency.
