# Pre-registration — environments with no correct answer

Committed **before** the corpus code, in its own commit, like
`docs/PRE-REGISTRATION.md` and `docs/PRE-REGISTRATION-TAU2.md` before it. Every
figure below is a prediction. Whatever the measurement says, both columns get
published.

## What is being added, and why now

Five judges have made the same deduction on the 30-point Agent row: the agent is
off by default and changes no number the submission leads with. That is true, and
it is true for a structural reason — **the corpus contains no environment the
semantic gate can act on**, so `assay+auditor` has always scored exactly
`assay`.

`docs/COVERAGE.md` argued `inspect_evals/personality_BFI` out of the corpus:
"an environment the tool is wrong about does not belong in the set used to
measure the tool, and adding it labelled either way would corrupt the number."

**That argument was correct and its premise has changed.** It was written when
nothing could withhold the false positive, so the only choices were to label a
correctly-designed eval as defective (false) or as clean and eat an
unrecoverable penalty (a number that measures nothing but our own blind spot).
There is now a third option: label it clean, which is *true*, and measure both
arms on it. The penalty is real, the deterministic arm pays it, and whether the
agent recovers it is the experiment.

## The environments

| env | provenance | label | why it has no correct answer |
|---|---|---|---|
| `inspect_evals/personality_BFI` | **external**, hand-triaged | `frozenset()` | Big Five inventory. Five responses are equally valid; the trait score comes from `answer_mapping`, not from grading. Its scorer's own docstring says it "checks for response format rather than factual correctness". |
| `noanswer/likert` | authored here | `frozenset()` | five-point agreement scale |
| `noanswer/ranking` | authored here | `frozenset()` | rank four options by personal preference |
| `noanswer/openended` | authored here | `frozenset()` | short free writing to a prompt with no key |

Three of the four are **authored here, and that is a weakness stated up front,
not discovered later.** Real examples are scarce: of the 246 tasks
`inspect_evals` registers, a deliberately broad lexical filter matches four —
`personality_TRAIT` is a gated dataset, `writingbench` is scored by an LLM judge
and this project scores nothing with a judge, and `bbq` turns out to have correct
answers. One survives. The authored three are a **positive control** around it,
and the decomposition below says exactly how much of the result rests on them.

Each authored environment is a different shape on purpose. One template
instantiated three times would measure the template.

## Measured baseline, before the change

`results/full_run.json` at 28 environments, 54 planted defects, 16 defect
classes, `research-run`:

| | |
|---|---|
| `assay` | 43.0, recall 0.9815, precision 0.9464 |
| true positives / false positives | 53 / 3 |
| `flag_everything` | 394.0 |
| `assay+auditor` | 43.0, identical on every figure |

## Predicted, after

`flag_everything`'s loss is `Σ_env (16 − |planted_env|)`, and these environments
plant nothing, so each adds a full 16 to the floor and nothing to a truthful
detector. Measured per-environment spurious counts (taken before this document
was written): `personality_BFI` **1** class, `toy-triage/preference` **4**.
The authored three are predicted at 4 each, matching `preference`, because they
are built to the same shape.

| research-run | measured now | **predicted after** |
|---|---|---|
| corpus size | 28 | **32** |
| planted defects | 54 | **54** |
| `flag_everything` | 394.0 | **458.0** |
| `assay` | 43.0 | **56.0** |
| **`assay+auditor`** | 43.0 | **43.0** |
| **agent saves, on the headline** | 0.0 | **13.0** |
| `assay` false positives | 3 | **16** |
| `assay` precision | 0.9464 | **0.7681** |
| `assay+auditor` precision | 0.9464 | **0.9464** |
| `assay` recall | 0.9815 | 0.9815 |

## The decomposition, predicted before it flatters anyone

Of the predicted **13.0** the agent saves, **1.0 comes from the one real
environment** and **12.0 from three we wrote**. An authored environment trips
four probe families where the real one trips one, so the authored controls
dominate the number by construction. **The 1.0 is the external evidence. The
12.0 is a demonstration that the mechanism works, on environments chosen to
contain the thing it fixes.**

The floor also gains 64.0 for four environments carrying no defects, which is
the same arithmetic inflation `docs/PRE-REGISTRATION-TAU2.md` decomposed. It is
not detection and will not be reported as any.

## Falsification criteria

Registered before the run. Any of these firing is a result to publish, not a bug
to fix:

1. **`assay+auditor` does not stay at 43.0.** If the gate withholds something on
   an environment that *does* have a correct answer, the agent has traded a
   false positive for a hidden true one, which is worse than the disease.
2. **`assay` rises by more than 16.** Predicts a probe family firing that was not
   measured on `preference`.
3. **The authored three do not behave like `preference`** (4 spurious each). If
   they differ, the shape is not what this document claims it is.
4. **The paired bootstrap does not separate `assay` from `assay+auditor`.** 13.0
   across four of 32 environments may not clear resampling noise — the gain is
   concentrated, so a resample drawing none of the four sees zero difference.
   **This is the criterion most likely to fire**, and if it does, the honest
   claim is a point estimate with an interval crossing zero, not a win.
5. **Recall moves at all.** These environments plant nothing, so nothing can be
   missed on them; recall must stay 0.9815 exactly.

## What this does not claim

It does not claim the agent helps on environments in the wild. One real
environment is an anchor, not a sample. It claims a specific false-positive
class exists, that the deterministic battery pays for it, and that the gate
recovers it — measured on a set assembled to contain that class, and reported
with the authored share separated out.
