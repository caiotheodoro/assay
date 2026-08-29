"""ScienceAgentBench, adapted from what is actually obtainable.

ScienceAgentBench splits into two halves that are not equally reachable. The
per-task metadata -- instruction, dataset tree, declared output path, the name
of the gold program and of the eval script -- is published on the Hub. The
gold programs and the eval scripts themselves are in a password-protected
archive behind a SharePoint link that redirects to a Microsoft login, so no
script can fetch them (see docs/SCIENCEAGENTBENCH.md for the exact URL, the
password, and the drop path).

This adapter therefore has two modes, and it never pretends to be in the one
it is not:

* **metadata-only** (no ``benchmark_root``) -- declares no capabilities at
  all. Every probe comes back NOT_APPLICABLE naming the archive. That is the
  honest result, not a degraded one: eight of Assay's nine families need to
  execute a verifier, and there is no verifier here to execute.
* **eval-programs present** (``benchmark_root`` containing ``eval_programs/``)
  -- unlocks family 6 only. ``verifier_asserts`` can read an eval script off
  disk and report what it checks, which is a static read, no Docker.

Execution capabilities are deliberately never declared, in either mode.
Running SAB's grader means building its per-task Docker image and driving
``compute_scores.py``; this adapter does not do that, so it does not claim
GOLD_TRAJECTORY or SEPARABLE_VERIFIER and the verifier-integrity probes stay
NOT_APPLICABLE rather than silently scoring nothing.

**Redistribution:** nothing from the archive is vendored here or emitted by
this module. Only per-task verdicts, which contain no benchmark content, are
publishable -- see src/assay/publish.py.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..adapter import BaseAdapter, NotSupported
from ..types import Action, Capability, Manifest, Observation, Score, Task, Transcript

#: SAB's own README: "A valid OpenAI API key is required since our evaluation
#: leverages GPT-4o to judge output visualizations." The judge lives in
#: gpt4_visual_judge.py and runs at temperature 0.2 with n=3, so it is not a
#: deterministic function of the transcript. Tasks whose declared output is an
#: image are scored, at least in part, by that judge.
JUDGED_OUTPUT_SUFFIXES = frozenset({".png", ".tif", ".tiff", ".jpg", ".jpeg", ".svg", ".pdf"})


@dataclass(frozen=True)
class SabTask:
    """One ScienceAgentBench instance, as published on the Hub."""

    instance_id: int
    task_inst: str
    output_fname: str
    eval_script_name: str
    gold_program_name: str = ""
    domain: str = ""
    dataset_folder_tree: str = ""

    @property
    def task_id(self) -> str:
        # BenchGuard's gold standard keys tasks by bare integer string.
        return str(self.instance_id)

    @property
    def llm_judged(self) -> bool:
        """Whether SAB scores this task with its GPT-4o visual judge.

        Derived from the declared output suffix, because the eval scripts that
        import the judge are inside the gated archive. This is a proxy and is
        reported as one: the criterion is public and checkable, but the exact
        set is only confirmable against ``benchmark/eval_programs/``.
        """
        return Path(self.output_fname).suffix.lower() in JUDGED_OUTPUT_SUFFIXES


#: The two 102-task splits SAB publishes, and why you would want each.
#:
#: ``verified`` is the one SAB's README tells you to use (2026/04/30, "to
#: mitigate false negatives in evaluation"). ``original`` is the pre-verification
#: CSV. The distinction is load-bearing when scoring against BenchGuard's gold
#: set: nine of BenchGuard's twelve defects are already corrected in the
#: verified split, so a detector run against `verified` is being asked to find
#: defects that are no longer in the text it is reading.
SPLITS = {
    "verified": "data/verified-00000-of-00001.parquet",
    "original": "ScienceAgentBench.csv",
}


def load_tasks_from_hub(
    split: str = "verified", revision: str | None = None
) -> list[SabTask]:
    """Read one of SAB's 102-task splits from the Hub."""
    import pandas as pd  # noqa: PLC0415 - optional dependency, `--extra sab`
    from huggingface_hub import hf_hub_download  # noqa: PLC0415

    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {sorted(SPLITS)}")
    path = hf_hub_download(
        "osunlp/ScienceAgentBench",
        SPLITS[split],
        repo_type="dataset",
        revision=revision,
    )
    frame = pd.read_csv(path) if path.endswith(".csv") else pd.read_parquet(path)
    return [
        SabTask(
            instance_id=int(row.instance_id),
            task_inst=str(row.task_inst),
            output_fname=str(row.output_fname),
            eval_script_name=str(row.eval_script_name),
            gold_program_name=str(row.gold_program_name),
            domain=str(row.domain),
            dataset_folder_tree=str(row.dataset_folder_tree),
        )
        for _, row in frame.iterrows()
    ]


