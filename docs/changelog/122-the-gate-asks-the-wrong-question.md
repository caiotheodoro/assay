# The semantic gate asks a question that is wrong for dialogue environments

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

## Not fixed in this slice, deliberately

A k=5 measurement of the current gate is running. Changing the prompt first
would destroy the only quantification of how often this happens, and "we fixed
it before we measured it" is not a claim anyone can check. The rate lands first,
then the fix, then the same measurement again.
