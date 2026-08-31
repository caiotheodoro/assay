# Self-score against the micro1 rubric

Scored against `micro1 - First Hackathon`, pages 5 (judging), 6 (ground rules) and
7 (final deliverables). Marked hard, on the assumption that a judge reads the repo
cold and follows only what the README points them at.

This file now carries **two** scores: the current one, and the 74/100 snapshot from
2026-08-29 that it replaces. The snapshot is kept because a rubric quietly rewritten
after the fixes it prescribed would no longer be evidence of anything — and because
the numbers it quotes moved so far that the drift is itself worth reading.

## Current self-score — 82 / 100

*Re-scored 2026-08-30 against the current tree.*

| Criterion | Available | Scored | Was (2026-08-29) |
|---|---|---|---|
| Problem & User Value | 15 | **13** | 12 |
| Agent Solution & Engineering | 30 | **23** | 23 |
| End to End Quality | 20 | **16** | 15 |
| Measured Improvement | 15 | **14** | 11 |
| Reproducibility | 15 | **12** | 10 |
| Hot Take / Insights | 5 | **4** | 3 |
| **Total** | **100** | **82** | 74 |

**What moved, and why.**

- **Measured Improvement, 11 → 14.** The largest change and the one that carries the
  submission. The margin against `flag_everything` went 50.0 → 36.0 → **274.0**, and
  it is now **statistically separated**: 95% CI [186, 326], resampling environments
  (n=26) rather than defects. The cost crossover moved 145 → **942**, so the headline
  survives a 685% error in the one number that was openly a guess. Four cost profiles
  are swept; Assay wins all four and separates on three. Not 15/15: the corpus is
  still only 4 genuinely third-party environments out of 26.
- **Reproducibility, 10 → 12.** The blocker at 10 was that there was no address
  to clone — that is fixed; `scripts/full_run.py` reproduces every deterministic arm of
  `results/full_run.json` byte-identically (verified from a fresh tree; the two LLM
  baseline arms need `--llm-arms` and a live Ollama), and `docs/REPRODUCTION.md` has
  cold-cache timings and a degradation table built by actually stopping things. Two new gates in
  `tests/test_published_claims.py` now check that every path cited in the
  reviewer-facing docs resolves, and that the suite size those docs advertise is the
  suite size that ran. Scored **12**, not 13, because the full headline still wants
  Docker and Ollama up, and there is no hosted demo to fall back on.
- **End to End Quality, 15 → 16.** The suite is now **650 passed / 0 skipped**
  (at the time of that scoring: 493 passed / 18 skipped); the two Harbor misses are closed; the red-team fixes landed;
  the corpus, cards, arms and a Challenger model are published on the Hub. Held at 16
  by the two things below.
- **Problem & User Value, 12 → 13.** Two defects in shipping upstream software are now
  verified with Assay out of the loop, and drafted as disclosures in
  `docs/disclosures/`.
- **Hot Take, 3 → 4.** "An auditor is an eval" is carried through to its conclusion:
  every instrument was turned on the tool, 12 published claims broke, and the breakage
  is published unedited in `docs/RED-TEAM.md`.
- **Agent Solution & Engineering, unchanged at 23.** Nothing here got worse, and
  nothing got better in a way a rubric rewards. See the deduction below.

**The two deductions that are not closed, and are not closing.**

1. **The video deliverable is now closed, and was open until the last pass.** It is
   rendered and hosted: https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4 —
   276.032 s = **4:36.03** against the 5:00 cap, h264 with an AAC track. The pipeline
   that builds it is tracked under `video/`; only the 24 MB render is hosted rather
   than committed. It is recorded here because for most of this project's life the
   video was finished on disk and absent from the repository, and two documents
   described it as unrecorded — a deliverable can be complete and still not delivered,
   which is the same class of gap as a correction landing one document downstream of
   the one people read.

2. **The agentic surface is small, at an agentic-workflows hackathon.** 10 of the 11
   probe families are deterministic programs. The Challenger found the reward-hack
   exploit class that a scripted attacker and `qwen3:8b` both missed, and that class
   was then compiled into a scripted policy that finds the same gap in ~2s instead of
   262s. That is the correct engineering outcome and it is reported as the result
   rather than hidden — but a reviewer counting agency will count less of it here than
   in a submission that keeps a model on the critical path. The argument for why that
   is the right trade is in `docs/FOR_AGENTS.md`, and it is an argument, not a defence.

Also unclosed and published rather than hidden: `inspect_evals/boolq` is still missed
(structurally — no train split), four of BenchJack's eight flaw classes are uncovered
(`docs/COVERAGE.md`), the GRPO Challenger does not beat the scripted floor, and there
is no hosted demo because Hugging Face returns HTTP 402 for a Gradio Space on the free
tier.

