# Assay — orientation for agents and reviewers

**An agentic auditor for RL environments and eval suites.** Point it at an
environment; it runs a battery of probes and emits an **Environment Card** — a
validity verdict where every claim is tied to a probe result, plus machine-readable
JSON and a nonzero exit code that blocks a training run.

`README.md` is long (~970 lines) because it carries the full argument and its
evidence. This file is the short path. **`docs/FOR_AGENTS.md` is the next stop** —
the same claims with a citation on each.

## The claim, in one line

A finding is not a result until you know what it is worth. Assay does **not** claim
to find more defects than the field; it claims to price them.

## The headline, and the comparison that decides it

| Arm | Expected loss (`research-run`) |
|---|---|
| `flag_nothing` | 3072.0 |
| `check_env` (the incumbent) | 3056.0 |
| `flag_everything` | 314.0 |
| **Assay** | **40.0** |

Assay saves **274.0 against `flag_everything`, 95% CI [186, 326], separated.**
Wins 4 of 4 cost profiles, separates on 3.

**Read the arms in the right order.** `check_env` saves 16.0 against `flag_nothing`'s 3072.0 —
0.52% of it, with a 95% interval of [0, 40] that includes zero, so beating the incumbent proves almost nothing. The arm that had to
be beaten is `flag_everything`, which catches every defect by construction — and for
most of this project's life, Assay did not beat it. Every headline rests on that
separation.

Intervals resample **environments** (n=26), not defects — `results/intervals.json`
carries a `"why"` field saying so.

## What is deliberately published as a weakness

- One environment is still missed: `inspect_evals/boolq`, structurally — no train
  split, so the contamination probe has nothing to compare.
- Four of BenchJack's eight flaw classes are uncovered (`docs/COVERAGE.md`, written
  in *their* vocabulary, not ours).
- Only **4 of 26** corpus environments are genuinely third-party. The split is
  published because it is unflattering.
- The GRPO-trained Challenger **does not beat the scripted floor** — a negative
  result, published as one.
- There is no hosted demo: Hugging Face returns HTTP 402 for a Gradio Space on the
  free tier. `space/app.py` runs locally. The solution video is hosted instead:
  [4:36, h264+aac](https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4).
- **12 of this repository's own published claims broke** when its instruments were
  turned on itself, and 3 real behavioural bugs fell out. Unedited in
  `docs/RED-TEAM.md`; the reusable protocol is `docs/METHOD.md`.

## Where the agent is

10 of the 11 probe families are deterministic programs; only the Challenger is an
agent. That is the design. The agent found the reward-hack exploit class
(`claude-cli`, turn 8, 262s) where a scripted attacker and `qwen3:8b` both missed;
that class was then written down as a policy, and the scripted Challenger now finds
the same gap in ~2s. Compiling a discovery into a cheap deterministic check is what
the workflow is for. No LLM judges any verdict anywhere in Assay.

## Verify in 60 seconds (no GPU, no API key)

```bash
uv sync --extra dev && uv run --extra tau2 python scripts/tau2_fetch.py   # snapshots; not committed
uv run --extra adapters --extra sweep --extra openenv --extra tau2 pytest -q   # 650 passed, 0 skipped
ASSAY_APPROVE_ALL="reproduction run" uv run --extra adapters --extra openenv python scripts/full_run.py   # 22s; compare results/full_run.json
uv run --extra adapters assay audit harbor/self-graded --yes --card /tmp/c.html; head -40 /tmp/c.html   # --yes because this runs unattended; without it you are asked
```

`--extra tau2` and the fetch are both load-bearing: `.tau2_cache/` is not committed, and
without the extra `tests/test_tau2_adapter.py` fails on a missing `loguru` rather than
skipping. Verified from a fresh tree with no `.venv`: **650 passed, 0 failed, exit 0** —
123 s for the whole cold path, `uv sync` and the snapshot fetch included.

The last command **exits 1 on purpose** — `harbor/self-graded` is reward-hackable, and a
nonzero exit is what blocks a training run. That is why it is separated by `;` and not
`&&`: chained with `&&`, the card never prints.

## Map

| | |
|---|---|
| Claims with a citation on each | `docs/FOR_AGENTS.md` |
| The method, written to be reused | `docs/METHOD.md` |
| What Assay cannot see, in someone else's vocabulary | `docs/COVERAGE.md` |
| Reproduce every number end to end | `docs/REPRODUCTION.md` |
| This repo's own claims, attacked | `docs/RED-TEAM.md` |
| What changed, slice by slice, with evidence | `docs/CHANGELOG.md` |
| An agent run, readable without executing anything | `results/trajectories/INDEX.md` |
| A sample Environment Card | `results/example-card.md` |
| Architecture and its known seams | `docs/ARCHITECTURE.md` |
| Scored against the hackathon rubric, by us | `docs/RUBRIC.md` |
| What existed before the competition | `docs/LINEAGE.md` |
| Arithmetic committed before the corpus grew | `docs/PRE-REGISTRATION.md` |
| Two unfiled upstream disclosures | `docs/disclosures/` |

Apache-2.0. Code: `github.com/caiotheodoro/assay`.
