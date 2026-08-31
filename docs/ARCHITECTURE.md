# Architecture review

12,253 lines of source across 20 scripts, written in about a day by six workers
and a coordinator who never saw each other's code. This is the first time it has
been read as one thing. Two questions: does the architecture still hold, and can
a stranger find the result.

Everything below was checked against the code, not against the write-ups.
`uv run --extra adapters --extra sweep --extra openenv pytest -q` is green before
and after every change here. At the time of the review that was 493 passed and
18 skipped; the 18 wanted the pinned tau2 snapshots, and with
`scripts/tau2_fetch.py` run first the current suite is **749 passed, 0 skipped,
0 failures, exit 0** in 128 s.

---

## Part 1 — Does the architecture hold?

**Mostly. One abstraction genuinely failed, and it is the one the module
docstring calls load-bearing.**

Four core abstractions have had six adapters and four ecosystems pushed through
them since they were designed. Three held. The fourth — the required/optional
split in the adapter protocol — did not, and two adapters had to express a
structural fact through a runtime exception because of it.

### 1.1 The probes did not leak. The brief's hypothesis is not borne out.

The suggested starting point —

```
grep -rn "_work_host\|_live\|\._" src/assay/probes/
```

— returns exactly one hit, `self._policy` in `determinism.py:62`, which is a
probe calling its own method. Widening to `hasattr` / `getattr` /
`isinstance(..., Adapter)` across the whole probe package returns exactly one
more: `getattr(adapter, "clear_cache", None)` at `determinism.py:64`.

That is the entire leak. Every other off-protocol adapter method that exists —
`OpenEnvAdapter.episode_reward`, `Tau2Adapter.policy_violations`,
`ScienceAgentBenchAdapter.eval_programs_dir` and `.missing_archive_reason`,
`HarborAdapter.clear_cache` — is called only by the adapter itself, that
adapter's own tests, and the one ecosystem-specific script that exists for that
ecosystem (`tau2_recall.py`, `sab_benchguard_recall.py`). None of it reaches the
probe layer.

Six adapters over four ecosystems, and the probes are still ecosystem-blind.
That is the strongest single thing this review found, and it is worth stating as
plainly as the failures: the type boundary in `types.py` — *"adapters translate
their world into these types; probes only ever see these types"* — is real, not
aspirational.

### 1.2 **The failure:** `verify` is required, and two of six adapters refuse it — *now fixed*

`EnvAdapter` splits its surface in two. `manifest / reset / step / verify` are
required — no default, no refusal path. The other eight are optional, and
`BaseAdapter` refuses each by default with a reason. The split is the design's
central bet, stated in the first paragraph of `adapter.py`:

> The load-bearing design decision is that `verify` is separable from `step`.

Two adapters cannot honour it:

| adapter | refuses | why |
|---|---|---|
| `OpenEnvAdapter` | `verify` | reward is computed inside `step()` and returned on the Observation. There is no scorer to call on a recorded transcript and no target to substitute. |
| `ScienceAgentBenchAdapter` | `reset`, `step`, `verify` | SAB is a static task-definition set. Its scoring is a Docker build plus `compute_scores.py`, behind a password-protected archive. |

So the required core is required of four of six. Both adapters handled it
honestly — the `NotSupported` messages are among the best prose in the repo, and
`OpenEnvAdapter` went as far as inventing a *differently named* method,
`episode_reward()`, specifically so it would not have to return a `Score` it
could not justify. But honesty at the call site is not the same as the protocol
being right. Both adapters are expressing a **static** fact about their
ecosystem through a **runtime** exception, and a caller cannot learn it from the
manifest.

The vocabulary to say it declaratively already exists: `Capability` has
`LIVE_STEPPING` and `SEPARABLE_VERIFIER`. The protocol simply does not use them
for this. That is the shape of the failure — not a missing concept, a concept
that was defined and then not wired to the boundary it was defined for.

