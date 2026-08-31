# Draft — `UKGovernmentBEIS/inspect_evals`

**Status: FILED — https://github.com/UKGovernmentBEIS/inspect_evals/issues/2331**

Reviewed by a second reader before filing; that review changed the reproduction section, the suggested fix and the version claim. What is above is what was sent.

- **Repo:** https://github.com/UKGovernmentBEIS/inspect_evals
- **Kind:** issue (bug)
- **Verified against:** `inspect_evals` 0.18.0 with `inspect_ai` 0.3.260. Re-checked against `main` and the `v0.19.0` tag: `src/inspect_evals/paws/paws.py` still has `scorer=includes()` and the same pinned dataset revision, so this is live in the current release.
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
import asyncio
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, Target, includes
from inspect_ai.solver import TaskState
from inspect_evals.paws.paws import DATASET_PATH, PAWS_DATASET_REVISION, record_to_sample
from inspect_evals.utils.huggingface import hf_dataset

ds = hf_dataset(path=DATASET_PATH, name="labeled_final", split="test",
                sample_fields=record_to_sample, shuffle=False,
                revision=PAWS_DATASET_REVISION)

def score(completion, target):
    state = TaskState(model="m", sample_id="1", epoch=1, input="i", messages=[],
                      output=ModelOutput.from_content(model="m", content=completion))
    return asyncio.run(includes()(state, Target(target))).value

hits = sum(1 for s in ds if score("yesno", str(s.target)) == CORRECT)
print(hits, len(ds))                                # 8000 8000
print(sum(1 for s in ds if str(s.target) == "No"))  # 4464
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

So a model that refuses or hedges is credited on 55.8% of the benchmark for
free, and the effect is larger for models that hedge more. I have not measured
this against real model outputs — the mechanism is what I'm reporting, not an
estimate of how far any published score moves.

### `boolq` has a narrower version of the same thing

`boolq` uses `pattern(r"(Yes|No).?\Z")`, which anchors and genuinely helps.
But *know* is *no* plus one character, so `"I don't know"` still matches on
every `No` item.

### Prior art

I searched the tracker before filing and found nothing on `paws`, or on
`includes()` specifically. Two open issues do report the same *class* of
failure in other evals, so this may be worth fixing as a family rather than one
at a time: #2310 (`agentic_misalignment` — yes/no parsed by substring,
"yesterday" ⊃ yes) and #2312 (AgentHarm refusal judge). Both are someone else's
find, not mine.

### Why I don't think this is just a deliberate trade-off

`includes()` is a reasonable default for free-form answers where the model may add
reasoning around the answer. It seems a poor fit for a **two-token label set where
one label is a substring of common English**. An end-anchored `pattern()` with word
boundaries keeps the tolerance for reasoning *before* the answer without admitting
`"I don't know"` — numbers below.

### Suggested fix

Anchor the label at the end of the completion, with word boundaries:

```python
from inspect_ai.scorer import pattern   # replaces the `includes` import
...
scorer=pattern(r"\b(Yes|No)\b\W*\Z"),
```

What each candidate leaves for a constant completion, measured over all 8000 items:

| constant completion | `includes()` (today) | `match(location="end")` | `pattern(r"\b(Yes\|No)\b\W*\Z")` |
|---|---|---|---|
| `"yesno"` | 100.0% | 55.8% | 0.0% |
| `"Yes or No"` | 100.0% | 55.8% | 55.8% |
| `"I don't know"` | 55.8% | 0.0% | 0.0% |
| `"no idea"` | 55.8% | 0.0% | 0.0% |

55.8% is the majority-class floor — always answering `No` scores that, and no scorer
can go below it — so the anchored pattern removes the whole exploit surface above the
floor.

Two caveats on my own suggestion. Both halves of the pattern matter: dropping the
end anchor and scoring on `\b(Yes|No)\b` alone puts `"no idea"` back to 55.8%,
and dropping the word boundaries puts `"yesno"` back to 100%. And it
is stricter than `includes()` about trailing prose — `"No, they are not paraphrases."`
becomes NOANSWER — though the `paws` template already asks for a bare `Yes`/`No`.

I'd also avoid rejecting completions that contain *both* labels, which was my
first instinct: the template itself says "Answer Yes … If they are not, answer
No", so any model that echoes the instruction or reasons out loud contains both,
and that rule would mark correct answers wrong — penalising verbose models,
which is the mirror of the bias above.

Happy to open a PR if that direction is welcome.

### Reproduction

The snippet above is the whole of it — `inspect_evals`' own `record_to_sample`,
`inspect_ai`'s own `includes()`, no third-party harness in the loop.

The `boolq` case and the one-sidedness table are also pinned as tests in a repo of
mine, if a green test run is easier to read than a snippet:
`tests/test_wild_findings.py` in https://github.com/caiotheodoro/assay. Those tests
are offline and use hand-written records, so they deliberately do not include the
full-split 8000/8000 number — that one needs the Hub, and is what the snippet above
does.

### Disclosure note

Found by a benchmark-auditing tool I'm building. To be straight about
attribution: the tool flagged 14 of 25 sampled `paws` items as reward-hackable
but did **not** find the `"yesno"` case; I found that by hand while triaging
its output. No `paws` content is redistributed in that repo — only the verdict
and this reproduction.
