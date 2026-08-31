## Slice 43: both disclosures filed, and what the second reader caught

**What and why.** Two defects in software shipping today have been in this repo
since the wild sweep found them, written up as drafts and never sent. Two model
judges named that independently as the gap between this submission and a higher
score: *"no real user touched it — disclosures drafted, not filed, so the
strongest possible value proof (an upstream maintainer confirming) does not
exist."*

Filed 2026-08-31:

| Finding | Upstream | Issue |
|---|---|---|
| `paws` `includes()` scorer: the constant string `"yesno"` scores 8000/8000 | `UKGovernmentBEIS/inspect_evals` | [#2331](https://github.com/UKGovernmentBEIS/inspect_evals/issues/2331) |
| `textarena_env.reset()` accepts a `seed` and discards it | `huggingface/OpenEnv` | [#1102](https://github.com/huggingface/OpenEnv/issues/1102) |

**`docs/disclosures/README.md` named two prerequisites and they were done first**
— re-check the line references, and get a second reader, because neither draft
had been read by anyone but its author. The second reader was given the drafts
and told to be adversarial, and it was not a formality. Three findings, any one
of which would have got a correct report closed as noise:

1. **The reproduction pointed at a file that does not contain the result.** The
   draft said the 8000/8000 figure was pinned in `tests/test_wild_findings.py`.
   That file's own docstring says the full-dataset numbers are not in it — they
   need the Hub — and `results/wild_sweep.json` is gitignored. There was no
   committed, runnable reproducer for the headline number anywhere public. The
   filed issue carries the whole snippet inline instead.
2. **The version claim was superseded that morning.** `inspect_evals` 0.19.0
   was released 2026-08-31T03:56Z, hours before filing. Checked the tag: the bug
   is live in it. "You are reporting against a version we shipped past" is the
   cheapest way to have an issue closed.
3. **The suggested fix was partly wrong and partly harmful.** Rejecting
   completions containing *both* labels — my own first instinct — would mark
   correct answers wrong, because the `paws` prompt template *itself* says
   "Answer Yes … If they are not, answer No". Any model that echoes the
   instruction or reasons out loud contains both labels. That would penalise
   verbose models, which is the mirror of the bias the report complains about.

Every replacement was re-measured here before it went out rather than taken on
the reviewer's word — which caught one wrong cell in its own table
(`"no idea"` under `match(location="end")` is 0.0%, not 55.8%) and confirmed the
rest exactly, including 4464 `No` targets of 8000 and the anchored pattern
taking a constant string to 0.0%.

**Decision.** Filed. No maintainer has replied yet, and the reply — whichever way
it goes — is the strongest evidence this repository can ever carry that any of
this matters outside it. It goes in the README when it arrives.

**What it cost to learn.** The drafts had sat finished for days, and the thing
stopping them was labelled a decision. Two of the three defects above are the
kind you only find by having someone else read the thing you are about to say in
public, which is exactly the argument this repo makes about benchmarks and had
not applied to its own outgoing mail.
