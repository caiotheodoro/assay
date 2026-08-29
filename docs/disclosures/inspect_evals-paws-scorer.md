# Draft — `UKGovernmentBEIS/inspect_evals`

**Status: DRAFT. Not filed. Do not post without approval.**

- **Repo:** https://github.com/UKGovernmentBEIS/inspect_evals
- **Kind:** issue (bug)
- **Verified against:** `inspect_evals` 0.18.0 (current PyPI release at time of writing), `inspect_ai` 0.3.260
- **Suggested title:** `paws`: `includes()` scorer credits any completion containing both labels — a constant string scores 100%

---

`paws` is scored with `includes()` against the literal targets `Yes` and `No`.
`includes()` is a case-insensitive **substring** test, so any completion
containing a label counts as that label — and a completion containing *both*
counts as either.

The constant string `"yesno"` therefore scores **8000/8000 = 100.0%** on the
full pinned test split, without reading the input.

I ran the real scorer over all 8000 items rather than reasoning about it:

```python
# inspect_evals 0.18.0, inspect_ai 0.3.260
from inspect_ai.scorer import includes
# ...score every item in the pinned paws test split with the constant "yesno"
# 8000/8000 = 1.0000
```

The looseness is also **one-sided**, which I think makes it worse than a
symmetric leak. 4464 of the 8000 items have target `No` (55.8%), and `No` is a
substring of ordinary hedging language:

| Completion | vs target `Yes` | vs target `No` |
|---|---|---|
| `"yesno"` | correct | correct |
| `"I don't know"` | incorrect | **correct** |
| `"Not sure"` | incorrect | **correct** |
| `"None of the above"` | incorrect | **correct** |
| `"I cannot determine the answer."` | incorrect | **correct** |

So a model that refuses or hedges is credited on ~56% of the benchmark for
free, and the effect is larger for models that hedge more — which is a
correlation with exactly the behaviour these evals are often used to measure.

### `boolq` has a narrower version of the same thing

`boolq` uses `pattern(r"(Yes|No).?\Z")`, which anchors and genuinely helps.
But *know* is *no* plus one character, so `"I don't know"` still matches on
every `No` item.

### Why I don't think this is just a deliberate trade-off

`includes()` is a reasonable default for free-form answers where the model may
add reasoning around the answer. It seems a poor fit for a **two-token label
set where one label is a substring of common English**. `match()` or an
anchored `pattern()` with word boundaries would keep the tolerance for
surrounding prose without admitting `"I don't know"`.

### Suggested fix

A word-boundary-anchored pattern for the two-label case, e.g. matching
`\b(yes|no)\b` at the end of the completion and rejecting completions
containing both labels. Happy to open a PR if that direction is welcome.

### Reproduction

Both the 8000/8000 result and the `boolq` case are pinned as tests here:
`tests/test_wild_findings.py` in <REPO_URL>. They call `inspect_evals`'
own `record_to_sample` and `inspect_ai`'s own `includes()` / `pattern()` — no
third-party harness in the loop.

### Disclosure note

Found by a benchmark-auditing tool I'm building. To be straight about
attribution: the tool flagged 14 of 25 sampled `paws` items as reward-hackable
but did **not** find the `"yesno"` case; I found that by hand while triaging
its output. No `paws` content is redistributed in that repo — only the verdict
and this reproduction.
