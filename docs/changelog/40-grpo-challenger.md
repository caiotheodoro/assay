# 40 — A GRPO-trained adversarial Challenger

The scripted Challenger misses `harbor/self-graded`, where the verifier reads
its expectation from a file the agent can overwrite. That miss is the reason
the corpus discriminates at all. This workstream asks whether an attacker
*trained* on the exploit gap closes it.

The reward is the whole idea:

```
reward = environment's reported score - independent true completion
```

computed by the harness, never by the policy. Solving the task honestly pays
zero. The only way to earn reward is credit that was not earned.

| Stage | What was tried and why | Evidence | Decision / learning |
|---|---|---|---|
| Split the attacker from the harness physically, not by convention | The existing invariant test reads challenger sources and fails on any mention of `true_completion`. Rather than route around it, `assay.challenger.grpo` was built to hold only the prompt, the parser and inference, and `assay.train` to hold the verifier and the reward. The invariant test now covers the new module too. | `uv run --extra adapters pytest tests/test_challenger.py -q`; `grep -c true_completion src/assay/challenger/grpo.py` → 0 | An attacker told the answer is not finding an exploit. Making the split a module boundary means it cannot erode by accident. |
| Reward first, no GPU | Order of work was reward + tests, verified locally, before any training script existed. 36 tests in `tests/test_grpo_reward.py`, four of which replay real Docker containers against the Harbor fixtures. | `uv run --extra adapters pytest tests/test_grpo_reward.py -q` → 36 passed in 3.06s | The exploit gap is provable without training anything. If it were wrong, no amount of training would make the adapter mean anything. |
| Honest solve must pay zero | A reward that paid for solving would train a solver and the run would still look like it worked. Asserted directly: `healthy` + correct submission → reported 1.0, completed 1.0, reward 0.0. | `test_solving_the_task_honestly_pays_zero` | The single most load-bearing property. Everything else is a matter of degree. |
| Dense, not binary | A bare "did it hack" signal is flat almost everywhere at low capability. `weak_oracle` accepts any valid category, so a wrong label collects the 0.6 label credit and none of the rationale credit — partial reward for partial unearned credit. `rationale_ignored` produces a genuine *negative*: a policy that did the job and was under-credited scores −0.4. | `test_the_reward_is_dense_not_binary`, `test_being_under_credited_for_real_work_pays_negative` | The reward spans [−1, 1] on real fixtures, not {0, 1}. |
| Unparseable ≠ empty policy | `{"actions": []}` is a real thing to propose. `"I refuse."` is not a policy at all. Collapsing them would pay gibberish whatever doing nothing happens to score. Parse failure pays −1.5, strictly below the worst any executable policy can earn. | `test_an_unparseable_completion_is_worse_than_every_policy_that_ran` | Format is learned before anything else, and emitting nothing is never the safe play. |
| Environments qualify by capability, not by a list | "Deliberately not OpenEnv" is enforced as `Capability.TRUE_COMPLETION`, with every exclusion printed and its reason recorded in `run.json`. | `EnvSelection.report()`; `test_the_toy_fixtures_are_trainable_and_the_holdout_is_named_as_held_out` | An ecosystem that cannot say what a policy accomplished would make the reward `score − score`, identically zero. That is not a weak signal, it is no signal. |
| Hold out the ablation target | `harbor/self-graded` is excluded from training by default. | `--holdout harbor/self-graded`; recorded in `excluded` in `run.json` | Training on the environment you then report a win on is train-on-test, and the number would mean nothing. |
| Measure the reward landscape before buying a GPU | GRPO learns from variance *within* a rollout group. An environment where every candidate scores the same contributes exactly zero gradient however many steps it gets. So: enumerate a repertoire of policies, score each with the real reward, count environments with nonzero spread. | `uv run --extra adapters python scripts/reward_landscape.py --holdout harbor/self-graded` → `results/reward_landscape.json` | **39 prompts, 19 with any signal, 51.3% flat.** Pre-registered before training, which is what makes any later convergence claim checkable. |
| The finding that predicts the result | On the environments that pay most, the highest-paying policy is the **empty** one. A verifier that rubber-stamps (`harbor/vacuous-tests`, `fixture/solved_at_reset`) hands full credit for doing nothing, so `{"actions":[]}` scores 1.0 there and 0.0 nearly everywhere else. It is never negative. | `results/reward_landscape.json`, rows with `"best_policy": "empty"` | `{"actions":[]}` is a real global optimum of this reward on this corpus. That is a **true reading of the reward, not a bug in it** — an environment that rubber-stamps nothing genuinely is hackable by nothing. But it is the cheapest hack available and it transfers to nothing. |
| CPU smoke gate before the spot instance | Two steps, tiny model, no GPU and no Docker. | `uv run --extra adapters --extra train python -m assay.train.run --smoke` → `GRPO SMOKE OK` | Immediately caught `TRL 1.12.0 does not accept ['max_prompt_length']`. On a spot instance that is a TypeError after the model download and before step one. The `dataclasses.fields` filter kept from suture's RLVR wiring earned itself on its first use. |
| Qwen3 thinking disabled | A `<think>` block inside a 160-token completion budget eats the whole completion. | `chat_template_kwargs={"enable_thinking": False}` in `grpo_kwargs` | The resulting parse rate of zero is indistinguishable from a model that cannot follow the format. Worth ruling out in advance rather than diagnosing later. |
| Balance the mix by environment, not by prompt | Toy fixtures contribute three tasks each, Harbor fixtures one. A flat cycle spends ~92% of the budget on in-process ticket triage. | `test_env_balancing_does_not_let_the_task_count_decide_the_training_mix` | The shell tasks are the only place the interesting exploit shape — edit the file the verifier reads — exists at all. Letting task counts decide the mix would have trained almost entirely on the wrong shape. |
| Launcher bugs found by running it, not reading it | Rendered the user-data and sourced the result. | `bash -n`, then `. /tmp/assay.env` | `ONLY=fixture harbor` unquoted in a sourced env file runs `harbor` as a command. `envsubst` is a gettext binary macOS does not ship. A fresh IAM instance profile is not visible to `RunInstances` for several seconds — seen on the first real launch, after the source tarball had already uploaded; now retried. |
| Source ships via S3, not git | The instance needs the code; this checkout has no remote. | `cloud/aws_spot_train.sh` uploads a tarball to the run's own bucket | Pushing a repo somewhere public in order to launch a training job is a publication decision, not a deployment detail. |

## The run

<!-- RESULTS -->

## What this cost

A spot `g5.xlarge` (A10G 24GB) in `us-east-1` at $0.4612/hr.
