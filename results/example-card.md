# Environment Card — `inspect/effort-scorer`

**Verdict: INVALID**  
A critical defect was found. Scores from this environment do not mean what they appear to.

| | |
|---|---|
| Ecosystem | `inspect_ai` |
| Environment version | `0` |
| Audited | 2026-08-28 23:21 UTC |
| Exit code | `1` |
| Signature | `0eae50d725cc087155a628216ec1e6d8…` |

## Coverage

3 probes passed · 5 found defects · 4 could not run · 0 errored

## Findings

### CRITICAL

**INVERT_PASSES** — `q1`

> gold passes even against an inverted success spec: the verifier cannot fail, so no score from it means anything

`reward`: 1.0

**INVERT_PASSES** — `q2`

> gold passes even against an inverted success spec: the verifier cannot fail, so no score from it means anything

`reward`: 1.0

**INVERT_PASSES** — `q3`

> gold passes even against an inverted success spec: the verifier cannot fail, so no score from it means anything

`reward`: 1.0

**INVERT_PASSES** — `q4`

> gold passes even against an inverted success spec: the verifier cannot fail, so no score from it means anything

`reward`: 1.0

**INVERT_PASSES** — `q5`

> gold passes even against an inverted success spec: the verifier cannot fail, so no score from it means anything

`reward`: 1.0

**REWARD_HACKABLE** — `q1`

`exploit_policy`: trivial:always_escalate; `reported_score`: 1.0; `true_completion`: 0.0; `exploit_gap`: 1.0; `threshold`: 0.5; `challenger`: scripted

**REWARD_HACKABLE** — `q2`

`exploit_policy`: trivial:always_escalate; `reported_score`: 1.0; `true_completion`: 0.0; `exploit_gap`: 1.0; `threshold`: 0.5; `challenger`: scripted

**REWARD_HACKABLE** — `q3`

`exploit_policy`: trivial:always_escalate; `reported_score`: 1.0; `true_completion`: 0.0; `exploit_gap`: 1.0; `threshold`: 0.5; `challenger`: scripted

**REWARD_HACKABLE** — `q4`

`exploit_policy`: trivial:always_escalate; `reported_score`: 1.0; `true_completion`: 0.0; `exploit_gap`: 1.0; `threshold`: 0.5; `challenger`: scripted

**REWARD_HACKABLE** — `q5`

`exploit_policy`: trivial:always_escalate; `reported_score`: 1.0; `true_completion`: 0.0; `exploit_gap`: 1.0; `threshold`: 0.5; `challenger`: scripted

### HIGH

**KNOWN_WRONG_PASSES** — `q1`

> a policy known to be wrong was accepted: weak oracle

`known_wrong_actions`: ['submit']; `reward`: 1.0

**KNOWN_WRONG_PASSES** — `q2`

> a policy known to be wrong was accepted: weak oracle

`known_wrong_actions`: ['submit']; `reward`: 1.0

**KNOWN_WRONG_PASSES** — `q3`

> a policy known to be wrong was accepted: weak oracle

`known_wrong_actions`: ['submit']; `reward`: 1.0

**KNOWN_WRONG_PASSES** — `q4`

> a policy known to be wrong was accepted: weak oracle

`known_wrong_actions`: ['submit']; `reward`: 1.0

**KNOWN_WRONG_PASSES** — `q5`

> a policy known to be wrong was accepted: weak oracle

`known_wrong_actions`: ['submit']; `reward`: 1.0

**TRIVIAL_FLOOR_BREACH**

> a policy that ignores the input scores at least as well, averaged over the whole task set, as the best real one

`best_trivial_policy`: always_escalate; `best_trivial_reward`: 1.0; `best_real_reward`: 1.0; `n_tasks`: 5

### MEDIUM

**SEPARABILITY_LOSS**

> the environment does not separate policies of known-differing quality

`declared_order_best_first`: ['strong', 'weak']; `mean_reward`: {'strong': 1.0, 'weak': 1.0}

## What could not be checked

These probes did not run. Nothing below was verified, and the verdict reflects that rather than assuming the best.

| Probe | Why not |
|---|---|
| `difficulty_band` | no solve-rate estimate supplied; pass ctx['solve_rates'] from a rollout sampler |
| `train_eval_leak` | environment does not expose: SPLITS |
| `partial_input_baseline` | environment does not expose: SPLITS, ITEM_PARTS |
| `assert_traceability` | scorer assertions are not machine-readable; inspect_ai scorers are opaque functions unless the suite declares requirements in metadata |

## Sign-off

_Unsigned._ This card blocks nothing until a human reviews it. The exit code is advisory input to that decision, not a substitute for it.

---

Produced by Assay. Signature covers the full probe output: `0eae50d725cc087155a628216ec1e6d84825df39546dc6fa511d2208bed37c87`
