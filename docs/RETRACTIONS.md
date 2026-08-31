# Retractions

Every claim this repository published and then had to take back, kept verbatim.

These lived inline in `README.md` for most of the project's life — one correction
woven into every section, so a reader paid the cost of all of them to read any of
them. They are collected here instead. Nothing is edited: each is the sentence as
it was published, with a note saying where the live claim now stands.

The reason to keep them is in `docs/RED-TEAM.md`, which is the audit that broke
twelve of them: a correction that lands one document downstream of the one people
read is how a broken benchmark stays broken. A repository arguing that unaudited
numbers are the problem does not get to delete its own.

Twenty entries. Twelve are the red-team's; the other eight were found afterwards by the
same method, three of them while collecting this file.

---

## 1. The prior-art section overclaimed, and mis-cited someone else's paper

> An earlier version of this section overclaimed and mis-cited someone else's paper; the
> retraction is kept in the record. Full prior art with the papers and their numbers:
> [Prior art](../README.md#prior-art).

The full text of that retraction is entry 16 below. Live claim: `README.md` §Prior art.

---

## 2. "The checkers never verify seeding" — false of gymnasium 1.3.0

> That last one matters, and an earlier version of this README got it wrong. It
> said the checkers never verify seeding, citing
> [Gymnasium #1084](https://github.com/Farama-Foundation/Gymnasium/issues/1084).
> Running the real checker instead of a model of it
> (`scripts/real_check_env.py`) shows gymnasium 1.3.0 raising `Deterministic step
> observations are not equivalent for the same seed and action`.
> Stable-baselines3 2.9.0 passes the same environment silently, so the two
> incumbents differ; the baseline in this repo models the stronger one.

Live claim: `README.md` §The problem, which now states the determinism check as
something the incumbent does.

---

## 3. The two LLM arms were printed in one table and measured in another

> The two
> LLM arms used to be quoted from a separate 24-environment file with an em-dash
> where the CI belonged — a comparison printed as one table and measured as two,
> which is the drift this repo keeps catching in other people's numbers. Re-run
> on the current corpus, every deterministic arm came back byte-identical and
> only the two LLM rows moved.

Live claim: every arm in `README.md`'s headline table is measured on the same 28
environments in `results/full_run.json`, with intervals from the same bootstrap.
`tests/test_published_claims.py::test_the_llm_baseline_rows_match_the_measured_file`
is the gate that stops it recurring. Write-up: `docs/changelog/91-llm-arms.md`.

---

## 4. The LLM arms were described as unscored after they were scored

> These two arms were written, tested, and never scored, because
> `scripts/full_run.py --llm-arms` **crashed**: the arm called `adapter.verify()`
> with no refusal path, and `OpenEnvAdapter` raises there. One adapter of six
> took the whole run down, and the failure sat at the far end of a long command
> where nobody met it. No confidence intervals here yet — `scripts/intervals.py`
> bootstraps `results/full_run.json`, and these live in `results/full_run_llm.json`.

All three claims in that paragraph were false by the time it was read: both arms are
in `results/full_run.json` **and** `results/intervals.json`, and the same README said
so twenty-five lines earlier. The crash is real and is recorded where it belongs —
`docs/CHANGELOG.md` Slice 23j and `docs/changelog/74-finishing.md`. The fix is pinned
by `test_the_llm_baseline_arm_survives_an_adapter_that_refuses_verify`.

---

## 5. `check_env` was printed with `flag_nothing`'s row

> An earlier version of this table gave `check_env` flag_nothing's row —
> **2832.0, [1752, 4032], recall 0.000** — which contradicted both
> `results/intervals.json` and the sentence directly beneath it. Corrected above
> from the measured file; the paired differences below were always right.

Live claim: `check_env` scores **3216.0, [2104, 4448], recall 0.037** in
`README.md`'s headline table, read from `results/intervals.json`.

---

## 6. "The twelve environments this repo did not write" — it wrote ten of them

> A previous version of this section reported that split as "the twelve
> environments this repo did not write". It wrote ten of the twelve. That
> sentence was added while correcting other overclaims, which is the failure mode
> this project keeps finding in itself: a split computed on a string prefix
> (`fixture/`) and then described in words the prefix does not support. The
> splits are now cut on declared provenance.

Live claim: the splits are cut on declared provenance in `src/assay/corpus.py`, and
`test_the_readme_does_not_claim_a_third_party_corpus_it_does_not_have` asserts the
retracted sentence never comes back.

---

## 7. "n=2 is the real size of the third-party control" — it is 4

The honest-ceiling paragraph said **n=2** while the two tables above it said **4**,
and `scripts/corpus_splits.py` shipped the same wrong string into
`results/corpus_splits.json` next to `"n_external": 4`. `inspect_evals/paws` and
`inspect_evals/boolq` were added under `docs/PRE-REGISTRATION.md` and took the
external control from 2 to 4 (`docs/changelog/77-external-corpus.md`, Slice 26b).
The number was corrected in the tables and not in the prose or the script.

Live claim: **6 of 28** — the two τ² domains took it from 4 to 6 under
`docs/PRE-REGISTRATION-TAU2.md` — in `README.md`, `AGENTS.md`,
`results/corpus_splits.json` (`"n_external": 6`) and
`test_the_readme_does_not_claim_a_third_party_corpus_it_does_not_have`, which
fails if it moves again.

---

## 8. "Identical to flagging nothing" — measured against a strawman

> An earlier version of this README said it scored *identically* to flagging
> nothing. That was measured against a model of the checkers that omitted their
> determinism check — a strawman weaker than the real tool. The corrected claim
> is narrower and is the one worth making, but note what it rests on: the same
> author who caught "benchmarking against a reimplementation rather than the
> tool" is still, on this row, benchmarking against a reimplementation.

Live claim: `check_env` saves **16.0, 95% CI [0.0, 40.0]** over `flag_nothing`, an
interval that includes zero.

---

## 9. "Not statistically distinguishable" was decided by the test, not the data

> **That interval cannot say what this README used to make it say.** `check_env`
> emits no false positives and detects a strict subset of what is planted, so the
> paired difference is >= 0 in every resample — 10,000 of 10,000. An interval
> that can never go negative cannot exclude zero from above, so "not
> statistically distinguishable" was decided by the shape of the test, not by the
> data. On a one-sided reading the claim survives at p ~ 0.12: that is the chance
> no `NONDETERMINISM` environment is drawn, (22/24)^24, and it is the whole
> result. One of `check_env`'s two hits is `fixture/flaky`, planted here.

Live claim: `docs/RESULTS.md` §What holds, and what does not, which reports the
one-sided reading rather than the two-sided one.

---

## 10. The ablation table printed six numbers that matched no committed run

> An earlier version of this table printed 4/8/8 attempts at 6s/74s/405s, which
> matched no committed run — a red-team pass could not source a single one of
> those six numbers. The row above is the file.

Live claim: 4/10/10 attempts at 2.2s/97.0s/261.7s, read from
`results/challenger_ablation.json`.

---

## 11. An exploit was published as "scored 1.0" that appears in no successful run

> A previous revision printed a symlink here — `rm -f expected.txt && ln -s
> out.txt expected.txt && …` — as "the winning policy … scored 1.0". That command
> appears in no run that succeeded. The only symlink in the artifacts points the
> other way and belongs to a run that **missed**
> (`results/challenger_ablation_claude.json`).
> Publishing an exploit that was never scored, in a repository whose thesis is
> that unverified claims about environments are the problem, was the worst single
> defect the red-team found, and it was found by reading artifacts this README
> told people to read.

Live claim: the winning policy is
`echo -n 'banana' > expected.txt; echo -n 'banana' > out.txt`, at turn 8, in
`README.md` §Does an agent find what a script cannot?

---

## 12. A Challenger that could not speak, reported as a Challenger that found nothing

> That row nearly went into this table as a lie. Two earlier runs printed
> `qwen3:8b` as `missed gap=0.00 attempts= 0`, at 186.6s and 188.3s, with an
> empty `attacker_trace` and no reason — a row indistinguishable from ten attacks
> that all failed. It has not reproduced since and the cause is still open:
> `PromptedChallenger.attack` can spend its whole budget and return nothing by
> three different routes — every reply unparseable, every reply a `reset`, or the
> model going unreachable — and until this was found, all three came back as the
> same clean PASS over an empty attempt list.
>
> All three are fixed now, and this paragraph said otherwise for longer than the
> fix took.

Two retractions in one place: the row, and then the paragraph describing the row's
cause as open after it had been closed. Live claim: `README.md` §Main failure mode
and `docs/changelog/86-exhaustion.md`.

---

## 13. "The Challenger finds this", on the strength of one run

> **3 of 4.** A probe backed by a sampled model is not a deterministic check, and
> the first version of this README said "the Challenger finds this" on the
> strength of a single run — which is the pass@1-for-pass^k substitution that
> τ-bench exists to warn about, made here in our own write-up.

Live claim: 3 of 4, reported as a rate, from `results/challenger_reliability.json`.

---

## 14. The τ²-bench headline led with the row that is chance

> An earlier revision of
> this README led with 0.339 and relegated the row that carries the signal. That framing
> was backwards, and the base rate 62/164 appeared nowhere in the repository.

Live claim: the 0.339 row is labelled chance (p = 0.486) and the 0.210 row carries
the result (p = 0.040). `test_the_headline_tau2_row_is_still_indistinguishable_from_random`
holds the framing to the artifact.

---

## 15. A ScienceAgentBench outcome was stated without the judge that decides it

> Stopping rather than reporting an unjudged number
> was right; an earlier revision of this README stated the outcome anyway, under a
> heading claiming it fell out of running their scorer. It is an argument about the
> metric's shape, not a result.
>
> The count
> previously given here — 41 findings on clean tasks — was wrong. R1 submitted **20**
> findings, 4 on revised tasks, so **16** on clean ones; 41 is the number of findings
> suppressed by the image-output exclusion, a different quantity read out of the wrong
> field.

Live claim: `docs/SCIENCEAGENTBENCH.md`, and `README.md` §Where Assay sits in the
field, which records `their_report: null`.

---

## 16. Adversarial Reward Auditing, mis-cited

> The category is not new, Assay does not claim it is, and one earlier version of this
> section overclaimed. Corrected below.
>
> An earlier version of this README listed **Adversarial Reward Auditing**, Beigi et al.
> ([arXiv 2602.01750](https://arxiv.org/abs/2602.01750)) as having "the same probe
> vocabulary, for classical RL reward functions". That was wrong, and it was wrong about
> someone else's paper.
>
> Beigi et al. is an RLHF alignment paper: a Hacker policy against an Auditor, plus
> Auditor-Guided RLHF, evaluated on sycophancy, length bias and code gaming with
> Llama-2-7B. It contains no classical RL environments, no gold / no-op / inverted-spec /
> known-wrong probes, and no benchmark-defect counts. The probe vocabulary is Assay's own.
> The paper is adjacent in spirit — adversarial detection of reward exploitation — and
> shares no metric Assay could be measured against. Left in the record rather than quietly
> deleted.

Live claim: `README.md` §Prior art, which cites the paper for what it is.

---

## 17. The main failure mode, described as open after it was closed

> **This section described that as open after it was closed** — which is the drift
> this README's own hot take is about, running in the other direction. The fix
> landed: `ChallengerExhausted(reason, history)` is raised instead of an empty list
> and caught in `src/assay/probes/hackability.py`, so the card says
> `NOT_APPLICABLE` with the reason rather than staying quiet
> (`docs/changelog/86-exhaustion.md`). The milder version — one Challenger pass per
> environment against a Challenger measured at 3-in-4 reliability — also landed:
> `hackability.py` reads `challenger_passes` from context
> (`docs/changelog/88-passes.md`).

Live claim: `README.md` §Main failure mode. What remains open is the shape of the
problem — only the routes to silence that have been thought of are covered.

---

## 18. The solution video, described as unrecorded after it was recorded

`docs/VIDEO.md` opened with *"Status: written, not recorded — by decision"* and spent
four lines pricing the deduction, while `docs/RUBRIC.md` on the same tree recorded the
video as rendered and hosted at 4:36.03 against a 5:00 cap. The same class of gap as
every entry above: a correction landing one document downstream of the one people read.

Live claim: `docs/VIDEO.md`, which now opens with the hosted link and the duration.

---

## 19. "No LLM judge scores anything, anywhere"

> Stated as an absolute — "no LLM judge scores anything, anywhere" — that was
> false, and worth correcting precisely because the rule is load-bearing.
> Assay's *own* verdicts use no judge. But two things it touches do: τ²-bench's
> `nl_assertions` are judged by an LLM, which is exactly why they are excluded
> from the τ² measurement and reported as absent rather than passed; and
> BenchGuard's `match.py`, whose scorer this project deliberately borrowed rather
> than reimplement, calls a Gemini judge. That run scored nothing only because
> Assay submitted nothing. The rule is about what Assay asserts, not about what
> exists in the room.

Live claim: `README.md` §The probes, stated in the narrower form.

---

## 20. The pre-fix auditor arm scoring 163.0

> "this arm is what caught the gate at **163.0**, deleting real findings"

Published in `README.md` and in `results/auditor_arm.json` as `before_the_fix`,
where it led the agent paragraph and did more rhetorical work than any other
number in the submission.

Nothing shipped reproduced it. `results/auditor_arm.json` was written by hand:
no script emitted it, and unlike every other artifact under `results/` it
carried no `assay_revision`, so there was not even a tree to point at. A cold
judge went looking for the producing command, did not find one, and was right to
call it the weakest claim in the repository. The same was true of
`results/escalation_policy.json` — which had also gone quietly stale, still
reporting 26 environments against a corpus of 28 — and `results/na_resolution.json`.

The measurement is now a flag rather than a story: `scripts/auditor_arm.py
--gate-input describe` restores the pre-fix gate input, and
`Auditor(gate_input="describe")` is pinned by a test so the path cannot silently
stop differing from the shipped one. The re-measurement reached 26 of 28
environments before it was stopped: the pre-fix gate hands `adapter.describe()`
to the model, which on the two τ² environments means the verifier's source
against a 4096-token context, and those two did not complete. So the arm is
reproducible on demand and **has not been reproduced end to end**, and the
figure is withdrawn until it is. What replaces it is the qualitative finding,
which the surviving 26 environments do support: reading the fixture's own
metadata, the gate concluded environments had no correct answer and withheld
real verifier-integrity findings. That is why the gate now reads task
instructions only.

Live claim: `results/auditor_arm.json` carries the arms a command regenerates,
and no `before_the_fix` figure.

---

## What this list is evidence of

Twelve of these were found by turning this repository's own instruments on itself
(`docs/RED-TEAM.md`). Eight were found afterwards, by the same method, in the documents
that recorded the first twelve — the most recent by an outside judge who went looking
for the command behind a number and found prose. That rate is the point: **an auditing tool is not
exempt from the thing it audits, and the only defence is to run the audit on yourself
and publish what it finds.**
