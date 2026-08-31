# What Assay cannot see

A tool that reports what it could not check is only useful if somebody has
written down what it is unable to check *in principle*. This is that list,
stated in **someone else's vocabulary** so it cannot quietly be drawn around
whatever this tool happens to do.

The vocabulary is BenchJack's flaw taxonomy ([arXiv 2605.12673](https://arxiv.org/abs/2605.12673),
Fig. 2): eight recurring classes **V1–V8**, derived from reported reward-hacking
incidents across ten agent benchmarks. It is not Assay's taxonomy, it predates
this mapping, and it was not chosen because it flatters the result.

Two mappings follow, because a one-directional one is always flattering.

---

## Their classes → our probes

| | BenchJack class | Assay | How, or why not |
|---|---|---|---|
| **V1** | Isolation failure | **Detected, Harbor only** | `v1_neuter_a_reachable_verifier` rewrites any `*test*.sh` reachable in the workspace to `exit 0`; caught because `truth/test.sh` is mounted read-only outside it. Correctly a no-op under `environment_mode = "separate"`. |
| **V2** | Answers shipped with the test | **Not detected** | Nothing enumerates the runtime filesystem for a reference solution, and nothing resolves a URL — Assay's own sandbox runs with `network=False`, so the public-URL variant is not even executable *by the auditor*. Caught incidentally only when the answer file is agent-writable and at workspace root. Note `CONTAMINATION_*` is **not** V2: it compares an environment's train split to its own eval split, which is a measurement-validity property, not a runtime-reachability one. |
| **V3** | RCE into the evaluator | **Detected where the verifier is Python** | `verifier_static_analysis` parses the verifier with `ast` — the same machinery the wild sweep's scorer gate uses, shared through `assay.astscan` — and reports `EVALUATOR_RCE` for `eval`/`exec`/`compile`, `os.system`/`popen`, `subprocess(shell=True)`, `pickle`/`dill`/`marshal`/`joblib`/`torch.load`, and `yaml.load` without a safe loader. `from os import system` and `import yaml as y` resolve to the same sinks. **Two limits, both structural.** It reads only the source the adapter returns and does not follow calls out of it, so a clean result means "no sink in this source", never "safe" — the probe's own `asymmetry` field says so. And it needs Python: Harbor grades with `tests/test.sh`, which is refused as unparseable rather than passed, because a second parser for shell is a different tool. Fed by `InspectAdapter` and by the fixtures, which hand over `ToyEnv.verify`'s real source: **0 findings, 19 PASS, 7 NOT_APPLICABLE** (5 Harbor, 2 OpenEnv). |
| **V4** | LLM-judge prompt injection | **Structurally undetectable, by design** | "No LLM judge scores anything inside Assay." The response to a judged scorer is *exclusion with a recorded reason*, never probing: τ²'s `nl_assertions` are reported **absent, not passed**; the wild sweep denied 57 packages for `model_judge`. The honest form of this gap is that Assay does not falsely clear a judge-scored environment — it declines it. |
| **V5** | Weak string matching | **Detected** | Three routes: `inverted_fails` (the spec adapter's matcher vocabulary *is* the V5 vocabulary — substring, aggressive normalisation, regex), `known_wrong_fails`, and `trivial_floor`. Both external findings this repo has published — `paws`, `boolq` — are V5. **Gap:** Harbor withholds `INVERTIBLE_SPEC` by design (a shell verifier has no target to negate), so route one is `NOT_APPLICABLE` across that entire ecosystem. |
| **V6** | Evaluation logic gaps | **Detected — best covered** | The whole `verifier_integrity` family maps here: `GOLD_FAILS` (scoring broken), `NOOP_PASSES` (scorer never consulted), `INVERT_PASSES` (scorer cannot fail). `harbor/vacuous-tests` is a pure V6 instance and comes back with five defect classes. |
| **V7** | Trusting untrusted output | **Detected, Harbor only** | `v7_make_the_comparison_agree` writes one token into every workspace-root file plus every filename the instruction names, so any evaluator comparing two agent-writable files finds them equal. **Structural limit:** V7 needs `TRUE_COMPLETION` — a verifier the agent provably cannot reach. τ², OpenEnv and ScienceAgentBench have none, so the probe is `NOT_APPLICABLE` on all three. |
| **V8** | Excessive permissions | **Probe exists; no shipped adapter feeds it** | `declared_permissions` reads a `SandboxPosture` — network setting, mounts, read-only root, uid — and reports `EXCESSIVE_PERMISSIONS` on four rules: network granted for a task declaring no network step, a **writable mount covering the verifier**, a writable root filesystem, and root for a task declaring it does not need root. Every rule compares a *grant* against a *declared need* and fires only when the need is declared and is `False`; an undeclared need is reported as a check not made, never inferred from the instruction. This is the only family that judges a manifest rather than a behaviour, and the only one that can audit an environment nothing can execute. **What it is not yet:** the only environments declaring `SANDBOX_POSTURE` are the 12 in-process fixtures, whose posture is a minimal one written here; on the 14 real ones it is `NOT_APPLICABLE`. **0 findings, 12 PASS, 14 NOT_APPLICABLE.** See the note below — the reason is a corpus label, not an oversight. |

**Five of eight reached, four fed.** V1 and V7 are implemented as Harbor
policies, so on the shipped 26-environment corpus they are testable on five
environments and nowhere else — not because the probes are ecosystem-specific
but because no other adapter's repertoire contains the mechanism, and three of
six adapters cannot supply `TRUE_COMPLETION` to score it against.

V3 and V8 are new and neither has found anything yet, which is worth stating in
the order that makes it checkable rather than in the order that makes it sound
better. V3 runs on **19 of 26** and passes on all of them: seven of those are
real `inspect_ai` environments whose scorers were read and are clean, and twelve
are this repository's own fixtures, so it is a result about seven environments,
not nineteen. V8 runs on **12 of 26** and every one of those twelve is a fixture
whose posture is written a few lines from the probe. On the fourteen real
environments V8 has never executed:

> **`harbor/shared-tests` has V8, and wiring Harbor would change a published
> number.** Harbor's `task.toml` carries exactly what the probe wants.
> Constructing the posture the adapter already computes for itself —
> `read_only_root=True`, `network = (network_mode == "public")`, `/work` and
> `/logs` writable, `/suite` read-only, and the verifier at `/work/tests` under
> `environment_mode = "shared"` and at `/suite/<task>/tests` otherwise — fires
> `writable_verifier_mount` on `harbor/shared-tests` and on nothing else in the
> suite. That is a **correct** finding: it is V1's mechanism, sitting in the
> manifest where anyone could have read it, and it is why that fixture's planted
> set already contains `REWARD_HACKABLE`. But `EXCESSIVE_PERMISSIONS` is not in
> that planted set, so the finding scores as *spurious*, and closing the gap
> would require relabelling a scored corpus environment. Relabelling a corpus to
> accommodate a detector one has just written is the move this repository
> refuses everywhere else, and it is not going to be made quietly here. The
> declaration is one line in `HarborAdapter.manifest`; the label is a decision.

---

## Our classes → their taxonomy

All sixteen, mapped:

| `DefectClass` | BenchJack counterpart |
|---|---|
| `EXCESSIVE_PERMISSIONS` | **V8** — added to answer V8, so the mapping is exact by construction and proves nothing about either taxonomy |
| `EVALUATOR_RCE` | **V3** — likewise. It carves out of `REWARD_HACKABLE` the sub-case whose mechanism a report can name |
| `GOLD_FAILS` | V6 — weak; "the reference solution fails its own tests" is a quality defect, not an exploit |
| `NOOP_PASSES` | V6 |
| `INVERT_PASSES` | V6 / V5 |
| `KNOWN_WRONG_PASSES` | V5 / V6 — a plausible wrong answer a loose matcher accepts |
| `REWARD_HACKABLE` | umbrella over V1, V3, V7, and V2 in its writable sub-case |
| `TRIVIAL_FLOOR_BREACH` | **none** |
| `SEPARABILITY_LOSS` | **none** |
| `CONTAMINATION_EXACT` | **none** |
| `CONTAMINATION_NEARDUP` | **none** |
| `SHORTCUT_LEAK` | **none** |
| `SPEC_VERIFIER_MISMATCH` | **none** |
| `NONDETERMINISM` | **none** |
| `DIFFICULTY_SATURATED` | **none** |
| `DIFFICULTY_IMPOSSIBLE` | **none** |

**Nine of sixteen have no BenchJack counterpart**, and the two that now map
exactly were written to. That is worth saying plainly: `EXCESSIVE_PERMISSIONS`
and `EVALUATOR_RCE` are not independent evidence that two taxonomies converged —
they are this repository adopting two of someone else's classes after that
taxonomy told it what it had missed. A mapping is only informative in the
direction it was not fitted, and these two were fitted.

The nine are not a gap in the taxonomy either; the two are answering different
questions, and the three reasons are distinct:

- **Direction.** V1–V8 are all false-*positive* mechanisms — the agent scores
  higher than it earned. `SPEC_VERIFIER_MISMATCH` is a false-*negative* class:
  the verifier demands something the instruction never asked for, so a correct
  agent fails. A benchmark that is too harsh is not "jackable", so the taxonomy
  has no slot for it.
- **Layer.** `CONTAMINATION_EXACT`, `CONTAMINATION_NEARDUP` and `SHORTCUT_LEAK`
  are dataset properties. They corrupt the number whether or not any agent
  misbehaves. V1–V8 are harness properties exploited at runtime.
- **Kind of statement.** `TRIVIAL_FLOOR_BREACH`, `SEPARABILITY_LOSS`,
  `NONDETERMINISM`, `DIFFICULTY_SATURATED` and `DIFFICULTY_IMPOSSIBLE` are
  statistical properties
  of the reward surface, not mechanisms. A taxonomy derived from *reported
  incidents* has no entry for "this environment's scores are uninformative",
  because nobody files an incident about that.

The two now overlap on roughly {V1, V3, V5, V6, V7, V8}. Assay names six
families the taxonomy does not; BenchJack names V2 and V4 that Assay does not.

---

## A class of eval where the core assumption fails

Everything above is about mechanisms Assay cannot *reach*. This is worse: a
family of benchmarks where Assay runs happily, reports a **CRITICAL** defect,
and is wrong.

`inspect_evals/personality_BFI` is the Big Five Inventory. Audited with the
standard battery it returns **verdict INVALID, 25 × `INVERT_PASSES`** — the
class reserved for "the verifier cannot fail", which is CRITICAL because it
means every number the environment produces is meaningless.

The observation is mechanically correct. Its scorer, `any_choice()`, checks
`letter in target.text` and its own docstring says it "checks for response
format rather than factual correctness". `invert_spec` appends a suffix to the
target, and `"A" in "ABCDE_definitely_not_this"` is still true, so gold passes
against an inverted spec. The verifier genuinely cannot distinguish targets.

It is also **semantically wrong**, because a personality inventory *has no
correct answer*. "I see myself as someone who is talkative — strongly agree to
strongly disagree" has five legitimate responses; the trait score is computed
from `answer_mapping` metadata, not from the scorer. A format check is the right
design, and Assay calls it a critical defect.

**The assumption that fails is Assay's, not the benchmark's:** the
verifier-integrity family takes for granted that a verifier's job is to
separate correct from incorrect. On preference elicitation, opinion surveys and
psychometric inventories that is false, and four of the twelve probes become
actively misleading rather than merely inapplicable.

That distinction matters for anyone reusing this. A probe that reports
`NOT_APPLICABLE` costs a reader nothing. **A probe that reports CRITICAL on a
healthy environment costs them the tool's credibility**, and no amount of
`NOT_APPLICABLE` discipline elsewhere protects against it. The right fix is a
capability an eval can withhold — "this environment has no correct answer".

**That capability now exists, and this paragraph said it did not for longer
than that was true.** `assay audit --auditor` runs a semantic gate that can
move a `verifier_integrity` DEFECT to `NOT_APPLICABLE` — never to PASS, never
into another family — and on the 13-environment set in
`results/semantic_gate.json` a `claude-cli:sonnet` backend withholds the
`personality_BFI` verdict 1 of 1 with 0 false positives on the 12 environments
that do have a correct answer. It is **off by default** and changes none of the
headline numbers. `qwen3:8b` fires on nothing, which is the honest form of the
same measurement: the gate is the conjunction of the model's label and the
model's evidence, and a model that cannot hold both together produces no
override at all. `docs/changelog/99-semantic-gate.md` has the two designs that
were measured and rejected first.

Found while triaging candidates for the corpus. `personality_BFI` is
deliberately **not** added: an environment the tool is wrong about does not
belong in the set used to measure the tool, and adding it labelled either way
would corrupt the number rather than test it.

---

## "No probe" versus "no adapter can feed it"

These are different failures and conflating them would overstate both.

**No probe exists — building adapters changes nothing:** V2, and V4 (excluded
by an architectural rule rather than a missing feature). V3 and V8 were in this
bucket and are not any more; V2 still is.

**A probe exists but no adapter feeds it:**

- **V8 everywhere** — the newest and the starkest. `declared_permissions` runs
  against a planted posture in `tests/test_dead_zone_probes.py` and against
  nothing in the corpus, because no shipped adapter declares
  `SANDBOX_POSTURE`. The blocker is not adapter work: Harbor's `task.toml`
  already carries the posture, and the reason it is not wired is the corpus
  label, written out under the V8 row above.
- **V3 outside inspect_ai** — `verifier_static_analysis` needs Python source.
  Harbor's `tests/test.sh` is refused as unparseable rather than passed, τ²'s
  verifier is an assertion list rather than source, and OpenEnv computes reward
  inside `step()`. Only `InspectAdapter` can hand over a scorer to read.
- **V1 and V7 outside Harbor** — the probes are general, the payloads are not.
- **V5 on Harbor** — `inverted_fails` works; Harbor cannot feed it, correctly.
- **`SHORTCUT_LEAK` and `CONTAMINATION_*` on nearly every real ecosystem** —
  both probes work, but `SPLITS`/`ITEM_PARTS` are declared by the fixtures, one
  `inspect/leaky-split`, and any submitted spec that carries splits. Harbor: 0 of
  5. τ²: refused with a written reason.

That last one is the same failure running in the other direction, and it is why
the corpus's one remaining miss is what it is. `inspect_evals/boolq` carries
`SHORTCUT_LEAK`; `WildInspectAdapter` supplies no train split; the probe declines
before it runs. **A miss because a probe cannot execute is a coverage gap, not
bad luck** — and it is the more useful kind to publish, because inventing a
train split for somebody else's benchmark would have closed it by constructing
the very structure being audited.
