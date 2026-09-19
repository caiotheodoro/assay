# One model call could withhold across five environments

**Found while trying to explain a false override**, not by looking for it.
`Auditor.shape()` keys the gate's memory on ecosystem plus task text, so two
environments that pose the same question to a reader are asked about once. Its
docstring justifies that with the twelve `toy-triage` fixtures, which really are
one ticket-classification prompt paired with twelve different planted defects.

Measured across the shipped corpus, the grouping is wider than the docstring
says. **33 environments collapse to 14 shapes:**

| shape | environments |
|---|---|
| the toy fixtures | 12 -- documented and intended |
| `harbor/*` | **5** -- `broken-gold`, `healthy`, `self-graded`, `shared-tests`, `vacuous-tests` |
| `inspect/*` | **5** -- `always-correct`, `constant-score`, `effort-scorer`, `healthy`, `leaky-split` |
| everything else | 11 singletons |

So one `no_correct_answer` from one model call withheld findings on **five**
environments. That is not hypothetical: `classify()`'s own comment records
`claude-cli` returning `no_correct_answer` for `harbor/self-graded` in 3 of 3
runs, and `results/gate_question_ablation.json` reproduces it. The only thing
standing between that and five environments' findings being deleted is the
abstention guard -- one check, and the failure is silent when it does not fire.

## The fix, and why it costs nothing

Cache the safe verdict only. `has_correct_answer` still carries between
environments; `no_correct_answer` is re-asked per environment.

Carrying "this has a correct answer" can only leave findings standing, which is
the direction that fails safe. Carrying "this has none" deletes findings, and
deleting five environments' worth from one sample is a blast radius nobody chose.

**No cache hit is lost.** Every environment that currently answers
`no_correct_answer` -- `personality_BFI`, `stereoset`, `toy-triage/preference`,
`noanswer/ranking`, `noanswer/openended` -- is already a shape of its own, so
the dangerous direction was never being shared in practice. And the saving
`results/auditor_memory.json` reports, twelve fixtures for one model call, is on
environments answering `has_correct_answer`, which still cache.

## What this does not explain

The `tau2/airline` false override. `tau2/airline` is a singleton shape, so it
got its own model call and inherited nothing. That failure is still unexplained;
this is a second, independent way the same kind of damage could have happened,
found while looking for the first.
