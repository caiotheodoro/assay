# Solution video — script and shot list

Five minutes, hard cap. The brief asks for: the problem and the simple baseline,
one realistic execution start to finish, the final comparison, the changelog,
the change that contributed most, and one experiment that was removed.

Numbers are left as `<>` until the final run freezes them. Nothing is recorded
against numbers that can still move.

---

## 0:00–0:40 — The problem, with receipts

On screen: the table from the top of `README.md`.

> Labs and vendors buy RL environments and eval suites as products. Nobody QAs
> them. When a flagship benchmark turns out to be broken, the fix is a human
> doing it by hand — 93 developers hand-triaged SWE-bench. An ICSE audit found
> 7.8% of its "passing" patches were wrong but passed.
>
> The only automated tooling for this is `gymnasium.utils.env_checker`. Here is
> everything it checks.

Cut to `src/assay/baselines/structural.py` — the whole list fits on one screen.

> Space shapes. That `reset` returns a tuple. That reward is not NaN. It is a
> linter for "will this crash my trainer", never "is this measuring anything".
> It does not even verify that seeding works.

## 0:40–1:15 — The baseline, and the number that makes the case

Terminal: `uv run --extra adapters python scripts/full_run.py`

Let it run. Cut to the table.

> `check_env` scores identically to flagging nothing. Not a weak detector of
> these defects — not a detector of them at all. Expected loss `<X>` against
> Assay's `<Y>`.

## 1:15–2:30 — One realistic execution, end to end

Terminal: `assay audit harbor/self-graded --card card.html`

Talk over it while the probes run:

> Nine probe families. Does gold pass. Does a no-op fail. Does an **inverted**
> spec fail — can this eval fail at all. Does a known-wrong policy fail. Can a
> trivial policy win. Contamination. Shortcut leakage. Determinism.
>
> And the ninth, which is the agentic one: a Challenger that tries to score
> well **without doing the job**.

Show the approval prompt firing before any container starts.

> Nothing executes untrusted environment code without a human. That gate
> defaults to deny.

Open `card.html`. Scroll to **What could not be checked**.

> This section is the point. Four probes could not run and each says why. An
> empty card must never read as a clean bill of health, so the verdict here is
> UNVERIFIED, and it exits nonzero.

## 2:30–3:20 — The two defects in software shipping today

> The corpus so far measures the tool against defects we planted. These two we
> did not.

Terminal: `pytest tests/test_wild_findings.py -q`

> `inspect_evals` — the UK AISI eval suite — scores `paws` with a **substring**
> test against the targets Yes and No. The constant string `"yesno"` contains
> both. It scores 8000 out of 8000. A hundred percent.
>
> And every hedge — "I don't know", "Not sure", "None of the above" — is marked
> correct on all 4464 items whose answer is No.

Terminal: `pytest tests/test_openenv_ground_truth.py -q`

> OpenEnv's `textarena_env` accepts a seed and drops it. Six resets at the same
> seed, six different secret words. That is the Gymnasium bug, in another
> ecosystem, on an environment people train against.

Both verified from the upstream projects' own code, with Assay out of the loop.

## 3:20–4:10 — What contributed most, and what was removed

**Contributed most:** the agentic Challenger.

Show the ablation table.

> Scripted misses. An 8B model misses. Claude finds it — writes a wrong answer
> into both the output and the file the verifier compares against, and is
> scored 1.0 while completing nothing.
>
> And it does not find it every time. `<H>` runs in `<K>`. A probe backed by a
> sampled model is not a deterministic check, so the number reported is a rate,
> not the one run that worked.

**Removed:** the ScienceAgentBench metadata rules.

> Seven of BenchGuard's twelve confirmed defects are instruction defects, and
> the benchmark publishes enough metadata that they look detectable
> deterministically. One rule recovered five of seven.
>
> It also fired on 61 of 102 tasks. That is flag-everything wearing a rule's
> clothing, and Assay's own trivial-floor check is what caught it. Rejected,
> and kept in the repo as a rejected experiment.

## 4:10–4:50 — What does not work

> Two results this project does not get to leave out.
>
> Assay does **not** separate from flag-everything at this corpus size. Loss
> saved `<D>`, confidence interval crossing zero.
>
> And under the production-training cost profile, where a missed defect costs
> 480 times a false alarm, flagging everything **beats** Assay. That is the
> right answer to the question that profile asks.
>
> The GRPO-trained Challenger did not learn either. Two runs on real GPUs.
> 99.7% of rollout groups had zero reward spread, so there was no gradient. We
> measured that before buying the GPU and ran it anyway to find out.

## 4:50–5:00 — Hot take

> The environments people are buying cannot survive a no-op policy, and the one
> tool that checks them scores the same as checking nothing.
>
> Every probe here is a deterministic program. The only model in the system is
> the attacker.

---

## Shot list

| # | Shot | Source |
|---|---|---|
| 1 | README defect table | `README.md` |
| 2 | `check_env`'s entire check list | `src/assay/baselines/structural.py` |
| 3 | `full_run.py` running, then its table | terminal |
| 4 | `assay audit` with the approval gate firing | terminal |
| 5 | Rendered card, scrolled to "What could not be checked" | `card.html` |
| 6 | Both wild-finding test runs | terminal |
| 7 | Ablation + reliability tables | `results/*.json` |
| 8 | Rejected SAB rule output | `scripts/sab_metadata_probe.py` |
| 9 | Intervals table showing the overlap with zero | `results/intervals.json` |

## Recording rules

- Record after the final run freezes. Nothing narrated that can still move.
- Every number on screen comes from a file in `results/`, not from a slide.
- No cuts inside a terminal run. If it takes eleven seconds, it takes eleven.
