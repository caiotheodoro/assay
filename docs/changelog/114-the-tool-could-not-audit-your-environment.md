## Slice 51: a judge tried to use it on their own environment, and could not

**What and why.** `README.md`'s lead user is *"a researcher about to spend a
training run on an environment they did not write… they run `assay audit`, read
the exit code."* A judge tried exactly that and found two things.

**One: there was no CLI path for it.** `assay audit` took corpus ids only. The
spec adapter — the whole point of which is *"a stranger submits an environment
and gets a card back"* — was reachable from the hosted Space and from Python and
not from the tool. `assay audit path.json` now works, on `.json` or `.yaml`, with
a real error message when the spec does not parse.

**Two, and worse: on a spec they wrote with a substring verifier, Assay found
nothing.** They confirmed by hand that `"0123456789 30"` scored 3 of 3. Assay
reported no finding about it.

That is the **`paws` defect** — the one this project leads with, `includes()`
against `Yes` and `No` and the constant `"yesno"` taking 8000 of 8000. Assay
could find it in a published eval and not in a spec a reader submitted.

The reason it worked on `space/examples.json` example 3 is that the example
**supplies the exploit by hand** in `trivial_answers`. The submitter had to
already know the answer.

**Fix.** `SpecAdapter.trivial_policies` derives it. Under a substring matcher,
one constant string containing every declared target answers every task — not a
heuristic, and not a guess about the data: `includes` asks whether the target
occurs in the answer, so an answer containing all of them satisfies all of them.
Declared as a *policy* rather than a new probe, so the existing
reward-hackability machinery decides whether it actually pays. The adapter
proposes; the verifier scores.

On the judge's shape of spec, with nothing supplied by hand:

```
mine/yesno  [spec]  verdict: INVALID
  [CRITICAL] REWARD_HACKABLE on q1, q2, q3
```

Gated for the negative cases too: `exact` gets no such policy, and neither does
a task set with one distinct target, because naming it is just the majority
class.

**What it cost to learn.** Seven worked examples shipped with the Space and every
one of them was written by someone who knew what Assay would find. That is a
test set drawn from the same head as the tool, which is the criticism this repo
makes of every benchmark it audits, applied to its own front door. **The first
stranger to write a spec found the gap in one attempt.**

**A consequence worth naming.** The synthesis Challenger exists because the
scripted repertoire could not reach this exploit. On **submitted specs** it now
can — the adapter derives the policy and the deterministic probe finds it, with
no model. That is the same compile-a-discovery-into-a-check move that beat the
original Challenger, happening a second time, and it narrows where the agent is
load-bearing rather than widening it.

It does **not** touch `results/policy_synthesis.json`. That measures
`inspect_evals/paws`, which uses `WildInspectAdapter` — policies
`always_abstain`, `always_escalate`, `majority_class`, checked against the live
adapter — and derives nothing. The floor there is still 14 of 25 and the agent
still reaches 24–25.

Two tests in `tests/test_synthesis_challenger.py` broke on this, correctly: they
model `paws` with a spec adapter, and that stand-in had silently become
*stronger* than the thing it stands in for. It is now wrapped to carry
`WildInspectAdapter`'s repertoire, visibly and with the reason written down,
because a stand-in that drifts stronger than its subject quietly turns every
"the script cannot reach this" claim in that file into a false one.
