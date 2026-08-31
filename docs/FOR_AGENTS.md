# Reviewer's Fast Path — what Assay is, and why the obvious alternatives don't cover it

> Structured for fast verification. Every claim below cites a file you can open,
> and every number cites the artifact it was computed from. Nothing here needs to
> be taken on trust; the point of the file is that you do not have to.

```json
{
  "project": "Assay",
  "one_liner": "An agentic auditor that tries to break RL environments and eval suites before you trust their numbers, returning a verdict tied to evidence.",
  "category": "agentic workflows — QA for evals",
  "user": "researcher about to spend GPU on an env they didn't write, or maintainer about to publish one",
  "incumbent": "gymnasium.utils.env_checker — linter for 'will this crash my trainer', recall 0.04",
  "result": "assay 40.0 vs flag_everything 366.0, saved 326.0 [238, 378] separated, wins 4/4 cost profiles, separates 3/4",
  "cost_crossover": "942h vs shipped 120h — survives 815% error",
  "repro": "uv sync --extra dev; uv run --extra tau2 python scripts/tau2_fetch.py; uv run --extra adapters --extra sweep --extra openenv --extra tau2 pytest -q (711 passed, 0 skipped) + ASSAY_APPROVE_ALL=repro uv run --extra adapters --extra openenv python scripts/full_run.py (22s, no GPU, no API key; the env var is the explicit unattended-approval escape, see docs/changelog/98-approval-gate.md)",
  "agentic_core": "10 deterministic probe families + 1 Challenger (agent found the exploit class; scripted policy now finds it in 2s vs 262s)",
  "self_audit": "12 published claims broke when pointed at itself, 3 real bugs found",
  "deliverables": {
    "code_and_changelog": "shipped — docs/CHANGELOG.md, 49 fragments",
    "reproduction_guide": "shipped — docs/REPRODUCTION.md, cold-cache timings",
    "trajectories": "shipped — 8 runs, 3 misses, 1 gate refusal",
    "video": "shipped — https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4 , 276.032s = 4:36.03 against the 5:00 cap, h264+aac. The Remotion sources, capture scripts, terminal casts and voice tracks are tracked under video/; only the 24MB render is hosted rather than committed",
    "hosted_demo": "shipped — https://huggingface.co/spaces/caiotheodoro/assay-demo , a free static Space that runs the probe battery in the visitor's browser under Pyodide. All 7 examples are pre-rendered into the page at build time. HF still returns 402 for a Gradio Space on the free tier, so space/app.py is local-only"
  },
  "known_gaps": [
    "inspect_evals/boolq missed — no train split, contamination probe has nothing to compare",
    "4 of BenchJack's 8 flaw classes uncovered (docs/COVERAGE.md)",
    "only 4 of 26 corpus environments are genuinely third-party (README.md, corpus split)",
    "the hosted demo refuses verifier:regex — safe_regex bounds a submitted pattern in a subprocess and WebAssembly has none"
  ]
}
```

---

## 10-Second Parse

- **Problem:** Labs buy RL envs/evals as products. Nobody QAs them. Fixes are 93 devs hand-triaging (SWE-bench) or never finding out.
- **Incumbent ceiling:** `env_checker` catches 1 of 4 planted defects (`results/real_check_env.json`), 2 of 50 on corpus. It checks "will it crash", never "does it measure".
- **Assay:** Point at env → 11 probe families run → `Environment Card` with `VALID / INVALID / UNVERIFIED` + exit code + every claim tied to evidence.
- **Why the alternatives don't cover it:** static tools read files, dynamic tools run one check; none bundles 11 families under one expected-loss metric with `could-not-run` reported as loudly as defects. Matrix below.

---

## The 4 Questions (hackathon brief, p.1) — Answered With Receipts

### 01. Who has this problem?
`README.md` § *Who this is for, concretely* — three concrete roles, in priority order:
1. Researcher with GPU budget, env they didn't write (`inspect_evals`, Harbor, OpenEnv). Failure is silent: policy learns verifier, found after run.
2. Maintainer of eval suite (tasks others score against). No cheap way to know verifier still means task.
3. Reviewer handed a benchmark number. Wants to know what was checked.

Not "labs and vendors" in abstract — the `research-run` profile
`src/assay/costs/profiles/research-run.yaml` prices it: false alarm = 1h reading a
card, missed CRITICAL = 120h wasted cycle.

