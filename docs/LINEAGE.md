# Lineage — what existed before this repo, and what was added here

Ground rule #02 of the hackathon: make it clear what existed before the
competition and what was added. This file is that statement.

**No code was copied into this repo.** Everything under `src/` and `tests/` was
written for this submission. The rows below are methodology this project
follows, with the file that states it, so a reader can check the debt.

## Written before, as prose — never executed

| What | Where | Form |
|---|---|---|
| Environment health dashboard: verifier integrity, solve-rate bands, harness fidelity, hack probes; the one-page report format ending "No report → no training" | `study/post-training/references/environments.md:26-146` | prose |
| `normalized_loss = (L_model − L_oracle)/(L_trivial − L_oracle)`; the trivial-policy list; the flat-cost profile as a theorem test, not a scenario | `study/post-training/references/criteria.md:47-55` | prose |
| "If you cannot beat always-escalate on total loss, the system has not earned existence" | `study/post-training/references/evals.md:71` | prose |
| Exact hashing is insufficient because train and eval come from the same generator under different seeds; MinHash at shingle 5 / 128 perms / Jaccard ≥ 0.8 | `study/hf-publication-specs.md` §11.4 | prose + script spec |
| Publication bar: bootstrap CIs on every number, trivial baselines published, contamination audit published, version tags | `study/hf-publication-specs.md` §11–12 | prose |

## Written before, as specification — zero implementation

| What | Where | Form |
|---|---|---|
| Probe runner shape: Gold / Noop / Invert / Known-wrong, fail closed | `keel/docs/superpowers/specs/04-keel-health.md` | spec, no code |
| Expected-loss oracle, trivial-baseline floor, flat-cost invariant | `blotter/docs/superpowers/specs/10-blotter-pack.md` | spec, no code |

## Working code in sibling projects — read for pattern, not vendored

`suture/forge/src/suture_forge/contamination.py` ·
`specula/forge/src/specula_forge/shortcuts.py` ·
`regretbench/src/lossbench/metrics/loss.py` ·
`reconforge/model/scripts/intervals.py` ·
`suture/model/src/suture_model/rlvr_reward.py`

## Added here

- Every probe, as executable code, against a common adapter protocol.
- The adapter abstraction itself, and the insistence that `verify` be separable
  from `step` — the primitive that makes the inverted-spec probe possible.
- Twelve fixture environments with planted defects and exact ground truth.
- The Environment Card: signed, fail-closed, with `NOT_APPLICABLE` reasons.
- The adversarial **Challenger** and the dense exploit-gap reward. This is the
  one component with no antecedent in the prose above; the closest prior text
  is a static five-row table of known hack patterns, not an agent that searches.
- Aggregating the trivial-floor and separability checks across the task set
  rather than per task — per-task comparison flags any task where the trivial
  answer happens to be right, which is small-n noise, not a property of the
  environment.
