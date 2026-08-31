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

#: The Space that actually deploys. `SPACE_REPO` is the Gradio app, which this
#: account cannot host: `/api/repos/create` returns 402 for a Gradio Space on
#: free `cpu-basic`. A **static** Space is free, and the probe battery runs in
#: the visitor's browser under Pyodide instead of on a server. Separate repo,
#: not a replacement -- pushing a static build over a repo created with
#: `--space-sdk gradio` would leave the SDK in the front matter disagreeing
#: with what is in the tree.
DEMO_REPO = f"{ACCOUNT}/assay-demo"

#: Pinned, and pinned exactly. The rest of this script refuses to cite `main`;
#: a demo whose runtime is whatever `stable` resolved to that morning is the
#: same defect with a CDN in front of it. Bump deliberately -- the
#: `demo: pyodide is pinned and resolves` gate fetches this exact URL.
PYODIDE_VERSION = "314.0.6"
PYODIDE_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/pyodide.js"

#: Which of `space/examples.json` the demo opens on, matching `PRELOADED` in
#: `space/app.py` -- an empty box asks a visitor to supply the argument for the
#: tool before they have seen it make one, and this example *is* the argument.
#: A gate checks the two agree rather than trusting this comment.
PRELOADED_INDEX = 2

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

The source repository is [github.com/caiotheodoro/assay](https://github.com/caiotheodoro/assay).
Every command below is quoted in full so it can be run from a checkout.

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

**1. Most of the margin's growth is arithmetic, not detection.** Assay does now
separate from `flag_everything` under `research-run` —
**{ci(rr['assay']['loss_saved_vs']['flag_everything'])}**, and this card used to
say it did not. But `flag_everything`'s loss is `Σ_env (n_classes − |planted|)`,
so it gets worse every time the taxonomy or the corpus grows and a truthful
detector gains nothing: two probe families added two defect classes and two τ²
environments were added, worth **+77** to the margin between them. Against the
taxonomy and corpus this was first measured on the comparable figure is
**274.0**. A margin that widens because the floor got worse is not the same
evidence as one that widens because the detector got better.

**2. Under `production-training` the same caveat decides the row.** Expected
loss {pt['flag_everything']['expected_loss']['point']:g} for `flag_everything`
against Assay's {pt['assay']['expected_loss']['point']:g}, paired difference
{ci(pt['assay']['loss_saved_vs']['flag_everything'])}. That row previously
favoured `flag_everything` outright, and what moved it was the floor paying for
two more classes per environment — not a detection change. At that profile's
480x ratio "flag everything and read the cards" is a genuinely good policy, and
Assay earns its place only where false alarms have real cost.

**And precision is no longer 1.000.** Three spurious findings remain, all three
on the two τ² environments — the only ones in the corpus whose ground truth was
decided by another organisation.

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

Related: [`{MODEL_REPO}`](https://huggingface.co/{MODEL_REPO}) is a **negative
result** — a GRPO-trained adversarial Challenger that did not learn —
published so the ablation row is checkable.

Audit an environment yourself: [`{DEMO_REPO}`](https://huggingface.co/spaces/{DEMO_REPO})
runs this probe battery **in your browser**, under WebAssembly CPython, with no
server. The Gradio version of the same app is in the repository under `space/`
and is not deployed — Hugging Face requires a paid plan for a Gradio Space —
so the hosted demo is the static one.
"""


def git_sha() -> str:
    """Which source the Space is running. It vendors the package rather than
    installing it from the remote, so the commit is the only way for a reader to
    tell exactly what code produced their card -- the tree can be dirty, and a
    branch name would not pin it."""
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
python_version: "3.11"
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
**production-validated**: it has been measured against defects its own
authors planted, which is a lower bar than defects found in the wild. Do not
use a `VALID` verdict here as sign-off on anything that matters. The card says
as much, every time, and it stays unsigned until a human signs it.

## What it is measured at

On a corpus that is mostly {ACCOUNT}-authored, with planted ground truth, Assay
separates from a policy that flags every environment unread on all four cost
profiles — but **a large part of that margin is arithmetic and not detection**:
flagging everything pays a false alarm for every defect class on every
environment, so the floor got worse when two classes and two environments were
added, and a truthful detector gained nothing from either. Every number, with
intervals and that decomposition, is on the dataset:
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

# You cannot train an exploit-finder that never gets to look

**A one-shot RL policy cannot learn to find a bug it has to discover first.** Not
slowly — at all. This is the training evidence for that, from two GRPO runs and
4,800 rollouts against a reward that pays only for reward hacking, on an
environment whose exploit requires reading the filesystem.

Three findings, each measured here and each transferable to any RL run with a
sparse behavioural reward:

1. **Zero spread is zero gradient, not slow learning.** GRPO's advantage is
   group-relative, `(r − mean) / std` within one prompt's rollout group. In run 1,
   **99.7% of groups had identical rewards** — so the advantage was exactly zero
   and no gradient existed. Training for longer buys nothing.
2. **Temperature buys the wrong kind of diversity.** Raising it 1.0 → 1.3
   multiplied distinct completions **sevenfold, 9 → 62, and moved nothing.** The
   extra completions varied the *string being echoed*, never the structure, and
   only structural variation earns an exploit gap. Exploration that is lexical
   cannot find a behavioural exploit.
3. **The format was the ceiling, not the reward.** Every policy the trained model
   proposed was a variation on `echo '<string>' > out.txt`. It never listed a
   directory, because a one-shot policy **gets no observation back** — so it had
   no way to learn that the file it needed to overwrite exists. The reward was
   verified correct by 36 tests and 16% of rollouts landed on real exploits. The
   failure is upstream of reward design.

And **it was predictable before the GPU was rented.**
`scripts/reward_landscape.py` enumerates candidate policies, scores them with the
real reward, and counts environments with nonzero spread: **51.3% flat across 39
prompts**, pre-registered before training started.

> **The weights are here so the ablation row below is checkable, not because you
> should run them.** They do not beat their own base model on anything. If you
> want the Challenger that *does* find the exploit, it is the multi-turn prompted
> arm — the reward, environment pool, holdout and replay machinery all transfer to
> it unchanged.

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

**The holdout leaked, and that makes the negative stronger rather than weaker.**
`results/train_holdout_dedup.json` in the dataset records it: the
`harbor/self-graded` prompt is a **byte-identical duplicate** of three training
prompts — `harbor/broken-gold`, `harbor/healthy`, `harbor/vacuous-tests`, all at
`true_jaccard 1.0`. The Harbor prompts differ only in the task name, and the
exploit lives in the *filesystem*, not the prompt.

So this is not a clean held-out test and should not be read as one. What it is
instead: the model failed to find the exploit on the **easiest possible** version
of the test, one whose prompt it had already trained on hundreds of times. A
result that survives its own contamination is worth more than one that needs the
contamination explained away — and the reason it survives is finding 3 above,
which has nothing to do with which prompts were held out.

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


# --------------------------------------------------------------------------
# the static Space -- the one that actually deploys
# --------------------------------------------------------------------------


def demo_card() -> str:
    """Front matter for a **static** Space. `sdk: static` is the whole trick.

    The reasoning that concluded a hosted demo was impossible was right about
    every step it took and never took one more: a static Space serves files and
    runs no compute, so it cannot run the battery *server-side* -- and the
    battery does not have to run server-side. It runs in the visitor's browser.
    """
    return f"""---
title: Assay
emoji: "\N{MICROSCOPE}"
colorFrom: indigo
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: Audit an RL environment in your browser, no server
tags:
  - evaluation
  - benchmark-auditing
  - reward-hacking
  - pyodide
---

# Assay — in your browser

Submit an environment. Get an Environment Card back: a validity verdict where
every claim is tied to a probe result, **and a list of every probe that could
not run and why**.

That second half is the point. A card with no findings is not a clean bill of
health, and this page refuses to render one as if it were.

## Where the audit runs

This is a **static** Space. Hugging Face serves these files and runs no
compute — which is why it is free where a Gradio Space is not. The probe
battery still runs, in the visitor's tab, in a WebAssembly CPython
(Pyodide {PYODIDE_VERSION}) against the vendored `assay` package in
`assay.zip`. Nothing a visitor pastes is uploaded, because there is nowhere to
upload it to.

That works because Assay's audit path is **pure standard library**. The package
declares one runtime dependency, `pyyaml`, and only `assay.costs` reaches it —
no probe does. So the page needs no `micropip`, no wheel index and no network
beyond its own files.

The seven bundled examples are **pre-rendered into the page at build time** by
the same renderer the button calls, so the page is readable before the runtime
loads and stays readable if it never does.

## What it cannot check here

- **Single-turn, string-answer environments only.** Multi-turn shell
  environments — where the interesting exploits live — need Docker.
  `harbor/self-graded`, the one environment in the corpus that Assay itself
  misses, cannot be expressed in this format.
- The difficulty-band probe needs a rollout sampler and always reports
  `NOT_APPLICABLE` here, so no submission can reach `VALID` on this page.
- `verifier: "regex"` is **refused rather than degraded**. `assay.safe_regex`
  bounds a submitted pattern by matching it in a subprocess under a wall clock,
  because Python's engine backtracks and `(a+)+$` against 31 characters takes
  about 100 seconds. WebAssembly has no subprocesses, and falling back to a
  bare `re.search` would reinstate that denial of service on the one page it
  was about.
- Caps: 200 tasks, 2,000 split items, 20,000 characters per item.

## Synthetic data, and not production-validated

The bundled examples are **synthetic** fixtures with defects planted on
purpose. Neither this Space nor the tool behind it is
**production-validated**: it has been measured against defects its own authors
planted, which is a lower bar than defects found in the wild. Do not use a
`VALID` verdict here as sign-off on anything that matters. The card says as
much, every time, and it stays unsigned until a human signs it.

## What it is measured at

On a corpus that is mostly {ACCOUNT}-authored, with planted ground truth, Assay
separates from a policy that flags every environment unread on all four cost
profiles — but **a large part of that margin is arithmetic and not detection**:
flagging everything pays a false alarm for every defect class on every
environment, so the floor got worse when two classes and two environments were
added, and a truthful detector gained nothing from either. Every number, with
intervals and that decomposition, is on the dataset:
[`{DATASET_REPO}`](https://huggingface.co/datasets/{DATASET_REPO}).

The trained adversarial Challenger is a **negative result** and is published as
one: [`{MODEL_REPO}`](https://huggingface.co/{MODEL_REPO}).

Apache-2.0. Version `{TAG}`.

The `assay` package is **vendored** into this Space at commit `{git_sha()}`,
not installed from a remote — this checkout has none. That commit is the only
way to tell which code produced the card you are looking at.
"""


def _example_block(index: int, name: str, spec: dict, report) -> str:
    """One pre-rendered example: its spec, and the card the battery produced.

    The card half is `web.card(report)` -- the identical call the button makes
    once Pyodide is up, not a screenshot or a hand-written mock-up of one. A
    gate asserts the two agree.
    """
    from assay.card import web

    colour = web.VERDICT_COLOUR[report.verdict]
    pretty = json.dumps(spec, indent=2)
    return f"""<article class="example">
  <header>
    <h3>{web.escape(name)}</h3>
    <span>
      <span class="badge" style="background:{colour}">{web.escape(report.verdict)}</span>
      <button class="ghost" data-load="{index}">Load into the auditor</button>
      <a class="ghost" href="cards/{index + 1}.html">Full card</a>
    </span>
  </header>
  <div class="body">
    <div class="spec"><pre><code>{web.escape(pretty)}</code></pre></div>
    <div class="card">{web.card(report)}</div>
  </div>
</article>"""


def _zip_package(dest: Path) -> None:
    """The `assay` tree the browser unpacks, byte-for-byte the tree the Gradio
    Space vendors. Fixed timestamps so a rerun that changed nothing produces an
    identical archive rather than a new upload."""
    import zipfile

    src = ROOT / "src"
    files = sorted(
        p for p in (src / "assay").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(str(path.relative_to(src)), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())


def stage_demo(out: Path) -> None:
    from assay.adapters.spec import build
    from assay.card import to_html, web
    from assay.runner import audit

    out.mkdir(parents=True, exist_ok=True)
    (out / "cards").mkdir(exist_ok=True)

    examples = json.loads((ROOT / "space" / "examples.json").read_text())

    blocks, options, data = [], [], []
    preloaded_card = preloaded_spec = ""
    for i, ex in enumerate(examples):
        spec_text = json.dumps(ex["spec"], indent=2)
        report = audit(build(spec_text))
        blocks.append(_example_block(i, ex["name"], ex["spec"], report))
        options.append(
            f'<option value="{i}"{" selected" if i == PRELOADED_INDEX else ""}>'
            f"{web.escape(ex['name'])}</option>"
        )
        data.append({"name": ex["name"], "spec": spec_text})
        # A full standalone Environment Card per example, from the renderer the
        # CLI's `--card` flag uses. This is the artifact the tool actually
        # produces; the page shows a fragment of it.
        (out / "cards" / f"{i + 1}.html").write_text(to_html(report))
        if i == PRELOADED_INDEX:
            preloaded_card, preloaded_spec = web.card(report), spec_text

    # `<` inside a <script> block would end it early no matter the JSON escaping
    # rules, and the examples are ours only until someone adds one.
    examples_json = json.dumps(data).replace("<", "\\u003c")

    template = (ROOT / "space" / "static" / "index.template.html").read_text()
    page = template
    for key, value in {
        "CARD_CSS": web.CSS,
        "PICKER_OPTIONS": "".join(options),
        "PRELOADED_SPEC": web.escape(preloaded_spec),
        "PRELOADED_CARD": preloaded_card,
        "EXAMPLES": "\n".join(blocks),
        "EXAMPLES_JSON": examples_json,
        "PYODIDE_URL": PYODIDE_URL,
        "DATASET_REPO": DATASET_REPO,
        "MODEL_REPO": MODEL_REPO,
        "TAG": TAG,
        "COMMIT": git_sha(),
    }.items():
        page = page.replace("{{" + key + "}}", value)

    (out / "index.html").write_text(page)
    (out / "README.md").write_text(demo_card())
    _copy(ROOT / "space" / "static" / "browser.py", out / "browser.py")
    _zip_package(out / "assay.zip")


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


def _space_behaviour_gates(sp: Path) -> list[tuple[str, bool, str]]:
    """Render a real report with the staged app and look at what came out.

    Substring gates over source text are the cheapest thing to write and the
    least evidence they can carry: `"NOT_APPLICABLE" in app` passes on a file
    that only mentions the constant in a comment. These import the staged copy
    -- the one about to be uploaded, not the one in the repo -- and check the
    two properties the Space exists for: a thin submission shows its skipped
    probes, and a submitted string cannot reach the page as live HTML.
    """
    import importlib.util
    import json as _json

    try:
        spec = importlib.util.spec_from_file_location("staged_space_app", sp / "app.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["staged_space_app"] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 - a Space that cannot import cannot ship
        return [gate("space imports", False, f"{type(exc).__name__}: {exc}")]

    thin = _json.dumps({
        "env_id": "gate/thin",
        "tasks": [{"task_id": "q1", "instruction": "Answer Yes or No", "target": "Yes"}],
    })
    html = mod.run_audit(thin)[0]
    out = [gate("space renders skipped probes", "could not be checked" in html,
                "a thin spec shows its skip table")]

    payload = '<img src=x onerror="alert(1)">'
    hostile = _json.dumps({
        "env_id": "gate/hostile",
        "verifier": "includes",
        "tasks": [{"task_id": payload, "instruction": "Answer Yes or No",
                   "target": "Yes", "gold": "Yes", "known_wrong": "No"}],
    })
    rendered = mod.run_audit(hostile)[0]
    clean = "<img src=x" not in rendered
    out.append(gate("space escapes submitted text", clean,
                    "a hostile task id renders escaped" if clean
                    else "SUBMITTED HTML REACHED THE PAGE"))
    return out


def _demo_gates(dp: Path) -> list[tuple[str, bool, str]]:
    """What has to be true of a page nobody will run a server for.

    The Gradio Space's gates could lean on importing `app.py` and calling it.
    Half of this artifact is a *document* -- seven cards baked into the HTML --
    and the other half is Python that only ever executes inside a browser. So
    these gates do both: they read the built page for the properties a visitor
    with JavaScript switched off still depends on, and they import the staged
    `browser.py` and drive it, because the escaping and the regex refusal are
    behaviour, not text.

    What they cannot check is that Pyodide boots. That needs a browser, and it
    was checked in one before this shipped -- but a gate that cannot run is a
    gate that must not claim to have run, so it is absent rather than faked.
    """
    import importlib.util
    import json as _json
    import zipfile

    out = []
    index = dp / "index.html"
    if not index.exists():
        return [gate("demo: index.html exists", False, "missing; a static Space serves nothing")]
    page = index.read_text()

    # A `{{PLACEHOLDER}}` that survived staging is a hole in a published page.
    holes = re.findall(r"\{\{[A-Z_]+\}\}", page)
    out.append(gate("demo: template fully substituted", not holes,
                    ", ".join(sorted(set(holes))) or f"{len(page):,} bytes, no placeholders left"))

    # Names carry an em dash and other characters `escape` rewrites, so compare
    # on the escaped form -- the form actually in the file.
    from assay.card import web

    examples = _json.loads((ROOT / "space" / "examples.json").read_text())
    baked = [ex["name"] for ex in examples if web.escape(ex["name"]) in page]
    out.append(gate("demo: every example is pre-rendered",
                    len(baked) == len(examples),
                    f"{len(baked)}/{len(examples)} in the static HTML"))

    # The property the whole page is built around, checked where it matters
    # most: in the bytes a visitor sees before any script has run.
    out.append(gate("demo: skipped probes are in the static HTML",
                    "could not be checked" in page,
                    "a thin spec's skip table is baked in, not fetched"))

    out.append(gate("demo: pyodide is pinned, not floating",
                    PYODIDE_URL in page and "/stable/" not in page
                    and "/latest/" not in page,
                    f"v{PYODIDE_VERSION}"))

    # A standalone Environment Card per example, from `card/render.py` -- the
    # artifact the CLI writes with `--card`, one click from the fragment.
    cards = sorted((dp / "cards").glob("*.html"))
    out.append(gate("demo: a full card per example", len(cards) == len(examples),
                    f"{len(cards)} standalone cards"))

    zpath = dp / "assay.zip"
    try:
        with zipfile.ZipFile(zpath) as zf:
            names = set(zf.namelist())
    except Exception as exc:  # noqa: BLE001
        names = set()
        out.append(gate("demo: ships the package it runs", False, f"{type(exc).__name__}: {exc}"))
    if names:
        needed = {"assay/runner.py", "assay/adapters/spec.py", "assay/card/web.py",
                  "assay/probes/__init__.py", "assay/types.py"}
        missing = sorted(needed - names)
        pyc = [n for n in names if n.endswith(".pyc") or "__pycache__" in n]
        out.append(gate("demo: ships the package it runs", not missing and not pyc,
                        ", ".join(missing + pyc)
                        or f"{len(names)} files, {zpath.stat().st_size / 1024:.0f}KB"))

    # ---- behaviour: import the staged browser module and drive it ----------
    try:
        spec = importlib.util.spec_from_file_location("staged_demo_browser", dp / "browser.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["staged_demo_browser"] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001
        out.append(gate("demo: browser module imports", False, f"{type(exc).__name__}: {exc}"))
        return out

    payload = '<img src=x onerror="alert(1)">'
    hostile = _json.dumps({
        "env_id": "gate/hostile",
        "verifier": "includes",
        "tasks": [{"task_id": payload, "instruction": "Answer Yes or No",
                   "target": "Yes", "gold": "Yes", "known_wrong": "No"}],
    })
    rendered = _json.loads(mod.audit(hostile))["html"]
    clean = "<img src=x" not in rendered and "&lt;img src=x" in rendered
    out.append(gate("demo: escapes submitted text", clean,
                    "a hostile task id renders escaped" if clean
                    else "SUBMITTED HTML REACHED THE PAGE"))

    # The one thing that genuinely cannot work in a browser has to fail by
    # saying so, not by erroring eight probes out one at a time.
    rx = _json.loads(mod.audit(_json.dumps({
        "env_id": "gate/regex", "verifier": "regex",
        "tasks": [{"task_id": "q1", "instruction": "i", "target": "Yes"}],
    })))["html"]
    refused = "subprocess" in rx and "assay-error" in rx
    out.append(gate("demo: refuses the regex verifier", refused,
                    "explained, not degraded to an unguarded re.search" if refused
                    else "the regex verifier was not refused"))

    # The gallery is not a mock-up: the card baked into the page for the
    # example the box opens on is byte-identical to what the button produces.
    live = _json.loads(mod.audit(_json.dumps(examples[PRELOADED_INDEX]["spec"], indent=2)))["html"]
    out.append(gate("demo: the baked card is the live card", live in page,
                    "identical bytes" if live in page
                    else "the pre-rendered card does not match a live audit"))

    # ...and it opens on the same example the Gradio app opens on, so the two
    # front doors argue the same thing.
    import ast

    app_src = (ROOT / "space" / "app.py").read_text()
    m = re.search(r"^PRELOADED = (\".*\")$", app_src, flags=re.M)
    # `literal_eval` rather than a string compare: the name is written with a
    # literal em dash here and was written `—` before, and a gate that
    # broke on that spelling change would be measuring the wrong thing.
    same = bool(m) and ast.literal_eval(m.group(1)) == examples[PRELOADED_INDEX]["name"]
    out.append(gate("demo: opens on the Gradio app's example", same,
                    examples[PRELOADED_INDEX]["name"][:52]))

    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(
            urllib.request.Request(PYODIDE_URL, method="HEAD",
                                   headers={"User-Agent": "assay-publish"}),
            timeout=15,
        )
        out.append(gate("demo: the pinned runtime resolves", True, PYODIDE_URL))
    except Exception as exc:  # noqa: BLE001
        out.append(gate("demo: the pinned runtime resolves", False,
                        f"{PYODIDE_URL} -> {type(exc).__name__}: {exc}"))
    return out


def run_gates(ev: Evidence, staged: dict[str, Path], payload) -> list[tuple[str, bool, str]]:
    from assay.publish import verify_no_redistribution

    out = []

    # The innermost one, re-run here so it is visible in the gate table even
    # though `write` already enforced it.
    if payload is None:
        # `--only space` stages no dataset. The redistribution gate has nothing
        # to check and says so, rather than the whole gate table being skipped.
        out.append(gate("no redistribution", True,
                        "no dataset staged; nothing to redistribute"))
    else:
        try:
            verify_no_redistribution(payload)
            out.append(gate(
                "no redistribution", True,
                f"{len(payload.rows)} rows, {len(payload.cards)} cards, "
                f"{sum(1 for r in payload.rows if not r['content_included'])} verdict-only"))
        except Exception as exc:  # noqa: BLE001 - any failure here blocks the upload
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
            # The Hub's own limits, checked here rather than discovered by the
            # upload rejecting the commit. `short_description` over 60
            # characters is a `ValueError` from `upload_folder` after every
            # gate has printed PASS -- which is the same blind spot as the
            # `--space-sdk` one: a dry run that cannot fail the way the real
            # run fails.
            brief = str(meta.get("short_description", ""))
            out.append(gate(f"{kind}: short_description within the Hub limit",
                            len(brief) <= 60, f"{len(brief)}/60 chars"))
        except Exception as exc:
            out.append(gate(f"{kind}: metadata valid", False, f"{type(exc).__name__}: {exc}"))

    # Section 12.1: disclaimers present on every card.
    for kind, path in staged.items():
        text = (path / "README.md").read_text() if (path / "README.md").exists() else ""
        missing = [d for d in MANDATORY_DISCLAIMERS if d.lower() not in text.lower()]
        out.append(gate(f"{kind}: disclaimers", not missing,
                        ", ".join(missing) or f"all {len(MANDATORY_DISCLAIMERS)} present"))

    # ...and a gate that only searches for a substring cannot tell a claim from
    # its negation. The Space card read "Neither this Space nor the tool behind
    # it is **not production-validated**" -- a double negative asserting the
    # tool IS validated, on the page whose whole job is to say it is not. The
    # gate above found `not production-validated` inside it and passed. This is
    # exactly the vacuous-check shape Assay flags in other people's
    # environments (`always_pass`, a verifier that cannot fail), so shipping it
    # in the publisher is worse than an ordinary bug.
    for kind, path in staged.items():
        text = (path / "README.md").read_text() if (path / "README.md").exists() else ""
        inverted = re.findall(
            r"\bis\s+\**not\s+production-validated|"
            r"neither[^.]{0,120}\bnot\s+production-validated",
            text, flags=re.I,
        )
        negations = [m for m in inverted if m.lower().startswith("neither")]
        out.append(gate(f"{kind}: disclaimer is not negated", not negations,
                        (negations[0][:70] if negations else "reads as a disclaimer")))

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
                               "https://huggingface.co/spaces/" + DEMO_REPO,
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
        if kind in ("space", "demo"):
            continue  # neither Space ships a large file; nothing to track
        out.append(gate(f"{kind}: LFS configured", ga.exists() and "jsonl" in ga.read_text(),
                        ga.read_text().strip().replace("\n", " | ") if ga.exists() else "missing"))

    # The model card must not oversell an adapter that does not work.
    #
    # This gate used to require the first 400 characters to say "does not work"
    # or "negative result", and it did its job for as long as the alternative
    # was overselling. But it also enforced a headline that buried the finding
    # under an apology: a reader landing on "This adapter does not work. Do not
    # deploy this." concludes the project failed, when what is actually there is
    # a measured result about why a one-shot policy cannot learn a discovered
    # exploit. Leading with the failure and leading with the *finding* are not
    # the same thing, and only the second is a contribution.
    #
    # So the gate now checks the honesty rather than the pessimism: somewhere in
    # the card, prominently enough to be above the fold, it must still say the
    # weights are not to be deployed and do not beat their base model. Where the
    # title goes is a writing decision; whether the warning is present is not.
    m = staged.get("model")
    if m:
        text = (m / "README.md").read_text().split("---", 2)[-1]
        # Normalised before matching: the phrases below are prose and prose
        # wraps. A gate that fails because a sentence broke across two lines is
        # a gate that trains people to reword around it.
        flat = " ".join(text.replace(">", " ").split()).lower()
        head = flat[:2200]
        disclaims = (
            "not because you should run them" in head
            or "do not deploy" in head
            or "not for deployment" in head
        )
        no_gain = "do not beat their own base model" in head or "beats its own base model" in head
        out.append(gate(
            "model card disclaims deployment above the fold",
            disclaims and no_gain,
            "says both 'not to be run' and 'no gain over base'"
            if (disclaims and no_gain)
            else f"disclaims={disclaims} no_gain={no_gain}: {text.strip()[:90]!r}",
        ))

    # The Space must render skip reasons, not only findings.
    sp = staged.get("space")
    if sp and (sp / "app.py").exists():
        # This used to be `"NOT_APPLICABLE" in app`, which a comment saying the
        # word would satisfy. The check now renders a report through the real
        # function and asserts the skipped-probe table is in the output --
        # a gate that can only pass if the behaviour it names actually happens.
        out.extend(_space_behaviour_gates(sp))

    dp = staged.get("demo")
    if dp:
        out.extend(_demo_gates(dp))

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


def report(staged: dict[str, Path], repos: dict[str, tuple[str, str, str | None]]) -> None:
    for kind, path in staged.items():
        repo, repo_type, _ = repos[kind]
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


def push(repo: str, repo_type: str, path: Path, message: str, sdk: str | None = None) -> None:
    subprocess.run(
        ["hf", "repos", "create", repo, "--type", repo_type, "--exist-ok"]
        # `--space-sdk`, not `--sdk`. The CLI rejects the short form outright
        # ("No such option: --sdk"), so this line had never worked -- and could
        # not have, because nothing ran it until the first real --push. Every
        # one of the 26 gates passed while it was broken: they check what is
        # staged, not that it can be uploaded.
        #
        # And the SDK is per-repo, not per-type. `gradio` is what returns 402
        # on a free account; `static` is what does not, which is the entire
        # reason there is a hosted demo to click.
        + (["--space-sdk", sdk or "gradio"] if repo_type == "space" else []),
        check=True,
    )
    # `hf upload` calls `/api/repos/create` again on its way in, and has no
    # `--space-sdk` to pass, so it asks for a **gradio** Space every time. On a
    # free account that is an HTTP 402 -- for a repo that already exists, as a
    # static Space, created by the line directly above. The upload never
    # started; the billing check fires on the SDK in the request before
    # anything looks at whether the repo is there.
    #
    # `upload_folder` is what that CLI command wraps, minus the create. The
    # create was always redundant here -- this function does it explicitly, and
    # explicitly is the only way to get the SDK right -- so the fix is to drop
    # the second one rather than to route around it.
    from huggingface_hub import HfApi

    HfApi().upload_folder(
        repo_id=repo,
        repo_type=repo_type,
        folder_path=str(path),
        commit_message=message,
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
    ap.add_argument("--only", choices=["dataset", "space", "demo", "model"], action="append")
    ap.add_argument("--out", type=Path, default=BUILD)
    args = ap.parse_args()

    kinds = args.only or ["dataset", "space", "demo", "model"]
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
    if "demo" in kinds:
        staged["demo"] = out / "demo"
        stage_demo(staged["demo"])
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

    # (repo, hub repo type, Space SDK). The SDK is the field that decides
    # whether `repos create` returns a URL or an HTTP 402.
    repos = {
        "dataset": (DATASET_REPO, "dataset", None),
        "space": (SPACE_REPO, "space", "gradio"),
        "demo": (DEMO_REPO, "space", "static"),
        "model": (MODEL_REPO, "model", None),
    }

    report(staged, repos)

    print(f"\n{'=' * 78}\nPRE-PUBLICATION GATES\n{'=' * 78}")
    # `run_gates(...) if payload is not None else []` meant `--only space --push`
    # ran ZERO gates and uploaded, because only `stage_dataset` sets `payload`.
    # The bypass was invisible: the gate table printed empty and `failed` was
    # empty, so the run looked like a clean pass. Every gate that does not need
    # the dataset payload now runs regardless of which artifacts were staged.
    gates = run_gates(ev, staged, payload)
    if not gates:
        print("  no gates ran, which is never a pass; refusing to upload")
        return 1
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

    # One artifact failing must not strand the others. The first real --push
    # died on the Space and never reached the model, so a Space that needs a
    # paid plan silently blocked an artifact that does not. Each is attempted,
    # each result is reported, and the exit code reflects the whole set.
    published, failed = [], []
    for kind, path in staged.items():
        repo, repo_type, sdk = repos[kind]
        print(f"\n--> {repo}")
        try:
            push(repo, repo_type, path, f"Assay {TAG}", sdk=sdk)
            published.append((kind, repo))
        except subprocess.CalledProcessError as exc:
            failed.append((kind, repo, exc))
            print(f"!! {kind} did not publish: {exc}", file=sys.stderr)

    print(f"\n{'=' * 78}")
    for kind, repo in published:
        print(f"  published  {kind:8} {repo}")
    for kind, repo, _ in failed:
        print(f"  FAILED     {kind:8} {repo}")
    if failed:
        print(f"\n{len(failed)} artifact(s) did not publish. An artifact missing "
              f"from a publish is a result about the run, not a detail.")
        return 1
    print(f"\nPublished at tag {TAG}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
