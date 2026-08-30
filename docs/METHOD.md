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
margin. The check did not change; the tool did.)*

**The check.** The crossover is analytic, not a bisection: if your detector's
loss is all misses and the floor's is all false alarms, they cross at
`shipped × floor / yours`. Publish it. "Costs are illustrative" hides whether
the margin is 21% or 685%.

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

**The check.** Report the distribution, not a run. And ablate downward — the
comparison that matters is against the version with the agent removed.

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

## What this does not buy

It does not make the tool better at finding defects. On that axis we are behind
the field and say so — ABA audits 34,285 tasks, BenchJack 219 flaws across ten
benchmarks, and our corpus is 26 environments of which **4** are genuinely
third-party.

What it buys is that every number here can be interpreted. When we say the
detector separates from its floor — 274.0 saved, 95% CI [186, 326] — that
sentence has a floor behind it, a cost sweep, a provenance split, a
pre-registration, and an adversary who tried to break it and is quoted where it
succeeded.

**Two rules underneath all six.** Absence of evidence is reported as loudly as
evidence: a check that could not run must never read as a check that passed. And
a correction that improves your own score carries the burden of proof — when
relabelling two fixtures lifted our precision from 0.959 to 1.000, the labels
were re-derived from the environments' own scripts with our tool out of the
loop, and **both numbers were published**, because the margin was 274.0 either
way and the result had to be shown not to depend on it.