**Not fixed in the review pass, fixed afterwards — and the prediction in this
paragraph was wrong.** It originally read:

> It touches all six adapters and changes which probes report NOT_APPLICABLE,
> which changes card output, which changes published numbers.

It touched two files of adapters and changed **nothing** a reader sees.
`reset`, `step` and `verify` moved to `BaseAdapter` with refusal defaults;
`LIVE_STEPPING` was wired to the six probes that drive an episode. Then every
one of the 24 corpus environments was audited on both revisions and the cards
compared:

- **22 of 24 cards are byte-identical**, digest and all.
- The 2 that differ are `fixture/flaky` and `openenv/textarena-wordle` — the
  two `NONDETERMINISM` environments, whose digests differ **between two runs on
  the same revision** (checked: three consecutive audits of `fixture/flaky`
  give three digests). Their probe statuses and reasons are identical.
- Every arm's expected loss was unchanged at that revision: assay 240.0,
  flag_everything 290.0, check_env 2816.0, flag_nothing 2832.0, and both trivial
  arms. Those are the 24-environment figures this pass ran against, not current
  ones.

The blast radius was zero because the declarative capability gate was **already
doing the work the required-method contract claimed to do**. OpenEnv withholds
`SEPARABLE_VERIFIER` and ScienceAgentBench declares `frozenset()`, so the probes
that would have called the refused methods were already declining before
`check()` ran. The required-method contract was not protecting anything; it was
describing a world the gate had already made obsolete.

One genuine defect surfaced. `InspectAdapter` implements `reset` and `step` for
real and **never declared `LIVE_STEPPING`** — nothing gated on it, so nothing
noticed. Enforcing the capability made that under-declaration visible in a
single test run. It now declares it, and
`test_no_capability_is_dead_vocabulary` fails if any `Capability` is ever again
declared by adapters and required by no probe.

### 1.3 `LIVE_STEPPING` is declared vocabulary that gates nothing — *now wired*

Five adapters and fixtures declare `Capability.LIVE_STEPPING`. One test asserts
it is present. **No probe requires it.** It is the only member of the enum with
no consumer.

It is also, precisely, the capability that would have let ScienceAgentBench say
"not steppable" in its manifest instead of raising from `reset()`. Dead
vocabulary sitting next to the gap it was designed to fill. Left in place —
removing it would make five adapters' manifests silently narrower, and the right
fix is to *use* it (§1.2), not to delete it.

**Now used.** Six probes require it: all four verifier probes, `separability`,
`trivial_floor`, `seed_determinism` and `challenger` — every probe that calls
`run_policy` or touches `adapter.reset`/`adapter.step`. Two tests keep it that
way: `test_no_capability_is_dead_vocabulary` fails if any `Capability` is
declared by adapters and required by no probe, and
`test_probes_that_drive_an_episode_require_live_stepping` reads each probe's
source and fails if one drives an episode without declaring it.

### 1.4 ~~Probe prerequisites are gated two incompatible ways~~ — **this finding was wrong**

**Retracted.** This section claimed `TrivialFloor` and `Separability` carry
`requires = ()` and gate only through a `NotSupported` escape. They do not, and
did not when it was written:

- `src/assay/probes/policies.py:43` — `TrivialFloor` requires
  `(TRIVIAL_POLICIES, GRADED_POLICIES, SEPARABLE_VERIFIER)`
- `src/assay/probes/policies.py:97` — `Separability` requires
  `(GRADED_POLICIES, SEPARABLE_VERIFIER)`

`git log -L` puts the last change to that file well before this review, so the
table was wrong on the day it was written rather than going stale afterwards.
The claim that "`TRIVIAL_POLICIES` and `GRADED_POLICIES` are declared by
adapters and consumed by nobody's `requires`" is false for the same reason.

