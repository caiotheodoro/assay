## Slice 45: the "~2s" that was never measured

**What and why.** Four documents said the scripted Challenger now finds the
`harbor/self-graded` exploit in *"~2s instead of 262s"*. The 262s is real and
sits in `results/challenger_ablation.json`. **The ~2s was in no committed
artifact at all.** The 2.2s that file records is the *pre-taxonomy* repertoire —
four policies, and it **missed**. The current repertoire has six and finds the
gap, and nobody had ever timed it.

A judge flagged it under ground rule 9, *connect every claim about your results
to the evidence you submit*, and was right to. A number with no file behind it
is the thing this repository audits other people's benchmarks for.

**Evidence.** `results/scripted_floor.json`.

| arm | found | gap | attempts | seconds |
|---|---|---|---|---|
| scripted, current repertoire | yes | 1.00 | 6 | **3.8** |
| `claude-cli:sonnet`, the run that first found it | yes | 1.00 | 10 | 261.7 |

**3.8 seconds, not ~2.** The repertoire grew from four policies to six when the
BenchJack V1 and V7 mechanisms were written down, so it does more work and now
succeeds where it used to fail. The comparison the documents draw is unharmed —
it is two orders of magnitude either way — but the number they printed was
invented rather than measured, and it has been corrected everywhere it appeared
rather than rounded to.

**Decision.** Artifact committed, claim corrected to the measured value, and the
one-line harness recorded so the next person does not have to reconstruct it:
`scripts/challenger_ablation.py --models`, which runs the scripted row alone.

**What it cost to learn.** This one is uncomfortable because the number was not
wrong in a way that changed any conclusion — 2 and 3.8 argue the same thing
against 261.7. That is exactly why it survived four documents and three earlier
reviews. The claims that get checked are the ones that look load-bearing; a
number nobody would dispute is a number nobody looks up.
