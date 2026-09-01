# Assay — orientation for agents and reviewers

**An agentic auditor for RL environments and eval suites.** Point it at an
environment; it runs a battery of probes and emits an **Environment Card** — a
validity verdict where every claim is tied to a probe result, plus machine-readable
JSON and a nonzero exit code that blocks a training run.

`README.md` is ~580 lines: the argument and the headline numbers, with the detail
moved into `docs/RESULTS.md` and every retraction collected in
`docs/RETRACTIONS.md`. This file is the shorter path. **`docs/FOR_AGENTS.md` is the
next stop** — the same claims with a citation on each.

## The claim, in one line

A finding is not a result until you know what it is worth. Assay does **not** claim
to find more defects than the field; it claims to price them.

## The headline, and the comparison that decides it

| Arm | Expected loss (`research-run`) |
|---|---|
| `flag_nothing` | 3232.0 |
| `check_env` (the incumbent) | 3216.0 |
| `agent_with_tools` | 2746.0 |
| `stratified_random` | 2838.0 |
| `direct_prompt` | 2343.0 |
| `always_modal_defect` | 2055.0 |
| `flag_everything` | 474.0 |
| **Assay** | **57.0** |
| **`assay+auditor`**, one draw | **44.0** |

Assay saves **417.0 against `flag_everything`, 95% CI [330, 471], separated.**
Wins 4 of 4 cost profiles and separates on all 4.

**Turning the agent on saves 13-14 in six runs of seven, and loses 65 in the
seventh.** `results/gate_reliability.json`: `assay+auditor` returns 43-44 across
seven identical runs and once returns 122.0, because the gate decided
`tau2/airline` had no correct answer and deleted two real planted defects with
the false ones. The paired bootstrap resamples environments and cannot see this;
the deterministic arm returned 57.0 every time. Do not quote the agent row as a
point estimate. Five
environments with no correct answer now sit in the corpus, so the deterministic battery
pays 16 false positives where it used to pay 3, and the semantic gate recovers 13 of
them while leaving the 3 τ² findings standing — the right answer on all 16.

**141.0 of that 417.0 is arithmetic, not detection.** `flag_everything` flags
every class in the taxonomy on every environment, so its loss gets worse whenever the
taxonomy or the corpus grows and no detector is involved: two probe families added two
defect classes (+52), two τ² environments added 28 more free false alarms while costing
Assay 3, and the four environments with no correct answer added 64 more while costing
Assay 13. Against the taxonomy and corpus this was first measured on, the
comparable margin is **274.0**. `docs/PRE-REGISTRATION-TAU2.md` predicted both figures
before the corpus grew.

**Read the arms in the right order.** `check_env` saves 16.0 against `flag_nothing`'s 3232.0 —
0.50% of it, with a 95% interval of [0, 40] that includes zero, so beating the incumbent proves almost nothing. The arm that had to
be beaten is `flag_everything`, which catches every defect by construction — and for
most of this project's life, Assay did not beat it. Every headline rests on that
separation.

Recall is 0.9815 and **precision is 0.9464** — no longer 1.000. Three spurious findings
remain and all three are on the two τ² environments.

Intervals resample **environments** (n=33), not defects — `results/intervals.json`
carries a `"why"` field saying so.

## What is deliberately published as a weakness

- One environment is still missed: `inspect_evals/boolq`, structurally — no train
  split, so the contamination probe has nothing to compare.
- Four of BenchJack's eight flaw classes are uncovered (`docs/COVERAGE.md`, written
  in *their* vocabulary, not ours).
- Only **8 of 33** corpus environments are genuinely third-party, and only **3 of those
  6** carry ground truth this repository did not decide. The split is published because
  it is unflattering.
- The GRPO-trained Challenger **does not beat the scripted floor** — a negative
  result, published as one.
- The hosted demo runs the battery **in the browser**:
  [`caiotheodoro/assay-demo`](https://huggingface.co/spaces/caiotheodoro/assay-demo), a free
  static Space with Pyodide. Hugging Face still returns HTTP 402 for a *Gradio* Space on the
  free tier, so `space/app.py` runs locally only. Also hosted: the solution video,
  [4:36, h264+aac](https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4).
- **12 of this repository's own published claims broke** when its instruments were
  turned on itself, and 3 real behavioural bugs fell out. Unedited in
  `docs/RED-TEAM.md`; the reusable protocol is `docs/METHOD.md`.

## Where the agent is

10 of the 11 probe families are deterministic programs — every family except reward
hackability. That is the design, and there are two agents around them, both opt-in.

The **Challenger** (`--challenger`) found the reward-hack exploit class
(`claude-cli`, turn 8, 262s) where a scripted attacker and `qwen3:8b` both missed;
that class was then written down as a policy, and the scripted Challenger now finds
the same gap in 3.8s (`results/scripted_floor.json`). Compiling a discovery into a cheap deterministic check is what
the workflow is for — and it means the agent is not load-bearing here.

The **Auditor** (`--auditor`) is the case where no script can take over. It withholds
the CRITICAL false positive on `inspect_evals/personality_BFI` — an inventory with no
correct answer, where a format check is the right design. On the 2 environments with no
correct answer it withholds in **6 of 6 runs**, and across the 18 that do have one it
pays **0 false overrides in 54** (`results/semantic_gate.json`, `claude-cli:sonnet`,
20 environments at k=3).
`qwen3:8b` matches it on the positives and pays **6 false overrides in 54**, which is
the column that matters, because a false override hides a real defect.
**No model ever scores a probe.** It can only move a
`verifier_integrity` DEFECT to `NOT_APPLICABLE`, never assert a verdict, and it is
off by default: the headline numbers above are fully deterministic.

## Verify in 60 seconds (no GPU, no API key)

```bash
uv sync --extra dev && uv run --extra tau2 python scripts/tau2_fetch.py   # snapshots; not committed
uv run --extra adapters --extra sweep --extra openenv --extra tau2 --extra space pytest -q   # 814 passed, 0 skipped
ASSAY_APPROVE_ALL="reproduction run" uv run --extra adapters --extra openenv --extra tau2 --extra sweep python scripts/full_run.py --out /tmp/check.json   # 22s; compare results/full_run.json
uv run --extra adapters assay audit harbor/self-graded --yes --card /tmp/c.html; head -40 /tmp/c.html   # --yes because this runs unattended; without it you are asked
```

`--extra tau2` and the fetch are both load-bearing: `.tau2_cache/` is not committed, and
without the extra `tests/test_tau2_adapter.py` fails on a missing `loguru` rather than
skipping. Verified from a fresh tree with no `.venv`: **814 passed, 0 failed, exit 0** —
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
| Two upstream disclosures, both filed | `docs/disclosures/` |

Apache-2.0. Code: `github.com/caiotheodoro/assay`.
