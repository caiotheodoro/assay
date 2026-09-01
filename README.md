# Assay

An agentic auditor for RL environments and eval suites.

Point Assay at an environment. It runs a battery of probes and emits an Environment Card: a validity
verdict where every claim is tied to a probe result, plus machine-readable JSON and a nonzero exit
code that blocks a training run.

Assay does not claim to find more defects than the field. It claims to price them. A finding is not
a result until you know what missing it costs against what a false alarm costs.

**[Audit an environment in your browser →](https://huggingface.co/spaces/caiotheodoro/assay-demo)**
No signup, no server, nothing uploaded. Paste a spec or load one of seven planted fixtures, press
Audit, and the probe battery runs in the tab under WebAssembly CPython, against the same vendored
package the CLI uses.

## Who this is for

- **The researcher about to spend a training run** on an environment they did not write. They cannot
  read every verifier, and the failure is silent: a policy that learns the verifier instead of the
  task, found from the reward curve weeks later, or never. They run `assay audit`, read the exit code.
- **The maintainer of an eval suite**, who owns tasks other people score against with no cheap way to
  know whether a verifier still means what the task says. They run the battery in CI and diff which
  environments changed status. [`docs/COVERAGE.md`](docs/COVERAGE.md) is written for them, in
  BenchJack's V1–V8 vocabulary rather than ours.
- **The reviewer deciding whether to trust a number.** They get the card: every claim tied to a probe,
  and every probe that could not run named with its reason.

The four cost profiles in `src/assay/costs/profiles/` are that decision made explicit. `research-run`
prices a missed defect at wasted compute, `benchmark-publication` at a retracted paper. This is not a
tool for someone who wants a score: `flag_everything` gives a score and beats a badly-calibrated
auditor, and the cost beliefs where it wins are in
[`results/cost_sensitivity.json`](results/cost_sensitivity.json).

## Run it

```bash
uv sync --extra dev && uv run pytest -q                          # every planted defect, caught
uv run --extra tau2 python scripts/tau2_fetch.py                 # the two pinned tau2 snapshots, ~1 min
ASSAY_APPROVE_ALL="reproduction" uv run --extra adapters --extra openenv \
  --extra tau2 --extra sweep python scripts/full_run.py --out /tmp/check.json
```

Skip the fetch and you get 30 environments, not 32. Neither τ² snapshot is redistributed here, so
without them the `tau2` provider reports itself unavailable and every arm's loss falls.
`full_run.py` prints the reason rather than shrinking quietly.

## The result

| Arm | Expected loss (`research-run`) | 95% CI |
|---|---|---|
| `flag_nothing` | 3232.0 | [2080, 4560] |
| `check_env`, the incumbent linter | 3216.0 | [2056, 4552] |
| `flag_everything`, the floor that had to be beaten | 474.0 | [453, 492] |
| **Assay** | **57.0** | **[8, 142]** |
| `assay+auditor`, the agent on — **one draw** | 44.0 | [1, 126] |

Assay saves 417.0 against `flag_everything`, 95% CI [330, 471], separated. 33 environments, 54
planted defects, 10,000 bootstrap resamples over environments, seed 11.

**The agent row is a distribution, not a number, and that is the honest form of it.**
Five environments in the corpus have no correct answer, so every finding the
deterministic battery reports on them is a false positive — 17 of them, precision
0.757. The semantic gate withholds those and `assay+auditor` comes back at **43–44
across seven runs of the same corpus, saving 13–14** — except once, where it came back
at **122.0**, because it decided `tau2/airline` had no correct answer and deleted two
real planted defects along with the false ones.

**One run in seven.** `results/gate_reliability.json` is that measurement, and the
failure mode it records is the bad kind: rare and catastrophic rather than common and
mild. Six runs look like a clean win and would pass any casual check; the seventh hides
real CRITICAL-class findings, which is the outcome this tool exists to prevent.
`docs/PRE-REGISTRATION-NOANSWER.md` predicted the 13.0 and named a criterion for exactly
this — "the agent has traded a false positive for a hidden true one, which is worse than
the disease" — and that criterion fired.

The paired bootstrap cannot see it. It resamples *environments*; the model is asked once
per environment per run and does not always answer the same. **An interval from one run
of an agentic arm is narrower than the truth by an unknown amount**, and that is a
limitation of the method, not of this run. The deterministic arm returned 57.0 every
single time.

Read the arms in the right order. Beating `check_env` proves almost nothing: 16.0 saved of
`flag_nothing`'s 3232.0, on an interval including zero. The arm that had to be beaten is
`flag_everything`, which catches every defect by construction, and for most of this project's life
Assay did not beat it.

**A large part of that 417.0 is arithmetic rather than detection.** `flag_everything`'s loss is
`Σ_env (n_classes − |planted_env|) × false_alarm`, so it gets worse whenever the taxonomy or the
corpus grows, with no detector involved. The four environments with no correct answer plant nothing,
so each hands the floor a free 16 — **80.0 of the margin's growth is arithmetic, and it cost the
deterministic arm 14.0.** A larger standing figure sits underneath: four of the sixteen defect
classes are planted nowhere in the corpus, which hands the floor `4 × 33 = 132` false alarms, 27.8%
of its 474.0. The full decomposition is in [`docs/RESULTS.md`](docs/RESULTS.md), and
[`docs/PRE-REGISTRATION-TAU2.md`](docs/PRE-REGISTRATION-TAU2.md) and
[`docs/PRE-REGISTRATION-NOANSWER.md`](docs/PRE-REGISTRATION-NOANSWER.md) predicted every figure in
it before the corpus grew.

Assay wins all four cost profiles and separates on all four. It previously won one and lost two
outright. The `production-training` row changed because the floor moved, not because the detector
did, and that is stated in [`docs/RESULTS.md`](docs/RESULTS.md) rather than banked here.

Three caveats decide how the table should be read, all in full in [`docs/RESULTS.md`](docs/RESULTS.md):

1. **The two LLM arms tie with random flagging.** `direct_prompt` and `agent_with_tools` score 2343.0
   and 2746.0 against `stratified_random`'s 2838.0, and the paired bootstrap gives 495.0, 95% CI
   [−93, 1123], not separated. Giving the model a tool loop bought nothing measurable — it scored
   *worse* than the coin, well inside the noise.
2. **The deterministic arm's precision is 0.7571, not 0.9464.** Seventeen spurious findings across
   33 environments: three on the two τ² environments, and fourteen on the five with no correct
   answer, where every finding is a false positive by construction. On six runs of seven the gate
   recovers those and leaves the three τ² findings standing, which is the right answer on all
   seventeen. On the seventh it also withheld `tau2/airline`, which has a correct answer.
3. **The corpus is 8 of 33 genuinely third-party**, 3 of them externally labelled. Every clean
   environment added moves the floor by +16 and the deterministic arm by 0 to 4, so self-authored
   environments carry most of the 417.0 margin. Provenance is declared in the registry before the
   corpus grows, and every expansion is pre-registered first. Three of the five no-answer
   environments are written here, and `docs/PRE-REGISTRATION-NOANSWER.md` says so before reporting
   the result that rests on them.

| split | n | assay | flag_everything |
|---|---|---|---|
| all (published) | 33 | 57.0 | 474.0 |
| genuinely external | 8 | 45.0 | 121.0 |
| our content, third-party format | 10 | 0.0 | 132.0 |
| in-process fixtures | 15 | 12.0 | 221.0 |

**Assay has no true misses on this corpus.** The one that used to be reported —
`inspect_evals/boolq`, `SHORTCUT_LEAK` — is not a miss: boolq ships no train split, so the probe
returns `NOT_APPLICABLE` and says why. The scorer had no third state and charged it as a failure to
detect, which is the defect class this tool exists to catch, in the code that produced its own
headline. It is now reported as `n_unchecked: 1` with `recall_on_checkable` 1.000 beside the
unchanged `recall` of 0.9815, and it is still priced at full miss cost — a defect nothing looked for
is still in your environment, and any cheaper price would let a probe lower its own score by
declining to answer.

The whole ranking rests on one made-up number. `research-run.yaml` prices a missed CRITICAL defect at
120 engineer-hours-equivalent and nothing derives that 120. Assay's loss is affine in `C`, so it
crosses `flag_everything` at **1371.0**: the headline survives a 1042% error in a
constant nobody derives. That margin comes partly from the floor getting worse, which is weaker
evidence than the detector getting better, and
[`results/cost_sensitivity.json`](results/cost_sensitivity.json) has the sweep.

## Two real defects, in software shipping today

Both are filed upstream: [inspect_evals#2331](https://github.com/UKGovernmentBEIS/inspect_evals/issues/2331)
and [OpenEnv#1102](https://github.com/huggingface/OpenEnv/issues/1102). No maintainer has replied yet.
The corpus measures Assay against defects this repo planted; these two were not, and both were
verified from the upstream project's own code with Assay out of the loop.

**`inspect_evals` 0.18.0 — `paws` scores a constant string at 100%.** It asks for `Yes` or `No` and
scores with `includes()`, a case-insensitive substring test, so `"yesno"` contains both labels and
scores 8000/8000. The looseness is one-sided, which is worse than symmetric: 4464 of 8000 items have
the target `No`, so every hedging answer is credited on 56% of the benchmark for free.

**`openenv` — `textarena_env` accepts a seed and ignores it.** Six calls to `reset(seed=1234)` return
six different secret Wordle words. The signature takes `seed`, then calls
`self._ta_env.reset(num_players=...)` without it. gymnasium 1.3.0 raises on exactly this shape.

Assay found one of the two; a human found the other. It flagged 14 of 25 sampled `paws` items as
`REWARD_HACKABLE` but not the `"yesno"` case, and that split is pinned as a test so it cannot quietly
close. Write-ups: [`docs/disclosures/`](docs/disclosures/README.md).

## The problem

Labs and vendors buy RL environments and eval suites as products. Nobody QAs them. When a flagship
benchmark turns out to be broken, the fix is a human doing it by hand:

| Benchmark | What was wrong | How it was found |
|---|---|---|
| SWE-bench | ~2/3 of instances unusable | 93 developers, hand-triaged → SWE-bench Verified |
| SWE-bench | 7.8% of "passing" patches are wrong-but-pass | manual audit (ICSE 2026) |
| SWE-bench | ~1/3 of instances leak the fix in the issue text | manual audit (SWE-bench+) |
| WebArena | substring-match evaluator produced false negatives | manual audit → WebArena Verified |
| tau2-bench | wrong gold actions, premature termination | 75+ ad hoc fixes across labs, unpublished |

The only automated tooling that exists is `gymnasium.utils.env_checker` and
`stable_baselines3.common.env_checker`. They assert space shapes, that `reset()` returns
`(obs, info)`, that reward is not NaN, and in gymnasium 1.3.0 that the same seed and action give the
same observation. On five API-correct environments carrying four planted defects they catch one,
determinism, and say nothing about a verifier that pays full reward at reset, a constant action that
beats every other, or a score that comes apart from the task. `scripts/real_check_env.py` runs the
real tools rather than a model of them.

## Does an agent find what a script cannot?

Ten of the eleven probe families are deterministic programs. The history of the eleventh is the
argument for that design, and it does not flatter the agent.

The `claude-cli` Challenger found a reward-hack exploit class at turn 8 in 262s that a scripted
attacker and `qwen3:8b` both missed. It overwrites the expected answer so the verifier's comparison
is trivially true, scoring 1.0 by the environment and 0.0 by an independent verifier it never had
access to. Writing that mechanism down as a fixed policy captured it permanently at zero marginal
cost, and the scripted Challenger now finds the same gap in 3.8s instead of 262s with no model in the
loop. Good for the tool, bad for the argument that the agent is load-bearing.

Where a script structurally cannot follow is proposing a policy rather than replaying one. On the
pinned `paws` subsample ([`results/policy_synthesis.json`](results/policy_synthesis.json)), the
scripted floor finds 14 of 25 and `claude-cli:sonnet` finds 24–25 of 25 across three runs, reaching
the both-labels-at-once class from the task text. `qwen3:8b` reaches 0, which makes this a capability
threshold rather than a property of the design. Nothing there is scored by a model: `self_report`
records what the challenger claimed and is used for nothing.

The second place is a judgement no probe can make. `inspect_evals/personality_BFI` comes back INVALID
with 25 × `INVERT_PASSES`, mechanically correct and semantically wrong, because a personality
inventory has no correct answer. `assay audit --auditor` runs a semantic gate that withholds exactly
that verdict, on 20 environments at three runs each per backend
([`results/semantic_gate.json`](results/semantic_gate.json)):

| backend | withheld the false positive | false overrides |
|---|---|---|
| `claude-cli:sonnet` | 6 of 6 runs | **0 of 54 runs** |
| `ollama:qwen3:8b` | 6 of 6 runs | 6 of 54 runs |

Read the second column. A false override hides a real defect, which is worse than missing one, so
`qwen3:8b` is not a backend to run this with.

The gate is the conjunction of the model's label and its own quoted evidence, because each alone
fails. `qwen3:8b` labels `personality_BFI` as having a correct answer in 3 of 3 runs immediately
after writing a valid contradicting pair into the evidence field, and reading the verdict off the
evidence alone turns 10 of the 12 healthy fixtures into `no_correct_answer`. The script owns
mechanism and the model owns meaning.

It is off by default and changes none of the numbers above. The override can only move a
`verifier_integrity` DEFECT to `NOT_APPLICABLE`, never to PASS, never into another family, and each
one prints the model, the text it quoted and the verdict it replaced.

**The agent is in the headline table and it changes nothing.** `assay+auditor` scores 43.0 on every
figure, identical recall, precision, misses and spurious, because the corpus contains no environment
without a correct answer for the gate to act on. Reproduce it with
`scripts/auditor_arm.py`; the artifact is [`results/auditor_arm.json`](results/auditor_arm.json).
The positive case is deliberately not reachable from the corpus:
[`docs/COVERAGE.md`](docs/COVERAGE.md) argues that an environment the tool is wrong about does not
belong in the set used to measure the tool.

```bash
# the gate declining on a corpus environment, because this one has a correct answer
uv run --extra adapters assay audit fixture/unfalsifiable --auditor \
  --auditor-model claude --yes
```

## Where Assay sits in the field

Everything above is measured against defects this repo planted, which is a closed loop. Two
measurements break it, scored where possible by other people's code.

**τ²-bench, 62 defects an independent team labelled**, built from the diff between two pinned
revisions rather than from the prose:

| | recall | precision | one-sided p |
|---|---|---|---|
| excluding `assert_traceability` | 0.210 (13/62) | 0.565 | **0.040** |
| all 12 probes | 0.339 (21/62) | 0.389 | **0.486** |

The 0.339 row is chance. Only the narrower row clears the floor, so the advisory probe is not a bonus
with a caveat: including it destroys the measurement. Read the p-values, not the recall. The split is
the result: 13/20 on ground-truth annotation errors against 8/42 on instruction under-specification.

**ScienceAgentBench, 0 of 12, by BenchGuard's own scorer.** The honest reading is not that Assay
finds instruction defects hard. Assay could not run at all here and said so twelve times: all 12
probes returned `NOT_APPLICABLE` with a reason and the verdict was `UNVERIFIED`, because SAB is a
static task-definition set and these probes need an executable environment. Running their scorer also
showed that nine of the twelve defects are already fixed in the split SAB tells you to use, so any
tool's SAB recall number is uninterpretable without naming the split.

Measured twice on two independently labelled sets: Assay does not detect instruction defects, because
"this instruction is ambiguous" is a judgement and nothing here scores with a judge.

## The probes

| Family | Question | A "no" means |
|---|---|---|
| Verifier integrity | Does gold pass? Does no-op fail? Does an inverted spec fail? | the eval cannot fail, or rubber-stamps |
| Trivial floor | Can a policy that ignores the input win? | it is not measuring capability |
| Separability | Can it tell apart policies known to differ? | it is saturated or dead |
| Contamination | Does the train split leak into the eval split? | held-out is not held out |
| Shortcut leakage | Is the answer recoverable from a part of the input? | it measures the artifact, not the task |
| Spec ↔ verifier | Does the verifier check what the instruction asked? | agents fail for following instructions |
| Determinism | Same seed, same result? | every comparison is partly noise |
| Difficulty band | Is the solve rate in a learnable range? | it contributes noise, not learning |
| Reward hackability | Can a policy score well without doing the job? | training on it teaches the exploit |
| Sandbox permissions | Does the deployment grant more than the task needs? | an exploit needs only the manifest |
| Evaluator code execution | Can the verifier be made to run what it is grading? | the agent writes a sentence, not a solution |

Family 9 is the adversarial Challenger, scripted, prompted or GRPO-trained. The rest are
deterministic programs. No model ever scores a probe: the Challenger only proposes actions, every one
is scored by a program, and the ground truth is held by the probe and never shown to the attacker. A
model can withhold a verdict through the `--auditor` gate. It can never assert one.

That is a claim about what Assay asserts, not about what exists in the room. Two things it touches do
use a judge: τ²-bench's `nl_assertions`, which is why they are excluded from the τ² measurement, and
BenchGuard's `match.py`. Stated as an absolute it was false, and
[`docs/RETRACTIONS.md`](docs/RETRACTIONS.md) §19 records that.

## Main failure mode

A Challenger that could not speak, reported as a Challenger that found nothing. An agent has more
ways to produce no output than a program does: the model refuses, every reply is unparseable, the
budget runs out mid-plan, the CLI is rate-limited. All of those arrive at the probe as an empty
attempt list, indistinguishable from a genuine "I attacked this environment and it held", which means
a card can read `VALID` because the auditor was silent. That is the worst thing this tool can do,
because it is the failure the tool exists to catch, happening inside the tool.

Two routes are closed. `ChallengerExhausted(reason, history)` is raised instead of an empty list and
caught in `src/assay/probes/hackability.py`, so the card says `NOT_APPLICABLE` with the reason, and
`hackability.py` reads `challenger_passes` from context so an audit can run the Challenger more than
once. What stays open is the shape of the problem: a silent auditor is indistinguishable from a clean
environment unless every route to silence is made to say so, and only the routes someone has thought
of are covered.

## Hot take

Nobody QAs the benchmark, including the people building the tool that QAs benchmarks.

The thesis is that the RL environments and eval suites labs buy ship unchecked, and it is right.
`paws` scores the constant string `"yesno"` at 100% on the current release of `inspect_evals`, and
OpenEnv's `textarena_env` accepts a seed and throws it away on `main` today.

Then we pointed the same hostility at this repository and twelve of its own published claims broke.
The external recall number was chance (p = 0.486) against a floor the project applies to every
environment it audits and had never applied to itself. Half the corpus proving the headline was the
project's own pytest fixtures, on which a test asserts perfect detection: a passing build wearing a
measurement's clothes. An exploit was published as "the winning policy, scored 1.0" that appears in
no run that succeeded. The Environment Card was described as signed and was an unkeyed hash anyone
could recompute.

None of that was dishonesty. It was a fast-moving repo where corrections landed one document
downstream of the one people read, which is exactly how a broken benchmark stays broken. An auditing
tool is not exempt from the thing it audits, and the only defence is to run the audit on yourself and
publish what it finds. [`docs/RED-TEAM.md`](docs/RED-TEAM.md) is that audit, unedited;
[`docs/RETRACTIONS.md`](docs/RETRACTIONS.md) is every claim it cost.

## Prior art

The category is not new and Assay does not claim it is. Static auditors read a benchmark's files:
**BenchGuard** ([arXiv 2604.24955](https://arxiv.org/abs/2604.24955)), **ABA**
([arXiv 2605.26079](https://arxiv.org/abs/2605.26079)). Dynamic auditors execute it: **BenchJack**
([arXiv 2605.12673](https://arxiv.org/abs/2605.12673)), 219 flaws across 10 agent benchmarks, and
[arXiv 2606.16062](https://arxiv.org/abs/2606.16062), whose gold-sanity gate on SWE-bench Verified
found 28.5% of 49 tasks hackable. Partial-input baselines, reward-model overoptimization and
separability-as-a-metric are ported, not invented.

What Assay adds is the bundle, eleven families in one report under one expected-loss metric, plus
pricing rather than counting defects, and absence of evidence reported as loudly as evidence. What
predates this repo is in [`docs/LINEAGE.md`](docs/LINEAGE.md), cited as lineage and not vendored.

## Start here

| | |
|---|---|
| Orientation, 130 lines | [`AGENTS.md`](AGENTS.md) |
| Every claim, with the file that backs it | [`docs/FOR_AGENTS.md`](docs/FOR_AGENTS.md) |
| Every number, with its caveats | [`docs/RESULTS.md`](docs/RESULTS.md) |
| Everything this repo published and took back | [`docs/RETRACTIONS.md`](docs/RETRACTIONS.md) |
| This repo's own claims, attacked | [`docs/RED-TEAM.md`](docs/RED-TEAM.md) |
| The method, written to be reused | [`docs/METHOD.md`](docs/METHOD.md) |
| What the tool cannot see, in someone else's vocabulary | [`docs/COVERAGE.md`](docs/COVERAGE.md) |
| Reproduce every number end to end | [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) |
| An agent run and a sample card, read without executing | [`results/trajectories/INDEX.md`](results/trajectories/INDEX.md), [`results/example-card.md`](results/example-card.md) |
| Architecture, changelog, self-score | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/CHANGELOG.md`](docs/CHANGELOG.md), [`docs/RUBRIC.md`](docs/RUBRIC.md) |
| Published artifacts | [Collection](https://huggingface.co/collections/caiotheodoro/assay-auditing-rl-environments-with-error-bars-6a946953e05a8669da74ee65), [code](https://github.com/caiotheodoro/assay), [corpus and cards](https://huggingface.co/datasets/caiotheodoro/assay-corpus), [the GRPO Challenger, a negative result](https://huggingface.co/caiotheodoro/assay-challenger-grpo), [the solution video, 4:36](https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4) |

The hosted demo is a free static Space, so the battery runs in the visitor's browser rather than on a
server. Hugging Face returns HTTP 402 for a Gradio Space on free `cpu-basic`, which is why
`space/app.py` runs locally only, with `python space/app.py`. The browser build refuses
`verifier: "regex"`, because `safe_regex` bounds a submitted pattern in a subprocess and WebAssembly
has none. The video carries one erratum: it says "separates on three", and it is now four, with
[`docs/VIDEO.md`](docs/VIDEO.md) on why the video's caution was the better instinct.

## License

Apache-2.0 — [`LICENSE`](LICENSE).
