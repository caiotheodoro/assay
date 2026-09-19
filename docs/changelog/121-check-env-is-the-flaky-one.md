# The incumbent's determinism check is the nondeterministic one

**Found by accident**, comparing two runs that differed only by one added
environment: `check_env` reported `NONDETERMINISM` on `openenv/textarena-wordle`
in one and not the other, moving its published loss between **3216.0** and
**3224.0**. Adding `inspect_evals/stereoset` cannot affect what a structural
linter sees on an OpenEnv Wordle task, so one of the two runs was wrong about
the same environment.

**Cause, and it is not in Assay.** `src/assay/baselines/structural.py:88-99`
repeats twice and fingerprints only the first step's observation:

```python
for _ in range(2):
    adapter.reset(task.task_id, seed=1234)
    result = adapter.step(action)
    fingerprints.add(canonical_json({"ok": ..., "data": result.observation.data}))
```

Wordle draws its secret word **at reset**, which this never looks at. Whether the
incumbent notices depends on whether two randomly drawn words happen to produce
identical feedback for the same first guess — for a guess that scores all-grey
against both, they do, and the environment reads as deterministic.

`src/assay/probes/determinism.py` does three repeats and puts the reset in the
fingerprint, and the comment saying why was written long before this:

> The seed is consumed at reset, so what reset produced belongs in the
> fingerprint. Leaving it out is how an environment that redraws its hidden
> state every episode reads as deterministic.

**Assay's arm detected it in both runs.** The flakiness belongs to the baseline.

**What this changes.** `check_env`'s expected loss is run-dependent by roughly 8
points, and it is the incumbent the README compares against, so the comparison
is quoted with that in mind rather than as a fixed figure. It is not corrected:
the baseline is the incumbent as it actually behaves, and silently strengthening
a competitor's check to make it look stabler would be a worse distortion than
the variance.

**Related.** One `assay+auditor` run reported no defects at all on this same
environment, where four later measurements report `NONDETERMINISM`. No mechanism
was ever found for that one, and it stays published as an unexplained anomaly in
`docs/PRE-REGISTRATION-NOANSWER.md`. `scripts/repeat_check.py` exists because of
it, and this slice is the first thing that turned up downstream.