**On the number itself.** 82 is a self-score by the people who wrote the thing, marked
hard, and an independent reviewer is entitled to a different one. An independent pass
run cold against this tree scored it **75**, taking 3 more points off Reproducibility
and 3 off Agent Solution; its Reproducibility deduction was the `byte-identically`
overclaim now corrected above, and its Agent Solution deduction is the second one below,
which is a matter of judgement rather than fact. Both numbers are published; the lower
one was not solicited to be flattering and is the more useful of the two.

---

## Historical snapshot — 74 / 100, as scored 2026-08-29

*Superseded by the score above. Kept as a record, not as a claim. Everything from
here down was written before `docs/RED-TEAM.md` broke twelve published claims and
before those were fixed.*

Numbers it quotes that have since moved: at the time it was `493 passed / 18 skipped`
(now 650 passed / 0 skipped with the τ² snapshots fetched); `0.339` was the README's
τ²-bench headline (now labelled chance, p = 0.486); the example card carried a
"signature" (now `content_digest`). Its line references into `README.md` no longer
resolve. Since it was written the corpus grew from 24 environments to 26 and the two
Harbor misses were closed, so the headline moved twice: assay 240.0 → 280.0 → **40.0**,
flag_everything 290.0 → 316.0 → **314.0**, margin 50.0 → 36.0 → **274.0 and now
separated**; the cost crossover went 145 → 942. Which deductions closed is recorded in
`docs/changelog/73-remediation.md`, `docs/changelog/74-finishing.md`,
`docs/changelog/77-external-corpus.md`, `docs/changelog/78-determinism-timeout.md`,
`docs/changelog/79-taxonomy-policies.md` and `docs/changelog/80-floor-of-the-field.md`.

One instruction below is **unsafe to follow**: fix #7 says to lift the hot take from
`docs/VIDEO.md` verbatim into the README. That passage contains "not distinguishable
from checking nothing", which Slice 22e retracted. The README's hot take was written
fresh instead.

| Criterion | Available | Scored | Lost |
|---|---|---|---|
| Problem & User Value | 15 | **12** | 3 |
| Agent Solution & Engineering | 30 | **23** | 7 |
| End to End Quality | 20 | **15** | 5 |
| Measured Improvement | 15 | **11** | 4 |
| Reproducibility | 15 | **10** | 5 |
| Hot Take / Insights | 5 | **3** | 2 |
| **Total** | **100** | **74** | **26** |

