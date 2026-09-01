# Bounding the failure that could not be explained

The semantic gate deleted two real planted defects on `tau2/airline` in 1 run of
7 and no diagnosis survived testing. Three slices tried to explain it
(`122`, `123`, `124`); this one stops trying and measures how big it can be.

## Why the run-level number could not settle anything

`results/gate_reliability.json` observes 1 false override in 7 runs. As a bound
that is almost empty: **the one-sided 95% upper bound on 1-of-7 is 52%.** Every
statement made from it -- including "five clean runs show the fix worked" -- was
reading noise. Getting a useful bound this way needs tens of ten-minute corpus
runs.

## Measuring where the decision is actually made

The decision is one `Auditor.classify()` call on one environment, and that costs
seconds. `scripts/false_override_rate.py` runs the **full shipped path** -- the
question, the abstention guard, the consensus requirement -- with a fresh
Auditor each trial so no shape memory can carry a verdict in.

| | |
|---|---|
| environment | `tau2/airline`, the one that failed |
| trials | **50** |
| false overrides | **0** |
| one-sided 95% upper bound | **5.8%** |
| model calls per trial | 1, in all 50 |

Fifty trials on the environment that failed, plus 10 under the old wording and
10 under the new one in `results/gate_question_ablation.json`, is 70
observations with zero false overrides on it.

**This is a bound, not a demonstration that the rate is zero.** It says the
shipped configuration's per-decision rate on this environment is below 5.8% with
95% confidence, and 1-in-7 sits outside that. It does not say what happened in
the run that failed, and nothing here does.

## A second thing it settles

Every one of the 50 trials cost **one** model call. Consensus never engaged,
because the first reply was `has_correct_answer` every time and standing down is
the asymmetric direction that needs no second opinion. So the 4-6 extra calls
`docs/changelog/125` priced are paid only on environments the gate is inclined
to withhold on -- not on the environments where a false override would hurt.
