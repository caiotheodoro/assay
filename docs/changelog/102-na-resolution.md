## Slice 42b: the split can be synthesized, and boolq is still missed

**What and why.** `inspect_evals/boolq` is the corpus's one remaining miss.
`docs/PRE-REGISTRATION.md` predicted it before the code existed, and gave the
reason: `WildInspectAdapter` supplies no train split, so `shortcut_leakage`
declines with `NOT_APPLICABLE` and the planted `SHORTCUT_LEAK` goes unfound.

`Probe.na(reason, **detail)` has always recorded what a probe attempted before
giving up, and nothing has ever read it. This slice has the Auditor read it and
try to supply what was missing: name the fields an item is built from, cut them
with literal delimiters, and cross-fit over a split it makes itself.

**It works, and it does not help.** Evidence: `results/na_resolution.json`.

Both backends return the identical decomposition, unprompted by any example
from this dataset:

```
{"parts": [{"name": "passage",  "after": "Passage: ",  "before": "\n\nQuestion:"},
           {"name": "question", "after": "Question: ", "before": null}],
 "must_not_determine": "question"}
```

The fields cut correctly, the split is 13/12, the probe runs. And it returns
PASS, with `per_part_accuracy` **0.75 for both parts, exactly equal to the
0.75 majority-class rate.**

**Why, and this is the part worth keeping.** `_part_accuracy` is a lookup from
an exact part value to a majority label. Of 13 training questions, 13 are
unique, and **0 of the 12 evaluation questions appear in that table**. Every
item takes the fallback, the fallback is the majority label, and the accuracy is
pinned to the majority rate by construction. No value of n fixes this: a
dictionary over free text has nothing to look up.

So the pre-registered reason for the miss is true and is not the binding
constraint. The adapter withholding a split is the reason the probe *declines*;
the reason it could not *succeed* is that a partial-input baseline implemented
as an exact-match dictionary cannot read free text at all. Supplying the split
turns NOT_APPLICABLE into PASS, which is a more honest verdict and still not a
detection.

**Decision.** The resolver is kept, and the claim is corrected rather than the
result. It is cheap, both backends agree on it, and it fires wherever part
values repeat -- categorical fields, templated prompts, multiple-choice stems --
which `test_the_resolver_fires_when_part_values_repeat` pins. It does not
rescue `boolq`, and nothing here pretends otherwise. Any finding it does produce
carries `synthesized_split: True` and the name of whatever proposed the split,
because a reader who did not know the division was invented would over-read it.

**What it cost to learn.** A miss that was explained once, correctly, can still
be explained shallowly. The explanation on file would have let someone conclude
that a better adapter closes this. It does not; a different probe does.
