## Slice 42c: the same answer, three times cheaper

**What and why.** The rubric this repo is scored against names the levers it
credits: *"better context or tools may improve one project, while memory,
verification, skills or orchestration may improve another."* Assay ships tools
(adapters), verification (the battery) and skills (probe families). It ships no
memory at all, and three judges scored the agent row accordingly.

The honest version of memory here is not a scratchpad. It is this: the semantic
gate asks whether an environment has a correct answer, and that question is
settled by the task text. Two environments with identical instructions have the
same answer whatever their verifiers do -- which is exactly the case across the
twelve `toy-triage` fixtures, where one ticket-classification prompt is paired
with twelve different planted defects.

**Evidence.** `results/auditor_memory.json`, `ollama:qwen3:8b`, all 12 fixtures.

| | model calls | wall clock | verdicts |
|---|---|---|---|
| a fresh Auditor per environment | 4 | 31.4s | — |
| one Auditor across the run | **1** | **2.9s** | identical |

`Auditor.shape()` keys on ecosystem plus the sorted instruction set, and
deliberately **not** on the manifest digest: capabilities and version differ
across those twelve, so keying on them would defeat the entire point.

Only 4 of the 12 reach the gate at all. It is consulted only when the battery
flagged something in `verifier_integrity`, so a healthy environment costs
nothing -- which is the right default for a tool that runs before a training
job, not after one.

**Decision.** Kept. A cached conclusion is returned with `carried_from` naming
the environment it was actually reached on, so no card claims a judgement it did
not get.

**What it cost to learn.** This is a cost result and not a capability result,
and it is worth being plain about the difference. Memory here makes the same
answer cheaper. It does not make a better one, and an agent design that reports
a speedup as though it were an improvement in what the tool can find is doing
the thing this repo audits benchmarks for.
