## Slice 42d: deciding not to run the expensive agent

**What and why.** The rubric credits *orchestration*, and the honest form of it
here is not a pipeline diagram. It is a decision: a model Challenger costs
minutes and paid sampling where the scripted one costs about two seconds, so an
Auditor that escalates everywhere has not made a design choice, it has written
a bill.

`Auditor.should_escalate()` decides, in code, and states a reason either way.

**Evidence.** `results/escalation_policy.json`, all 28 scored environments.

| | n |
|---|---|
| escalate | 12 |
| refuse — the scripted attacker already found the exploit | 10 |
| refuse — the probe did not run at all | 4 |
| refuse — the declared repertoire is wide enough that silence is evidence | 2 |

*(Re-measured at 28 environments after the τ² corpus landed. The two τ² domains
both land in "the probe did not run": `reward_hackability` reports
NOT_APPLICABLE there because tau2 exposes no `true_completion` for an exploit
gap to be measured against, so there is nothing for a second attacker to
improve on.)*

**The refusals are the point.** The largest bucket is environments where the
cheap attacker already won, and there a second one *cannot* add information:
`CompositeChallenger` concatenates and the hackability probe takes the **max**
gap, so a model arm against a saturated floor can only match it or contribute
false positives. `docs/changelog/84-agentic-remeasured.md` Slice 33a established
that as an argument and then had nothing act on it. This is the code that acts
on it, and `test_escalation_is_refused_where_the_scripted_attacker_already_won`
pins it.

**Decision.** Kept, and scoped honestly. This is a **cost-control** policy and
its effect on detection is not measured here — whether escalation finds anything
depends entirely on what it escalates *to*. That question belongs to the
synthesis Challenger and its own measurement, not to this file, and writing one
number under both headings is how a cost saving gets reported as a capability.

**What it cost to learn.** The first draft of the threshold was tuned until the
firing set looked small, which is fitting a policy to the corpus it is measured
on. What it is tuned on now is the stated reason — a repertoire thin enough that
finding nothing is weak evidence — and the firing count is whatever that yields.
Twelve of twenty-six is not a flattering number and it is the one the rule
produces.