Everything below that says "verified" was run against this tree while scoring, not
read off a file. Those runs are listed in [What was executed](#what-was-executed).

---

## Problem & User Value — 12 / 15

> *A strong project solves a meaningful problem for a clearly defined user.*
> *Who experiences the bottleneck and why does solving it matter?*

**Evidence for.**

- `README.md:18-31` — the problem with five documented precedents (SWE-bench ×3,
  WebArena, tau2-bench), each with what was wrong and that a human found it by hand.
  This is a real bottleneck with a paper trail, not a hypothesis.
- `README.md:32-50` — the incumbent's ceiling, established by running the real
  `gymnasium` and `stable_baselines3` checkers (`scripts/real_check_env.py`) rather
  than a model of them, including a correction where an earlier claim about them was
  wrong.
- `README.md:52-92` — two defects in shipping software that this repo did **not**
  plant: `inspect_evals` 0.18.0 `paws` scoring a constant string `"yesno"` at
  8000/8000, and `openenv`'s `textarena_env` accepting `seed` and ignoring it. Both
  verified from the upstream project's own code with Assay out of the loop. This is
  the strongest single piece of evidence in the submission that the problem is real.
- `src/assay/costs/profiles/*.yaml` — four cost profiles, each describing a distinct
  caller (`research-run`, `production-training`, `benchmark-publication`, `flat`).

**Deductions — 3 points.**

1. **−2: there is no defined user.** Page 7 asks the README to *"introduce the
   intended user and explain their current bottleneck."* `README.md:20` names "labs
   and vendors" collectively and never gets more specific. There is no section
   describing one person, what they do today instead, how long it takes them, or
   what they currently do when they suspect an environment is broken. The closest
   thing to a user story in the repo is `src/assay/costs/profiles/research-run.yaml:3-6`
   — and the README never surfaces it.
   *To earn it back:* a "Who this is for" section at the top of the README naming a
   concrete role, the workflow they run today, and the point in that workflow where
   Assay is invoked. Lift the four profile descriptions into it.
2. **−1: the value is denominated in a unit nobody grounded.**
   `src/assay/costs/profiles/research-run.yaml:8` sets a missed CRITICAL at 120
   "engineer-hours-equivalent". Every headline number — the 2576.0 saved against
   `check_env` — scales linearly with that constant, and nothing derives it. Page 4's
   suggested "human time per task" and "cost per task" rows are not reported anywhere.
   *To earn it back:* one paragraph deriving the miss costs from something observable
   (the 93-developer SWE-bench Verified triage is already cited at `README.md:26` and
   is a real number), or a sensitivity sweep showing the ranking is stable across a
   range of CRITICAL costs.

---

## Agent Solution & Engineering — 23 / 30

> *A strong solution uses agents purposefully and is technically sound.*
> *Which design choices helped the agent solve the problem?*

**Evidence for.**

- Eleven probe families (`README.md` § *The probes*), ten deterministic and one agentic. The
  boundary is a design choice and it is argued: no LLM judge scores anything, the
  Challenger only proposes actions, and the ground truth it is scored against is held
  by the probe and never shown to the attacker.
- The agentic arm is shown to be load-bearing rather than decorative, by ablation:
  `README.md:204-208` — scripted misses, `qwen3:8b` misses, `claude-cli` finds the
  exploit at turn 8 with gap 1.00. `results/trajectories/01-*` and `03-*` are the two
  runs side by side.
- And then measured for reliability rather than claimed: `README.md:254-259`,
  3 of 4 runs, from `scripts/challenger_reliability.py`.
- One adapter protocol over four ecosystems — `src/assay/adapters/{inspect_ai_adapter,harbor,openenv,spec,tau2}.py`.
- `src/assay/sandbox.py:194-372` — the approval gate. `current_approver()` is the single place that decides and its default is a prompt showing image, command, mounts, network and every limit before asking; with no terminal to ask at it refuses. Unattended running is an explicit escape (`assay audit --yes`, `ASSAY_APPROVE_ALL=<reason>`) and is stamped on the Environment Card. This used to read "fail-closed by default" while `_harbor_corpus.py` hard-coded `AutoApprove` on the shipped path — see `docs/changelog/98-approval-gate.md`.
- Invariants enforced as tests that read the source, not as comments: no challenger
  module may reference `true_completion` (`docs/CHANGELOG.md` Slice 4); the scripted
  log may not record a score the attacker never saw (Slice 11b).
- **Verified: 493 passed, 18 skipped, 0 failed, exit 0, 177 s** on this machine with
  Docker up.

**Deductions — 7 points.**

1. **−3: the headline result is produced with the agent switched off.**
   `scripts/full_run.py:95-99` defaults `--challenger` to `scripted`, and
   `results/full_run.json` was produced that way — I re-ran it and it reproduces
   byte-identically. Assay's 0.957 recall in the headline table is 44 of 46 defects
   found by deterministic Python. The two it misses are precisely the two the agentic
   arm exists to close (`README.md:197-198`). So in the number this submission rests
   on, the agent contributes zero. That is disclosed and the ablatability is
   deliberately argued (`full_run.py:98-99`), but this is the *Agentic Workflows*
   hackathon and the measured artefact contains no agent.
   *To earn it back:* publish a second headline row, `assay+claude-cli`, over the same
   24 environments, with its own cost and wall-clock. The composition path already
   exists at `scripts/full_run.py:129-139`; nothing new needs writing.
2. **−2: two known correctness gaps in the agentic arm are open, and one of them is
   the exact failure the tool exists to detect.**
   - `README.md:239-246`: a Challenger run in which every reply is unparseable, or
     every reply is a `reset`, still exports as a clean PASS over an empty attempt
     list. An arm that could not speak is reported as an arm that found nothing. This
     is a vacuous check inside the auditor.
   - `README.md:266-269`: the probe runs the Challenger once per environment, so a
     card can read `VALID` on an environment a second attempt would have broken —
     while the repo's own reliability measurement says the attempt succeeds 3 times
     in 4.
   *To earn them back:* make `PromptedChallenger.attack` return
   `(attempts, exhaustion_reason)` and have the probe report `NOT_APPLICABLE` for the
   two remaining routes as it already does for the third; add `--challenger-passes`
   and report the probe verdict as a rate.
3. **−1: the learned agent failed and is unrunnable.** `README.md:271-283` is an
   honest negative result and the diagnosis is unusually good (`docs/CHANGELOG.md`
   Slice 20p: `pct_in_band_10_80` = 0.0467 against a ~20% floor). But
   `docs/changelog/40-grpo-challenger.md` plus Slice 20n record that no checkpoint
   survives and both spot instances are gone, so nobody can reproduce or resume it.
   *To earn it back:* push the LoRA adapter and `rewards.jsonl` somewhere fetchable
   and reference it, or state plainly in the README that the artifact does not exist.
4. **~~−1: no CI.~~ Earned back.** This deduction said *"there is no `.github/` in
   the tree"*. There is: `.github/workflows/ci.yml`, with two jobs — the suite, and a
   `results-are-reproducible` job that re-runs the corpus and diffs it against the
   committed arms, which is the harder of the two to fake. The snapshot banner at the
   top of this file covers measurements that have since moved; it does not cover a
   deduction that is **wrong on its face**, and leaving it standing would be scoring
   ourselves against a tree that no longer exists.

---

## End to End Quality — 15 / 20

> *Completes a realistic and self-contained execution and produces a final result the
> user can use, with the finish of something a person would sign their name to.*

**Evidence for.**

- The execution is real and self-contained. **Verified:**
  `assay audit inspect/always-correct` → `verdict: INVALID`, 22 findings with
  severities, 4 `NOT_APPLICABLE` each with a reason, exit **1**.
  `assay audit fixture/healthy` → `verdict: UNVERIFIED`, exit **1**. Both match
  `docs/REPRODUCTION.md:224-229`.
- `results/example-card.md` is a genuine deliverable a reader can evaluate without
  running anything: verdict, coverage counts, findings by severity, signature.
- `space/app.py:1-13` — the design constraint is stated and it is the right one: an
  empty card must never read as a clean bill of health, so probes that could not run
  render first, at the same visual weight as findings.
- The prose reads as a person's. It argues, it retracts (`README.md:126-129`,
  `README.md:150-154`, `README.md:458-471`), and it publishes the cost profiles under
  which the tool loses (`README.md:174-195`). Nothing here reads as an AI draft.