What survives is the narrow, correct version: **two** probes gate only through
the runtime escape, `DifficultyBand` and `SpecVerifierMatch`, and the section
already conceded that neither has a capability to name — `DifficultyBand` needs
a solve-rate estimate from `ctx`, and `SpecVerifierMatch` needs
`verifier_asserts`, which has no `Capability`. So the inconsistency is real, has
two cases rather than four, and is not fixable by naming a capability that does
not exist.

Left as a retraction rather than a rewrite. A review that quietly edits its own
wrong table is worth less than one that says which of its findings did not hold
— and this document exists to be checked, not to be right.

### 1.5 "Unknown task id" raises five different exception types

The protocol never says what an unknown `task_id` should do. Six adapters
answered independently:

| adapter | raises |
|---|---|
| `harbor`, `inspect_ai`, `openenv`, `tau2` | `KeyError` |
| `spec` | `SpecError` (a `ValueError`) |
| `scienceagentbench` | `NotSupported` |

`Probe.run` maps `NotSupported` → NOT_APPLICABLE and everything else → ERROR.
So the *same caller mistake* reads as "this environment is less auditable" on
SAB and "the probe crashed" on the other five. Nothing currently hits this — the
probes iterate `manifest().tasks`, so the ids are always real — which is why it
has survived. Left alone: unifying it would change probe statuses, and probe
statuses are what the cards report.

### 1.6 `close()` and `clear_cache()` are load-bearing and off-protocol — *partly fixed*

Neither is on `EnvAdapter`. Both are used anyway.

`close()` was duck-typed at four sites in three spellings — `if close:` in
`cli.py` and `publish.py`, `if callable(closer):` twice in `train/reward.py`.
**Consolidated** behind `adapter.close_adapter()`, and both methods are now
documented in `adapter.py`'s module docstring.

`clear_cache()` is the sharper one, and stays a seam. `probes/determinism.py`
calls it when present, because a memoised `verify` would answer the determinism
probe with a memory instead of a run — a vacuous check, of exactly the shape
this tool exists to flag in environments. Harbor is the only adapter that caches
and the only one that defines it. **An adapter that starts memoising `verify`
and forgets `clear_cache` silently disarms the determinism probe, and nothing in
the type system or the test suite would say so.** That is now written down at
the top of `adapter.py` rather than living only in one probe's `getattr`.

Not promoted to the protocol: making them required would put a no-op `close()`
on every pure-data adapter to satisfy a type checker, and `clear_cache` really
is a property of one adapter's implementation strategy rather than of an
ecosystem.

### 1.7 The corpus registry covers six of seven adapters

`corpus.py` is explicit about its purpose:

> adding an ecosystem means adding a file — never editing this one. That matters
> when several people are adding ecosystems at once.

Six `_*_corpus.py` modules exist: `_fixture_`, `_harbor_`, `_inspect_`,
`_inspect_evals_`, `_openenv_`, `_tau2_`. **Two adapters still register
nothing** — ScienceAgentBench and the submitted-spec adapter.

Consequence: everything routed through `corpus.entries()` — `assay list`,
`assay audit <env>`, `publish.py` — cannot see them. They are reachable only
through bespoke scripts.

Each remaining case is individually defensible. SAB is scored against *other
people's* confirmed defect lists, so it has no planted `frozenset[DefectClass]`
to register; the spec adapter is built at runtime from a stranger's submission to
a Space, so there is nothing to enumerate at import time. But the brief asked for
this to be said plainly, so: **a registry whose stated purpose was to have no
special cases has two, and they are among the most recent ecosystems.** The
registry held for the ecosystems it was designed against and stopped being the
front door the moment the corpus stopped being planted defects.

**What changed for tau2, and what the objection above was actually about.** This
section previously listed tau2 alongside SAB, on the grounds that an environment
scored against somebody else's confirmed defect list "has no planted
`frozenset[DefectClass]` to register". That was true and it was also the wrong
conclusion: the missing thing was not a *planted* set, it was a *mapping* from
task-level "this record differs between two pinned revisions" onto the sixteen
classes. Deriving that mapping is the whole of
[`docs/PRE-REGISTRATION-TAU2.md`](PRE-REGISTRATION-TAU2.md) — two rules over the
changed field paths, fourteen classes excluded with a written reason each, and
`tests/test_tau2_corpus_ground_truth.py` checking every rule against the two
snapshots with Assay out of the loop. The registry did not need a special case;
it needed somebody to do the mapping and argue it in public. SAB still needs the
same work done for its own ground truth and has not had it.

