# Solution video — the next cut, not yet recorded

**Status: written, not recorded.** Deliberately, and the distinction matters.
[`docs/VIDEO.md`](VIDEO.md) is the script of the video that *exists*
([assay.mp4](https://huggingface.co/datasets/caiotheodoro/assay-corpus/blob/main/video/assay.mp4),
4:36.03, hosted). It is left alone. Editing a shooting script after the shoot
turns it into a description of a video nobody made, which is the exact failure
mode this file's predecessor was caught in — it claimed "written, not recorded"
for longer than that was true, while the rubric on the same tree already
recorded the render.

So this is the script for the cut that replaces it, and it says plainly that it
has not been shot.

**What changed since the shipped cut, and why a re-record is needed:** the
submission acquired a second agent, two probe families, an approval gate on the
shipped path, and a green CI — and the video's central claim ("eight of nine
probes are deterministic; the one agent got compiled into a script") is now only
half the story. A judge who watches the current cut and then reads the README
hits a contradiction, and a contradiction between deliverables costs more than a
slightly dated video.

Five minutes, hard cap. The brief asks for six things: the problem and the
simple baseline, one realistic execution start to finish, the final comparison,
the changelog, the change that contributed most, and one experiment that was
removed. Every one has a beat below.

---

## 0:00–0:35 — The problem, with receipts

**On screen:** three citations, then a terminal.

> Nobody QAs the benchmark. SWE-bench Verified needed ninety-three human
> annotators to certify tasks that had already shipped. τ²-bench got
> seventy-five ad-hoc fixes in a verified fork. WebArena and three separate
> SWE-bench audits found the same class of thing: the environment was wrong, and
> the numbers everyone had published were measured against it.
>
> If you are about to spend a week of GPU on an RL environment, the thing you
> cannot check today is whether the environment can be gamed, whether its
> verifier can fail at all, and whether the answer is sitting in the input.

**Cut to:** `assay audit harbor/self-graded` → `INVALID`, exit 1.

> That exit code is the product. It blocks a training run.

## 0:35–1:10 — The baseline, and the number

**On screen:** the arms table from `results/full_run.json`.

> The honest baseline is not another tool. It is flagging everything. A detector
> that cannot beat "assume every environment is broken" has not earned its
> runtime.
>
> Twenty-six environments, fifty planted defects, one cost model. Flag everything
> scores 366. Assay scores 40. The saving is separated at 95% — the interval is
> bootstrapped over environments, not defects, because a verifier that always
> passes fails six probes at once and resampling defects would count that six
> times.

**Say the weakness out loud, on screen:**

> Twenty-two of those twenty-six environments are ours. The four that are not are
> named, and the split is published. This is a controlled experiment, and it is
> labelled as one.

## 1:10–2:25 — One realistic execution, end to end

**Single unbroken take.** `assay audit` on a real `inspect_evals` task.

> One environment. The battery runs eleven probe families. Watch what it says it
> could *not* check — that table is not an apology, it is the deliverable. A
> probe that reports NOT_APPLICABLE costs a reader nothing. A probe that reports
> CRITICAL on a healthy environment costs them the tool.

**Show the card:** verdict, every finding tied to a probe result, content digest.

**Then the approval prompt, un-cut:**

> Before it ran anything it asked. Image, command, mounts, network state, every
> limit — then a human says yes. Until three days ago the shipped corpus path
> hard-coded a standing approval and the README claimed deny-by-default. A judge
> found it. `docs/changelog/98-approval-gate.md`.

## 2:25–3:15 — The change that contributed most

**This is the beat the brief asks for, and the answer changed.**

> The largest single improvement was not a probe. It was pricing — moving from
> "how many defects did you find" to expected loss under a cost model, which is
> what took the margin from 50 to 274 and made it separate at all.
>
> The most *interesting* change is newer, and it is where the agent lives now.

**On screen:** `personality_BFI`, verdict INVALID, 25 × `INVERT_PASSES`.

> This is the Big Five personality inventory, and Assay calls it critically
> broken. Assay is wrong. A personality inventory has no correct answer, so a
> scorer that checks the response format is the right design. The finding is
> mechanically true and semantically false, and no amount of better probe
> engineering fixes it, because the thing being got wrong is *meaning*.

**Run it again with `--auditor`:** INVALID → the finding withheld, with the
quote that justifies it printed on the card.

> That is the division the whole repo now argues for. **The script owns
> mechanism. The model owns meaning.** And it is measured, not asserted:
> `results/semantic_gate.json`, twelve environments that have a correct answer
> plus the one that does not. Zero false positives on both backends.

## 3:15–4:00 — What was removed, and what failed

**Two removals, both required by the brief and both real.**

> Removed: the GRPO-trained Challenger. It is a published negative — trained,
> measured, did not beat a two-second script, and the artifact is on the Hub
> labelled as a negative result.
>
> Also removed, and this one is newer: I tried to have the agent close the
> corpus's one remaining miss. `inspect_evals/boolq`, a shortcut leak the probe
> skips because the suite ships no train split. The agent named the fields
> correctly — both backends agreed, unprompted — and synthesized the split. The
> probe still returns PASS.

**On screen:** `per_part_accuracy` 0.75 for both parts, majority rate 0.75.

> Because the partial-input baseline is a lookup table over exact values, and
> thirteen of thirteen training questions are unique. Zero of the twelve
> evaluation questions are in that table. Every item takes the majority fallback.
> The pre-registered reason for that miss — no train split — is true, and it is
> not the binding constraint. A different probe closes it. A better adapter never
> could.

## 4:00–4:35 — The auditor, audited

> This repo red-teams itself and publishes what breaks. Twelve of its own claims
> broke and are printed unedited. Three were behavioural bugs in the tool.
>
> The newest one is my favourite, because the machine caught it and nobody
> looked. CI had been red on every single push since the day it was added.

**On screen:** the run list, five red X's, then the workflow comment.

> The workflow says: *"Docker and Ollama are absent here, and that is the point:
> the suite must skip with a reason rather than fail."* GitHub's runners ship a
> running Docker daemon. So the skip guards never fired, ten tests ran in an
> environment nobody had tried, and they failed for a reason worth knowing: the
> sandbox drops every capability including `CAP_DAC_OVERRIDE`, so a container
> cannot read a directory it does not own — and Docker Desktop on macOS never
> consults the mode, so the suite was green on the only machine it had ever run
> on.

**Cut to:** green CI.

## 4:35–5:00 — Hot take

> Nobody QAs the benchmark — including the people building the tool that QAs
> benchmarks. Every failure in this project has the same shape as the failures it
> looks for: a check that cannot fail, a green light bought by not looking, a
> claim that outlived its evidence.
>
> The lesson I would take to the next agent I build is narrower than that, and I
> only learned it by measuring. A small model, asked whether an environment has a
> correct answer, writes down a correct example of two valid answers and then
> labels the environment wrong anyway — in three runs out of three. It can make
> the observation. It cannot make the decision. So take the observation from the
> model, make the decision in code, and require them to agree before anything
> moves.
>
> That is the whole design, and it is the reason a weak model here loses recall
> and cannot lose precision.

---

## Shot list

| # | Shot | Source |
|---|---|---|
| 1 | three citations | `README.md` § the problem |
| 2 | `assay audit harbor/self-graded` → exit 1 | live terminal, approval prompt un-cut |
| 3 | arms table, 366 vs 40 | `results/full_run.json` |
| 4 | corpus split, 22 of 26 | `results/corpus_splits.json` |
| 5 | Environment Card | `assay audit --card` |
| 6 | `personality_BFI` INVALID → withheld | `--auditor`, both takes |
| 7 | semantic gate table | `results/semantic_gate.json` |
| 8 | boolq per-part accuracy | `results/na_resolution.json` |
| 9 | five red CI runs, then green | `gh run list` |

## Recording rules

Carried over from `docs/VIDEO.md` because they were right:

- Every number on screen comes from a committed artifact, read live where possible.
- No take is re-shot to hide a failure. The approval prompt and the CI red are
  the point, not blemishes.
- If a figure moves before the shoot, the script changes before the camera does.