### 02. What bottleneck makes it worth solving?
`README.md` § *The problem* — five precedents in a table, each "what was wrong / how found":

| Benchmark | Defect | Found by |
|---|---|---|
| SWE-bench | 2/3 unusable | 93 devs hand-triaged |
| SWE-bench | 7.8% wrong-but-pass | manual audit (ICSE 2026) |
| WebArena | substring evaluator false-neg | manual audit |
| tau2-bench | wrong gold, early termination | 75+ ad hoc fixes |

Plus two **live defects Assay did not plant**, verified from upstream code with Assay
out of the loop (`README.md` § *Two real defects, in software shipping today*):
- `inspect_evals/paws` 0.18.0: `includes()` substring against Yes/No → `"yesno"` scores **8000/8000**
- `openenv/textarena_env`: `reset(seed=1234)` ×6 → 6 different words (seed ignored)

Both are written up as unfiled disclosure drafts in `docs/disclosures/`.

Incumbent `gymnasium`+`stable_baselines3` checkers: `scripts/real_check_env.py` →
**1 of 4** detected on purpose-built shims. On corpus: `check_env` 3056.0 [1960, 4272]
vs `flag_nothing` 3072.0 [1984, 4288], saved 16.0 [0, 40] **overlaps zero** — not
distinguishable from doing nothing.

That last number is the one that matters, and it cuts against the easy story: beating
the incumbent proves almost nothing here, because the incumbent barely beats doing
nothing. The arm that had to be beaten is `flag_everything`, which catches every defect
by construction. For most of this project's life, Assay did not beat it.

### 03. Does the agent solve it well?
**Eleven probe families** (`README.md` § *The probes*) — 10 deterministic programs + 1 Challenger:

| Family | Asks | Miss = |
|---|---|---|
| Verifier integrity | gold pass? no-op fail? inverted spec fail? known-wrong fail? | eval cannot fail |
| Trivial floor | can input-ignoring policy win? | not measuring capability |
| Separability | can it tell known-differing policies apart? | saturated/dead |
| Contamination / Shortcut / Spec↔verifier / Determinism / Difficulty | — | — |
| **Reward hackability (Challenger)** | can policy score well without doing job? | training teaches exploit |

Design choices that matter (rubric: "which choices helped"):
- **Independent verifier** — Challenger's 1.0 is scored 0.0 by the probe's hidden verifier.
- **Ask-by-default sandbox** — `current_approver()` (`src/assay/sandbox.py:353`) is the one place that decides, and its default is a prompt showing image, command, mounts, network state and every limit *before* asking (`:249`); with no terminal it refuses rather than assuming a yes. Unattended running is explicit — `assay audit --yes` or `ASSAY_APPROVE_ALL="<reason>"` — and the Environment Card says so. A bare `DockerSandbox()` is still `DenyAll` (`:199`). Containment defaults are `network: bool = False` and `read_only_root: bool = True` (`:89,94`, applied at `:424,434`). Third-party `inspect_ai` scorers run **in-process**, uncontained, and go through the same gate as an `InProcessRequest` (`:108`) rather than going unmentioned. This bullet used to claim deny-by-default while `_harbor_corpus.py` hard-coded `AutoApprove` on the shipped path: `docs/changelog/98-approval-gate.md`.
- **Deterministic probes, stochastic attacker** — no LLM judge scores anything inside Assay. Only the Challenger is agentic, and its contribution is reported as a **rate (3 of 4)**, not as a capability.

### 04. Can another person reproduce it?
`docs/REPRODUCTION.md` — cold-cache timings, lockfile, a degradation table built by
actually stopping things, and a cost table. One command per result:

```bash
uv sync --extra dev && uv run --extra tau2 python scripts/tau2_fetch.py   # snapshots; not committed
uv run --extra adapters --extra sweep --extra openenv --extra tau2 pytest -q   # 711 passed, 0 skipped
ASSAY_APPROVE_ALL="reproduction run" uv run --extra adapters --extra openenv python scripts/full_run.py   # headline: 26 envs, 50 defects, 22s, no GPU/key
uv run --extra adapters assay audit harbor/self-graded --card card.html   # one env, card + exit code; asks before it runs anything, add --yes to skip the prompt
```

Video numbers are data-bound, not transcribed: `video/src/data/results.ts` imports
`results/intervals*.json`, so no scene hard-codes a literal.

