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
| **V3** | RCE into the evaluator | **Not detected** | No static analysis of verifier source for `eval`/`exec`/`pickle`/`yaml.load`, and no `DefectClass` for it. A Challenger could in principle land one on Harbor, but it would surface as `REWARD_HACKABLE` with no evidence field ever saying "RCE". |
| **V4** | LLM-judge prompt injection | **Structurally undetectable, by design** | "No LLM judge scores anything inside Assay." The response to a judged scorer is *exclusion with a recorded reason*, never probing: τ²'s `nl_assertions` are reported **absent, not passed**; the wild sweep denied 57 packages for `model_judge`. The honest form of this gap is that Assay does not falsely clear a judge-scored environment — it declines it. |
| **V5** | Weak string matching | **Detected** | Three routes: `inverted_fails` (the spec adapter's matcher vocabulary *is* the V5 vocabulary — substring, aggressive normalisation, regex), `known_wrong_fails`, and `trivial_floor`. Both external findings this repo has published — `paws`, `boolq` — are V5. **Gap:** Harbor withholds `INVERTIBLE_SPEC` by design (a shell verifier has no target to negate), so route one is `NOT_APPLICABLE` across that entire ecosystem. |
| **V6** | Evaluation logic gaps | **Detected — best covered** | The whole `verifier_integrity` family maps here: `GOLD_FAILS` (scoring broken), `NOOP_PASSES` (scorer never consulted), `INVERT_PASSES` (scorer cannot fail). `harbor/vacuous-tests` is a pure V6 instance and comes back with five defect classes. |
| **V7** | Trusting untrusted output | **Detected, Harbor only** | `v7_make_the_comparison_agree` writes one token into every workspace-root file plus every filename the instruction names, so any evaluator comparing two agent-writable files finds them equal. **Structural limit:** V7 needs `TRUE_COMPLETION` — a verifier the agent provably cannot reach. τ², OpenEnv and ScienceAgentBench have none, so the probe is `NOT_APPLICABLE` on all three. |
| **V8** | Excessive permissions | **Not detected** | The clearest gap. Nothing reads a sandbox policy, uid, mount list or network setting and emits a finding. Assay does the *inverse*: it imposes containment on itself and **obeys** a task's declared permissions rather than judging them — `network_mode` and `environment_mode` are parsed and never asserted on. V8 is a static property of a deployment; Assay is a behavioural auditor of scoring. No adapter work closes this without a new probe family. |

**Four of eight detected, and two of those on one ecosystem.** V1 and V7 are
implemented as Harbor policies, so on the shipped 26-environment corpus they are
testable on five environments and nowhere else — not because the probes are
ecosystem-specific but because no other adapter's repertoire contains the
mechanism, and three of six adapters cannot supply `TRUE_COMPLETION` to score it
against.

---

## Our classes → their taxonomy

All fourteen, mapped:

| `DefectClass` | BenchJack counterpart |
|---|---|
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

**Nine of fourteen have no BenchJack counterpart.** That is not a gap in the
taxonomy; the two are answering different questions, and the three reasons are
distinct:

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

The two overlap on roughly {V1, V5, V6, V7}. Assay names six families the
taxonomy does not; BenchJack names V2, V3, V4 and V8 that Assay does not.

---

## "No probe" versus "no adapter can feed it"

These are different failures and conflating them would overstate both.

**No probe exists — building adapters changes nothing:** V2, V3, V8, and V4
(excluded by an architectural rule rather than a missing feature).

**A probe exists but no adapter feeds it:**

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
