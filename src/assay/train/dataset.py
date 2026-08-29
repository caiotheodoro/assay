"""Prompts to train on: one row per (environment, task).

The row carries the chat prompt the Challenger will see at inference time,
byte-identical, plus the two columns the reward needs to replay what comes
back. Nothing else. In particular no label, no hint, and no marker saying
which environments are the hackable ones -- the model has to find that out by
being paid for it.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..adapter import NotSupported
from ..challenger.grpo import MAX_ACTIONS, chat_prompt, prompt_for
from .reward import EnvPool, EnvSelection, trainable_environments


@dataclass
class PromptSet:
    rows: list[dict[str, Any]]
    #: (env_id, task_id) -> why no prompt could be built for it.
    excluded: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.rows)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.rows:
            out[row["env_id"]] = out.get(row["env_id"], 0) + 1
        return dict(sorted(out.items()))

    def report(self) -> str:
        lines = [f"prompt set: {len(self.rows)} rows"]
        lines += [f"  {env_id}: {n}" for env_id, n in self.counts().items()]
        if self.excluded:
            lines.append("no prompt could be built for:")
            lines += [f"  - {k}: {v}" for k, v in sorted(self.excluded.items())]
        return "\n".join(lines)

    def to_hf(self):
        from datasets import Dataset

        return Dataset.from_list(self.rows)

    def write_jsonl(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for row in self.rows:
                fh.write(json.dumps(row) + "\n")
        return out


def build_prompts(pool: EnvPool, *, max_actions: int = MAX_ACTIONS) -> PromptSet:
    rows: list[dict[str, Any]] = []
    excluded: dict[str, str] = {}
    for env_id in pool.env_ids():
        adapter = pool.get(env_id)
        for task in adapter.manifest().tasks:
            try:
                system, user = prompt_for(adapter, task.task_id, max_actions)
            except NotSupported as exc:
                excluded[f"{env_id}/{task.task_id}"] = str(exc)
                continue
            rows.append(
                {
                    "prompt": chat_prompt(system, user),
                    "env_id": env_id,
                    "task_id": task.task_id,
                }
            )
    return PromptSet(rows=rows, excluded=excluded)


def repeat_and_shuffle(
    prompts: PromptSet, *, target: int, seed: int = 0, balance: str = "env"
) -> PromptSet:
    """Grow the prompt set to `target` rows by cycling it, then shuffle once.

    Cycling before shuffling keeps the mix even at any prefix length, so a run
    cut short by a spot reclaim is still a balanced run rather than whatever the
    shuffle happened to front-load.

    `balance="env"` cycles environments round-robin rather than cycling the flat
    row list, and the difference is not cosmetic. The toy fixtures contribute
    three tasks each and the Harbor fixtures one, so a flat cycle spends ~92% of
    the budget on in-process ticket triage and ~8% on the shell tasks -- and the
    shell tasks are the only place the interesting exploit shape (edit the file
    the verifier reads) exists at all. `balance="row"` is the flat version, kept
    because "every prompt equally" is the right default for a corpus whose
    environments have comparable task counts.
    """
    if not prompts.rows or target <= 0:
        return PromptSet(rows=[], excluded=dict(prompts.excluded))

    if balance == "row":
        grown = [dict(prompts.rows[i % len(prompts.rows)]) for i in range(target)]
    elif balance == "env":
        by_env: dict[str, list[dict[str, Any]]] = {}
        for row in prompts.rows:
            by_env.setdefault(row["env_id"], []).append(row)
        env_ids = sorted(by_env)
        grown = []
        for i in range(target):
            bucket = by_env[env_ids[i % len(env_ids)]]
            grown.append(dict(bucket[(i // len(env_ids)) % len(bucket)]))
    else:
        raise ValueError(f"unknown balance mode: {balance!r} (use 'env' or 'row')")

    random.Random(seed).shuffle(grown)
    return PromptSet(rows=grown, excluded=dict(prompts.excluded))


def training_data(
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    holdout: list[str] | None = None,
    target: int = 0,
    seed: int = 0,
    balance: str = "env",
    max_actions: int = MAX_ACTIONS,
) -> tuple[EnvSelection, PromptSet]:
    """The whole pipeline: pick environments, build prompts, size the set."""
    selection = trainable_environments(only=only, skip=skip, holdout=holdout)
    prompts = build_prompts(selection.pool, max_actions=max_actions)
    if target:
        prompts = repeat_and_shuffle(prompts, target=target, seed=seed, balance=balance)
    return selection, prompts
