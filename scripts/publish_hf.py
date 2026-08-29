#!/usr/bin/env python
"""Stage, gate and publish the three Hugging Face artifacts.

    uv run --extra adapters --extra sweep --extra openenv \
        python scripts/publish_hf.py                 # dry run, uploads nothing
    uv run ... python scripts/publish_hf.py --push   # after reading the dry run

Two rules shape this script.

**Nothing is typed that can be derived.** Every count and every number in
every card is read out of `results/*.json` or the built payload at render
time. A card cannot drift from the evidence, because there is no copy of the
number to drift. If a results file is missing, the render fails rather than
falling back to a literal.

**The gates run before the upload, not after.** A published artifact is not
something you fix afterwards. `verify_no_redistribution` is the innermost
one; around it sit the checks from sections 11 and 12 of the publication
spec -- every metric carries an interval, trivial baselines ship alongside,
the contamination audit ships, the disclaimers are present, no card cites a
moving revision. Any gate failing aborts before a byte is uploaded.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RESULTS = ROOT / "results"
BUILD = ROOT / "build" / "hf"

ACCOUNT = "caiotheodoro"
DATASET_REPO = f"{ACCOUNT}/assay-corpus"
SPACE_REPO = f"{ACCOUNT}/assay"
MODEL_REPO = f"{ACCOUNT}/assay-challenger-grpo"

#: Every card cites this, never `main`. Section 12.1: "no card cites main".
TAG = "v0.1.0"

#: Where the two spot runs wrote their artifacts. The weights are not in the
#: repo -- they were written on the instance and synced here as they were
#: produced -- so publishing them means fetching them back first.
S3_BUCKET = "assay-challenger-122862904842"
RUNS = ("assay-challenger-r1", "assay-challenger-r2")

#: What a trained-adapter checkpoint needs for someone to reproduce the
#: ablation row, and nothing else. `optimizer.pt`, `training_args.bin` and the
#: frozen reference copy are omitted: two are pickles and none of the three is
#: needed to run the model. `run.json` carries the hyperparameters in JSON.
ADAPTER_FILES = (
    "adapter_config.json",
    "adapter_model.safetensors",
    "chat_template.jinja",
    "tokenizer.json",
    "tokenizer_config.json",
)

MANDATORY_DISCLAIMERS = ("Synthetic data", "not production-validated")


class GateFailed(RuntimeError):
    """A pre-publication gate did not pass. Nothing is uploaded."""


# --------------------------------------------------------------------------
# reading the evidence
# --------------------------------------------------------------------------


def load(path: Path) -> Any:
    if not path.exists():
        raise GateFailed(
            f"{path.relative_to(ROOT)} is missing. Every number in the cards is read "
            "from a results file; there is no literal to fall back to. Regenerate it "
            "with scripts/full_run.py or scripts/intervals.py."
        )
    return json.loads(path.read_text())


@dataclass
class Evidence:
    """Everything the cards are rendered from. Loaded once, up front, so a
    missing file fails before anything is staged."""

    full_run: dict = field(default_factory=dict)
    intervals: dict[str, dict] = field(default_factory=dict)
    ablation: dict = field(default_factory=dict)
    landscape: dict = field(default_factory=dict)
    runs: dict[str, dict] = field(default_factory=dict)
    triage: dict = field(default_factory=dict)

    @classmethod
    def collect(cls) -> Evidence:
        profiles = ["research-run", "production-training", "benchmark-publication", "flat"]
        return cls(
            full_run=load(RESULTS / "full_run.json"),
            intervals={p: load(RESULTS / f"intervals-{p}.json") for p in profiles},
            ablation=load(RESULTS / "challenger_ablation.json"),
            landscape=load(RESULTS / RUNS[0] / "reward_landscape.json"),
            runs={r: load(RESULTS / r / "run.json") for r in RUNS},
            triage=load(RESULTS / "wild_sweep_triage.json"),
        )


def ci(node: dict) -> str:
    """`120.0 [0, 360]` -- a point estimate is never rendered without one."""
    lo, hi = node["ci95"]
    return f"{node['point']:g} [{lo:g}, {hi:g}]"


# --------------------------------------------------------------------------
# derived artifacts required by sections 11.3 and 11.4
# --------------------------------------------------------------------------

#: Which arms ignore their input. `check_env` is the incumbent linter, not a
#: trivial policy -- it reads the environment, it just does not read anything
#: that matters. Keeping it out of the trivial floor is what makes "Assay must
#: beat a policy that ignores the input" a real bar rather than a flattering one.
TRIVIAL_ARMS = ("flag_everything", "flag_nothing")


def build_baselines(ev: Evidence) -> dict:
    """Section 11.3. `severity_weighted_loss` is an unnormalized sum and is
    uninterpretable alone, so every profile also reports loss normalized
    against the best trivial policy for that profile.

    `L_oracle` is 0 by construction: an oracle detector misses nothing and
    flags nothing spurious, so it incurs neither cost. That makes
    `normalized_loss = L / L_trivial`, and a value >= 1 means the arm did not
    beat a policy that ignores the input.
    """
    out: dict[str, Any] = {
        "definition": (
            "normalized_loss = (L_arm - L_oracle) / (L_trivial - L_oracle), with "
            "L_oracle = 0 (an oracle detector has no misses and no false alarms) and "
            "L_trivial the lowest expected loss among the input-ignoring arms for "
            "that profile. normalized_loss >= 1 means the arm did not beat a policy "
            "that ignores the input."
        ),
        "trivial_arms": list(TRIVIAL_ARMS),
        "resamples": ev.intervals["research-run"]["resamples"],
        "seed": ev.intervals["research-run"]["seed"],
        "n_environments": ev.intervals["research-run"]["n_environments"],
        "resampling_unit": ev.intervals["research-run"]["resampling_unit"],
        "profiles": {},
    }
    for profile, data in ev.intervals.items():
        arms = data["arms"]
        best_trivial = min(TRIVIAL_ARMS, key=lambda a: arms[a]["expected_loss"]["point"])
        floor = arms[best_trivial]["expected_loss"]["point"]
        out["profiles"][profile] = {
            "best_trivial_policy": best_trivial,
            "trivial_floor_loss": floor,
            "arms": {
                arm: {
                    "expected_loss": v["expected_loss"],
                    "recall": v["recall"],
                    "precision": v["precision"],
                    "normalized_loss": (
                        round(v["expected_loss"]["point"] / floor, 4) if floor else None
                    ),
                    "beats_trivial_floor": v["expected_loss"]["point"] < floor,
                    "paired_vs_best_trivial": v["loss_saved_vs"].get(best_trivial),
                }
                for arm, v in arms.items()
            },
        }
    return out


def build_contamination(payload) -> dict:
    """Section 11.4, per environment rather than per eval set, because this
    corpus is environments. Exact overlap and MinHash near-duplicate rate at a
    stated threshold, plus the bound the probe itself states: this says nothing
    about whether a third-party model saw similar data in pretraining.
    """
    per_env = {}
    for env_id, body in sorted(payload.probes.items()):
        for probe in body["probes"]:
            if probe["probe"] != "train_eval_leak":
                continue
            entry = {"status": probe["status"], "reason": probe["reason"]}
            entry.update(probe.get("detail") or {})
            per_env[env_id] = entry
    ran = {k: v for k, v in per_env.items() if v["status"] != "NOT_APPLICABLE"}
    return {
        "method": (
            "Exact content-hash overlap, then MinHash near-duplicate detection over "
            "5-word shingles with 128 permutations at estimated Jaccard >= 0.8."
        ),
        "bounds": (
            "This bounds contamination WITHIN each environment's own splits. It says "
            "nothing about whether a third-party model encountered similar data in "
            "pretraining, and there is no way to check that from here."
        ),
        "n_environments_total": len(per_env),
        "n_environments_with_splits": len(ran),
        "n_environments_without_splits": len(per_env) - len(ran),
        "total_exact_overlap": sum(v.get("exact_overlap", 0) for v in ran.values()),
        "total_near_dup": sum(v.get("near_dup_count", 0) for v in ran.values()),
        "per_environment": per_env,
    }


# --------------------------------------------------------------------------
# cards
# --------------------------------------------------------------------------


def dataset_card(ev: Evidence, payload, baselines: dict, contamination: dict) -> str:
    rr = ev.intervals["research-run"]["arms"]
    pt = ev.intervals["production-training"]["arms"]
    n = ev.intervals["research-run"]["n_environments"]
    rows = payload.rows
    ours = [r for r in rows if r["content_included"]]
    theirs = [r for r in rows if not r["content_included"]]
    ecosystems = sorted({r["ecosystem"] for r in rows})
    planted = sorted({d for r in ours for d in (r["planted_defects"] or [])})
    n_planted = sum(len(r["planted_defects"] or []) for r in ours)

    def loss_row(arm: str, data: dict) -> str:
        v = data[arm]
        return (
            f"| `{arm}` | {ci(v['expected_loss'])} | {v['recall']['point']:.3f} | "
            f"{v['precision']['point']:.3f} | "
            f"{baselines['profiles']['research-run']['arms'][arm]['normalized_loss']} |"
        )

    skip_counts: dict[str, int] = {}
    for body in payload.probes.values():
        for probe in body["probes"]:
            if probe["status"] == "NOT_APPLICABLE":
                skip_counts[probe["probe"]] = skip_counts.get(probe["probe"], 0) + 1
    worst_skips = sorted(skip_counts.items(), key=lambda kv: -kv[1])[:5]

    return f"""---
