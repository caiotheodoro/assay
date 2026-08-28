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

## Costs

Everything above is free. Compute is one laptop; the models are local. The only
resource worth noting is time: container startup dominates, at roughly four
seconds per container on Docker Desktop, which is why the sandbox holds one
container open per suite instead of starting one per command.
