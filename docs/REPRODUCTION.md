# Reproduction guide

Written for someone starting from a clean machine. Every command below is one
you run; every number the project claims comes from one of them.

## What you need

| | Required for | Notes |
|---|---|---|
| Python ≥ 3.11 + [uv](https://docs.astral.sh/uv/) | everything | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | the Harbor quarter of the corpus | Desktop or Engine; the daemon must be running |
| Network | the inspect_ai and OpenEnv corpora, and the wild sweep | datasets and environments are fetched once and cached |
| [Ollama](https://ollama.com) + a small model | the prompted Challenger and the difficulty probe | `ollama pull qwen3:8b` |
| Claude CLI | the strongest Challenger arm only | optional; the headline needs no model |

**No GPU. No API key for the headline result. No network at audit time** — the
sandbox runs with networking disabled, which is the point.

If a runtime is missing the run still completes on a reduced corpus and says so,
per ecosystem, with the reason — in the console and in `runtime_availability` /
`unavailable` in the results JSON. A corpus that shrank because Docker was not
running would make every arm look better than it is.

## Setup

```bash
git clone <repo> && cd assay
uv sync --extra dev --extra adapters --extra sweep --extra openenv
```

Dependency groups are separate on purpose: `adapters` (inspect_ai), `sweep`
(inspect_evals), `openenv` (pinned to a git revision, because an audit whose
subject moves between runs is not an audit), `train` (GRPO, needs a GPU).

## The headline comparison

```bash
uv run --extra adapters --extra sweep --extra openenv python scripts/full_run.py
uv run --extra adapters python scripts/intervals.py --resamples 10000 --seed 11
```

23 environments across four ecosystems. Roughly three minutes, most of it
container startup. `intervals.py` adds 95% bootstrap CIs and paired differences;
read those, not the point estimates.

Expect: `check_env` — the incumbent linter, reimplementing what
`gymnasium.utils.env_checker` and `stable_baselines3.common.env_checker`
actually assert — scoring identically to `flag_nothing`. Expect also that Assay
does **not** separate from `flag_everything` at this corpus size, and that under
`--profile production-training` it loses to it outright. Both are in the README.

## The two defects in shipping software

Neither needs Assay to verify — that is the point of how they are written.

```bash
# paws: a constant string scores 100%
uv run --extra adapters --extra sweep pytest tests/test_wild_findings.py -q

# textarena_env: reset(seed=...) does nothing
uv run --extra adapters --extra openenv pytest tests/test_openenv_ground_truth.py -q
```

## The Challenger ablation

```bash
uv run --extra adapters python scripts/challenger_ablation.py --models qwen3:8b --claude
```

Scripted misses, `qwen3:8b` misses, `claude-cli` finds the exploit at turn 8
with gap 1.00. The misses are as much the result as the hit.

## Tests

```bash
uv run --extra adapters --extra sweep --extra openenv pytest -q
```

Container tests skip cleanly without Docker; model tests skip without Ollama.
Neither silently passes.

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

## Auditing a single environment

```bash
uv run --extra adapters --extra sweep --extra openenv assay list
uv run --extra adapters assay audit inspect/always-correct
uv run --extra adapters assay audit harbor/self-graded --card card.html
uv run --extra adapters assay reap --dry-run    # leftover sandbox containers
```

Exit code is 0 only for `VALID`. `UNVERIFIED` — some probe could not run —
exits nonzero like any other non-clean verdict. No defects found is not the same
as no defects.

## What is not automated, and why

- **ScienceAgentBench gold programs** sit behind a password-protected archive
  requiring a browser session. See `docs/SCIENCEAGENTBENCH.md` for the manual
  step and the exact drop path. Upstream asks that the unzipped files not be
  redistributed, so nothing from it enters any published artifact.
- **The GRPO-trained Challenger** needs a GPU. It is deliberately ablatable: the
  scripted Challenger works without it and nothing in this guide requires it.

## Costs

Everything above is free apart from optional model calls. Container startup
dominates at roughly four seconds each, which is why the sandbox holds one
container open per suite rather than starting one per command.
