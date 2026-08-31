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
  submission. The margin against `flag_everything` went 50.0 → 36.0 → 326.0 → **351.0**,
  and it is now **statistically separated**: 95% CI [263, 404], resampling environments
  (n=28) rather than defects. The cost crossover moved 145 → 942 → **1099.53**, so the
  headline survives an 816% error in the one number that was openly a guess. Four cost
  profiles are swept; Assay wins all four and **separates on all four**. Not 15/15, and
  the reasons got sharper rather than softer: the corpus is still only 6 genuinely
  third-party environments out of 28, only 3 of those 6 carry ground truth decided
  elsewhere, and **77.0 of the 351.0 margin is arithmetic rather than detection** —
  two probe families and two τ² environments made the floor worse, which is a different
  fact from the detector getting better. Against the taxonomy and corpus this was first
  measured on, the comparable margin is 274.0.
- **Reproducibility, 10 → 12.** The blocker at 10 was that there was no address
  to clone — that is fixed; `scripts/full_run.py` reproduces every deterministic arm of
  `results/full_run.json` byte-identically (verified from a fresh tree; the two LLM
  baseline arms need `--llm-arms` and a live Ollama), and `docs/REPRODUCTION.md` has
  cold-cache timings and a degradation table built by actually stopping things. Two new gates in
  `tests/test_published_claims.py` now check that every path cited in the
  reviewer-facing docs resolves, and that the suite size those docs advertise is the
  suite size that ran. Scored **12**, not 13, because the full headline still wants
  Docker and Ollama up. (The "no hosted demo to fall back on" half of that reason is
  closed: [`caiotheodoro/assay-demo`](https://huggingface.co/spaces/caiotheodoro/assay-demo)
  runs the battery in the browser. It does not lift the score, because it audits submitted
  specs rather than reproducing the headline — Docker and Ollama are still what that wants.)
- **End to End Quality, 15 → 16.** The suite is now **746 passed / 0 skipped**
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
(`docs/COVERAGE.md`), and the GRPO Challenger does not beat the scripted floor. The
"no hosted demo" item that stood here is closed:
[`caiotheodoro/assay-demo`](https://huggingface.co/spaces/caiotheodoro/assay-demo) runs
the battery in the visitor's browser on a free static Space. HTTP 402 for a *Gradio*
Space on the free tier is still true and still why `space/app.py` is local-only.

**On the number itself.** 82 is a self-score by the people who wrote the thing, marked
hard, and an independent reviewer is entitled to a different one. An independent pass
run cold against this tree scored it **75**, taking 3 more points off Reproducibility
and 3 off Agent Solution; its Reproducibility deduction was the `byte-identically`
overclaim now corrected above, and its Agent Solution deduction is the second one below,
which is a matter of judgement rather than fact. Both numbers are published; the lower
one was not solicited to be flattering and is the more useful of the two.

---

## The 74 / 100 snapshot this replaces

[`docs/history/RUBRIC-2026-08-29.md`](history/RUBRIC-2026-08-29.md) is the previous
scorecard, kept verbatim: every criterion, the four required deliverables, the ten ground
rules one by one, and the fix-first ordering. **It is superseded, and it scores a tree
that no longer exists** — it predates `docs/RED-TEAM.md` breaking twelve published claims,
and its own header lists the numbers that have moved since. Kept because a rubric quietly
rewritten after the fixes it prescribed would no longer be evidence of anything, and the
drift between the two scores is the calibration record. Which deductions closed:
`docs/changelog/73-remediation.md` through `docs/changelog/80-floor-of-the-field.md`.
