## Slice 46: the agent made the tool worse, and the arm is what caught it

**What and why.** A cold judge scored this submission 76.5 and wrote: *"the agent
is off in every number the submission leads with."* Fair. So `full_run.py` gained
`--auditor-arm`, which runs the same battery with the Auditor reading the results
before the verdict is recorded, and puts the answer in the table as a row rather
than an argument.

The row said **163.0**, against the deterministic arm's **43.0**. Recall 0.982 →
0.926. One miss became four. **The agent made the tool measurably worse**, on
both backends, and nothing else in the repository would have shown it.

**First cause: the gate was reading the verifier.** It was handed
`adapter.describe()`, which carries declared capabilities, task metadata and the
verifier's source. On `harbor/vacuous-tests` `claude-cli` quoted the fixture's own
metadata back —

> The verifier always exits 0. Nothing it reports means anything.

— and concluded the environment had no correct answer. **It has one.** The
verifier is broken, which is precisely the defect the battery found and the gate
then withheld. *"The verifier cannot distinguish answers"* and *"there is nothing
to distinguish"* are different claims, and only the second is this gate's
business. Reading the verifier is how they got confused, so the gate now sees
task instructions and nothing else. `assay+auditor` went back to **43.0,
identical to `assay`**.

**Second cause, found by re-measuring the first fix.** With five Harbor
environments added as negatives, `claude-cli` called `harbor/self-graded`
answerless in **3 of 3** runs. That task's entire text is *"Write the answer to
the file out.txt in the working directory"* — it never says what the question
**is**. Asked whether two answers could both be fair, the model quoted the whole
instruction back, because there was nothing else to quote.

So a quote that is the entire prompt is now treated as no evidence at all, and
the gate abstains and says so. The rule is deterministic and is not tuned to this
corpus: the quote must be shorter than the body it came from.

**Evidence.** `results/semantic_gate.json` — 18 environments, 2 with no correct
answer, at three runs each.

| backend | true positives | false positives |
|---|---|---|
| `claude-cli:sonnet` | **6 / 6** | **0 / 54** |
| `ollama:qwen3:8b` | 6 / 6 | 6 / 54 |

**Decision.** Both fixes kept, the arm kept, and `qwen3:8b` named in the README as
a backend not to run this with — 6 false overrides in 54 is not a rounding error,
it is a hidden defect six times over.

**What it cost to learn.** Three things, and the third is the one worth keeping.

The gate's negatives were twelve toy fixtures and one published QA set, none of
which has a deliberately broken verifier — so the measurement could not have
caught this, and said 0 false positives while the feature was actively deleting
real findings. **A false-positive rate is a statement about the negatives you
chose.**

The bug was found by building the number the judge asked for, not by looking for
the bug. The row was added to answer a criticism about presentation and it
returned a correctness result.

And the fix had a bug of its own: the abstention rewrote `verdict` before
`model_said` was captured, so a card would have printed the gate's conclusion as
the model's own label. Caught by a test asserting the two can disagree — the same
test that exists because the two disagreeing is the whole design.
