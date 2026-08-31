## Slice 53: a heuristic finding read exactly like an executed one

**What and why.** `spec_verifier_match` is a content-word overlap heuristic. It
says so itself — every finding it emits carries
`confidence: "advisory - lexical overlap heuristic, review by hand"` — and this
repository takes that seriously enough to **exclude it from its own external
recall measurement**: `results/tau2_recall.json` ships a
`combined_excluding_advisory_probe` row precisely because leaving it in destroys
the number.

And then it shipped on by default, contributing to a stranger's verdict, with
**nothing on the Environment Card to say which kind of finding it was.** A judge
wrote their own environment spec, received three `SPEC_VERIFIER_MISMATCH`
findings, and had no way to tell they came from a lexical heuristic rather than
from execution.

That is the asymmetry `docs/COVERAGE.md` argues about at length, running in the
one direction nobody checked: *"A probe that reports CRITICAL on a healthy
environment costs them the tool's credibility."* The confidence field existed,
was populated correctly, and was read by nothing a user sees.

**Fix.** The card marks it, and says what it means:

```
**SPEC_VERIFIER_MISMATCH** — `t1` *(advisory)*

> Advisory: surfaced by a heuristic for a human to check, not established by
> execution. This repo excludes this probe from its own external recall
> measurement (`results/tau2_recall.json`), so weigh it accordingly.
```

Two tests pin it: an advisory finding carries the marker, and an executed one
(`GOLD_FAILS`) does not — because a marker that appears on everything
distinguishes nothing.

**What was deliberately not done.** The probe is not disabled and the verdict
arithmetic is unchanged. `SPEC_VERIFIER_MISMATCH` is a planted defect class in
the corpus (`fixture/drifted_asserts`), so downgrading it would move published
numbers to fix a presentation problem — the exact trade this repo refuses
elsewhere. The finding was never wrong to *make*; it was wrong to make it
look like the others.

**What it cost to learn.** Nothing here was undiscovered. The probe knew its own
confidence, the τ² measurement already excluded it, and the reason was written
down in three places. The gap was entirely between what the codebase knew and
what the artifact a reader holds actually said — which is the same gap as the
stale documents, arriving through a different door.