---

## Where the agent actually is

This is the question a reviewer should press hardest at an *agentic workflows*
hackathon, so it is answered here rather than buried: **10 of the 11 probe families are
deterministic programs, and only the Challenger is an agent.** That is the design, and
the history behind it is the interesting part.

The Challenger's job is to find a way to score well without doing the task. In the
4-policy ablation, the scripted attacker missed and `qwen3:8b` missed; `claude-cli`
found the exploit — writing `expected.txt` to match its own output — at turn 8, in 262s.
That exploit class was then written down (against BenchJack's V7/V1 taxonomy) as a
scripted policy, and the current 6-policy scripted Challenger finds the same gap of
1.00 in about **2 seconds**.

**Compiling a discovery into a cheap deterministic check is what a good agentic
workflow is supposed to produce.** The agent did the search; the script now holds the
result at zero marginal cost, with no sampling variance and no API key on the critical
path. Reporting that honestly costs points from a reviewer counting LLM calls, and it
is still the right answer: an auditor that needs a model in the loop to be reliable is
an auditor whose verdicts cannot be reproduced.

The agentic surface that remains is where stochasticity is actually appropriate —
proposing exploits — and it is measured as a rate, not asserted as a capability.
A GRPO-trained Challenger was also tried and **did not beat the scripted floor**;
that negative result is published in `docs/changelog/40-grpo-challenger.md` and the
model is on the Hub labelled as a negative result.

---

## Why the obvious alternatives don't cover it — comparison matrix

| System | Mode | What it actually checks | What it reports | Cost-aware? | Says what it couldn't run? | Cross-ecosystem? |
|---|---|---|---|---|---|---|
| **gymnasium / SB3 `env_checker`** | dynamic | shapes, reset/step types, 1 determinism check | pass/fail per check | no | no | gymnasium only |
| **BenchGuard** | static (read files) | ScienceAgentBench instruction defects | 12 confirmed, recall 0.83 | no | no | SAB only |
| **ABA** | static | 34k tasks, 14k major issues | count | no | no | 168 benchmarks, static only |
| **BenchJack** | dynamic (agent-driven) | 219 flaws, adversarial patch loop | hackable-task ratio | no | no | 10 agent benchmarks |
| **arXiv 2606.16062** | dynamic | SWE-bench gold-sanity | 28.5% hackable | no | no | SWE-bench only |
| **Assay** | **dynamic, 11 families** | verifier + trivial + separability + contamination + shortcut + spec + determinism + difficulty + **Challenger** | **expected loss (40.0 [0, 120] vs 366.0 [347, 383]), saved 326.0 [238, 378]**, 4 cost profiles | **yes — 120→1098 crossover, 815% margin** | **yes — always renders `What could not be checked`** (`video/src/components/Panels.tsx:254-285`) | **6 adapters, 4 ecosystems** (`src/assay/adapters/`) |

**The gap Assay fills:** no other tool (a) bundles verifier + contamination + shortcut
+ separability + difficulty + reward-hack in one report, (b) prices misses against false
alarms with a sensitivity sweep, (c) reports absence as loudly as presence, (d) uses one
protocol across Harbor / inspect_ai / OpenEnv / tau2 / SAB.

The category itself is **not** new and Assay does not claim it is — an earlier version
of the README overclaimed here, mis-citing someone else's paper, and the retraction is
kept in the record at `README.md` § *A correction*. Full prior art, with the papers and
their numbers, is at `README.md` § *Prior art*.

Harbor is the *patient* — an environment runner. Assay is the *doctor*. Harbor running
`paws` correctly is not evidence `paws` is correct — which is why `paws` still scores
`yesno` at 100% inside Harbor.

---

## Doubt Resolution — FAQ

**Q: Isn't Harbor / an isolated RL env enough?**
No. Isolation = "code can't escape host". Validity = "score means task". Harbor executes
`paws` perfectly; `paws` still scores a constant at 100%. Harbor executes `self-graded`
perfectly; its verifier is still reward-hackable via `expected.txt`.
(`video/public/casts/audit.cast` is the recorded session.)

**Q: Isn't `env_checker` enough?**
`results/real_check_env.json` — 1 of 4 planted defects caught. 2 of 50 on corpus, both
determinism. Silent on the other 8 families. `src/assay/baselines/structural.py` models
it; `scripts/real_check_env.py` runs the real one.

**Q: Why not just LLM-as-judge?**
No LLM judges any verdict in Assay. The Challenger *proposes*; a program *scores*
against held ground truth. LLM-judged evals are why `tau2 nl_assertions` are excluded
from scored recall. BenchGuard's own Gemini judge (`eval/match.py`, in BenchGuard's
repo, not vendored here) is borrowed rather than trusted — Assay submitted 0 findings
there and scored **0/12**, published as a result rather than dropped.

