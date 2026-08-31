# Submission — micro1 Agentic Workflows Hackathon

**Assay** — an agentic auditor for RL environments and eval suites.

Labs and vendors buy RL environments and eval suites as products, and nothing checks whether
they measure what they claim. Point Assay at one: it runs nine probe families, one of them an
agent that tries to score well without doing the job, and returns an Environment Card — a
verdict tied to evidence, plus a nonzero exit code that can block a training run.

The contribution is the error bars. This does not claim to find more defects than the field;
it claims that a finding is not a result until you know what it is worth.

---

## The four deliverables

| # | Deliverable | Where |
|---|---|---|
| 01 | Solution code and Improvement Changelog | this repository · [`docs/CHANGELOG.md`](docs/CHANGELOG.md) |
| 02 | Reproduction guide | [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) |
| 03 | Solution video, 4:36 | [`assay-corpus/video/assay.mp4`](https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4) · pipeline in [`video/`](video/) |
| 04 | Agent trajectories | [`results/trajectories/`](results/trajectories/) · [`INDEX.md`](results/trajectories/INDEX.md) |

Published artifacts: [collection](https://huggingface.co/collections/caiotheodoro/assay-auditing-rl-environments-with-error-bars-6a946953e05a8669da74ee65)
· [code](https://github.com/caiotheodoro/assay)
· [corpus and cards](https://huggingface.co/datasets/caiotheodoro/assay-corpus)
· [GRPO Challenger — a negative result](https://huggingface.co/caiotheodoro/assay-challenger-grpo)

---

## The main result

28 environments, 10,000 resamples, seed 11,
resampled over environments.

| arm | expected loss | 95% CI |
|---|---|---|
| **assay** | 43 | [0, 125] |
| flag everything | 394 | [375, 411] |
| `check_env` (the incumbent) | 3216 | [2104, 4448] |

The comparison that decides it is not the incumbent — it is flagging everything, which catches
every defect by construction. **351 saved, 95% CI
[263, 404], separated.**
`production-training` does not separate and is shown crossing zero rather than omitted.

Every figure above is read from `results/intervals.json` by the script that generates this
file, not transcribed. Reproduce with
`uv run --extra adapters --extra openenv python scripts/full_run.py`, then
`scripts/intervals.py --resamples 10000 --seed 11`.

## The main failure mode

An auditing tool is not exempt from the thing it audits. The same probes were pointed at this
repository and **twelve of its published claims broke** — recorded unedited in
[`docs/RED-TEAM.md`](docs/RED-TEAM.md). The external measurement against τ²-bench came out at
chance (p = 0.486) and is published as such.

**One live instance, disclosed rather than hidden.** The corpus grew to 28
environments after the video's narration was recorded. The video's figures are data-bound and
show the current numbers on screen; the recorded voice still speaks the previous ones
(`assay` at 40 against 43, the floor at 314 against
394). The binding updated everything it controls and could not
reach recorded speech. It is the exact failure this project exists to catch, found by running
the check rather than by reading the file, and left in the open.

## Hot take

Every probe here is a deterministic program. The only model in the system is the attacker —
and at an agentic-workflows hackathon that is a real limitation, not a boast: the headline is
produced with the agent switched off. The agent earned its place by finding the exploit first;
the script now finds it in two seconds because the discovery was written down.

---

## Before you run it

- The minimal install is honest about what it skips: `uv sync --extra dev && uv run pytest -q`
  gives **430 passed, 56 skipped, 0 failed**. The full optional set collects 594.
- The whole result rests on one constant nothing derives: a missed critical defect priced at
  120 engineer-hours. The ranking only flips at
  1173 — 9.78× larger.
- There is no hosted demo. `space/app.py` is finished and gated, but Hugging Face returns
  HTTP 402 for a Gradio Space on the free tier, so it runs locally instead. A decision,
  documented rather than hidden.
