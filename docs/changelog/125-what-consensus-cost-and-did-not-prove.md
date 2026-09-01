# What requiring agreement cost, and what it did not prove

`Auditor(consensus=2)` landed as a bound on a failure nobody explained
(`docs/changelog/124-ask-again-before-deleting.md`). Claiming a bound without
measuring it would be the same error this repository has retracted twice today,
so here is the measurement.

Five runs of the auditor arm on the 33-environment corpus, with consensus on:

| | before consensus | with consensus |
|---|---|---|
| `assay+auditor` | 43.0 x2, 44.0 x3 | 43.0 x2, 44.0 x3 |
| model calls | 20 | **24–26** |
| false overrides | 0 of 5 | 0 of 5 |
| `assay`, for contrast | 57.0 every run | 57.0 every run |

**The cost is real and small: four to six extra model calls**, all on the five
environments that reach the destructive branch. The verdict distribution is
unchanged, which is what a second opinion should do when the first one was
already right.

## What this does not show

**It does not show the bound works.** Zero false overrides in five runs is what
the un-bounded gate also produced in its last five runs; the failure it is meant
to catch happened once in seven. At that rate, five clean runs occur about 46%
of the time whether or not anything changed, and the same arithmetic already
retracted one claim in `docs/changelog/122-the-gate-asks-the-wrong-question.md`.
Repeating it here with a different number would be the third instance of one
mistake.

Confirming a rate this low needs runs this project cannot afford: separating
1-in-7 from 1-in-50 at any useful confidence is tens of full-corpus runs at
roughly ten minutes each. **What is published is therefore the cost, which is
measured, and the argument, which is not.** If per-call errors are independent
at rate p, two agreements give about p²; independence is an assumption and
nothing here tests it.

## Why it ships anyway

The cost is four calls and the downside it guards against is deleting real
CRITICAL findings from an environment that has a correct answer. An unmeasurable
improvement at a measured price of four model calls is worth taking when the
failure it addresses has already happened once and has no diagnosis.