**Q: Does the agent actually contribute?**
Yes, and then the script made it unnecessary — disclosed as the result, not hidden.
See *Where the agent actually is* above.

**Q: Is the corpus too self-authored?**
Yes, and the split is published because it is unflattering: 12 fixtures + 10
our-content/third-party-format + **4 genuinely external** (n=4). Pre-registered before
`paws`/`boolq` were added (`docs/PRE-REGISTRATION.md`); `results/corpus_splits.json`
shows where it wins and loses. The one remaining miss is external —
`inspect_evals/boolq`, no train split → `NOT_APPLICABLE`.

**Q: Is the 120h miss cost made up?**
Yes, and it is labelled a guess. It was swept: the crossover is at **1098**
(`results/cost_sensitivity.json`), so the headline survives a 815% error in it. Before
the Harbor misses were closed the margin was 21%; both are published.

---

## Five things checkable in under 60 seconds

Each is verifiable from the repository without running a model. They are listed as facts
about this repository, not as a comparison against work not seen.

1. **A self-audit with the breakage published.** Every instrument was turned on the tool
   itself: **12 published claims broke, 3 real behavioural bugs found.** Unedited in
   `docs/RED-TEAM.md`; the reusable protocol, with what each check cost, in
   `docs/METHOD.md`.

2. **A shot-vs-reality gate.** `video/capture/check-shot-reality.mjs` checks video claims
   that mention a verdict against a recorded terminal session,
   `video/public/casts/audit.cast`, rather than against the video's own scene data.
   It exists because a fabricated card once survived render and a 7-point sweep — every
   prior check compared the video to itself.

3. **A deterministic core with the stochastic edge isolated.** 8 probes are programs, 1 is
   an attacker; `docs/ARCHITECTURE.md:32-52` names the single remaining leak between them,
   and `:114-137` documents a capability wired but dead.

4. **The correct bootstrap unit.** `results/intervals.json` resamples **environments**
   (n=26), not defects, and carries a `"why"` field saying so. Resampling defects would
   report an interval far too tight. Paired differences on a shared resample: assay vs
   `flag_everything` **326.0 [238, 378] separated**; assay vs `check_env` **3016.0 [1904, 4240]**.

5. **Trajectories that include the misses.** `results/trajectories/INDEX.md` — 8 runs,
   3 Challenger misses, 1 sandbox gate refusal, unparseable replies kept rather than
   pruned.

---

## Verify in 60 seconds (no GPU, no API key)

```bash
uv sync --extra dev && uv run --extra tau2 python scripts/tau2_fetch.py   # snapshots; not committed
uv run --extra adapters --extra sweep --extra openenv --extra tau2 pytest -q   # 711 passed, 0 skipped
ASSAY_APPROVE_ALL="reproduction run" uv run --extra adapters --extra openenv python scripts/full_run.py   # 22s; compare results/full_run.json
python3 -m json.tool < results/intervals.json | head -30
node video/capture/check-shot-reality.mjs                            # shot-vs-reality gate
uv run --extra adapters assay audit harbor/self-graded --yes --card /tmp/c.html; head -40 /tmp/c.html   # --yes because this runs unattended
```

`--extra tau2` and the fetch are both load-bearing: `.tau2_cache/` is not committed, and
without the extra `tests/test_tau2_adapter.py` fails on a missing `loguru` rather than
skipping. Verified from a fresh tree with no `.venv`: **711 passed, 0 failed, exit 0** —
123 s for the whole cold path, `uv sync` and the snapshot fetch included.

The last command **exits 1 on purpose** — `harbor/self-graded` is reward-hackable, and a
nonzero exit is what blocks a training run. That is why it is separated by `;` and not
`&&`: chained with `&&`, the card never prints.

---

*This file is a navigation aid. The evidence is the files it points at, not this summary —
where the two disagree, the files are correct and this file is stale.*