def _comparison_claims(tree: ast.AST) -> list[str]:
    """Render the comparisons an eval script makes as readable claims.

    Family 6 requires assertions derived from the *scorer*, never from the
    instruction -- deriving them from the instruction would make the check
    compare the instruction against itself and pass vacuously. So this reads
    only the eval script's own syntax: `assert` statements, and the
    comparisons that gate what it returns.
    """
    claims: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            claims.append(ast.unparse(node.test))
        elif isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Compare):
            claims.append(ast.unparse(node.test))
    # Stable order, no duplicates: the same claim twice is not two claims.
    seen: dict[str, None] = {}
    for claim in claims:
        seen.setdefault(claim, None)
    return list(seen)


class ScienceAgentBenchAdapter(BaseAdapter):
    """SAB as an Assay environment. See the module docstring for the two modes."""

    def __init__(
        self,
        tasks: list[SabTask],
        benchmark_root: Path | None = None,
        env_version: str = "verified",  # which SPLITS key the tasks came from
    ) -> None:
        self.tasks = list(tasks)
        self.benchmark_root = Path(benchmark_root) if benchmark_root else None
        self.env_version = env_version
        self._by_id = {t.task_id: t for t in self.tasks}

    # -- what is on disk ---------------------------------------------------

    @property
    def eval_programs_dir(self) -> Path | None:
        """``benchmark/eval_programs`` if the gated archive was dropped in."""
        if self.benchmark_root is None:
            return None
        candidate = self.benchmark_root / "eval_programs"
        return candidate if candidate.is_dir() else None

    def missing_archive_reason(self) -> str:
        return (
            "ScienceAgentBench's gold programs and eval scripts are in a "
            "password-protected archive behind a SharePoint link that redirects to a "
            "Microsoft login; no benchmark_root was supplied. See "
            "docs/SCIENCEAGENTBENCH.md for the URL, the password, and the drop path."
        )

    # -- manifest ----------------------------------------------------------

    def manifest(self) -> Manifest:
        return Manifest(
            env_id="osunlp/ScienceAgentBench",
            ecosystem="scienceagentbench",
            version=self.env_version,
            source="https://huggingface.co/datasets/osunlp/ScienceAgentBench",
            tasks=[
                Task(
                    task_id=t.task_id,
                    instruction=t.task_inst,
                    metadata={
                        "domain": t.domain,
                        "output_fname": t.output_fname,
                        "eval_script_name": t.eval_script_name,
                        "gold_program_name": t.gold_program_name,
                        "llm_judged": t.llm_judged,
                    },
                )
                for t in self.tasks
            ],
            # Never any execution capability: this adapter does not build SAB's
            # Docker images, so it cannot honestly claim a separable verifier.
            capabilities=frozenset(),
        )

    # -- episode: not available in either mode -----------------------------

    def reset(self, task_id: str, seed: int = 0) -> Observation:
        raise NotSupported(
            "SAB episodes are a Docker build plus compute_scores.py; this adapter "
            "reads published metadata and does not execute the benchmark"
        )

    def step(self, action: Action) -> Any:
        raise NotSupported("SAB is not steppable through this adapter")

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        raise NotSupported(
            "scoring a SAB task runs its eval script inside the task's Docker image; "
            + self.missing_archive_reason()
        )

    # -- family 6: the one static check the archive unlocks ----------------

    def verifier_asserts(self, task_id: str) -> list[str]:
        task = self._by_id.get(task_id)
        if task is None:
            raise NotSupported(f"unknown task_id {task_id!r}")
        directory = self.eval_programs_dir
        if directory is None:
            raise NotSupported(self.missing_archive_reason())
        script = directory / task.eval_script_name
        if not script.is_file():
            raise NotSupported(
                f"eval script {task.eval_script_name!r} not found under {directory}"
            )
        try:
            tree = ast.parse(script.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            raise NotSupported(
                f"eval script {task.eval_script_name!r} does not parse: {exc}"
            ) from exc
        return _comparison_claims(tree)