### 1.8 Duplication — less than expected, and one helper nobody used

The thing that looked most likely to be duplicated is not.
`trivial_policies` / `graded_policies` are genuinely per-ecosystem: "delete the
tests" for Harbor, majority-class for inspect_ai, and tau2 *refusing* to invent
graded policies on the grounds that constructing them would mean inventing the
grades the probe is supposed to check. No shared implementation is hiding in
there.

What is real:

- **`rewards_by_group()` in `train/reward.py` was dead while its body was
  inlined twice elsewhere** — verbatim at `train/run.py:212`, in a third variant
  in `scripts/env_health_report.py`. The shared helper existed, was correct, and
  nobody used it. Removed rather than wired in: the two live callers need
  different shapes, and `run.py` chunks completions alongside rewards in the same
  pass.
- **Majority-class computed two ways**: `Counter(...).most_common(1)[0][0]`
  (inspect_ai) vs `max(set(targets), key=targets.count)` (spec). Same intent,
  different tie-breaking on a tie. Two lines each; not worth a shared helper and
  not worth the churn.

### 1.9 Dead code — five definitions removed

| removed | file | why it was dead |
|---|---|---|
| `PromptApprover` | `sandbox.py` | a third `Approver` alongside `DenyAll` and `AutoApprove`, never constructed, never wired to a CLI flag, never mentioned in any doc. An interactive-approval approach that was abandoned. **Since restored, and the deletion is the more interesting half of the story — see `docs/changelog/98-approval-gate.md`.** It really was dead, so removing it was right on the evidence available. What the sweep could not see is that it was dead *because* `_harbor_corpus.py` had quietly hard-coded `AutoApprove("assay corpus run")`, so the shipped audit path never needed to ask anyone. Deleting the unused approver tidied away the only visible sign that the gate had been bypassed. A dead-code sweep answers "is anything calling this"; it cannot answer "should something have been". |
| `reap_sessions()` | `sandbox.py` | a second implementation of what `cli._reap` does inline. `cli._reap` is the one that ships, is tested, and supports `--all`. |
| `Timeout` | `sweep.py` | an exception class never raised and never caught. Left over from the `signal.alarm` approach the module docstring records as replaced. |
| `rewards_by_group()` | `train/reward.py` | §1.8. |
| `rule_names()` | `adapters/tau2_policy.py` | introspection helper over `RULES`, never called. |

**Deliberately kept:** `grpo_loss()` and `ratio_bounds()` in `train/grpo_math.py`
are also unreferenced, but `docs/LINEAGE.md` names them specifically as a
verbatim port from a sibling project, "kept as they were". Deleting them would
make the lineage record wrong about what was vendored, which is a worse defect
than an unused function.

---

## Part 2 — Can a judge find anything?

Read cold, README top to bottom, then the first link that looked important.

### What was already right

**The headline is above the fold.** *"Two real defects, in software shipping
today"* is the third section, ~10% in, after a problem statement that earns it
with a table of five benchmarks that shipped broken. Both defects are stated
with the mechanism, a reproduction, and — unusually — the split between what the
tool found and what a human found. **I did not move it.** A reviewer's instinct
to reorder should stop when the ordering is already correct, and this one is.

**The write-up is honest in a way that is legible fast.** Sections named "The
profiles where Assay loses" and "What holds, and what does not", corrections
kept in the record rather than deleted, a trained Challenger listed "as an
attempt, not a contribution". That reads as something a person signed.

### What was buried, and what I changed

