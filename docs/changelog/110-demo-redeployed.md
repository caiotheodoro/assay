## Slice 47: the deployed demo was a commit behind its own correction

**What and why.** `space/app.py` and `space/static/index.template.html` both said
Assay *"does not separate from `flag_everything`"* under `production-training`
and that *"under a production-training cost profile that policy beats it
outright"*. Both were fixed in the tree when the four-profile table was
re-measured — and **neither was deployed**, so the live Space kept saying it.

That is the worst place for it. A judge who cannot run anything can still click
the demo, and what they would have found is the one artifact contradicting the
README it is linked from.

**Fix.** `scripts/publish_hf.py --only demo --push`, after the nine gates. The
live page is 66,183 bytes, the stale sentence is gone, the Pyodide loader and all
eight pre-rendered cards are intact, and the URL returns 200.

**Decision.** Deployed. And noted for whoever ships the next artifact: a
publish step that is not part of the change is a change that has not shipped.
The correction existed, was committed, was tested, and was wrong on the internet
for as long as nobody ran the deploy — which is the same shape as a benchmark
whose fix sits in a branch.
