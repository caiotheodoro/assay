# Pre-registration — `inspect_evals/stereoset`

Committed **before** the corpus entry, like the three pre-registrations before
it. Every figure is a prediction. Both columns get published.

## Why this environment

`docs/RETRACTIONS.md` entry 21 withdrew the claim that two no-answer
environments was "a ceiling rather than a choice". The filter behind it read
task *names*, so it could not match `stereoset`, whose name carries none of its
words. The corpus that resulted is three-quarters authored here, and that ratio
caps how strongly any result about the semantic gate can be stated.

`stereoset` is external (McGill-NLP, pinned), deterministic, and scored by no
LLM judge. Verified before this document: the battery returns **DEFECTIVE with
`GOLD_FAILS` × 10**, identical on two runs.

**The mechanism is different from `personality_BFI`'s, which is the point.**
`personality_BFI` trips `INVERT_PASSES` because its scorer checks response
format. `stereoset` trips `GOLD_FAILS` because it carries *two* scorers:
`multiple_choice_scorer` accepts either the stereotype or the anti-stereotype
option (`stereoset.py:308`, `target_letters` is built from both), while
`stereoset_scorer` returns a **signed bias measurement**,
`{stereotype: 1, anti-stereotype: -1, unrelated: 0}` (`stereoset.py:215`). The
reward is their mean, so an accepted answer scores `(1.0 + -1)/2 = 0.0` and Assay
reads a reference answer that fails. It is not a broken eval; it is a bias
measurement being read as a correctness grade.

One environment the tool is wrong about is an anecdote. Two, wrong in two
different ways, is a class.

## Predicted

From 32 environments, 54 planted, 16 defect classes, `research-run`, where the
floor is `Σ_env (16 − |planted_env|)` and `stereoset` plants nothing.

| | measured now | **predicted after** |
|---|---|---|
| corpus size | 32 | **33** |
| planted defects | 54 | **54** |
| `flag_everything` | 458.0 | **474.0** |
| `assay` | 56.0 | **57.0** |
| `assay` false positives | 16 | **17** |
| `assay` precision | 0.7681 | **0.7571** |
| **`assay+auditor`** | 43.0 | **43.0** |
| `assay+auditor` precision | 0.9464 | 0.9464 |
| recall, both arms | 0.9815 | 0.9815 |

Ten findings collapse to **one** spurious class, so the arm moves by 1.0 and the
floor by 16.0. The floor's 16.0 is arithmetic, not detection, and is not
reported as any.

## The prediction that is actually at risk

**That the gate withholds it at all.** This is a harder case than
`personality_BFI` and the honest reasons it might fail:

1. **Two options *are* accepted as correct.** Asked "does this environment have
   a correct answer?", a defensible answer is "yes, two of them". The gate would
   decline, the false positive would stand, and `assay+auditor` would measure
   **44.0**.
2. **The abstention guard may fire.** `stereoset`'s prompts are bare context
   sentences — "I'm going to visit Iraq." — with no question attached. The gate
   rejects a worked example that quotes the whole prompt (`auditor.py:477-491`),
   and on a prompt this short any example is close to the whole prompt. A gate
   that abstains leaves the finding standing, which is the fail-closed behaviour
   working as designed and still a miss for this prediction.

**Prediction: it withholds, and `assay+auditor` stays at 43.0.** Stated plainly
so that 44.0 counts as wrong rather than as a nuance.

## Falsification criteria

1. **`assay` does not land on 57.0.** Predicts a probe family firing that the
   two verification runs did not show.
2. **`assay+auditor` is not 43.0.** Either the gate declined (44.0, criterion 1
   above) or it withheld something on an environment that does have a correct
   answer, which is worse than the disease.
3. **Recall moves.** Nothing is planted here, so nothing can be missed here.
4. **`GOLD_FAILS` count is not 10.** Both verification runs gave 10; a different
   number means the subsample is not pinned the way `N_SAMPLES=25, SEED=0`
   claims.

## What this does not claim

Two external environments is not a sample. It claims the false-positive class is
real, is not confined to one eval, and takes more than one mechanical form —
measured on a set assembled to contain it, with the authored share still stated
separately.

---

## Measured

Run after this document was committed, with
`scripts/full_run.py --llm-arms qwen3:8b --auditor-arm claude`.

| | predicted | **measured** |
|---|---|---|
| corpus size | 33 | **33** |
| planted defects | 54 | **54** |
| `flag_everything` | 474.0 | **474.0** |
| `assay` | 57.0 | **57.0** |
| `assay` false positives | 17 | **17** |
| `assay` precision | 0.7571 | **0.757** |
| **`assay+auditor`** | **43.0** | **43.0** |
| `assay+auditor` precision | 0.9464 | **0.946** |
| recall, both arms | 0.9815 | **0.982** |

**Every row, including the one that was actually at risk.** This document named
the gate withholding at all as the prediction most likely to fail, for two
stated reasons: `stereoset` accepts *two* options as correct, so "yes, it has
correct answers" is a defensible reply, and its prompts are bare context
sentences short enough that the abstention guard could fire on any worked
example. Neither happened. The gate withheld the `GOLD_FAILS` finding and the
arm landed on 43.0, unmoved by adding an environment the deterministic battery
is wrong about.

**All four falsification criteria pass.** `assay` is 57.0, not something else;
`assay+auditor` is 43.0; recall did not move; and `GOLD_FAILS` fired 10 times as
both verification runs said it would.

**What this now supports, and what it still does not.** Two external
environments, wrong by two mechanisms — a format-only scorer producing
`INVERT_PASSES`, and a bias metric read as a grade producing `GOLD_FAILS` — and
the same gate recovers both without touching the three τ² findings, which are
real. That is a class rather than an anecdote. It is still two environments, it
is still a set assembled to contain the thing the gate fixes, and the three
authored no-answer environments still carry most of the arithmetic. None of that
changed.
