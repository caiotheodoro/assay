## Slice 44: the gate re-measured at k=3, and it was wrong in both directions

**What and why.** `results/semantic_gate.json` was the only headline artifact in
this repository that **nothing could regenerate**. No script wrote it, and
`docs/REPRODUCTION.md` — the document whose whole job is to say how every number
is produced — never mentioned it. A cold judge found that and scored it as a
ground-rule 9 failure, correctly: a measurement with no producer is a claim, not
evidence, in a project whose entire argument is the difference between those two.

`scripts/semantic_gate.py` now produces it, and running it properly changed the
result.

**Evidence.** 15 environments — 2 with no correct answer, 13 with one — at three
runs each per backend.

| backend | true positives | false positives | wall clock |
|---|---|---|---|
| `claude-cli:sonnet` | **6 / 6 runs** | **0 / 39 runs** | 378.5s |
| `ollama:qwen3:8b` | 4 / 6 runs | **2 / 39 runs** | 261.1s |

**The old file said `claude-cli` 1-of-1 and `qwen3:8b` 0-of-1, at k=1, over 13
environments. Both halves of the weak backend's row were wrong.** It withholds
far more often than one draw suggested — 4 of 6, not 0 of 1 — *and* it produces
false overrides, which one draw did not show at all. A single run of a
stochastic classifier reported as a capability is precisely the error this
repository exists to point at in other people's benchmarks, and it was sitting
in the README.

**What changed in the corpus, and what could not.** The negatives went 12 → 13
and the positives 1 → 2. `inspect_evals/bbq` is the addition worth naming: a
bias benchmark whose questions read like matters of opinion and have documented
correct answers, so it is where a gate pattern-matching on *subject matter*
rather than on the structure of the task would show. It does not fire on either
backend.

n_positive is 2 and that is a ceiling rather than a choice. Of the 246 tasks
`inspect_evals` registers, a deliberately broad lexical filter matches four:
`personality_TRAIT` is a gated dataset, `writingbench` is scored by an LLM judge
and this project scores nothing with a judge, and `bbq` turned out to belong in
the other column. Environments with no correct answer are *rare*, which is part
of why this false positive went unnoticed long enough to be worth writing about.

**Decision.** Kept, with the corrected numbers and the correction stated rather
than quietly swapped in. The design conclusion is unchanged and is now better
supported: the conjunction is what makes a weak backend degrade to doing
nothing, and 2 false positives in 39 runs is what "degrades" looks like when
measured properly instead of asserted.

**What it cost to learn.** Twice now the interesting result has come from
running something three times instead of once — the reliability run that made
the Challenger's hit a 3-of-4 rate, and this. The lesson did not transfer the
first time because nothing forced it to. `--k` defaults to 3 here so the next
person does not have to remember.