| problem | fix |
|---|---|
| The first question a stranger has — *how do I run this* — was answered at **line 497 of 516**. | A two-line quickstart directly under the status blockquote. |
| The status blockquote named **two adapters when six exist**, and read as three build-log entries appended over time. It is the first paragraph a judge reads and it described a repo that no longer existed. | Rewritten to the current six adapters. Every published number (four ecosystems, 246 tasks) kept verbatim. |
| **20 scripts, flat, no index.** No way to tell `full_run.py` from `sab_metadata_probe.py` without opening both. | New `scripts/README.md`: five entry points with run order and what each writes, then the other fifteen grouped by the README section each supports. |
| **The ScienceAgentBench result was told twice** — ~25 lines restating 0/12, the twelve NOT_APPLICABLEs, "nine of the twelve are already fixed", and the 61-of-102 precision-denominator argument, once at §*Where Assay sits in the field* and again 60 lines later at §*Prior art*. Two statements of the same finding read as padding. | Collapsed the second into a pointer, keeping the one thing Prior art actually added: **ABA scores 10/12 on that same gold with that same scorer.** |
| **`docs/review/spec-adapter-redos.md` was reachable from nothing.** A 102-line security review of the submitted-spec adapter — a real ReDoS, `(a+)+$` against 31 characters taking 100.7 seconds, found by reading and fixed before merge. A judge following links would never have seen it. | Named from the changelog row that records the fix, and linked here: [`review/spec-adapter-redos.md`](review/spec-adapter-redos.md). |

### What I left alone, and why

- **`docs/CHANGELOG.md` — 119 KB of generated output committed beside the 21
  fragments it is generated from.** Every row exists twice in the repo. It stays:
  it is the file README and REPRODUCTION link to, `merge_changelog.py --check`
  keeps it from drifting, and the fragment split is load-bearing for exactly the
  reason `docs/changelog/README.md` gives — it is the file every workstream wants
  to append to.
- **The documents in `docs/`.** They looked like consolidation candidates and
  are not. LINEAGE (what predates the repo), REPRODUCTION (how to rerun),
  SCIENCEAGENTBENCH (one measurement in depth), VIDEO (a shot list), RUBRIC (a
  self-score), CHANGELOG (the record). The only real overlap was
  README↔SCIENCEAGENTBENCH, and the duplication was inside the README, not
  between the two files.
- **`docs/RUBRIC.md`.** It landed in the working tree while this review was
  running, so it is someone else's in-flight work and not mine to move. Worth
  saying anyway, because it reached the same conclusion from a separate context:
  *"most of the loss is work that exists and cannot be found"*, and its top fix
  is a links table. It is itself linked only from the CHANGELOG — the same
  orphan pattern as §2's `docs/review/`. Whoever finishes it should link it from
  the README.
- **The README's length.** 516 lines is long, but nearly every paragraph carries
  a number or a correction. Cutting it would mean cutting evidence.
- **The source tree, module names, and every published number.** Per the brief.
- **The six architectural findings in §1.2–§1.7.** Each is a protocol or registry
  change that would alter what probes report, and probe reports are the product.
  They are written down here so the next person changing the protocol starts from
  the list rather than rediscovering it.

---

## Summary

The abstraction that held: **probes never learned what ecosystem they were
looking at.** Four ecosystems and six adapters later, the probe package touches
exactly one thing outside the protocol.

The abstraction that failed: **the required/optional split in `EnvAdapter`.**
`verify` is required and two of six adapters refuse it; `reset` and `step` are
required and one refuses both. The `Capability` enum can already express this and
is not wired to. `LIVE_STEPPING` — the capability that would have solved it — is
declared by five adapters and required by no probe.

Changed here: five dead definitions removed, four duck-typed `close()` calls
consolidated, two off-protocol methods documented at the boundary they cross, a
`scripts/README.md`, a README quickstart, a corrected status paragraph, one
duplicated section collapsed, one orphaned security review linked.

Not changed: the protocol, the source tree, any published number.
