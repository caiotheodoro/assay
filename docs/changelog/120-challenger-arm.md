# `--challenger-arm`: the agent as a row, and the first thing it did

**Slice.** `--challenger` replaces the assay arm — a run produces
`assay+scripted+prompted[...]` *instead of* `assay`, so no artifact has ever held
both, and "the agent is in the headline table and it changes nothing" was true
only because the default kept it out of the table. `--challenger-arm` adds a row
instead, gated by `Auditor.should_escalate`, which had no runtime consumer at all
until now despite being measured in `results/escalation_policy.json`.

**Command.**

```
ASSAY_APPROVE_ALL=... uv run --extra adapters --extra sweep --extra openenv \
  --extra tau2 python scripts/full_run.py --only toy-triage noanswer \
  --allow-reduced --challenger-arm qwen3:8b --challenger-turns 2
```

**Result, on the three environments with no correct answer:**

| env | `assay` | `assay+scripted+prompted[ollama:qwen3:8b]` |
|---|---|---|
| `toy-triage/preference` | 4 findings | 4 findings |
| `noanswer/ranking` | 4 findings | 4 **+ REWARD_HACKABLE** |
| `noanswer/openended` | 4 findings | 4 **+ REWARD_HACKABLE** |

Nothing is planted in any of them, so every finding on these three is a false
positive and the model Challenger **added two more**. It escalated on all three,
which the policy is right to do — the scripted attacker found nothing and the
repertoire is thin — and then it reported reward hacking in an environment that
has no reward to hack.

**This is the same failure the semantic gate exists to catch, arriving from the
other direction.** The gate stops the battery calling a no-answer environment
broken; nothing yet stops an agentic *attacker* doing it. The Auditor reads
probe output, and a Challenger finding enters as `REWARD_HACKABLE` under
`reward_hackability`, which `SEMANTIC_SCOPE` deliberately excludes because it is
the only CRITICAL class and a false withhold there hides the worst defect.

**Not run, and therefore not claimed:** the full corpus at k=3 with
`claude-cli`. `results/challenger_reliability.json` puts the agentic hit rate at
3 of 4, so one pass is not a claim, and a pass costs hours — a smoke run over 12
fixture environments was stopped at 2h19m without completing. The cheap run
above is what is claimed: the arm works, the escalation policy selects, and the
first measured effect of the model Challenger on this corpus is a precision
loss.
