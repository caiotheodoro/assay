# Assay

**An agentic auditor for RL environments and eval suites.**

Point Assay at an environment. It runs a battery of probes and emits a signed
**Environment Card**: a validity verdict where every claim is tied to a probe
result, plus machine-readable JSON and a nonzero exit code that blocks a
training run.

> Status: early. Core, all nine probe families, and the inspect_ai and Harbor
> adapters are implemented and tested. The prompted and GRPO-trained
> Challengers are built; the trained one **does not beat the scripted floor**,
> and the two runs behind that statement are written up with their numbers in
> [`docs/changelog/40-grpo-challenger.md`](docs/changelog/40-grpo-challenger.md).
> The OpenEnv adapter and the wild sweep are not built yet.

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

## First measured result

21 environments, 44 planted defects, `research-run` cost profile. Needs Docker
for the Harbor tasks. No GPU, no API key, no network —
`uv run --extra adapters python scripts/full_run.py`.

| arm | expected loss | normalized | recall | precision | misses |
|---|---|---|---|---|---|
| assay | **120.0** | 0.480 | 0.977 | 1.000 | 1 |
| flag_everything | 250.0 | 1.000 | 1.000 | 0.150 | 0 |
| **check_env** (incumbent) | **2704.0** | 10.816 | **0.000** | 0.000 | 44 |
| flag_nothing | 2704.0 | 10.816 | 0.000 | 0.000 | 44 |

The structural linter scores **identically to flagging nothing**. It is not a
weak detector of these defects; it is not a detector of them at all.

Assay's one miss is `harbor/self-graded`, where the verifier reads its
expectation from a file the agent can overwrite. The exploit is real — it is
exhibited directly in `tests/test_harbor_ground_truth.py` — and the scripted
Challenger does not find it. That miss is the reason the corpus discriminates
at all, and closing it is what the prompted and trained Challengers are for.

**It is still open.** A Challenger was trained with GRPO against a dense
exploit-gap reward (`reported score` minus `independent true completion`, held
by the harness and never shown to the attacker) on a spot A10G, with
`harbor/self-graded` held out so the test would mean something. It did not
close the miss, and neither did the prompted Challenger on local 1.7B/8B
models. The reward itself is verified -- 36 tests, four against real
containers, no GPU -- and the run logs say precisely what failed: 99.7% of GRPO
rollout groups had zero reward spread, so there was no gradient at all.
Numbers, the single-variable follow-up run, and what to try next are in
[`docs/changelog/40-grpo-challenger.md`](docs/changelog/40-grpo-challenger.md).
Nothing about the trained Challenger is required to run Assay: it ships as an
optional artifact, the scripted Challenger is the floor, and the reproduction
guide never asks for a GPU.

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
scores anything, anywhere.** The Challenger only ever proposes actions; every
one of them is scored by a program, and the ground truth it is scored against
is held by the probe and never shown to the attacker.

```bash
uv run --extra adapters pytest tests/test_grpo_reward.py -q      # the reward, no GPU
uv run --extra adapters python scripts/reward_landscape.py       # what it can pay
```

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
