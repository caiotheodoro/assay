## Slice 42a: the capability the coverage doc said did not exist

**What and why.** `docs/COVERAGE.md` records a CRITICAL false positive the
battery cannot avoid: `inspect_evals/personality_BFI` returns verdict INVALID
with 25 x `INVERT_PASSES`, which is mechanically correct and semantically
wrong, because a personality inventory has no correct answer and a format
check is the right design. That section ends: *"The right fix is a capability
an eval can withhold -- 'this environment has no correct answer' -- and it does
not exist yet."*

`src/assay/runner.py` has said since the first commit that reading the results
is "the Auditor agent's job". Grep for `Auditor` returned one hit: that comment.
This slice writes the agent the seam was describing, and gives it exactly one
job -- the one no script can do.

**Evidence.** `results/semantic_gate.json`, 12 fixtures that all have a correct
answer plus the one environment that does not.

| backend | true positives | false positives | 13 envs |
|---|---|---|---|
| `ollama:qwen3:8b` | 0 / 1 | 0 / 12 | 58.5s |
| `claude-cli:sonnet` | 1 / 1 | 0 / 12 | 136.6s |

**Two designs measured and rejected before this one.**

*The model's label alone.* `qwen3:8b` labels `personality_BFI`
`has_correct_answer` in 3 of 3 runs -- immediately after writing a genuinely
valid pair, `"Yes, I tend to be disorganized" / "No, I am usually organized"`,
into the example field. It contradicts its own evidence.

*The model's evidence alone.* Deriving the verdict from "did it produce an
example" turns **10 of the 12** fixtures into `no_correct_answer`. Asked
whether two answers could both be fair on an ordinary ticket-classification
task, the model will invent a pair rather than say none.

So the gate is the conjunction of the two, and a model too weak to hold them
together produces no override at all. `qwen3:8b` fires on nothing.

**Decision.** Kept, off by default. `assay audit --auditor` opts in; the
headline numbers stay deterministic and the flag changes none of them. The
override can only move a `verifier_integrity` DEFECT to `NOT_APPLICABLE` --
never to PASS, never into another family -- and every one is printed with the
model that proposed it, the text it quoted, and the verdict it replaced.

**What it cost to learn.** The interesting half is not that a model can read
task text. It is that the small model *could* make the observation and could
not make the decision. Moving the decision into `decide()` and leaving the
observation with the model is the same split this repo argues for everywhere
else, applied one level down: the script owns mechanism, the model owns meaning.
