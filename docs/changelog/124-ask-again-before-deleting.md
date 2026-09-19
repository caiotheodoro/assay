# Withholding now takes agreement, because the failure was never explained

`results/gate_reliability.json` measures the semantic gate deleting two real
planted defects on `tau2/airline` in 1 run of 7. Three explanations were tried
and none held:

| hypothesis | how it was tested | verdict |
|---|---|---|
| the question's wording caused it | `gate_question_ablation.py`, k=10 on that environment | **no** -- the old wording answers correctly 10 of 10 |
| the shape cache carried another environment's verdict | shapes computed across the corpus | **no** -- `tau2/airline` is a singleton shape |
| its shape is unstable between runs | shape computed over four constructions | **no** -- one distinct value |

What is left is that `Auditor.task_text` for this environment is fifty
concatenated user personas, and a model asked about a long ambiguous prompt
occasionally answers differently. That is not a satisfying diagnosis and it is
the honest one.

## An unexplained error still has a shape

It is rare, it is stochastic, and its consequence is destructive. The remedy for
that shape does not require knowing the cause: **ask again, and act only on
agreement.**

`Auditor(consensus=2)` is now the default. Before anything is withheld a second
independent reply must also say `no_correct_answer`; one dissent stands the gate
down and is recorded on the card as an abstention.

**Asymmetric on purpose.** A single `has_correct_answer` still costs one call
and ends there, because leaving findings standing is the direction that fails
safe. Only the destructive direction pays for a second opinion, and only on the
environments that reach it -- five of thirty-three on the shipped corpus.

## What this does and does not buy

If the failure is an independent per-call error at rate p, requiring two
agreements takes it to about p². That is an argument, not a measurement, and the
rate is too low for the corpus-level run to confirm at any k this project can
afford: at 1 in 7, five clean runs already happen 46% of the time with no change
at all. What it does not do is explain anything, and it is not filed as a fix
for the cause.

Related: `docs/changelog/123-one-call-decided-five-environments.md` closed the
amplifier -- one wrong answer withholding across five environments -- and
`docs/changelog/122-the-gate-asks-the-wrong-question.md` records the two
retracted diagnoses.
