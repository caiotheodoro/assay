## Slice 49: the documented command produced a better number than the truth

**What and why.** A judge cloned the repo, ran the command `README.md` gives a
newcomer, and got:

```
corpus: 24 environments, 48 planted defects
assay 0.0    recall 1.000    precision 1.000
```

against a published **28 environments, 54 defects, assay 43.0, recall 0.982**.
The run printed two warnings and **exited 0**.

Two causes, and both are invisible on any machine that has ever installed
anything else — which is every machine this was developed on:

1. `--extra sweep` was missing from the command, dropping the two
   `inspect_evals` environments, one of which is `boolq`, **the single
   documented miss in the whole corpus**.
2. `tau2` imports `toml` at module scope, and `toml` was reaching the venv only
   as a transitive dependency of `inspect_evals`. Declared in the `tau2` extra
   now, where it always belonged.

**Both errors flatter.** The environments a missing provider takes with it are
the ones Assay does *worst* on, so a reduced corpus reports a **better** number.
`assay 0.0 at recall 1.000` is a perfect score bought by deleting the four
environments that hold the only miss and all three false positives. That is not
a reporting bug; it is the exact defect class this tool exists to find, running
in the tool's own reproduction path.

**Three fixes, because one would not have held.**

- `scripts/full_run.py` **refuses** to write a headline when any provider is
  unavailable, and says why in the message. `--allow-reduced` opts in.
- Every documented command carries all four extras, gated by
  `test_every_documented_headline_command_carries_the_extras_it_needs`.
- A CI job, `the-readme-command-works`, runs the README's **literal** command
  and fails if the corpus it produces differs from the committed artifact.

**What it cost to learn.** CI had a reproduction job the whole time, and it
passed, because it syncs its own extras — it verified the code and never the
instructions. `docs/REPRODUCTION.md` also asserted the opposite of the truth:
*"`--extra sweep` is not needed here… leaving it out gives a byte-identical
`results/full_run.json`, checked by diffing the two."* Someone checked that, on a
machine where it was true. **A reproduction guide is only tested by someone who
does not have your venv**, and until a judge did, nobody had.