**Deductions — 5 points.**

1. **−2: a judge cannot find three of the four deliverables from the README.**
   `README.md` never links `docs/REPRODUCTION.md`, never links `docs/CHANGELOG.md`,
   never links `docs/VIDEO.md`, and never mentions `docs/` as a place to look. The
   only doc it links is `docs/LINEAGE.md`, at line 510, second-to-last section. The
   Improvement Changelog is correctly titled (`docs/CHANGELOG.md:1`) and 389 lines of
   genuinely good record — and it is invisible.
   *To earn it back:* a "Start here" table immediately after the status block:
   README → `docs/REPRODUCTION.md` → `docs/CHANGELOG.md` → `results/trajectories/INDEX.md`
   → the video.
2. **−1: no LICENSE file.** `README.md:514-516` and `pyproject.toml:7` both declare
   Apache-2.0; `ls LICENSE*` finds nothing. A repo that ships no licence text is not
   adoptable, and it undercuts ground rule 3.
   *To earn it back:* add `LICENSE` with the Apache-2.0 text.
3. **−1: the clone ships with junk in it.** `out.txt` and `expected.txt` are tracked
   at the repo root — droppings from a self-graded exploit run that escaped into the
   CWD. `.redteam_scratch/` tracks eight files including `truth_test.sh.bak` and
   `work/tests_test.sh` with an absolute `/Users/...` path baked in.
   `docs/CHANGELOG.md` Slice 12p sees all of this and declines to fix it, for a reason
   that was valid then and is not a reason to ship it.
   *To earn it back:* `git rm --cached out.txt expected.txt` and untrack
   `.redteam_scratch/`.
