# The semantic gate deleted real findings once in seven runs, and I misdiagnosed why

> **Correction, added after the measurement below was written.** The title of
> this slice used to read "the semantic gate asks a question that is wrong for
> dialogue environments", and the argument under it was that the old wording
> *caused* the false override. **That is not supported.** A direct ablation --
> `scripts/gate_question_ablation.py`, k=10 per wording on the failing
> environment -- returns `has_correct_answer` **10 times out of 10 under the
> old question**, and 10 of 10 under the new one. The old wording answers
> `tau2/airline` correctly on demand. The reasoning below still describes a
> real ambiguity in the question, and that ambiguity is *not* demonstrated to
> be the cause of anything. The failure remains unexplained.

**Found by running the auditor arm twice.** Same corpus, same code:

| run | `assay+auditor` | missed | spurious | recall |
|---|---|---|---|---|
| 1 | **43.0** | 1 | 3 | 0.9815 |
| 2 | **122.0** | 3 | 2 | 0.9444 |

In run 2 the gate withheld **25 findings on `tau2/airline`**, destroying two real
planted defects — `KNOWN_WRONG_PASSES` and `SPEC_VERIFIER_MISMATCH`. This is
`docs/PRE-REGISTRATION-NOANSWER.md` criterion 1 firing on a real environment:
"the agent has traded a false positive for a hidden true one, which is worse
than the disease."

## The model was right; the question was wrong

`auditor.py:_SYSTEM` asks exactly one thing:

> Could two DIFFERENT responses to the same task both be legitimately correct,
> such that a fair scorer ought to accept both?

`tau2/airline` is a multi-turn customer-service dialogue. Its task text is a user
persona — *"You want to cancel reservation EHGLP3… If Agent tells you that
cancellation is not possible, mention that you were told you didn't need
insurance"* — and there are obviously many legitimate ways to conduct that
conversation. **Under the question as asked, `no_correct_answer` is the correct
answer.** The model did not hallucinate; it answered accurately.

τ² nonetheless has a definite fact of the matter: it grades the resulting
**database state**. The same task text even says so in its last line — *"Testing
that agent refuses to proceed with a cancellation that is not allowed"*.

**The question conflates two different things:** whether the correct response is
unique *in surface form*, and whether there is a correct *outcome* at all. For
maths and classification those coincide, which is why the gate looked sound on
`personality_BFI`, `stereoset` and twelve toy fixtures. For any environment where
many utterances reach one correct state, they come apart, and the gate deletes
real findings.

The criterion the gate actually wants is already written two paragraphs further
down its own prompt — *"the result is computed from the response, not graded
against a key"* — but the question at the top does not ask that.

## Why it looked reliable

`results/semantic_gate.json` reports `claude-cli:sonnet` at 6/6 positives and
**0 false overrides in 54 negatives**. That subset contains no multi-turn
dialogue environment, so it could not have caught this. The figure is a property
of the subset, not of the gate.

It is also why this is intermittent rather than constant: a borderline question
gets a borderline answer, and the same model answers it differently on different
runs. `assay+auditor` at 43.0 is one draw.

## What was measured, in order

1. **The rate, before touching anything.** Seven runs: 43.0 x4, 44.0 x2, 122.0
   x1. One false override in seven (`results/gate_reliability.json`).
2. **The wording changed**, on the reasoning above.
3. **The rate after.** Five runs: 43.0 x2, 44.0 x3, no false overrides
   (`results/gate_reliability_after.json`).
4. **The ablation that undercuts step 2.** At a 1-in-7 rate, five clean runs
   happen about 46% of the time with no fix at all, so step 3 demonstrates
   nothing on its own. Asking the question directly, k=10 per wording:
   **both wordings answer `has_correct_answer` 10 of 10.**

**So the wording change is kept on clarity grounds and is not claimed as a
fix.** The new question states the criterion the prompt already contained
instead of a proxy for it, and the after distribution is no worse. Neither of
those is evidence that it repaired the failure, and the failure is still
unexplained.

## What was actually wrong, and is now fixed

The audit trail. The decision log recorded `model_said: no_correct_answer` and
nothing else, so the one occurrence is indistinguishable from a hundred correct
withholds and could not be diagnosed after the fact. Withholds now record the
referent, the quote and the confidence, so a recurrence is explainable rather
than merely countable.
