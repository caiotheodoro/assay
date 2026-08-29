# OpenEnv audit — huggingface/OpenEnv @ e059726da215f615c44dd10f60402970a3cb20ad

Reproduce with `uv sync --extra dev --extra adapters --extra openenv`, then the
commands below. No Docker, no GPU, no API key, no network at audit time. The NLTK
`words` corpus must already be present locally — the corpus provider reports its
absence as a reason rather than fetching it behind the caller.

## The battery

```
$ uv run assay audit openenv/echo
openenv/echo  [openenv]  verdict: UNVERIFIED
coverage: {'PASS': 1, 'DEFECT': 0, 'NOT_APPLICABLE': 11, 'ERROR': 0}
  - gold_passes: NOT_APPLICABLE (environment does not expose: GOLD_TRAJECTORY, SEPARABLE_VERIFIER)
  - noop_fails: NOT_APPLICABLE (environment does not expose: SEPARABLE_VERIFIER)
  - inverted_fails: NOT_APPLICABLE (environment does not expose: GOLD_TRAJECTORY, INVERTIBLE_SPEC, SEPARABLE_VERIFIER)
  - known_wrong_fails: NOT_APPLICABLE (environment does not expose: KNOWN_WRONG, SEPARABLE_VERIFIER)
  - trivial_floor: NOT_APPLICABLE (environment does not expose: GRADED_POLICIES, SEPARABLE_VERIFIER)
  - separability: NOT_APPLICABLE (environment does not expose: GRADED_POLICIES, SEPARABLE_VERIFIER)
  - difficulty_band: NOT_APPLICABLE (no solve-rate estimate supplied; pass ctx['solve_rates'] from a rollout sampler)
  - train_eval_leak: NOT_APPLICABLE (environment does not expose: SPLITS)
  - partial_input_baseline: NOT_APPLICABLE (environment does not expose: SPLITS, ITEM_PARTS)
  - assert_traceability: NOT_APPLICABLE (verifier assertions are not machine-readable)
  - challenger: NOT_APPLICABLE (environment does not expose: TRUE_COMPLETION, SEPARABLE_VERIFIER)
exit code: 1
```

```
$ uv run assay audit openenv/textarena-wordle
openenv/textarena-wordle  [openenv]  verdict: DEFECTIVE
coverage: {'PASS': 0, 'DEFECT': 1, 'NOT_APPLICABLE': 11, 'ERROR': 0}
  [MEDIUM] NONDETERMINISM on Wordle-v0
  - gold_passes: NOT_APPLICABLE (environment does not expose: GOLD_TRAJECTORY, SEPARABLE_VERIFIER)
  - noop_fails: NOT_APPLICABLE (environment does not expose: SEPARABLE_VERIFIER)
  - inverted_fails: NOT_APPLICABLE (environment does not expose: GOLD_TRAJECTORY, INVERTIBLE_SPEC, SEPARABLE_VERIFIER)
  - known_wrong_fails: NOT_APPLICABLE (environment does not expose: KNOWN_WRONG, SEPARABLE_VERIFIER)
  - trivial_floor: NOT_APPLICABLE (environment does not expose: GRADED_POLICIES, SEPARABLE_VERIFIER)
  - separability: NOT_APPLICABLE (environment does not expose: GRADED_POLICIES, SEPARABLE_VERIFIER)
  - difficulty_band: NOT_APPLICABLE (no solve-rate estimate supplied; pass ctx['solve_rates'] from a rollout sampler)
  - train_eval_leak: NOT_APPLICABLE (environment does not expose: SPLITS)
  - partial_input_baseline: NOT_APPLICABLE (environment does not expose: SPLITS, ITEM_PARTS)
  - assert_traceability: NOT_APPLICABLE (verifier assertions are not machine-readable)
  - challenger: NOT_APPLICABLE (environment does not expose: TRUE_COMPLETION, SEPARABLE_VERIFIER)
exit code: 1
```

## What the reward alone shows, where a probe cannot

The reward `step()` reports is still readable, and `describe()` prints it. It is
printed rather than scored for two reasons. Nothing on the client contract says
which of these numbers is a pass, so scoring them would mean inventing a
threshold. And on Wordle they are not stable: the secret word is redrawn every
episode, so the same policy earns a different reward each run — which is the
nondeterminism finding, seen from the other side. A trivial floor needs a fixed
task to measure against, and this environment does not offer one.

```
$ uv run python -c "from assay.adapters.openenv import OpenEnvAdapter, echo_binding, wordle_binding; [print(OpenEnvAdapter(b).describe()) for b in (echo_binding(), wordle_binding())]"
environment: openenv/echo
reward reported by the environment, per input-ignoring policy:
  echo / list_tools_only: final=0.0 steps=1 rewards=[0.0, None]
  echo / echo_empty_string: final=0.0 steps=1 rewards=[0.0, None]
  echo / noop: final=0.0 steps=0 rewards=[0.0]
environment: openenv/textarena-wordle
reward reported by the environment, per input-ignoring policy:
  Wordle-v0 / repeat_one_guess: final=0.4 steps=3 rewards=[0.0, 0.0, 0.0, 0.4]
  Wordle-v0 / fixed_six_guesses: final=0.0 steps=6 rewards=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
  Wordle-v0 / non_answer: final=0.0 steps=2 rewards=[0.0, 0.0, 0.0]
  Wordle-v0 / noop: final=0.0 steps=0 rewards=[0.0]
```

Run it twice and the Wordle numbers move. That is the point.
