## Slice 52: a negative result framed as a warning label is not a contribution

**What and why.** `caiotheodoro/assay-challenger-grpo` opened with:

> **This adapter does not work.** … **Do not deploy this.**

Every judge praised the *decision* to publish a failed adapter. Nobody asked
whether the card made the failure legible as a **finding**, and it did not. A
reader landing on that page cold concludes the project failed. What is actually
in the card is a measured result about why a one-shot RL policy cannot learn an
exploit it has to discover — and it was the last section, under the fold.

The honesty was never in question. The framing was doing the wrong job:
*leading with the failure* and *leading with the finding* are not the same
thing, and only the second is a contribution.

**Reframed.** The card now opens on the transferable claim — *a one-shot policy
cannot learn to find a bug it has to discover first* — and states the three
findings that carry it: zero group spread is zero gradient rather than slow
learning; raising temperature multiplied lexical diversity sevenfold and moved
nothing, because only structural variation earns an exploit gap; and the ceiling
was the training **format**, not the reward, which 36 tests and a 16% real-exploit
rate confirm was working. Then that it was predictable before the GPU was rented,
from a pre-registered flat-landscape count.

The deployment warning stays, one paragraph down, saying the weights exist so the
ablation row is checkable and do not beat their own base model.

**The gate had to change with it, and that is the interesting part.** A
publication gate required the first 400 characters to contain "does not work" or
"negative result". It was written to stop overselling and it worked — and it also
*enforced* the apology, because the only framing it accepted was the pessimistic
one. It now checks that the card disclaims deployment and claims no gain over
base, anywhere above the fold, and says nothing about the headline. **Gate the
honesty, not the pessimism.** It also normalises whitespace before matching,
because a gate that fails when a sentence wraps teaches people to reword around
it rather than to comply with it.

**Also disclosed, and it should have been from the start:** the holdout leaked.
`results/train_holdout_dedup.json` records `harbor/self-graded` as a
byte-identical duplicate of three training prompts at `true_jaccard 1.0`. The
card called it "held out of training so the test would mean something" and said
nothing more. It now says the model failed on the **easiest possible** version of
the test — one whose prompt it had trained on hundreds of times — which makes the
negative stronger, not weaker, and rests on a finding that has nothing to do with
which prompts were held out.

**What it cost to learn.** The repo had a rule about this and applied it in one
direction only: never let a claim read stronger than its evidence. It never asked
whether a claim was reading *weaker* than its evidence. An understated result is
also a misreported one, and it costs the reader the finding.
