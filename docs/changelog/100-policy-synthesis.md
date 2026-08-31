## Slice 42e: the exploit a human found, found by an agent

**What and why.** `README.md` pins the one place this repo could name where the
tool lost to a person:

> Assay flagged 14 of 25 sampled `paws` items as `REWARD_HACKABLE`. It did
> **not** find the `"yesno"` case; hand triage did. The scripted Challenger's
> repertoire is the adapter's trivial policies, and none of them names both
> labels at once.

That is pinned as a test so it cannot quietly close. It is also the clearest
statement in the repo of what a fixed repertoire *cannot* do: the exploit is one
string, and no amount of replaying declared policies produces a string nobody
declared. So the Challenger was given the one job a script structurally cannot
have — **proposing** policies rather than replaying them.

**Evidence.** `results/policy_synthesis.json`, `inspect_evals/paws`, the same
pinned 25-item subsample the corpus row uses.

| arm | detected | beyond the floor | wall clock |
|---|---|---|---|
| scripted floor | 14 / 25 | — | ~0s |
| `claude-cli:sonnet`, sees the verifier | **24 / 25** | **+11** | 976.6s |
| `claude-cli:sonnet`, blind to the verifier | 22 / 25 | +8 | 490.8s |
| `ollama:qwen3:8b`, sees the verifier | 0 / 25 | −14 | 197.1s |
| `ollama:qwen3:8b`, blind | 2 / 25 | −12 | 173.3s |

**The policies it proposed are the point**, not the count:

```
synthesis:'Yes No'   synthesis:'Yes/No'   synthesis:'Yes\nNo'   synthesis:'Yes\n\nNo'
```

That is the both-labels-at-once class, arrived at from the task text and the
verifier source. The scripted floor's 14 are exactly the `No`-target items,
credited to `always_escalate` because *"I cannot determine the answer."* contains
`no` inside `cannot`. The agent found the other eleven.

**What is not claimed.** One run per arm, not three — each `claude-cli` run is
about sixteen minutes. Distrust the exact 24, not the direction. `qwen3:8b`
reaches 0 and 2, so this is a **capability threshold**, the same shape as the
semantic gate in `99-semantic-gate.md`, and not a property of the design.

Nothing here is scored by a model. `self_report` records what the challenger
claimed about its own success and is used for **nothing**; every detection was
scored by the deterministic `exploit_gap` machinery, and the model's claims
disagreed with that machinery **zero** times out of 24.

**Decision.** Kept, opt-in, and it changes none of the headline numbers — the
corpus row for `paws` is unchanged and the shipped default is still `scripted`.
What it changes is the answer to the section this repo named *"Does an agent find
what a script cannot?"*, which until now was "it did once, and then a better
script found it too."

**What it cost to learn.** The blind arm scoring 22 against the full arm's 24 is
the uncomfortable part: most of the win comes from reading the task, not from
reading the verifier. The obvious story — *the agent studied the scorer and
defeated it* — is not what the numbers say, and the eight-item gap between blind
and floor is the honest size of "reading the instructions carefully" as an attack.