4. **−1: the usable artefact is a local CLI.** ~~No published URL appears anywhere in
   the tree.~~ **Partly earned back.** Three artifacts are now published: the
   [repository](https://github.com/caiotheodoro/assay), the
   [corpus dataset](https://huggingface.co/datasets/caiotheodoro/assay-corpus) and the
   [GRPO adapter](https://huggingface.co/caiotheodoro/assay-challenger-grpo).

   **The Space is still not deployed, and will not be.** Hugging Face returns
   HTTP 402 on repo creation: hosting a Gradio Space on free `cpu-basic` needs a
   PRO subscription. A static Space is free and cannot serve this app, because the
   probe battery runs server-side in Python — that is the product, not a detail of
   the hosting. So the deduction stands in part: there is no click-to-try demo, and
   "a final result the user can use" means `uv run assay audit`, plus two artifacts
   anyone can `load_dataset` or `from_pretrained` without cloning anything.

   The app itself is finished rather than abandoned: hardened against HTML
   injection, covered by 7 tests, gated by 9 pre-publication checks, and it runs
   with `python space/app.py`.

---

## Measured Improvement — 11 / 15

> *Demonstrates gains over a fair baseline and uses the changelog to connect each
> iteration with evidence.*

**Evidence for.**

- Five baselines, not one: the real incumbent `check_env`, `flag_everything`,
  `flag_nothing`, `stratified_random`, `always_modal_defect` (`README.md:117-124`).
  The incumbent was corrected *upward* after running the real checkers
  (`docs/changelog/18-real-incumbent.md`), which is the rare direction.
- Bootstrap CIs and paired differences on a shared resample, with the resampling unit
  and the reason for it recorded in the artefact itself (`results/intervals.json`:
  `"resampling_unit": "environment"` and a `"why"` field).
- **Every figure in `README.md:117-124` and `README.md:161-167` matches
  `results/intervals.json` exactly.** I checked them one by one.
- The profiles where Assay loses are published (`README.md:174-195`), including two of
  four where `flag_everything` wins outright.
- **Verified: the headline reproduces byte-identically.** `scripts/full_run.py`
  re-run against a copy of the committed `results/full_run.json` → no diff.
- `docs/CHANGELOG.md` is 389 rows across 21 merged fragments (all present, merge
  verified current), with removed experiments kept: Slice 3b removed before it was
  written, Slice 4a's first prompted run discarded rather than reported, Slice 20o's
  rejected shortcut, Slice 20h's instrument that could not resolve the question.

**Deductions — 4 points.**

1. **−2: the brief's own simple baseline is implemented and never scored.**
   Page 2 names "one direct prompt with basic instructions" and "one general purpose
   agent with basic tools". Both exist: `src/assay/baselines/llm.py:63` `DirectPromptArm`
   and `:115` `ToolAgentArm`, and `scripts/full_run.py:148-161` will run them over the
   whole corpus under `--llm-arms`. `results/full_run.json` contains neither — its arms
   are `assay`, `check_env`, `flag_everything`, `flag_nothing`, `stratified_random`,
   `always_modal_defect`. The two LLM arms appear only as single-environment
   trajectories on `toy-triage/weak_oracle` (`results/trajectories/06-*`, `07-*`),
   n=1, with no score. The comparison this rubric row asks for has no number anywhere.
   *To earn it back:* `uv run --extra adapters python scripts/full_run.py --llm-arms qwen3:8b`
   and put the two rows in the README's headline table. One command.
2. **−1: the improvement over the trivial floor is not established.**
   `README.md:169-172` says so itself: assay vs `flag_everything` is 50.0 with 95% CI
   [−309, 295]. By this project's stated rule a policy that ignores the input must not
   win, and at n=24 it has not been beaten. What separates cleanly is assay vs the
   *incumbent linter* — a real and well-earned result, but not the same claim.
   *To earn it back:* grow the corpus until the paired difference separates, or state
   the required n up front from the observed variance so the reader knows what would
   settle it.
3. **−1: the changelog does not have the shape page 3 asks for.** It starts at
   "Slice 1 | Core adapter protocol…" rather than at the simple baseline, and there is
   no Final row combining what worked. The last row is Slice 12p. Page 7 also asks it
   to *"close with the main failure mode and your hot take"* — it closes with a note
   about untracked files.
   *To earn it back:* prepend a Baseline row (`check_env` at 2816.0) and append a
   Final row plus the two closing sections.

---

## Reproducibility — 10 / 15

> *Gives another person a clear path to run the solution and baseline and reach the
> main result. Could they do it from a clean environment?*

**Evidence for.**

`docs/REPRODUCTION.md` is the best-executed document in the submission. Every timing
was measured against a cold cache on a stated machine (`:6-12`), the lockfile is
committed and the resolved versions are named (`:56-60`), the degradation table was
produced by actually stopping things rather than asserted (`:196-207`), what is not
automated is listed with the reason (`:271-278`), and the cost table names the one
figure in the file that was not re-measured (`:353-358`). I reproduced the headline
from it byte-identically.

**Deductions — 5 points.**

1. **−2: there is nothing to clone.** `docs/REPRODUCTION.md:51` is
   `git clone <repo>`, and `git remote -v` returned nothing. **Both fixed:** the
   tree is at `https://github.com/caiotheodoro/assay` and the clone line is real.
   Ground rule 10 asks that judges be given enough access to run the project; as the
   tree stands there is no address.
   *To earn it back:* push, and replace the placeholder with the real URL.
2. **−2: the guide's "expect exactly this" table is wrong, and states a claim the
   README retracts.** `docs/REPRODUCTION.md:104` says
   `check_env | 2832.0 | 0.000 | 0.000`. The tool prints `2816.0 | 0.043 | 1.000` —
   I ran it. `:107-109` then says `check_env` "scores identically to `flag_nothing`",
   which is exactly the claim `README.md:150-154` retracts as having been measured
   against a strawman. The reproduction guide is the retracted version. Under ground
   rule 9 this is a claim with no submitted evidence behind it, sitting in the one
   document whose entire job is telling a judge what to expect.
   *To earn it back:* regenerate that table from `results/full_run.json` — all six
   arms, not four — and delete the "identically to flag_nothing" sentence.
3. **−1: the test claims do not survive contact.** `docs/REPRODUCTION.md:179` promises
   `275 collected, 0 skipped, 0 failed, exit 0, 49–60 s` and adds "Nothing skips when
   everything is installed and running". **Measured here with Docker and Ollama up:
   493 passed, 18 skipped, 177 s.** All 18 skips are `tests/test_tau2_adapter.py`,
   which needs `--extra tau2` and `scripts/tau2_fetch.py` — neither appears anywhere
   in the guide. `:202` and `:206` carry the same stale 275.
   *To earn it back:* re-measure and update the three numbers; add the `tau2` extra
   and the fetch command to the setup section.
4. **−0 (noted, folded into 3): two headline sections cannot be reproduced from the
   guide.** `docs/REPRODUCTION.md` never mentions τ²-bench at all, though
   `README.md:308-334` reports recall 0.339 from it, and mentions ScienceAgentBench
   only under "not automated" (`:273-276`) with no command, though `README.md:336-359`
   reports 0/12 from it and `README.md:425-429` does give a command. Both `tau2` and
   `sab` extras exist in `pyproject.toml` and neither is in the guide's `uv sync`.
   *To earn it back:* a "Field evaluation" section in the guide with both commands,
   their extras, and their expected output.

---

## Hot Take / Insights — 3 / 5

> *A strong insight turns an observed failure mode into a practical lesson for
> building more reliable agents.*

**Evidence for.** The insights are first-rate and specific:

- `README.md:101-105` — the `textarena_env` defect was found only after two bugs in
  Assay's own determinism probe were fixed. It had been requiring a verifier OpenEnv
  does not have, and replaying an empty action list when no gold trajectory existed.
  *A vacuous check in the auditor, of exactly the shape it flags in environments.*
- `README.md:261-264` — "the Challenger finds this" was written on one run. That is
  pass@1 substituted for pass^k, in this project's own write-up, about the exact
  failure mode τ-bench exists to warn about.
- `docs/CHANGELOG.md` Slice 12i — `assay reap --dry-run` with no daemon reported a
  clean bill of health from a check that never ran. Absence of evidence reported as
  evidence of absence, in the tool whose thesis is that those differ.
- `README.md:356-359` — BenchGuard's precision denominator counts only findings on
  the 12 revised tasks, so a detector firing on 61 of 102 scores well on it. Assay's
  own trivial-floor rule rejected exactly that detector.

**Deductions — 2 points.**

1. **−2: none of it is where the rubric looks.** Page 7 requires the README to
   *"close with the main failure mode and your hot take."* `README.md` has no
   hot-take section, names no single main failure mode, and ends on Lineage and
   License. The only written hot take in the repo is `docs/VIDEO.md:148-155` — a
   script for a video that does not exist, in a file nothing links to. A judge scoring
   this row against the README finds nothing to score.
   *To earn it back:* two closing README sections. **Main failure mode** — the
   Challenger arm reporting a run that could not speak as a run that found nothing
   (`README.md:239-246`), which is the auditor committing the error it audits for.
   **Hot take** — lift `docs/VIDEO.md:148-155` verbatim; it is already written and it
   is good.

---

## The four required deliverables

Checked as a judge who has not been told where to look.

| # | Deliverable | Status | Finding |
|---|---|---|---|
| 1 | Complete solution code + clearly labelled Improvement Changelog | **Partial** | Code is complete and green (493 passed, verified). `docs/CHANGELOG.md:1` is titled exactly "Improvement Changelog", 389 rows, 21 fragments all merged (merge re-run and confirmed current), removed experiments kept. **But nothing in the README links to it**, it has no Baseline row and no Final row, and it does not close with the main failure mode and hot take as page 7 requires. |
| 2 | Reproduction guide for a clean environment | **Present, degraded** | `docs/REPRODUCTION.md` is thorough, measured and honest about its own limits. Not linked from the README. `:51` has no clone URL. `:104-109` states a number and a claim the README retracts. `:179` is ~2× off on test count and ~3× off on runtime. τ²-bench and ScienceAgentBench — two headline evidence sections — have no commands in it. |
| 3 | Solution video, up to five minutes | **MISSING** | No video file, no hosted link, no reference to one anywhere in the tree. `docs/VIDEO.md` is a script and shot list, and `:7-8` says outright: *"Numbers are left as `<>` until the final run freezes them. Nothing is recorded against numbers that can still move."* The numbers are frozen now — `results/` reproduces byte-identically. **This is a required deliverable and it does not exist.** |
| 4 | Representative trajectories for every agent used | **Met — the strongest deliverable** | `results/trajectories/INDEX.md` + 8 runs in both markdown and JSON. Readable from instructions to result, tool responses included, feedback that shaped the next step included. Three of eight are misses (`:18`, `:19`, `:21`); one is the same `claude-cli` arm failing the task it cracks in another run, shipped next to the hit so the hit is not read as a capability; one is the human checkpoint refusing (`:25`). Unparseable model replies are kept rather than dropped (`:22`). Agents with no run are named in their own table with the reason (`:27-33`). |

**On deliverable 3:** it is not a scored rubric row, but it is one of four things page 7
says to submit, and it is the only one that is simply absent. The script is finished.
Recording it is the single highest-value hour available.

---

## The ten ground rules, one by one

| # | Rule | Verdict | Evidence / gap |
|---|---|---|---|
| 1 | Build with tools and components you already know | **Met** | No constraint to violate. `docs/LINEAGE.md:27-35` names the sibling projects whose patterns were reused. |
| 2 | Make clear what existed before the competition and what you added | **Met, exemplary** | `docs/LINEAGE.md` splits four ways: prose written before but never executed (`:12-18`), specs with zero implementation (`:22-25`), sibling code read for pattern but not vendored (`:29-35`), and **one file vendored with attribution and a diff of what changed** (`:43-45`). Then "Added here" (`:56-72`). Caveat, not a deduction: the "before" artefacts live outside the submission (`study/…`, `keel/…`, `blotter/…`), so a judge takes the claim on trust. |
| 3 | Use every tool and component according to its license and service terms | **Partial** | Strong on other people's content: `src/assay/publish.py` + `tests/test_publish.py` make the redistribution guard *code*; ScienceAgentBench content is never republished; `third_party/` and `.tau2_cache/` are gitignored with the shas recorded so a reader clones them themselves (`.gitignore:23-36`). **Weak on its own:** no `LICENSE` file though Apache-2.0 is claimed at `README.md:516` and `pyproject.toml:7`, and no third-party licence inventory. |
| 4 | Keep consequential actions controlled through a sandbox or simulation. Add human approval before the action happens | **Met, exemplary** | `src/assay/sandbox.py:46-50` — `DenyAll` is the default, so an unattended Assay executes nothing. `:53-64` — `AutoApprove` must be passed explicitly and carries a `reason`, because "an approval nobody can account for later is the same as no approval". `:67-79` — `PromptApprover` shows image, command, mounts, network state and every limit *before* asking. Containment at `:94-104`: network off, read-only root, cpu/memory/pid/wall caps. `results/trajectories/08-*.md` puts the identical request to both approvers and shows the default **refusing** with nothing executed. |
| 5 | Make a qualified human reviewer part of any solution that could significantly affect someone | **Met in substance** | The card is advisory and fails closed: `UNVERIFIED` when a probe could not run, nonzero exit either way (verified on `fixture/healthy`), every `NOT_APPLICABLE` carries a reason. No LLM judges anything (`README.md:383-386`); the Challenger only proposes actions and a program scores them. Gap: the repo never states who the qualified reviewer is or what they are expected to do with a card — the reviewer is implied by the cost profiles rather than named. |
| 6 | Choose a legal and ethical use case that treats people and their data responsibly | **Met** | The subject is benchmark software. No personal data anywhere in the tree. |
| 7 | Use information you are allowed to share | **Met, better than required** | The line is drawn between a claim and a copy, in code: `tests/test_publish.py::test_a_verdict_about_third_party_software_may_ship`. Verdicts about `paws` and `textarena_env` ship; the environments do not, with `content_included: false` and a pointer upstream (`docs/CHANGELOG.md` Slice 10a-10b). |
| 8 | Keep credentials and private information outside the submission | **Met** | No `.env`, no tracked file with a credential-shaped name, and no `sk-`/`hf_`/`AKIA`/`ghp_` pattern in tracked content — grepped. |
| 9 | Connect every claim about your results to the evidence you submit | **Mostly met, one live contradiction** | Every figure in `README.md:117-124` and `:161-167` matches `results/intervals.json` exactly, checked one by one; the README even records where it previously got this wrong (`:126-129`) and where a claim was measured against a strawman (`:150-154`). **The contradiction:** `docs/REPRODUCTION.md:104-109` states `check_env 2832.0 / 0.000 / 0.000` and "scores identically to `flag_nothing`" — no submitted file supports either, and the tool prints `2816.0 / 0.043 / 1.000`. |
| 10 | Give judges enough access to run the project and reproduce the main result | **Yes** | `scripts/full_run.py` reproduces every deterministic arm of `results/full_run.json` byte-identically (the two LLM baseline arms need `--llm-arms qwen3:8b` and a live Ollama) and the suite is green at 593 passed. The gap was an address, not the software: there is now a public remote at `https://github.com/caiotheodoro/assay` and `docs/REPRODUCTION.md` clones it. |

---

## Fix first, by points per hour

Ordered by points recovered against effort. Items 1–5 are roughly two hours in total
and move the score from 74 to about 86.

| # | Fix | Where | Recovers | Effort |
|---|---|---|---|---|
| 1 | **Record the video.** The script is finished and the numbers are frozen. | `docs/VIDEO.md` → a file or a link | Deliverable 3 — currently the only absent required item | ~1 h |
| 2 | **Score the LLM baselines on the corpus and put them in the headline table.** `uv run --extra adapters python scripts/full_run.py --llm-arms qwen3:8b` | `scripts/full_run.py:148-161` already implements it; `README.md:117-124` | **+2** Measured Improvement | ~15 min |
| 3 | **Publish an `assay+claude-cli` headline row** over the same 24 environments, so the measured artefact contains an agent. | `scripts/full_run.py:129-139` already composes it | **+3** Agent Solution | ~30 min |
| 4 | **Fix `docs/REPRODUCTION.md:104-109`** — regenerate from `results/full_run.json`, all six arms; delete the "identically to `flag_nothing`" sentence. | `docs/REPRODUCTION.md` | **+2** Reproducibility, closes the rule 9 contradiction | ~10 min |
| 5 | ~~**Push and replace `git clone <repo>`.**~~ **Done.** | `docs/REPRODUCTION.md:53` | **+2** Reproducibility, rule 10 closed | done |
| 6 | **Add a "Start here" table** to the README linking the four deliverables. | `README.md`, after line 16 | **+2** End to End Quality | ~10 min |
| 7 | **Add "Main failure mode" and "Hot take" as closing README sections.** Lift `docs/VIDEO.md:148-155` verbatim. | `README.md`, after line 507 | **+2** Hot Take | ~15 min |
| 8 | **Add a "Who this is for" section** naming a concrete role and their workflow today; surface the cost-profile descriptions. | `README.md`, after line 17 | **+2** Problem & User Value | ~30 min |
| 9 | **Re-measure the pytest claims** (493/18/177 s) and add the `tau2` and `sab` extras plus their commands. | `docs/REPRODUCTION.md:52, 179, 202, 206` | **+1** Reproducibility | ~20 min |
| 10 | **Add `LICENSE`** (Apache-2.0 text). | repo root | **+1** End to End, closes rule 3 | ~2 min |
| 11 | **Untrack `out.txt`, `expected.txt`, `.redteam_scratch/`.** | repo root | **+1** End to End | ~5 min |
| 12 | **Close the two open Challenger gaps** — exhaustion reason, and `--challenger-passes` reporting a rate. | `src/assay/challenger/prompted.py`, `src/assay/probes/hackability.py` | **+2** Agent Solution | ~3 h |
| 13 | **Add CI** — `pytest -q`, plus `full_run.py` with a diff-check against committed `results/`. | `.github/workflows/` | **+1** Agent Solution / Reproducibility | ~30 min |
| 14 | **Add Baseline and Final rows** to the Improvement Changelog. | `docs/CHANGELOG.md` via `docs/changelog/` | **+1** Measured Improvement | ~15 min |
| 15 | **Ground the cost weights** — derive the miss costs from something observable, or sweep them and show the ranking is stable. | `src/assay/costs/profiles/`, `scripts/intervals.py` | **+1** Problem & User Value | ~2 h |

---

## What was executed

Every "verified" above came from one of these, run against this tree while scoring.

| Command | Result |
|---|---|
| `uv run --extra dev --extra adapters --extra sweep --extra openenv pytest -q` | **493 passed, 18 skipped, 0 failed, exit 0, 177 s** (Docker up) |
| the same with `-rs` | all 18 skips are `tests/test_tau2_adapter.py`, needing `--extra tau2` + `scripts/tau2_fetch.py` |
| `uv run --extra adapters --extra openenv python scripts/full_run.py` | `corpus: 24 environments, 46 planted defects`; assay 240.0 / 0.957 / 1.000; check_env 2816.0 / 0.043 / 1.000; **`results/full_run.json` byte-identical to the committed file** |
| `uv run --extra adapters assay audit inspect/always-correct` | `verdict: INVALID`, 22 findings, 4 `NOT_APPLICABLE` with reasons, **exit 1** |
| `uv run --extra adapters assay audit fixture/healthy` | `verdict: UNVERIFIED`, 11 PASS / 0 DEFECT / 1 `NOT_APPLICABLE`, **exit 1** |
| `uv run python scripts/merge_changelog.py` then diff | `docs/CHANGELOG.md` already current against all 21 fragments |
| `git remote -v` | *(empty)* |
| `ls LICENSE*` | no match |
| `git ls-files` + credential-pattern grep | no `.env`, no key-shaped strings in tracked content |
| figure-by-figure check of `README.md:117-124` and `:161-167` against `results/intervals.json` | every figure matches |
| the same check against `docs/REPRODUCTION.md:104` | **does not match** — guide says 2832.0 / 0.000 / 0.000, tool says 2816.0 / 0.043 / 1.000 |