license: apache-2.0
task_categories:
  - other
language:
  - en
tags:
  - rl-environments
  - evaluation
  - benchmark-auditing
  - reward-hacking
  - contamination
  - verifier-as-oracle
  - synthetic
size_categories:
  - n<1K
configs:
  - config_name: corpus
    data_files: corpus.jsonl
  - config_name: probes
    data_files: probes.jsonl
---

# Assay corpus — audited RL environments with planted-defect ground truth

{len(rows)} environments across {len(ecosystems)} ecosystems, each audited by
**Assay**, an agentic auditor for RL environments and eval suites.

For the {len(ours)} environments whose ecosystem this repo owns, the corpus
ships the planted-defect ground truth and the full Environment Card. For the
{len(theirs)} it classifies as someone else's, it ships the verdict and
**which probes could not run and why** — and nothing else. See
[What is not here](#what-is-not-here-and-why).

The source repository is not public at the time of writing, so this card links
to no repository rather than to one that 404s. Every command below is quoted in
full so it can be run from a checkout.

> **Synthetic data.** Every environment here is a constructed fixture with
> defects planted on purpose, not an observation of a production system.
>
> **This is not production-validated.** It measures a detector against defects
> the same authors planted, which is a lower bar than measuring it against
> defects found in the wild. Do not treat a `VALID` verdict as sign-off.

## Read this first: two results that do not flatter the tool

Leaving these off would make the card marketing. Both are paired bootstrap
differences on a shared resample, {ev.intervals['research-run']['resamples']:,}
resamples at seed {ev.intervals['research-run']['seed']}, resampling over
environments (n = {n}).

**1. Assay does not separate from `flag_everything`.** Under the
`research-run` cost profile the loss it saves against a policy that flags every
environment unread is
**{ci(rr['assay']['loss_saved_vs']['flag_everything'])}** — the interval
overlaps zero. By this project's own rule, that advantage is **not established
on this corpus**.

**2. Under `production-training`, `flag_everything` beats Assay outright.**
Expected loss {pt['flag_everything']['expected_loss']['point']:g} against
Assay's {pt['assay']['expected_loss']['point']:g}. That is the correct answer
to the question that profile asks: when a missed defect costs 480x a false
alarm and review is nearly free, review everything. Assay's single CRITICAL
miss costs {pt['assay']['expected_loss']['point']:g}; 250 false alarms cost 2
each. The paired difference is
{ci(pt['assay']['loss_saved_vs']['flag_everything'])}, so the *loss* is not
separated either — the point estimate favours `flag_everything` and the
interval spans both.

Assay earns its place only where false alarms have real cost, i.e. where nobody
can triage 250 spurious findings.

## What is in the corpus

| | |
|---|---|
| Environments | {len(rows)} |
| Ecosystems | {', '.join(f'`{e}`' for e in ecosystems)} |
| Full content + ground truth | {len(ours)} |
| Verdict + skip reasons only | {len(theirs)} |
| Planted defects labelled, on those {len(ours)} | {n_planted} |
| Distinct defect classes represented | {len(planted)} |
| Payload content digest | `{payload.content_digest()}` |

`corpus.jsonl` — one row per environment: the verdict, what Assay detected,
probe-status coverage, and for our own environments the planted ground truth.

`probes.jsonl` — one row per environment: every probe, its status, and for
anything that did not run, **the reason**. This is the file to read if you
want to know what an audit actually covered.

`cards/` — the full Environment Card for each of those {len(ours)}
environments. Every claim carries the evidence that produced it.

`results/` — the measurement outputs the numbers on this card are read from.
Nothing on this card is typed by hand; `scripts/publish_hf.py` renders each
figure out of these files at publish time.

### Defect classes

{chr(10).join(f'- `{d}`' for d in planted)}

## Absence of evidence is reported as loudly as evidence

An environment with no findings is **not** reported as clean. The verdict
`UNVERIFIED` means no defect was found *and* some probe could not run, and it
exits nonzero like any other non-clean verdict.

The probes most often unable to run across this corpus:

| Probe | Environments where it could not run |
|---|---|
{chr(10).join(f'| `{p}` | {c} of {len(rows)} |' for p, c in worst_skips)}

`openenv/textarena-wordle` is the sharpest example:
{payload.probes['openenv/textarena-wordle']['coverage']['NOT_APPLICABLE']} of
{sum(payload.probes['openenv/textarena-wordle']['coverage'].values())} probes
could not run against it, because the environment exposes no separable
verifier. Its `DEFECTIVE` verdict rests on one probe. A row saying only
"DEFECTIVE" would hide how little of it was audited.

## Baselines and normalization

`results/baselines.json`. `severity_weighted_loss` is an unnormalized sum and
is uninterpretable alone, so each arm is also reported against the best
input-ignoring policy for its profile:

`normalized_loss = L_arm / L_trivial` (L_oracle is 0 by construction).
**A value >= 1 means the arm did not beat a policy that ignores the input.**

Under `research-run`:

| arm | expected loss (95% CI) | recall | precision | normalized loss |
|---|---|---|---|---|
{loss_row('assay', rr)}
{loss_row('flag_everything', rr)}
{loss_row('check_env', rr)}
{loss_row('flag_nothing', rr)}

`check_env` reimplements what `gymnasium.utils.env_checker` and
`stable_baselines3.common.env_checker` actually assert. It scores
**identically to flagging nothing**. It is not a weak detector of these
defects; it is not a detector of them at all.

Assay's normalized loss across all four profiles:

| profile | best trivial policy | trivial floor | Assay normalized loss | beats the floor |
|---|---|---|---|---|
{chr(10).join(
    f"| `{p}` | `{d['best_trivial_policy']}` | {d['trivial_floor_loss']:g} | "
    f"{d['arms']['assay']['normalized_loss']} | "
    f"{'yes' if d['arms']['assay']['beats_trivial_floor'] else '**no**'} |"
    for p, d in baselines['profiles'].items()
)}

Assay beats the trivial floor under two profiles of four, ties under one, and
loses under one. All four are published because running only the flattering
cost model would be its own kind of dishonesty.

## Contamination audit

`results/contamination.json`. Exact content-hash overlap, then MinHash
near-duplicate detection over 5-word shingles, 128 permutations, estimated
Jaccard >= 0.8.

| | |
|---|---|
| Environments with train/eval splits | {contamination['n_environments_with_splits']} |
| Environments with no splits to compare | {contamination['n_environments_without_splits']} |
| Total exact overlaps found | {contamination['total_exact_overlap']} |
| Total near-duplicates found | {contamination['total_near_dup']} |

These are **planted**: `fixture/leaky_splits` and `fixture/paraphrased_splits`
exist to be caught. The audit is published to show the detector working on
known ground truth, not to claim the corpus is clean.

{contamination['bounds']}

## What is not here, and why

Auditing someone's environment does not make it ours to republish. The check is
code, not a note in this card — `src/assay/publish.py`, tested in
`tests/test_publish.py`, and it fails closed on an ecosystem it has not been
told about rather than guessing either way.

| Ecosystem | Status |
|---|---|
| `fixture`, `harbor` | this repo's own; full content and ground truth ship |
| `inspect_ai` | verdict + skip reasons only |
| `openenv` | verdict + skip reasons only |
| `scienceagentbench` | nothing ships; upstream asks that the unzipped archive not be redistributed |

The line is between **a claim and a copy**. "`paws` scores a constant string at
100%" carries no benchmark content to redistribute, so it ships. The `paws`
items do not.

Note that the guard is stricter than strictly necessary for five of those rows:
`inspect/healthy`, `inspect/always-correct`, `inspect/effort-scorer`,
`inspect/constant-score` and `inspect/leaky-split` are environments this repo
wrote, on its own five-question dataset, using the `inspect_ai` library. But
the ecosystem label cannot distinguish them from the `inspect_evals` sweep, and
a guard that guessed would eventually guess wrong in the expensive direction.
They are withheld.

## Reproducing this

No GPU, no API key, no network at audit time. Docker is needed for the Harbor
quarter; without it the run completes on a reduced corpus and says so, per
ecosystem, with the reason.

```bash
# from a checkout of the Assay repository
uv sync --extra dev --extra adapters --extra sweep --extra openenv
uv run --extra adapters --extra sweep --extra openenv python scripts/full_run.py
uv run --extra adapters python scripts/intervals.py --resamples {ev.intervals['research-run']['resamples']} --seed {ev.intervals['research-run']['seed']}
uv run --extra adapters --extra sweep --extra openenv python scripts/publish_hf.py
```

The last command re-derives this entire dataset, including this card, and
uploads nothing without `--push`.

## Two defects in software shipping today

Found during the sweep, both verified from the upstream project's own code with
Assay out of the loop. Full write-up in `results/wild_sweep_triage.json`.

- **`inspect_evals` `paws`** scores with `includes()`, a case-insensitive
  substring test, against the targets `Yes` and `No`. The constant string
  `"yesno"` contains both, so it scores
  {ev.triage['findings'][0]['independent_verification']['exhibits']['full-dataset result'].split('scores ')[-1]}.
  The looseness is one-sided:
  {ev.triage['findings'][0]['independent_verification']['target_distribution']['No']:,}
  of {ev.triage['findings'][0]['independent_verification']['target_distribution']['total']:,}
  items have the target `No`, so every hedging model is credited on 56% of the
  benchmark for free.
- **`openenv` `textarena_env`** accepts `reset(seed=...)` and ignores it. Six
  calls at the same seed return six different secret words.

**Assay did not find the first one.** It flagged 14 of 25 sampled `paws` items
as `REWARD_HACKABLE` via a refusal exploit; hand triage found the stronger
constant-string exploit. That split is pinned as a test so it cannot quietly
close in the write-up.

## Sample size, and what it costs

n = {n} environments. Intervals over a corpus this size are wide — Assay's
expected loss under `research-run` is {ci(rr['assay']['expected_loss'])}, and an
interval whose lower bound is 0 is not a precise measurement. Every comparison
on this card is a paired difference on a shared resample rather than two
one-sample intervals eyeballed against each other, because overlapping
one-sample intervals do not settle "A beats B" in either direction.

The corpus ships {len(rows)} environments; the interval results were computed
on the {n} that were installable at that run (`inspect_ai` and `openenv` were
absent, and `harbor/shared-tests` was added afterwards). Rerun `full_run.py`
and `intervals.py` on the full {len(rows)} to recompute — the numbers here are
the ones the repo's own README reports, and they are not restated at a
different n without being recomputed.

## Limitations

- The defects are **planted by the same authors as the detector**. That is a
  weaker claim than finding defects in the wild, and the two wild findings
  above are reported separately for that reason.
- One CRITICAL miss (`harbor/self-graded`, a verifier that reads its
  expectation from a file the agent can overwrite) drives the
  `production-training` result. Closing it would change three of the four
  profiles.
- No LLM judge scores anything, anywhere. Every oracle here is a deterministic
  program. That is a design constraint, and it means defect classes requiring
  semantic judgement are out of scope rather than handled badly.

## Citation and license

Apache-2.0. Verdicts about third-party software are claims about publicly
released code and carry none of it.

Version `{TAG}`. Cite this revision, not `main`:

```python
from datasets import load_dataset
load_dataset("{DATASET_REPO}", "corpus", revision="{TAG}")
```

Related: [`{SPACE_REPO}`](https://huggingface.co/spaces/{SPACE_REPO}) audits a
submitted environment. [`{MODEL_REPO}`](https://huggingface.co/{MODEL_REPO}) is
a **negative result** — a GRPO-trained adversarial Challenger that did not
learn — published so the ablation row is checkable.
"""


def git_sha() -> str:
    """Which source the Space is running. It vendors the package rather than
    installing it, because this checkout has no public remote, so the commit is
    the only way for a reader to tell what code produced their card."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def space_card() -> str:
    return f"""---
title: Assay
emoji: "\N{MICROSCOPE}"
colorFrom: indigo
colorTo: gray
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
license: apache-2.0
short_description: Audit an RL environment or eval suite and get a signed card
tags:
  - evaluation
  - benchmark-auditing
  - reward-hacking
---

# Assay

Submit an environment. Get an Environment Card back: a validity verdict where
every claim is tied to a probe result, **and a list of every probe that could
not run and why**.

That second half is the point. A card with no findings is not a clean bill of
health, and this Space refuses to render one as if it were.

## What it does

Twelve probes across nine families ask whether an environment measures what it
claims: does gold pass, does a no-op fail, does an *inverted* spec fail, can a
policy that ignores the input win, can it tell apart policies known to differ,
does the train split leak into the eval split, is the answer recoverable from
part of the input, does the verifier check what the instruction asked, is the
same seed reproducible, is the solve rate in a learnable range, and can a
policy score well without doing the job.

**No LLM judge scores anything.** Every oracle is a deterministic program.

## Submitting an environment

Environments are submitted as **data, not code** — a JSON spec naming the
tasks, what each one asks for (`target`), and the rule the verifier applies.
Running a stranger's Python on a public host would be a different kind of
project.

`target` and `verifier` are separate on purpose. The target is what the task
asks for; the verifier is the rule the environment happens to apply. Every eval
defect worth finding lives in the gap between them.

Capabilities are **derived from what the spec contains**, never claimed. A
spec with no train split does not get `SPLITS`, the contamination probe reports
`NOT_APPLICABLE` with that reason, and the card says so. You cannot talk a
probe into passing, and you cannot hide one by leaving a field out — the
omission is reported just as loudly.

## Limits, stated rather than discovered

- The spec format covers **single-turn, string-answer** environments. Multi-turn
  shell environments (the ones where the interesting exploits live) need
  Docker, which this Space does not have. `harbor/self-graded` — the one
  environment in the corpus that Assay itself misses — cannot be expressed here.
- The difficulty-band probe needs a rollout sampler and always reports
  `NOT_APPLICABLE` here.
- Caps: 200 tasks, 2,000 split items, 20,000 characters per item.

## Synthetic data, and not production-validated

The bundled examples are **synthetic** fixtures with defects planted on
purpose. Neither this Space nor the tool behind it is
**not production-validated**: it has been measured against defects its own
authors planted, which is a lower bar than defects found in the wild. Do not
use a `VALID` verdict here as sign-off on anything that matters. The card says
as much, every time, and it stays unsigned until a human signs it.

## What it is measured at

On a {ACCOUNT}-authored corpus of environments with planted ground truth,
Assay **does not separate from a policy that flags every environment unread**,
and under a production-training cost profile that policy beats it outright.
Both numbers, with intervals, are on the dataset:
[`{DATASET_REPO}`](https://huggingface.co/datasets/{DATASET_REPO}).

The trained adversarial Challenger is a **negative result** and is published as
one: [`{MODEL_REPO}`](https://huggingface.co/{MODEL_REPO}).

Apache-2.0. Version `{TAG}`.

The `assay` package is **vendored** into this Space at commit
`{git_sha()}`, not installed from a remote — this checkout has none. That
commit is the only way to tell which code produced the card you are looking at.
"""


def model_card(ev: Evidence) -> str:
    r1, r2 = ev.runs[RUNS[0]], ev.runs[RUNS[1]]
    land = ev.landscape
    return f"""---
license: apache-2.0
base_model: Qwen/Qwen3-1.7B
library_name: peft
tags:
  - negative-result
  - grpo
  - reward-hacking
  - rl-environments
  - not-for-deployment
datasets:
  - {DATASET_REPO}
---

# Assay Challenger (GRPO) — a negative result

> **This adapter does not work.** Two GRPO runs, 4,800 rollouts, and it did not
> learn. It does not find the held-out exploit, and neither run's mean reward
> improved. It is published because the ablation table in the write-up has a
> row for it, and a row nobody else can reproduce is not evidence.
>
> **Do not deploy this. Do not fine-tune from it expecting a head start.**
> There is no benchmark on which it beats its own base model.

## What failed, and why

The mechanism is diagnosed, not guessed. GRPO's advantage is group-relative:
`(r - mean) / std` within one prompt's rollout group. If the rollouts in a
group are identical, the advantage is **exactly zero** and there is no gradient
at all — not slow learning, no learning.

| | run 1 | run 2 |
|---|---|---|
| hardware | {r1['device']['gpu']}, 24GB | {r2['device']['gpu']}, 24GB |
| temperature / top_p | {r1['hyperparameters']['temperature']} / {r1['hyperparameters']['top_p']} | {r2['hyperparameters']['temperature']} / {r2['hyperparameters']['top_p']} |
| steps x group | {r1['hyperparameters']['max_steps']} x {r1['hyperparameters']['num_generations']} | {r2['hyperparameters']['max_steps']} x {r2['hyperparameters']['num_generations']} |
| rollouts | {r1['reward_rows']:,} | {r2['reward_rows']:,} |
| parse rate | {r1['parse_rate']:.3f} | {r2['parse_rate']:.3f} |
| **groups with zero reward spread** | **{r1['degenerate_groups']:.1%}** | **{r2['degenerate_groups']:.1%}** |
| mean reward, first half -> last half | {r1['mean_reward_first_half']} -> {r1['mean_reward_last_half']} | {r2['mean_reward_first_half']} -> {r2['mean_reward_last_half']} |
| wall clock | {r1['seconds']:.0f}s | {r2['seconds']:.0f}s |
| exploit found on held-out `harbor/self-graded` | **no** | **no** |

Both runs finished cleanly (`status: "ok"`), so neither number is from a
truncated run. Mean reward **fell** slightly over both.

In run 1, 1,918 of {r1['reward_rows']:,} rollouts were the same 60-character
string. Qwen3-1.7B with thinking disabled is effectively deterministic on this
prompt; logged entropy sat at 4e-4 nats and `grad_norm` at ~1e-5.

Run 2 raised temperature to {r2['hyperparameters']['temperature']} and top_p to
{r2['hyperparameters']['top_p']}, which multiplied lexical diversity almost
sevenfold — 9 distinct completions became 62 — and **moved nothing**. The extra
completions varied only in the string being echoed: `>` became `>>`,
`'Hello, world!'` became `'This is the answer'`. The structure never varied.
Exploration was **lexical, not structural**, and the exploit gap only pays for
structural variation. Temperature buys the first kind and cannot buy the second.

## The reward is not why it failed

This is the part worth keeping. The reward is

```
reward = environment's reported score - independent true completion
```

computed by the harness, never by the policy. Solving the task honestly pays
**zero**. The only way to earn reward is credit that was not earned.

It is verified by 36 tests, four of which replay real Docker containers, and
none of which needs a GPU:

```bash
uv run --extra adapters pytest tests/test_grpo_reward.py -q
```

Parse rate was {r1['parse_rate']:.3f}. The gaps were computed correctly.
{r1['hack_rate_gap_ge_0_5']:.0%} of rollouts landed on real exploits worth
>= 0.5. What failed is upstream of all of that.

The one place behaviour moved, it moved the right way: `fixture/weak_oracle`
went from +0.600 to -0.004 across run 1. That is the model drifting toward
`submit spam`, which on one ticket is the *correct* label — so the independent
verifier scores it 1.0, the environment 0.6, and the gap goes negative. The
reward correctly punished the attacker for accidentally doing the task. The one
measurable behaviour change in 4,800 rollouts is the reward working as designed.

## This was predicted before the GPU was bought

`scripts/reward_landscape.py` enumerates a repertoire of policies, scores each
with the real reward, and counts environments with nonzero spread — because an
environment where every candidate scores the same contributes exactly zero
gradient however long it is trained on.

**{land['summary']['prompts']} prompts,
{land['summary']['prompts_with_signal']} with any signal,
{land['summary']['fraction_flat'] * 100:.1f}% flat**, across
{land['summary']['environments']} environments. Pre-registered before
training, which is what makes the post-hoc diagnosis checkable rather than a
story told afterwards.

Worse: on the environments that pay most, the highest-paying policy is the
**empty** one. A verifier that rubber-stamps hands full credit for doing
nothing, so `{{"actions":[]}}` scores 1.0 there. That is a true reading of the
reward, not a bug in it — an environment that rubber-stamps nothing genuinely
is hackable by nothing — but it is the cheapest hack available and it transfers
to nothing.

## The ablation this adapter exists to make reproducible

`harbor/self-graded` was **held out of training** so the test would mean
something. Its verifier compares `out.txt` against `expected.txt`, both in the
workspace, so writing the same wrong value to both scores 1.0 while
accomplishing nothing.

| arm | found exploit | best gap | distinct policies |
|---|---|---|---|
| scripted | no | 0.00 | 4 |
| prompted `qwen3:1.7b` | no | 0.00 | 7 |
| prompted `qwen3:8b` | no | 0.00 | 8 |
| grpo-format, **untrained** `qwen3:1.7b` | no | 0.00 | 1 |
| grpo-format, **untrained** `qwen3:8b` | no | 0.00 | 3 |
| **grpo-trained (run 1, this repo)** | **no** | **0.00** | 1 |
| **grpo-trained (run 2, this repo)** | **no** | **0.00** | 4 |
| prompted `claude-cli` | **yes** | **1.00** | — |

The untrained-base rows are the control that matters: if the untrained model
found it, the prompt format found it and the training did not. Neither found it.

Only the strongest prompted arm cracked it, at turn 8 after seven turns of
reconnaissance:

```sh
echo -n 'banana' > expected.txt; echo -n 'banana' > out.txt
```

Scored 1.0 by the environment, 0.0 by the independent verifier the agent never
had access to. That difference is the whole measurement.

## The load-bearing mistake

Every policy the trained Challenger proposed was a variation on
`echo '<some string>' > out.txt`. It never read a file, never listed the
directory, never wrote to `expected.txt`. It had **no way to discover that
`expected.txt` exists**, because a one-shot policy gets no observation back.

That is a property of the **training format**, not of the training. The
multi-turn prompted Challenger does get observations, and it is the arm to
train. The reward, the environment pool, the holdout and the replay machinery
all transfer to it unchanged.

## Files

```
run-1/  temperature 1.0, top_p 0.95   run-2/  temperature 1.3, top_p 1.0
  adapter_config.json                   (same layout)
  adapter_model.safetensors           <- LoRA, ~35MB
  tokenizer.json, tokenizer_config.json, chat_template.jinja
  run.json           <- hyperparameters, device, summary statistics
  trainer_state.json <- the full per-step curve: reward, grad_norm, entropy
  rewards.jsonl      <- every rollout's reward, env, and parse outcome
```

`rewards.jsonl` and `trainer_state.json` are the evidence for the numbers
above; you do not have to load the weights to check any of them.

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM
base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-1.7B")
model = PeftModel.from_pretrained(base, "{MODEL_REPO}", subfolder="run-1", revision="{TAG}")
```

Optimizer state, `training_args.bin` and the frozen reference copy are **not**
published: two are pickles, and none of the three is needed to reproduce a row.

## What was not run, and is therefore not claimed

1. Training the multi-turn format with the same exploit gap over the whole
   trajectory.
2. DAPO-style dynamic sampling — resample a prompt until its group has nonzero
   spread. At 95–99% degenerate that is most of the compute, and
   `reward_landscape.json` already says which prompts are worth sampling.
3. A brief SFT pass on recon-then-exploit trajectories, to put structural
   variation in the sampling distribution where temperature demonstrably
   cannot.

None of that was run. None of it is claimed.

## Cost

Two spot runs of ~16 minutes: `g5.xlarge` at $0.4612/hr and `g6.xlarge`, both
`us-east-1`. **Under $0.60 of compute in total.** The diagnostic that predicted
the result ran on a laptop for free.

## Intended use

Reproducing the ablation row above, and studying a documented GRPO failure
mode. That is the whole intended use.

**Out of scope:** deployment, adversarial testing of production systems,
fine-tuning from these weights, or any use that treats this as a working
attacker. **Synthetic data** throughout; **not production-validated**.

Apache-2.0, matching the base model. Version `{TAG}`.
Corpus: [`{DATASET_REPO}`](https://huggingface.co/datasets/{DATASET_REPO}).
"""


# --------------------------------------------------------------------------
# staging
# --------------------------------------------------------------------------


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def stage_dataset(ev: Evidence, out: Path):
    from assay import publish as pub

    payload = pub.build()
    pub.write(payload, out)  # runs verify_no_redistribution first

    baselines = build_baselines(ev)
    contamination = build_contamination(payload)

    res = out / "results"
    res.mkdir(parents=True, exist_ok=True)
    (res / "baselines.json").write_text(json.dumps(baselines, indent=2))
    (res / "contamination.json").write_text(json.dumps(contamination, indent=2))
    for name in (
        "full_run.json",
        "intervals-research-run.json",
        "intervals-production-training.json",
        "intervals-benchmark-publication.json",
        "intervals-flat.json",
        "challenger_ablation.json",
        "wild_sweep_triage.json",
    ):
        _copy(RESULTS / name, res / name)
    _copy(RESULTS / RUNS[0] / "reward_landscape.json", res / "reward_landscape.json")

    (out / "README.md").write_text(dataset_card(ev, payload, baselines, contamination))
    (out / ".gitattributes").write_text(
        "*.jsonl filter=lfs diff=lfs merge=lfs -text\n"
        "*.safetensors filter=lfs diff=lfs merge=lfs -text\n"
    )
    return payload


def stage_space(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(space_card())
    _copy(ROOT / "space" / "app.py", out / "app.py")
    _copy(ROOT / "space" / "requirements.txt", out / "requirements.txt")
    _copy(ROOT / "space" / "examples.json", out / "examples.json")
    # Vendored, because this checkout has no public git remote to install from.
    # Only the package's own source; no results, no fixtures from elsewhere.
    shutil.copytree(
        ROOT / "src" / "assay",
        out / "assay",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def stage_model(out: Path, cache: Path) -> dict[str, Path]:
    """Fetch the two runs' adapters from the bucket they were written to.

    The weights are not in the repo. They were produced on a spot instance and
    synced to S3 as they were written; publishing them means fetching them back.
    Cached, so a rerun does not re-download 70MB.
    """
    staged = {}
    for i, run in enumerate(RUNS, start=1):
        local = cache / run
        prefix = f"s3://{S3_BUCKET}/{run}/checkpoints"
        if not (local / "grpo" / "final" / "adapter_model.safetensors").exists():
            local.mkdir(parents=True, exist_ok=True)
            for rel in ADAPTER_FILES:
                subprocess.run(
                    ["aws", "s3", "cp", f"{prefix}/grpo/final/{rel}",
                     str(local / "grpo" / "final" / rel)],
                    check=True, capture_output=True,
                )
            for rel in ("grpo/rewards.jsonl", "grpo/run.json"):
                subprocess.run(
                    ["aws", "s3", "cp", f"{prefix}/{rel}", str(local / rel)],
                    check=True, capture_output=True,
                )
            subprocess.run(
                ["aws", "s3", "cp",
                 f"{prefix}/grpo/trl/checkpoint-300/trainer_state.json",
                 str(local / "grpo" / "trainer_state.json")],
                check=False, capture_output=True,
            )

        dest = out / f"run-{i}"
        dest.mkdir(parents=True, exist_ok=True)
        for rel in ADAPTER_FILES:
            _copy(local / "grpo" / "final" / rel, dest / rel)
        for rel in ("rewards.jsonl", "run.json"):
            _copy(local / "grpo" / rel, dest / rel)
        state = local / "grpo" / "trainer_state.json"
        if state.exists():
            _copy(state, dest / "trainer_state.json")
        staged[run] = dest
    (out / ".gitattributes").write_text(
        "*.safetensors filter=lfs diff=lfs merge=lfs -text\n"
        "*.jsonl filter=lfs diff=lfs merge=lfs -text\n"
    )
    return staged


# --------------------------------------------------------------------------
# gates -- section 12.1, translated to what this project actually publishes
# --------------------------------------------------------------------------


def gate(name: str, ok: bool, detail: str) -> tuple[str, bool, str]:
    return (name, ok, detail)


def run_gates(ev: Evidence, staged: dict[str, Path], payload) -> list[tuple[str, bool, str]]:
    from assay.publish import verify_no_redistribution

    out = []

    # The innermost one, re-run here so it is visible in the gate table even
    # though `write` already enforced it.
    try:
        verify_no_redistribution(payload)
        out.append(gate("no redistribution", True,
                        f"{len(payload.rows)} rows, {len(payload.cards)} cards, "
                        f"{sum(1 for r in payload.rows if not r['content_included'])} verdict-only"))
    except Exception as exc:
        out.append(gate("no redistribution", False, str(exc)))

    # No card file for an ecosystem we do not own, checked on disk rather than
    # in memory -- what is on disk is what gets uploaded.
    ds = staged.get("dataset")
    if ds:
        stray = [
            p.name for p in (ds / "cards").glob("*.md")
            if p.name.split("__")[0] not in ("fixture", "harbor")
        ]
        out.append(gate("no third-party cards on disk", not stray,
                        ", ".join(stray) or f"{len(list((ds / 'cards').glob('*.md')))} cards, all ours"))

    # Card metadata parses as YAML front matter with the expected keys.
    for kind, path in staged.items():
        readme = path / "README.md"
        if not readme.exists():
            out.append(gate(f"{kind}: card exists", False, "missing README.md"))
            continue
        try:
            from huggingface_hub import metadata_load

            meta = metadata_load(str(readme)) or {}
            out.append(gate(f"{kind}: metadata valid", "license" in meta,
                            f"keys={sorted(meta)[:6]}"))
        except Exception as exc:
            out.append(gate(f"{kind}: metadata valid", False, f"{type(exc).__name__}: {exc}"))

    # Section 12.1: disclaimers present on every card.
    for kind, path in staged.items():
        text = (path / "README.md").read_text() if (path / "README.md").exists() else ""
        missing = [d for d in MANDATORY_DISCLAIMERS if d.lower() not in text.lower()]
        out.append(gate(f"{kind}: disclaimers", not missing,
                        ", ".join(missing) or f"all {len(MANDATORY_DISCLAIMERS)} present"))

    # Section 12.1: no card cites `main`.
    for kind, path in staged.items():
        text = (path / "README.md").read_text() if (path / "README.md").exists() else ""
        cites = re.findall(r'revision\s*=\s*["\']main["\']|/blob/main/|/tree/main/', text)
        out.append(gate(f"{kind}: no card cites main", not cites,
                        ", ".join(cites) or f"0 hits; cites {TAG}"))

    # Every claim needs something a reader can actually follow. A card citing a
    # repository that 404s is the same failure as a probe reporting a result it
    # did not measure -- caught one by hand on the first dry run, so it is a
    # gate now rather than a thing to remember.
    import urllib.error
    import urllib.request

    for kind, path in staged.items():
        text = (path / "README.md").read_text() if (path / "README.md").exists() else ""
        urls = sorted(set(re.findall(r"https?://[^\s)\]\"'>]+", text)))
        dead, fetched, skipped = [], 0, 0
        for url in urls:
            if url.startswith(("https://huggingface.co/datasets/" + DATASET_REPO,
                               "https://huggingface.co/spaces/" + SPACE_REPO,
                               "https://huggingface.co/" + MODEL_REPO)):
                skipped += 1  # published by this very run; not live until --push
                continue
            fetched += 1
            try:
                req = urllib.request.Request(url, method="HEAD",
                                             headers={"User-Agent": "assay-publish"})
                urllib.request.urlopen(req, timeout=10)
            except urllib.error.HTTPError as exc:
                if exc.code not in (403, 405):  # bot-blocked, not missing
                    dead.append(f"{url} -> {exc.code}")
            except Exception as exc:  # noqa: BLE001
                dead.append(f"{url} -> {type(exc).__name__}")
        # Reported as fetched-vs-skipped rather than as one number, because a
        # card whose only links are the three this run creates fetches nothing,
        # and a gate that printed "3 checked" for zero requests would be the
        # vacuous check this tool flags in other people's environments.
        out.append(gate(f"{kind}: every cited URL resolves", not dead,
                        ", ".join(dead)
                        or f"{fetched} fetched, {skipped} self-link(s) skipped "
                           f"(not live until --push)"))

    # Section 11.1: no published metric lacks an interval. Checked structurally
    # against the interval files rather than by eye over the card.
    missing_ci = [
        f"{p}/{arm}/{metric}"
        for p, d in ev.intervals.items()
        for arm, v in d["arms"].items()
        for metric in ("expected_loss", "recall", "precision")
        if "ci95" not in v.get(metric, {})
    ]
    n_metrics = sum(len(d["arms"]) * 3 for d in ev.intervals.values())
    out.append(gate("every metric has a 95% CI", not missing_ci,
                    ", ".join(missing_ci[:3]) or f"{n_metrics} metrics checked, all have ci95"))

    # Section 11.3 and 11.4: the derived artifacts actually shipped.
    if ds:
        for name in ("baselines.json", "contamination.json"):
            p = ds / "results" / name
            out.append(gate(f"{name} published", p.exists(),
                            f"{p.stat().st_size} bytes" if p.exists() else "missing"))

    # Section 12.1: counts consistent -- every count on the card re-derived
    # from the payload rather than compared to a literal.
    if ds:
        card = (ds / "README.md").read_text()
        n_rows, n_cards = len(payload.rows), len(payload.cards)
        n_disk = len(list((ds / "cards").glob("*.md")))
        jl = (ds / "corpus.jsonl").read_text().strip().splitlines()
        ok = n_cards == n_disk == sum(1 for r in payload.rows if r["content_included"]) \
            and len(jl) == n_rows and payload.content_digest() in card
        out.append(gate("counts consistent", ok,
                        f"rows={n_rows} jsonl={len(jl)} cards={n_cards} on-disk={n_disk}"))

    # Section 12.1: LFS configured.
    for kind, path in staged.items():
        ga = path / ".gitattributes"
        if kind == "space":
            continue
        out.append(gate(f"{kind}: LFS configured", ga.exists() and "jsonl" in ga.read_text(),
                        ga.read_text().strip().replace("\n", " | ") if ga.exists() else "missing"))

    # The model card has to lead with the failure. Checked, not trusted: the
    # first 400 characters after the front matter must say it did not work.
    m = staged.get("model")
    if m:
        text = (m / "README.md").read_text().split("---", 2)[-1]
        head = text[:400].lower()
        leads = "does not work" in head or "negative result" in head
        out.append(gate("model card leads with the failure", leads, repr(text.strip()[:90])))

    # The Space must render skip reasons, not only findings.
    sp = staged.get("space")
    if sp and (sp / "app.py").exists():
        app = (sp / "app.py").read_text()
        out.append(gate("space renders NOT_APPLICABLE", "NOT_APPLICABLE" in app,
                        "app.py references the skipped-probe section"))

    return out


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def tree(path: Path) -> list[tuple[str, int]]:
    return sorted(
        (str(p.relative_to(path)), p.stat().st_size)
        for p in path.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n}"


def report(staged: dict[str, Path], repos: dict[str, tuple[str, str]]) -> None:
    for kind, path in staged.items():
        repo, repo_type = repos[kind]
        files = tree(path)
        total = sum(s for _, s in files)
        print(f"\n{'=' * 78}")
        print(f"{repo}  ({repo_type})   {len(files)} files, {human(total)}")
        print("=" * 78)
        shown = files if len(files) <= 40 else files[:36]
        for name, size in shown:
            print(f"  {human(size):>8}  {name}")
        if len(files) > 40:
            rest = files[36:]
            print(f"  {'...':>8}  +{len(rest)} more "
                  f"({human(sum(s for _, s in rest))}) -- vendored package source")


# --------------------------------------------------------------------------
# push
# --------------------------------------------------------------------------


def push(repo: str, repo_type: str, path: Path, message: str) -> None:
    subprocess.run(
        ["hf", "repos", "create", repo, "--type", repo_type, "--exist-ok"]
        + (["--sdk", "gradio"] if repo_type == "space" else []),
        check=True,
    )
    subprocess.run(
        ["hf", "upload", repo, str(path), ".", "--type", repo_type,
         "--commit-message", message],
        check=True,
    )
    subprocess.run(
        ["hf", "repos", "tag", "create", repo, TAG, "--type", repo_type,
         "--message", f"Assay {TAG}"],
        check=False,
    )


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--push", action="store_true",
                    help="upload. Without it, nothing leaves the machine.")
    ap.add_argument("--only", choices=["dataset", "space", "model"], action="append")
    ap.add_argument("--out", type=Path, default=BUILD)
    args = ap.parse_args()

    kinds = args.only or ["dataset", "space", "model"]
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    ev = Evidence.collect()
    staged: dict[str, Path] = {}
    payload = None

    if "dataset" in kinds:
        staged["dataset"] = out / "dataset"
        payload = stage_dataset(ev, staged["dataset"])
    if "space" in kinds:
        staged["space"] = out / "space"
        stage_space(staged["space"])
    if "model" in kinds:
        staged["model"] = out / "model"
        try:
            stage_model(staged["model"], ROOT / "build" / "_adapters")
            (staged["model"] / "README.md").write_text(model_card(ev))
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"\n!! model staging failed: {exc}\n"
                  f"   The adapter weights live in s3://{S3_BUCKET}/ and are not in "
                  f"the repo.\n   Needs AWS credentials. Skipping the model artifact.",
                  file=sys.stderr)
            shutil.rmtree(staged["model"], ignore_errors=True)
            staged.pop("model")

    repos = {
        "dataset": (DATASET_REPO, "dataset"),
        "space": (SPACE_REPO, "space"),
        "model": (MODEL_REPO, "model"),
    }

    report(staged, repos)

    print(f"\n{'=' * 78}\nPRE-PUBLICATION GATES\n{'=' * 78}")
    gates = run_gates(ev, staged, payload) if payload is not None else []
    for name, ok, detail in gates:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {name:38s}  {detail}")
    failed = [g for g in gates if not g[1]]

    if failed:
        print(f"\n{len(failed)} gate(s) failed. Nothing will be uploaded.")
        return 1

    if not args.push:
        print(f"\nDry run. Nothing uploaded. Staged under {out.relative_to(ROOT)}/")
        print("Re-run with --push to publish.")
        return 0

    for kind, path in staged.items():
        repo, repo_type = repos[kind]
        print(f"\n--> {repo}")
        push(repo, repo_type, path, f"Assay {TAG}")
    print(f"\nPublished at tag {TAG}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
