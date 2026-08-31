## Slice 50: the crossover formula was right until precision stopped being 1.000

**What and why.** `docs/METHOD.md` published the crossover as a reusable check:
*"if your detector's loss is all misses and the floor's is all false alarms, they
cross at `shipped × floor / yours`."* That is a ratio, and it is correct **only
when the detector has no false alarms**.

Assay had none for most of this project. Then the two τ² environments arrived
with three, and the formula went wrong silently.

**The truth.** Only the *miss* half of the loss scales with the cost constant.
The false-alarm half does not move at all. So the line is affine, not
proportional:

```
assay(C) = (assay(shipped) − fa) × C / shipped + fa      =  C/3 + 3
```

which fits every published row exactly — 3.33 at C=1, 43.0 at 120, 269.67 at
800, 669.67 at 2000. Solving against the floor's constant 394.0 gives a crossover
of **1173.0**, not the 1099.53 that shipped, and an **878%** margin rather than
816%.

At the published 1099.53, Assay is at **369.5** against 394.0. The "tie" row in
four documents was not a tie.

**Found by a judge**, who derived `C/3 + 3` from the rows this repo publishes and
checked the formula against them. That is the argument for publishing rows
alongside a summary statistic, made by someone using it.

**Fixed** in `scripts/cost_sensitivity.py` with the affine solve, regenerated
into `results/cost_sensitivity.json` and `results/cost_unit.json`, and
propagated to the six live documents that quoted the old number. `docs/METHOD.md`
now teaches the affine version and says plainly which special case the old one
was.

**What it cost to learn.** The error is *self-penalising* — it understated the
margin, so nothing looked suspicious and no gate fired. It also survived a
sensitivity sweep whose entire purpose is checking whether a conclusion is a
property of the detector or of a constant: the sweep printed the rows that
disprove the formula, in the same file as the formula's output, and nobody
divided one by the other. **A number that flatters you less than the truth is
still a number nobody checked.**
