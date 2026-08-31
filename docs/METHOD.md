# Auditing the auditor

**An auditor is an eval. An unaudited auditor hands you an unaudited number
telling you your benchmarks are fine.**

This project builds a tool that audits RL environments and eval suites. Partway
through, the obvious question got asked out loud: *if benchmarks ship unchecked
because nobody QAs them, what exactly makes the QA tool different?* Nothing. So
every instrument the tool applies to an environment was turned on the tool.

**Twelve of this repository's published claims broke.** The self-audit also
found three real behavioural bugs, not just bad prose. What follows is the
protocol, written so it transfers: six checks, each with what it cost us when we
ran it. None of them requires our code.

The claim is not that we detect more defects than the field — we do not, and
[the numbers say so](README.md#prior-art). The claim is that **a finding is not
a result until you know what it is worth**, and these six checks are what that
takes.

---

## 1. Give your auditor a trivial floor, and publish it

> *"If it cannot beat the best policy that ignores its input, it has not earned
> its existence."* — `src/assay/metrics.py`

We apply that rule to every environment we audit. We had never applied it to our
own external measurement.

**What it cost us.** Our headline third-party number was recall **0.339** against
62 independently labelled τ²-bench defects. Flagging the same 54 of 164 tasks
uniformly at random lands 20.41 positives in expectation; we landed 21.
One-sided hypergeometric **p = 0.486**. Precision 0.389 against a base rate of
0.378 — the precision of *any* random flagger. **The headline was chance**, and
the base rate `62/164` appeared nowhere in the repository.

The framing was also inverted: the row we relegated as narrower
(`excluding assert_traceability`, recall 0.210) is the only one that clears the
floor, at **p = 0.040**.

**The check.** For an auditor, the floor is a flagger that picks the same number
of items at random. It is one hypergeometric away and needs no model. If you
report recall on an imbalanced set without it, you have reported a number nobody
can interpret — including you.

`scripts/tau2_recall.py` · `results/tau2_recall.json`

### The same test, pointed outward

Having failed our own floor test, the obvious question is what it says about
the numbers this category publishes. Mostly it cannot be asked, and the reason
is specific rather than sloppy.

BenchGuard ([arXiv 2604.24955](https://arxiv.org/abs/2604.24955)) Table 2
reports, on ScienceAgentBench, **12 confirmed defects across 102 tasks** and
per-model recall up to **83.3%**. Its precision column is *flagged-task
precision*, defined in the caption as "computed over findings within tasks
containing confirmed defects"; findings on the other 90 tasks fall outside both
columns. **So the number of tasks flagged is not recoverable from the table** —
and that is the one quantity a floor test needs.

The authors state the convention and defend it: *"For a human-in-the-loop
auditing tool, recall is the primary objective: missing a genuine defect risks
corrupting leaderboard conclusions, whereas a false positive costs only a few
seconds of expert review."* That is a coherent position about triage, and none
of this is a claim about their rigour. It is a claim about what the published
table supports.

Sweeping the missing number (`scripts/floor_of_the_field.py`):

| reported | stops clearing the floor at | as a share of the benchmark |
|---|---|---|
| ensemble, 11/12 (91.7%) | 69 tasks flagged | 68% |
| best single model, 10/12 (83.3%) | 59 tasks flagged | 58% |
| **four of five models, 7/12 (58.3%)** | **34 tasks flagged** | **33%** |

The top rows are almost certainly real results: an auditor flagging 58% of a
benchmark would be an odd tool. **The 58.3% rows are the uncomfortable ones** —
they stop being distinguishable from random at a third of the benchmark, which
is well inside what an auditing tool might plausibly flag. Nothing in the paper
lets a reader tell, and no baseline or significance test is reported alongside.

We can only point this out because we ran it on ourselves first and it came back
`p = 0.486`.

`scripts/floor_of_the_field.py` · `results/floor_of_the_field.json`

---

## 2. Declare provenance, and make it a scoring rule

An empty defect set is what a verified-clean environment carries **and** what one
nobody looked at carries. They are the same value and not the same claim.

**Why it matters more than it sounds.** On a per-defect-class loss,
`flag_everything` costs `Σ_env (14 − |planted_env|)`. Every clean environment
added moves the trivial floor by `14 × false_alarm` and a truthful detector by
**zero** — `+14` on our research profile, **`+112`** on the publication profile.
Roughly eight unlabelled environments flip a headline with no change to the
detector at all. Worse, `normalized_loss` divides by `min(trivial_arms)`, so
growth improves the normalised figure almost unconditionally: simulated,
**+100 clean environments takes 0.828 → 0.142**.

**What it cost us.** Our corpus was **22 of 24 self-authored**, and we had said
otherwise in print — a split computed on a filename prefix and then described in
words the prefix did not support.

**The check.** Record who wrote each environment and who established its labels.
Then make the distinction load-bearing: environments whose labels nobody
established are audited and reported but **excluded from every scored number**.
Ours (`Provenance.is_evidence`) existed as vocabulary and gated nothing for
months.

`src/assay/corpus.py` · `scripts/corpus_splits.py`

---

## 3. Pre-register the arithmetic before you grow the corpus

Because of §2, corpus growth is a lever on your own headline. The defence is to
write down what the arithmetic predicts **before** writing the code, and commit
it separately so the ordering is checkable in version control rather than
asserted.

**What it cost us.** Nothing — and that is the point. Adding two external
environments, we predicted the floor 290.0 → 316.0, our loss 240.0 → 280.0, the
margin narrowing 50.0 → 36.0. **Every number landed exactly, and every one made
us look worse.** An expansion that *widens* your margin needs its arithmetic
explained before anyone should believe it.

One falsification criterion fired, and not the predicted one — see §6.

`docs/PRE-REGISTRATION.md`

---

## 4. Sweep the cost model you invented

Expected-loss framings need a price for a miss. Ours is 120 "engineer-hours-
equivalent" for a CRITICAL defect and nothing derives it. Every published number
scales linearly with it.

**What it cost us.** Sweeping it put the crossover — where flagging everything
wins — at **145 against a shipped 120**. The entire headline survived a **21%
error** in a number somebody guessed. That was the sharpest criticism of this
work, and it was only sayable because we ran the sweep.

*(After later work closed two detector misses the crossover moved to 942, a 685%
margin. The check did not change; the tool did. It then moved again, to **1100**
— an 816% margin — and that time the tool did not change either: the crossover's
numerator is `flag_everything`'s loss, and two probe families added to the
taxonomy plus two τ² environments added to the corpus raised it. A safety margin
that widens because the floor got worse is a different fact from one that widens
because the detector got better, and only the second is a result.)*

**The check.** The crossover is analytic, not a bisection: if your detector's
loss is all misses and the floor's is all false alarms, they cross at
`shipped × floor / yours`. Publish it. "Costs are illustrative" hides whether
the margin is 21% or 815%.

`scripts/cost_sensitivity.py`

---

## 5. Ablate your own agent against a dumb floor

If your tool has an agentic component, the question is not whether it works. It
is whether it beats the cheapest thing you could have written instead.

**What it cost us.** Ours does not. Over four independent runs a composite
Challenger driven by a frontier model, ten turns per environment, ~30 minutes a
run, **matched a four-policy fixed repertoire and never beat it** — and before a
bug was fixed it scored *worse*, losing a defect the script catches for free.

That bug is the finding: a member that could not reach its model raised, and the
composite let the exception discard attempts an earlier member had **already
successfully made**. The probe recorded `n_attempts: 0` and reported
`NOT_APPLICABLE`. A stochastic agent producing an identical result 4 times out
of 4 is what made it findable.

**Then the check kept paying, in the direction that hurts.** The exploit the
agent had found was written down as two fixed policies — named after the flaw
classes in a published taxonomy — and the script now finds both Harbor exploits
with no model at all, in about two seconds against ~30 minutes. So the honest
statement got stronger and less flattering at once: the agent demonstrated a
class existed, and the cheapest possible response captured it permanently.

It also **invalidated the measurement above**, so it was re-run. Against the
current floor: **agentic 0.0 loss, recall 1.000, precision 1.000 — identical to
the scripted arm**, at roughly 45 minutes and paid sampling against about two
seconds and nothing.

That re-run confirms rather than establishes the point, because there is a
proof. The composite concatenates its members' attempts and the probe takes the
**maximum** exploit gap over them, so composite detections are a *superset* of
scripted detections. Once the script is perfect on a slice, the agent cannot
improve it — only match it or add false positives. **An ablation against a
saturated floor cannot produce information**, and noticing that is cheaper than
buying it.

**The check.** Report the distribution, not a run. Ablate downward — the
comparison that matters is against the version with the agent removed. And when
the floor moves, the ablation is stale even though nothing about the agent
changed: an ablation is a claim about a *pair*, and it expires when either half
does.

`results/agentic_profile.json` · `src/assay/challenger/composite.py`

---

## 6. Have something adversarial read your write-up, then publish what it breaks

Every check above is one you choose to run. This is the one that finds what you
did not think to check.

**What it cost us.** **Twelve claims broke.** The external number was chance
(§1). Half the corpus was our own pytest fixtures, with a test asserting perfect
detection — a passing build wearing a measurement's clothes. An exploit was
published as "the winning policy, scored 1.0" that appears in **no run that
succeeded**. The Environment Card was described as *signed* and was an unkeyed
hash anyone could recompute in three lines.

It also caught what a prediction could not. §3's falsification list said that if
results stopped reproducing, our dataset-shuffle pinning had failed. Results
stopped reproducing and that was not why: a sandbox command hitting its wall
clock surfaced as a different exit code, and the determinism probe read it as a
**nondeterministic environment**. An inconclusive observation promoted to a
finding — the exact failure this tool audits environments for, happening inside
it, in 1 of 6 runs.

**The check.** Adversarial, not a re-read: the same context that wrote a claim
will not break it. Publish the breakage unedited. `docs/RED-TEAM.md` is ours,
including the six claims it could not break.

---

## Seventh check: say what you cannot see, in someone else's words

Every check above is inward. This one is the boundary of the tool, and stating it
in your own vocabulary is worthless — the categories get drawn around whatever
you happen to do.

[`docs/COVERAGE.md`](COVERAGE.md) maps Assay's eleven probe families onto
BenchJack's eight published flaw classes, in both directions. **Five of eight are
reached and four are fed**, and two of the four on one ecosystem only. V2 has no
probe at all; V3 and V8 have one each and are new, so V8 is `NOT_APPLICABLE` on
every corpus environment and V3 runs only where the verifier is Python. V4 is
excluded by an architectural rule rather than a missing feature, so the honest
form is that Assay *declines* a judge-scored environment rather than falsely
clearing it. In the other direction, nine of sixteen `DefectClass`
members have no counterpart in the taxonomy — for three distinct reasons, none of
which is that the taxonomy is deficient.

The distinction that matters for anyone reusing this: **"no probe exists" and "a
probe exists but no adapter can feed it" are different failures**, and only the
second is fixed by writing adapters. The corpus's one remaining miss is the
second kind.

## What this does not buy

It does not make the tool better at finding defects. On that axis we are behind
the field and say so — ABA audits 34,285 tasks, BenchJack 219 flaws across ten
benchmarks, and our corpus is 28 environments of which **6** are genuinely
third-party. Two of those six are τ²-bench domains whose ground truth another
organisation published at a commit, and on those 164 tasks, *per task*, our
recall is 0.339 and does not beat flagging at random.

What it buys is that every number here can be interpreted. When we say the
detector separates from its floor — 351.0 saved, 95% CI [263, 404] — that
sentence has a floor behind it, a cost sweep, a provenance split, a
pre-registration, and an adversary who tried to break it and is quoted where it
succeeded. It also has a decomposition: of that 351.0, **77.0 is the taxonomy
and the corpus growing and 274.0 is the detector**, and the first number is
published because nothing forced it to be.

**Two rules underneath all six.** Absence of evidence is reported as loudly as
evidence: a check that could not run must never read as a check that passed. And
a correction that improves your own score carries the burden of proof — when
relabelling two fixtures lifted our precision from 0.959 to 1.000, the labels
were re-derived from the environments' own scripts with our tool out of the
loop, and **both numbers were published**, because the margin was 274.0 at the
time either way and the result had to be shown not to depend on it.

That 1.000 no longer holds and the rule is why we can say so cleanly. Precision
is **0.9464**: registering two τ²-bench domains under a label an outside
organisation published cost three spurious findings, because an externally
derived label is a lower bound on what is wrong with an environment and
`Outcome.spurious` scores everything outside it as a false alarm. The
same burden applies with the sign flipped — the easy fix would have been to
widen the label until the false alarms disappeared, and that is the move
`docs/PRE-REGISTRATION-TAU2.md` was written to make visible rather than
available.
