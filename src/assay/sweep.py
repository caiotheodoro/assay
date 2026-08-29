"""Sweep published inspect_evals tasks for genuine, unplanted defects.

The corpus in `_inspect_corpus.py` audits environments whose defects this repo
planted itself. That measures the detector. It does not tell you whether the
evals people actually train and publish against are sound. This module points
the same probe battery at `inspect_evals` -- 246 registered `@task` callables
across 129 packages in the installed distribution -- and reports what it finds.

Pointing it there naively would be worse than useless, and the reason is the
whole design of this file.

The problem
-----------
`InspectAdapter` scores by fabricating a `TaskState` that carries the
completion and nothing else, then calling the scorer directly. For a scorer
whose entire world is `(completion, target)` -- `match`, `includes`, `pattern`,
`exact` -- that is exactly faithful. For a scorer that reads sandbox filesystem
state, a tool-call transcript, or `state.store`, it is not faithful and it does
not raise: it returns a degenerate score computed from an empty world. Every
such score looks like a finding. A sweep that reported them would emit
fabricated defect reports against real published benchmarks, which is a worse
outcome for this project than finding nothing at all.

So the filter is a correctness requirement, not a performance optimisation, and
it refuses loudly rather than skipping quietly. Three gates, cheapest first:

1. `static_filter` -- no dataset materialised, no network. Name denylist for
   the known agentic families, container artifacts (`compose.yaml`,
   `values.yaml`, `Dockerfile`) anywhere in the package, and a source-token
   scan of the package for sandbox / store / tool / message / model-judge use.
   Deliberately coarse: it excludes at package granularity, so a package with
   one LLM-graded scorer loses its purely lexical tasks too. Over-exclusion
   costs coverage; under-exclusion costs the truth of every number downstream.

2. `dynamic_filter` -- after materialising, with the real `Task` object in
   hand. `Sample.sandbox`/`files`/`setup` set anywhere in the dataset, and an
   AST gate (`state_reads`) over each scorer's own source establishing that it
   reads only attributes of `TaskState` this adapter actually populates. A
   scorer that passes `state` on to a helper is refused, because this filter
   cannot see through the call.

3. `gold_anchor` -- per item, and the one that makes the results trustworthy.
   Submit the sample's own declared target as the completion. If the scorer
   marks it correct, this adapter is demonstrably speaking that scorer's answer
   protocol well enough for it to recognise a right answer, and any subsequent
   "the scorer accepted something it should not have" on that item is a
   statement about the eval. If gold does *not* pass, a broken eval and a
   mis-fitted probe are indistinguishable from here, so the item is dropped and
   counted under `gold_unverified` -- never reported as `GOLD_FAILS`.

Gate 3 is asymmetric on purpose. It makes `GOLD_FAILS` unreportable in the
wild, which is a real loss, and makes everything it does report resistant to
the fabrication mode above.

Scope
-----
Only tasks whose source lives under `inspect_evals/` are in scope. The
`register/` entries the project added since May 2026 are YAML pointers to
third-party repositories; they are not Python, not importable, and are not
shipped in the installed wheel at all -- `installed_scope()` states this and
checks it rather than asserting it.

Cost
----
Importing `inspect_evals._registry` is network-free. *Calling* a task factory
materialises `.dataset` and hits the HF Hub, so a fully offline sweep is
impossible. Budget one network hit per task; `DatasetCache` makes re-runs and
triage free.
"""

from __future__ import annotations

import ast
import inspect as pyinspect
import json
import pathlib
import random
import re
import signal
import sys
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from .adapters.inspect_ai_adapter import ANSWER_TOOL, InspectAdapter
from .types import Action, Capability, Score, Transcript

# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------

#: Task factories whose source is not under this package are not swept.
PACKAGE = "inspect_evals"


def installed_scope() -> dict[str, Any]:
    """What the installed distribution actually contains, checked not assumed.

    The claim being checked is that `register/` is out of scope because it is
    not here: it is a repo-level directory of YAML pointers to third-party
    repositories, and the wheel ships only the Python evals under `src/`. A
    reader who upgrades `inspect_evals` and finds `register_dir_present: true`
    knows this file's scope statement has gone stale.
    """
    import inspect_evals

    root = pathlib.Path(inspect_evals.__file__).parent
    return {
        "package_root": str(root),
        "eval_packages": sorted(
            p.name for p in root.iterdir() if p.is_dir() and p.name != "__pycache__"
        ),
        "register_dir_present": (root / "register").exists(),
        "yaml_pointer_files": sorted(str(p.relative_to(root)) for p in root.glob("register/*.y*ml")),
    }


# --------------------------------------------------------------------------
# Enumeration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskRef:
    """One registered `@task` callable, located but not called."""

    name: str
    package: str
    source_file: str
    factory: Callable[..., Any] = field(repr=False, compare=False)


def _unwrap(fn: Any, limit: int = 20) -> Any:
    for _ in range(limit):
        inner = getattr(fn, "__wrapped__", None)
        if inner is None:
            return fn
        fn = inner
    return fn


def _registered_task_objects() -> list[tuple[str, Any]]:
    import inspect_evals._registry as registry
    from inspect_ai._util.registry import is_registry_object, registry_info

    out = []
    for name in sorted(dir(registry)):
        if name.startswith("_"):
            continue
        obj = getattr(registry, name)
        if callable(obj) and is_registry_object(obj) and registry_info(obj).type == "task":
            out.append((name, obj))
    return out


def out_of_scope_tasks() -> list[Exclusion]:
    """Registered tasks whose source is not under `inspect_evals/`.

    Expected to be empty for a released wheel. Non-empty means the installed
    distribution grew a task defined elsewhere, and the scope statement at the
    top of this file needs rewriting before the numbers below mean anything.
    """
    import inspect_evals

    root = pathlib.Path(inspect_evals.__file__).parent
    out = []
    for name, obj in _registered_task_objects():
        try:
            src = pathlib.Path(pyinspect.getsourcefile(_unwrap(obj)) or "")
            src.relative_to(root)
        except (TypeError, OSError, ValueError) as exc:
            out.append(
                Exclusion(
                    name,
                    "?",
                    "scope",
                    "out_of_package",
                    f"task source is not under {PACKAGE}/: {type(exc).__name__}: {exc}",
                )
            )
    return out


def enumerate_tasks() -> list[TaskRef]:
    """Every `@task` in `inspect_evals._registry`, located by source file.

    Import only -- no factory is called, so this is free and offline.
    """
    import inspect_evals

    root = pathlib.Path(inspect_evals.__file__).parent
    refs: list[TaskRef] = []
    for name, obj in _registered_task_objects():
        try:
            src = pathlib.Path(pyinspect.getsourcefile(_unwrap(obj)) or "")
            rel = src.relative_to(root)
        except (TypeError, OSError, ValueError):
            # Source outside `inspect_evals/`, or unavailable. Out of scope by
            # definition, and reported by `out_of_scope_tasks()` rather than
            # dropped -- a task that vanished from the sweep without a reason is
            # the failure mode this whole file exists to prevent.
            continue
        refs.append(
            TaskRef(
                name=name,
                package=rel.parts[0] if len(rel.parts) > 1 else rel.stem,
                source_file=str(rel),
                factory=obj,
            )
        )
    return refs


# --------------------------------------------------------------------------
# Gate 1 -- static filter
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Exclusion:
    """A task that was not swept, and exactly why.

    An excluded task is a reported result, not a silent gap: absence of
    evidence is stated as loudly as evidence.
    """

    task: str
    package: str
    gate: str
    rule: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "task": self.task,
            "package": self.package,
            "gate": self.gate,
            "rule": self.rule,
            "reason": self.reason,
        }


#: Packages named in the audit brief as agentic or tool-using, plus the prefix
#: families. These would be caught by the token scan anyway; naming them makes
#: the exclusion legible instead of incidental, and survives a refactor of the
#: package that drops a token.
DENY_PACKAGES = frozenset(
    {
        "agentdojo",
        "agentharm",
        "agent_bench",
        "agentic_misalignment",
        "agent_threat_bench",
        "b3",
        "core_bench",
        "cve_bench",
        "cybench",
        "gaia",
    }
)

#: Package name prefixes with the same status.
DENY_PREFIXES = ("gdm_", "agent_", "cyberseceval_")

#: Files whose presence means the package expects a container runtime.
CONTAINER_ARTIFACTS = frozenset(
    {
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
        "Dockerfile",
        "values.yaml",
        "helm-values.yaml",
    }
)

#: Source tokens that mean a scorer or solver in this package reaches for a
#: world the fabricated `TaskState` does not have. Regexes, matched against the
#: concatenated Python source of the package.
RISK_TOKENS: dict[str, tuple[str, ...]] = {
    "sandbox": (
        r"\bsandbox\s*\(",
        r"\bSandboxEnvironment\b",
        r"\bsandbox\s*=",
        r"\bsandbox_agent\b",
    ),
    "store": (
        r"\bstate\.store\b",
        r"\bstore_as\s*\(",
        r"\bStoreModel\b",
    ),
    "tools": (
        r"\buse_tools\s*\(",
        r"\bbasic_agent\s*\(",
        r"\breact\s*\(",
        r"@tool\b",
        r"\bToolCall\b",
        r"\bbash\s*\(",
        r"\bweb_search\s*\(",
        r"\bhandoff\s*\(",
    ),
    "transcript": (
        r"\bstate\.messages\b",
        r"\bstate\.output\.message\b",
    ),
    "model_judge": (
        r"\bmodel_graded_qa\b",
        r"\bmodel_graded_fact\b",
        r"\bget_model\s*\(",
        r"\bmodel\.generate\b",
    ),
    "multimodal": (
        r"\bContentImage\b",
        r"\bContentAudio\b",
        r"\bContentVideo\b",
        r"\bContentPdf\b",
    ),
}

_RISK_REASON = {
    "sandbox": "package uses a sandbox; a scorer reading sandbox filesystem state "
    "would be handed an empty world and would score a degenerate result",
    "store": "package uses state.store, which the fabricated TaskState leaves empty",
    "tools": "package is agentic or tool-using; there is no tool transcript to score",
    "transcript": "package scores state.messages, which the fabricated TaskState "
    "leaves empty",
    "model_judge": "package grades with a model; no LLM judge scores anything in "
    "this project, and a judge is not a deterministic oracle",
    "multimodal": "package builds samples with non-text content; the sweep does "
    "not pull image, audio or video corpora. This is a cost exclusion and is "
    "labelled as one -- the audit itself would lose nothing, because a "
    "completion-only scorer never reads the image -- but pulling tens of "
    "gigabytes to discard them is not a cost this sweep takes. Two runs stalled "
    "on docvqa and mmiu before this rule existed",
}


def package_signals(package: str) -> dict[str, Any]:
    """Container artifacts and risk tokens found anywhere in a package.

    Package granularity, not task granularity. A package that ships one
    sandboxed task loses its lexical ones too. That is the intended trade: a
    coverage loss is recorded and recoverable, a fabricated finding against a
    published benchmark is not.
    """
    import inspect_evals

    root = pathlib.Path(inspect_evals.__file__).parent
    directory = root / package
    if directory.is_dir():
        py_files = sorted(directory.rglob("*.py"))
        artifacts = sorted(
            str(p.relative_to(root))
            for p in directory.rglob("*")
            if p.name in CONTAINER_ARTIFACTS
        )
    else:
        py_files = [root / f"{package}.py"]
        artifacts = []
    blob = "\n".join(p.read_text(errors="ignore") for p in py_files if p.exists())
    tokens = {
        kind: sorted({m.group(0) for pat in pats for m in re.finditer(pat, blob)})
        for kind, pats in RISK_TOKENS.items()
    }
    return {
        "container_artifacts": artifacts,
        "risk_tokens": {k: v for k, v in tokens.items() if v},
        "n_python_files": len(py_files),
    }


def static_filter(refs: list[TaskRef]) -> tuple[list[TaskRef], list[Exclusion]]:
    """Gate 1. Offline, no dataset materialised, no network."""
    kept: list[TaskRef] = []
    excluded: list[Exclusion] = []
    cache: dict[str, dict[str, Any]] = {}

    for ref in refs:
        if ref.package in DENY_PACKAGES or ref.package.startswith(DENY_PREFIXES):
            excluded.append(
                Exclusion(
                    ref.name,
                    ref.package,
                    "static",
                    "denied_package",
                    f"package {ref.package!r} is a named agentic or tool-using "
                    "benchmark; its scorers read a transcript or a sandbox, neither "
                    "of which this adapter can reconstruct",
                )
            )
            continue

        signals = cache.setdefault(ref.package, package_signals(ref.package))
        if signals["container_artifacts"]:
            excluded.append(
                Exclusion(
                    ref.name,
                    ref.package,
                    "static",
                    "container_artifact",
                    "package ships a container/k8s definition ("
                    + ", ".join(signals["container_artifacts"][:3])
                    + "); it expects a Docker or k8s sandbox this sweep does not run",
                )
            )
            continue

        risky = signals["risk_tokens"]
        if risky:
            kind = sorted(risky)[0]
            excluded.append(
                Exclusion(
                    ref.name,
                    ref.package,
                    "static",
                    f"risk_token:{kind}",
                    _RISK_REASON[kind]
                    + f" (matched {sorted(risky[kind])[:4]} in package {ref.package!r})",
                )
            )
            continue

        kept.append(ref)
    return kept, excluded


# --------------------------------------------------------------------------
# Gate 2 -- the scorer AST gate
# --------------------------------------------------------------------------

#: `TaskState` attributes this adapter populates from the real `Sample`, so a
#: scorer reading them is reading something true. Everything else -- `store`,
#: `messages`, `scores`, `tools` -- is left empty by construction, and a scorer
#: that reads it is scoring an empty world.
POPULATED_STATE_ATTRS = frozenset(
    {
        "state.output.completion",
        "state.input",
        "state.input_text",
        "state.user_prompt",
        "state.metadata",
        "state.sample_id",
        "state.epoch",
        "state.model",
        "state.target",
    }
)

#: Populated only when the task's own solver is `inspect_ai/multiple_choice`,
#: because only then can the real solver's answer-parsing step be replayed to
#: set it. See `MULTIPLE_CHOICE`.
CHOICES_ATTR = "state.choices"


class StateEscapes(Exception):
    """The scorer hands `state` to a helper this filter cannot see through."""


def unsafe_reads(reads: set[str], allowed: frozenset[str]) -> list[str]:
    """Attribute chains that reach outside what this adapter populates.

    Prefix-closed downward: `state.output.completion.strip` is safe because
    `state.output.completion` is, and reaching further into a string cannot
    reach anything else. `state.output` on its own is not safe, because from
    there `.message` reaches the tool calls. So the check is on the prefix, and
    the reported path stays the maximal chain the scorer actually wrote.
    """
    return sorted(
        chain
        for chain in reads
        if not any(chain == ok or chain.startswith(ok + ".") for ok in allowed)
    )


def state_reads(fn: Any) -> set[str]:
    """Attribute paths the scorer reads off its `TaskState` argument.

    AST over the scorer's own source. Maximal chains only, so
    `state.output.completion` is reported as itself and not also as
    `state.output` -- the distinction matters, because reading the whole
    `output` object reaches `.message` and therefore tool calls.

    Raises `StateEscapes` if `state` is passed anywhere as a bare value. This
    filter reads one function; it does not follow calls, so a scorer that
    forwards `state` is refused rather than guessed at.
    """
    src = textwrap.dedent(pyinspect.getsource(fn))
    tree = ast.parse(src)

    func = next(
        (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
        None,
    )
    if func is None:
        raise StateEscapes("scorer source contains no function definition to analyse")

    args = func.args.posonlyargs + func.args.args
    state_name = next(
        (
            a.arg
            for a in args
            if isinstance(a.annotation, ast.Name) and a.annotation.id == "TaskState"
        ),
        args[0].arg if args else None,
    )
    if state_name is None:
        raise StateEscapes("scorer takes no positional TaskState argument")

    reads: set[str] = set()

    def chain(node: ast.AST) -> str | None:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name) and node.id == state_name:
            return ".".join(["state", *reversed(parts)])
        return None

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Attribute):
            path = chain(node)
            if path is not None:
                reads.add(path)
                return  # whole chain accounted for; do not descend
        elif isinstance(node, ast.Name) and node.id == state_name:
            raise StateEscapes(
                f"scorer passes {state_name!r} on as a bare value; this filter "
                "reads one function and cannot see what the callee touches"
            )
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in func.body:
        visit(stmt)
    return reads


def scorer_functions(task: Any) -> list[Any]:
    scorers = task.scorer if isinstance(task.scorer, list) else [task.scorer]
    return [s for s in scorers if s is not None]


def scorer_name(fn: Any) -> str:
    return getattr(fn, "__qualname__", None) or repr(fn)


#: Solver steps whose whole effect is on the prompt, or whose post-generation
#: step this sweep replays. Anything else changes what `state.output.completion`
#: *is* -- `air_bench` injects an `annotate()` solver that replaces the prompt
#: with a judge template and regenerates, so the completion its scorer reads is
#: an LLM annotator's verdict, not the model's answer. The scorer passes the AST
#: gate cleanly and auditing it would be auditing a judge, which this project
#: does not do. Found by running the sweep: the gold anchor caught it and
#: reported INCONCLUSIVE, but a reason at the filter beats a refusal downstream.
REPLAYABLE_SOLVERS = frozenset(
    {
        "inspect_ai/generate",
        "inspect_ai/multiple_choice",
        "inspect_ai/system_message",
        "inspect_ai/user_message",
        "inspect_ai/prompt_template",
        "inspect_ai/chain_of_thought",
    }
)


def solver_registry_names(task: Any) -> list[str]:
    """Registry names of the task's solver steps, for protocol detection."""
    from inspect_ai._util.registry import is_registry_object, registry_info

    solver = task.solver
    steps = getattr(solver, "_solvers", None)
    if steps is None:
        steps = solver if isinstance(solver, list) else [solver]
    names = []
    for step in steps:
        if is_registry_object(step):
            names.append(registry_info(step).name)
    return names


# --------------------------------------------------------------------------
# Answer protocols
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AnswerProtocol:
    """How a competent model's completion would carry an answer for this task.

    Not a guess about the model: a replay of the step the task's *own* solver
    performs after generation. `RAW` is the null protocol -- the completion is
    the answer, which is what `match`/`pattern`/`includes` scorers assume.
    `MULTIPLE_CHOICE` formats the answer the way `inspect_ai`'s
    `SINGLE_ANSWER_TEMPLATE` asks for it and then calls `inspect_ai`'s own
    `parse_answers` and `set_choices_based_on_generated_response`, so the
    `Choices` object the scorer reads is built by the library, not by this file.

    Recorded per task in the sweep output. A reader who distrusts a protocol
    can see exactly which one produced a finding.
    """

    name: str
    render: Callable[[str], str]
    #: Applied to the fabricated TaskState after `output` is set.
    prepare: Callable[[Any], None] | None = None
    #: State attributes this protocol makes faithful, on top of the base set.
    grants: frozenset[str] = frozenset()


def _mc_prepare(state: Any) -> None:
    """Replay exactly the two calls `multiple_choice` makes after generation.

    `multiple_correct=False` is not a default chosen here -- `detect_protocol`
    refuses the task unless the solver's own closure says so, because a
    multi-answer task scored as single-answer would silently mark every gold
    answer wrong and look like a broken benchmark.
    """
    from inspect_ai.solver._multiple_choice import (
        parse_answers,
        set_choices_based_on_generated_response,
    )

    set_choices_based_on_generated_response(state, parse_answers(state, False))


RAW = AnswerProtocol(name="raw", render=lambda target: target)

MULTIPLE_CHOICE = AnswerProtocol(
    name="multiple_choice",
    render=lambda target: f"ANSWER: {target}",
    prepare=_mc_prepare,
    grants=frozenset({CHOICES_ATTR}),
)


class UnknownProtocol(Exception):
    """The task's answer protocol could not be read off the task itself."""


def solver_closure_value(task: Any, name: str) -> Any:
    """Read a keyword the task passed to its own solver, out of the closure.

    Used instead of assuming a default. If the value is not there to be read,
    the caller refuses the task rather than picking one.
    """
    solver = task.solver
    steps = getattr(solver, "_solvers", None)
    if steps is None:
        steps = solver if isinstance(solver, list) else [solver]
    for step in steps:
        code = getattr(step, "__code__", None)
        cells = getattr(step, "__closure__", None)
        if code is None or cells is None:
            continue
        if name in code.co_freevars:
            return cells[code.co_freevars.index(name)].cell_contents
    raise UnknownProtocol(
        f"solver does not expose {name!r} in its closure, so its value cannot be "
        "read off the task and will not be assumed"
    )


def detect_protocol(task: Any) -> AnswerProtocol:
    """The answer protocol the task's own solver establishes. Never guessed."""
    if "inspect_ai/multiple_choice" not in solver_registry_names(task):
        return RAW
    multiple_correct = solver_closure_value(task, "multiple_correct")
    if multiple_correct:
        raise UnknownProtocol(
            "task uses multiple_choice(multiple_correct=True); the adapter's "
            "single-target answer model cannot express a multi-letter gold answer, "
            "so every gold would score wrong for a reason that is not the eval's"
        )
    return MULTIPLE_CHOICE


def dynamic_filter(ref: TaskRef, task: Any) -> tuple[AnswerProtocol | None, Exclusion | None]:
    """Gate 2. The materialised `Task` in hand; still no scoring performed."""
    samples = list(task.dataset)
    if not samples:
        return None, Exclusion(
            ref.name, ref.package, "dynamic", "empty_dataset", "task materialised zero samples"
        )

    for attr, why in (
        ("sandbox", "requires a sandbox environment per sample"),
        ("files", "ships per-sample files that only exist inside a sandbox"),
        ("setup", "runs a per-sample setup script inside a sandbox"),
    ):
        offenders = [str(s.id) for s in samples if getattr(s, attr, None)]
        if offenders:
            return None, Exclusion(
                ref.name,
                ref.package,
                "dynamic",
                f"sample_{attr}",
                f"{len(offenders)} of {len(samples)} samples set Sample.{attr}: the task "
                f"{why}, so any score computed without one is degenerate",
            )

    multi = [
        str(s.id)
        for s in samples
        if isinstance(s.target, list) and len(s.target) > 1
    ]
    if multi:
        return None, Exclusion(
            ref.name,
            ref.package,
            "dynamic",
            "multi_target",
            f"{len(multi)} of {len(samples)} samples declare more than one target; "
            "the adapter scores against target[0] and would silently discard the "
            "rest, so a gold answer could be marked wrong for a reason that is not "
            "the eval's",
        )

    steps = solver_registry_names(task)
    unreplayable = sorted(set(steps) - REPLAYABLE_SOLVERS)
    if unreplayable or not steps:
        return None, Exclusion(
            ref.name,
            ref.package,
            "dynamic",
            "unreplayable_solver",
            f"solver chain is {steps or '[unregistered]'}; this sweep replays only "
            f"{sorted(REPLAYABLE_SOLVERS)}. A step outside that set changes what "
            "state.output.completion holds by the time the scorer sees it -- an "
            "annotator solver makes it an LLM judge's verdict rather than the "
            "model's answer -- so the completion this adapter submits is not the "
            "thing the scorer grades",
        )

    try:
        protocol = detect_protocol(task)
    except UnknownProtocol as exc:
        return None, Exclusion(
            ref.name, ref.package, "dynamic", "unknown_answer_protocol", str(exc)
        )
    allowed = POPULATED_STATE_ATTRS | protocol.grants

    fns = scorer_functions(task)
    if not fns:
        return None, Exclusion(
            ref.name, ref.package, "dynamic", "no_scorer", "task declares no scorer to audit"
        )
    if len(fns) > 1:
        # Several scorers get averaged by the adapter, which is a judgement
        # about how to combine them that this sweep has no basis to make.
        return None, Exclusion(
            ref.name,
            ref.package,
            "dynamic",
            "multiple_scorers",
            f"task declares {len(fns)} scorers ({[scorer_name(f) for f in fns]}); "
            "combining them into one reward is a weighting decision this sweep "
            "cannot make on the suite's behalf",
        )

    for fn in fns:
        try:
            reads = state_reads(fn)
        except StateEscapes as exc:
            return None, Exclusion(
                ref.name, ref.package, "dynamic", "state_escapes",
                f"scorer {scorer_name(fn)}: {exc}",
            )
        except (OSError, TypeError, SyntaxError) as exc:
            return None, Exclusion(
                ref.name, ref.package, "dynamic", "scorer_source_unavailable",
                f"scorer {scorer_name(fn)} source could not be read for analysis: "
                f"{type(exc).__name__}: {exc}",
            )
        unsafe = unsafe_reads(reads, allowed)
        if unsafe:
            return None, Exclusion(
                ref.name,
                ref.package,
                "dynamic",
                "unpopulated_state_read",
                f"scorer {scorer_name(fn)} reads {unsafe}, which the fabricated "
                "TaskState leaves empty; the score it returns would be computed "
                f"from an empty world (protocol={protocol.name})",
            )

    return protocol, None


# --------------------------------------------------------------------------
# The wild adapter
# --------------------------------------------------------------------------

#: Marks an action whose payload is an option label / answer string that the
#: answer protocol should format. Trivial policies that decline to answer are
#: deliberately left unformatted: rendering "I cannot determine the answer."
#: into "ANSWER: I cannot determine the answer." would manufacture a
#: protocol-conformant answer out of a non-answer, and the resulting score
#: would be an artifact of this file rather than a property of the eval.
AS_ANSWER = "assay_as_answer"


class WildInspectAdapter(InspectAdapter):
    """`InspectAdapter` over a real published task, speaking its answer protocol.

    Two differences from the corpus adapter, both forced by real evals:

    * the completion is rendered through the task's `AnswerProtocol` and the
      solver's post-generation step is replayed, so a `choice()` scorer sees the
      `Choices` object `inspect_ai` itself would have built;
    * `sample.metadata` is passed through to the `TaskState`, because it is
      genuinely available from the sample and several real scorers read it.

    Capabilities are unchanged: the wild sweep supplies no train split, so the
    contamination and shortcut probes report NOT_APPLICABLE rather than
    comparing the eval split against itself.
    """

    def __init__(self, task: Any, *, protocol: AnswerProtocol = RAW, **kwargs: Any) -> None:
        super().__init__(task, **kwargs)
        self.protocol = protocol

    # -- protocol-aware scoring -------------------------------------------

    def _score_with(self, sample, answer: str, target_text: str) -> Score:
        from inspect_ai.model import ModelOutput
        from inspect_ai.scorer import Target
        from inspect_ai.solver import TaskState

        state = TaskState(
            model="assay/probe",
            sample_id=sample.id,
            epoch=1,
            input=sample.input,
            messages=[],
            choices=sample.choices,
            metadata=dict(sample.metadata or {}),
            output=ModelOutput.from_content(model="assay/probe", content=answer),
        )
        if self.protocol.prepare is not None:
            self.protocol.prepare(state)

        target = Target(target_text)

        import asyncio

        from .adapters.inspect_ai_adapter import _reward

        async def run_all():
            return [await fn(state, target) for fn in self._scorers]

        scores = asyncio.run(run_all())
        rewards = [_reward(s.value) for s in scores]
        reward = sum(rewards) / len(rewards) if rewards else 0.0
        return Score(
            passed=reward >= self._pass_threshold,
            reward=reward,
            profile={
                "completion": answer,
                "target": target_text,
                "protocol": self.protocol.name,
                "per_scorer": [
                    {"scorer": scorer_name(fn), "value": s.value}
                    for fn, s in zip(self._scorers, scores)
                ],
            },
        )

    @staticmethod
    def _last_answer(transcript: Transcript) -> tuple[str, bool]:
        for action in reversed(transcript.actions):
            if action.tool == ANSWER_TOOL:
                return str(action.args.get("answer", "")), bool(action.args.get(AS_ANSWER))
        return "", False

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        sample = self._sample(transcript.task_id)
        target_text = str(spec) if spec is not None else self._target_text(sample)
        raw, formatted = self._last_answer(transcript)
        completion = self.protocol.render(raw) if formatted else raw
        return self._score_with(sample, completion, target_text)

    def true_completion(self, transcript: Transcript) -> float:
        """Exact match on the declared target, independent of the suite's scorer.

        Compares the *raw* answer, before protocol formatting, so the ground
        truth stays a statement about the answer and not about the wrapper.
        """
        from .adapters.inspect_ai_adapter import _normalise

        sample = self._sample(transcript.task_id)
        raw, _ = self._last_answer(transcript)
        return 1.0 if _normalise(raw) == _normalise(self._target_text(sample)) else 0.0

    # -- protocol-formatted policies --------------------------------------

    def _answer_action(self, text: str) -> list[Action]:
        return [Action(ANSWER_TOOL, {"answer": text, AS_ANSWER: True})]

    def gold_actions(self, task_id: str) -> list[Action]:
        return self._answer_action(self._target_text(self._sample(task_id)))

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        return self._answer_action(str(self.invert_spec(task_id)))

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        return {
            "strong": self.gold_actions(task_id),
            "weak": self.known_wrong_actions(task_id),
        }

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        """`majority_class` is protocol-formatted -- it is a real answer, just
        an input-ignoring one. The abstain and escalate policies are not: a
        model that declines to answer emits no answer in any protocol."""
        from collections import Counter

        targets = [self._target_text(s) for s in self._samples]
        majority = Counter(targets).most_common(1)[0][0] if targets else ""
        return {
            "always_abstain": [],
            "always_escalate": [
                Action(ANSWER_TOOL, {"answer": "I cannot determine the answer."})
            ],
            "majority_class": self._answer_action(majority),
        }


# --------------------------------------------------------------------------
# Gate 3 -- the gold anchor
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    anchored: list[str]
    unverified: list[str]
    detail: dict[str, dict[str, Any]]

    @property
    def rate(self) -> float:
        total = len(self.anchored) + len(self.unverified)
        return len(self.anchored) / total if total else 0.0


def gold_anchor(adapter: WildInspectAdapter) -> Anchor:
    """Which sampled items this adapter can demonstrably score correctly.

    An item is anchored when submitting its own declared target as the
    completion is marked correct by the suite's own scorer. That is the proof
    that the fabricated `TaskState` and the answer protocol are faithful enough
    for *this* scorer on *this* item -- without it, a subsequent "the scorer
    accepted a wrong answer" could equally be "the scorer never understood any
    of our answers", and the two are not distinguishable from here.
    """
    anchored, unverified, detail = [], [], {}
    for task in adapter.manifest().tasks:
        actions = adapter.gold_actions(task.task_id)
        transcript = Transcript(task_id=task.task_id, seed=0)
        for action in actions:
            transcript.record(action, adapter.step(action))
        score = adapter.verify(transcript)
        detail[task.task_id] = {
            "gold_completion": score.profile.get("completion"),
            "target": score.profile.get("target"),
            "reward": score.reward,
            "passed": score.passed,
        }
        (anchored if score.passed else unverified).append(task.task_id)
    return Anchor(anchored=anchored, unverified=unverified, detail=detail)


# --------------------------------------------------------------------------
# Materialisation, with a cache and a wall clock
# --------------------------------------------------------------------------


class Timeout(Exception):
    pass


def sweep_task_isolated(
    ref: TaskRef,
    *,
    n_samples: int = 25,
    seed: int = 0,
    timeout: int = 300,
    python: str | None = None,
) -> TaskSweep:
    """Run one task's sweep in a child process with a timeout that actually holds.

    The first version bounded materialisation with `signal.alarm`. It does not
    work: a task whose factory pulls a multi-gigabyte multimodal dataset sits
    inside `datasets`' C-level download and never reaches a Python bytecode
    boundary where the handler could run. `docvqa` took the cache past 18 GB
    with the 240 s budget nominally in force.

    A child process can be killed regardless of what it is blocked in, so the
    budget is enforced by `subprocess` and the whole process *group* is torn
    down -- `datasets` spawns workers, and killing only the parent leaves them
    downloading. `TaskSweep` is plain data, so the result crosses the boundary
    as JSON. Isolation also means a task that segfaults or calls `sys.exit`
    costs one row, not the sweep.
    """
    import os
    import subprocess

    code = (
        "import json,sys;"
        "from assay.sweep import enumerate_tasks, sweep_task;"
        "ref=[r for r in enumerate_tasks() if r.name==sys.argv[1]][0];"
        "print('<<<ASSAY>>>'+json.dumps(sweep_task("
        "ref, n_samples=int(sys.argv[2]), seed=int(sys.argv[3]), timeout=0"
        ").to_dict(), default=str))"
    )
    argv = [python or sys.executable, "-c", code, ref.name, str(n_samples), str(seed)]
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**os.environ, "HF_HUB_DISABLE_PROGRESS_BARS": "1"},
    )
    try:
        out, err = proc.communicate(timeout=timeout if timeout > 0 else None)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.communicate()
        return TaskSweep(
            task=ref.name,
            package=ref.package,
            source_file=ref.source_file,
            status="EXCLUDED",
            reason=(
                f"materialisation_timeout: the task did not materialise within "
                f"{timeout}s and its process group was killed. A gated dataset "
                "waiting on credentials, and a dataset too large to pull for an "
                "audit, both present exactly this way"
            ),
            seconds=round(time.monotonic() - started, 2),
        )

    marker = "<<<ASSAY>>>"
    if marker in out:
        payload = json.loads(out.split(marker, 1)[1].splitlines()[0])
        result = TaskSweep(**payload)
        result.seconds = round(time.monotonic() - started, 2)
        return result

    return TaskSweep(
        task=ref.name,
        package=ref.package,
        source_file=ref.source_file,
        status="ERROR",
        reason=(
            f"child process exited {proc.returncode} without a result; "
            f"last stderr: {(err or '').strip().splitlines()[-1] if err.strip() else '(empty)'}"
        )[:600],
        seconds=round(time.monotonic() - started, 2),
    )


def deterministic_task_args(factory: Any) -> dict[str, Any]:
    """Arguments that pin the task's dataset order, where the task allows it.

    Roughly 35 `inspect_evals` task factories take `shuffle: bool = True` and
    pass it on without a seed, so two identical calls return different sample
    orders. That is not hypothetical here: two runs of this sweep at the same
    `--seed 0` reported 18 and then 17 findings on `paws`, because
    `sample_indices` is deterministic but the list it indexes into was not.

    Passing `shuffle=False` where the factory accepts it makes the sweep
    reproducible. It is a deviation from the task's default configuration and
    is recorded per task in `task_args` rather than applied silently -- the
    audit is about the scorer, and the sample set is a subsample either way,
    but a reader should not have to infer that.
    """
    try:
        params = pyinspect.signature(_unwrap(factory)).parameters
    except (TypeError, ValueError):
        return {}
    return {"shuffle": False} if "shuffle" in params else {}


def sample_indices(n_total: int, n_want: int, seed: int) -> list[int]:
    """Deterministic subsample. Same seed, same items, so triage is repeatable."""
    if n_total <= n_want:
        return list(range(n_total))
    return sorted(random.Random(seed).sample(range(n_total), n_want))


def subsample(task: Any, n: int, seed: int) -> Any:
    """A copy of the task over a deterministic subsample of its dataset."""
    from inspect_ai.dataset import MemoryDataset

    samples = list(task.dataset)
    picked = [samples[i] for i in sample_indices(len(samples), n, seed)]
    task.dataset = MemoryDataset(picked, name=getattr(task.dataset, "name", None))
    return task


# --------------------------------------------------------------------------
# Per-task sweep
# --------------------------------------------------------------------------


@dataclass
class TaskSweep:
    """Everything the sweep learned about one task, findings or not."""

    task: str
    package: str
    source_file: str
    status: str
    reason: str | None = None
    protocol: str | None = None
    dataset_name: str | None = None
    #: Non-default arguments passed to the task factory, and why. Empty for
    #: tasks whose dataset order is already fixed.
    task_args: dict[str, Any] = field(default_factory=dict)
    n_dataset: int | None = None
    n_sampled: int | None = None
    n_anchored: int | None = None
    n_gold_unverified: int | None = None
    gold_unverified_examples: list[dict[str, Any]] = field(default_factory=list)
    scorers: list[str] = field(default_factory=list)
    state_reads: list[str] = field(default_factory=list)
    verdict: str | None = None
    coverage: dict[str, int] = field(default_factory=dict)
    #: Probes that ran to completion and found nothing. Without this list a
    #: zero-finding result is unreadable: it looks identical whether five
    #: probes ran and passed or all of them reported NOT_APPLICABLE.
    probes_passed: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    not_applicable: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def sweep_task(
    ref: TaskRef,
    *,
    n_samples: int = 25,
    seed: int = 0,
    timeout: int = 300,
    task_args: dict[str, Any] | None = None,
) -> TaskSweep:
    """Materialise, filter, anchor, and audit one task.

    Never raises. A crash mid-sweep is recorded as an ERROR row with the
    traceback's first line, because a sweep that died on task 40 of 75 and
    reported the first 39 as the whole picture would be the same silent-gap
    failure this file exists to prevent.
    """
    try:
        return _sweep_task(
            ref, n_samples=n_samples, seed=seed, timeout=timeout, task_args=task_args
        )
    except Exception as exc:  # noqa: BLE001 - a crash is a reportable outcome
        return TaskSweep(
            task=ref.name,
            package=ref.package,
            source_file=ref.source_file,
            status="ERROR",
            reason=f"sweep crashed: {type(exc).__name__}: {exc}"[:600],
        )


def _sweep_task(
    ref: TaskRef,
    *,
    n_samples: int,
    seed: int,
    timeout: int,
    task_args: dict[str, Any] | None,
) -> TaskSweep:
    from . import audit
    from .types import ProbeStatus

    out = TaskSweep(task=ref.name, package=ref.package, source_file=ref.source_file, status="")
    args = dict(task_args) if task_args is not None else deterministic_task_args(ref.factory)
    out.task_args = args
    started = time.monotonic()
    try:
        task = ref.factory(**args)
    except BaseException as exc:  # noqa: BLE001 - the cause is the result
        # A missing optional dependency and an unreachable dataset are different
        # coverage losses with different fixes, and a reader chasing either needs
        # to know which it was. `ifeval` raises AssertionError("please install
        # the optional dependency ..."), not ImportError, so the message is
        # consulted as well as the type.
        text = str(exc)
        missing = isinstance(exc, ImportError) or "install" in text.lower()
        out.status = "EXCLUDED"
        out.reason = (
            (
                f"missing_dependency: {type(exc).__name__}: {text}; the eval needs "
                "a package the sweep environment does not install"
            )
            if missing
            else (
                f"dataset_unavailable: {type(exc).__name__}: {text}"
                " (a gated dataset, a missing key, or a moved Hub repo presents this way)"
            )
        )[:600]
        out.seconds = round(time.monotonic() - started, 2)
        return out

    out.seconds = round(time.monotonic() - started, 2)
    out.dataset_name = getattr(task.dataset, "name", None)
    out.n_dataset = len(task.dataset)
    out.scorers = [scorer_name(f) for f in scorer_functions(task)]

    protocol, exclusion = dynamic_filter(ref, task)
    if exclusion is not None:
        out.status = "EXCLUDED"
        out.reason = f"{exclusion.rule}: {exclusion.reason}"
        return out
    assert protocol is not None
    out.protocol = protocol.name
    try:
        out.state_reads = sorted(
            r for fn in scorer_functions(task) for r in state_reads(fn)
        )
    except StateEscapes:  # already handled above; defensive
        out.state_reads = []

    subsample(task, n_samples, seed)
    adapter = WildInspectAdapter(task, protocol=protocol, env_id=f"inspect_evals/{ref.name}")
    out.n_sampled = len(task.dataset)

    anchor = gold_anchor(adapter)
    out.n_anchored = len(anchor.anchored)
    out.n_gold_unverified = len(anchor.unverified)
    out.gold_unverified_examples = [
        {"sample_id": tid, **anchor.detail[tid]} for tid in anchor.unverified[:3]
    ]

    if not anchor.anchored:
        out.status = "INCONCLUSIVE"
        out.reason = (
            f"gold_anchor_empty: the declared target was not accepted by this task's "
            f"own scorer on any of {out.n_sampled} sampled items under protocol "
            f"{protocol.name!r}. A broken eval and a mis-fitted probe are not "
            "distinguishable from here, so nothing is reported as a defect"
        )
        return out

    anchored_task = subsample_ids(task, anchor.anchored)
    anchored_adapter = WildInspectAdapter(
        anchored_task, protocol=protocol, env_id=f"inspect_evals/{ref.name}"
    )
    report = audit(anchored_adapter)

    out.verdict = report.verdict
    out.coverage = report.coverage
    out.findings = [
        {
            "defect": f.defect.value,
            "severity": f.severity.value,
            "task_id": f.task_id,
            "probe": r.probe,
            "family": r.family,
            "evidence": f.evidence,
        }
        for r in report.results
        for f in r.findings
    ]
    out.probes_passed = [r.probe for r in report.by_status(ProbeStatus.PASS)]
    out.not_applicable = [
        {"probe": r.probe, "reason": r.reason or ""}
        for r in report.by_status(ProbeStatus.NOT_APPLICABLE)
    ]
    out.errors = [
        {"probe": r.probe, "reason": r.reason or ""}
        for r in report.by_status(ProbeStatus.ERROR)
    ]
    out.status = "SWEPT"
    return out


def subsample_ids(task: Any, ids: list[str]) -> Any:
    """A copy of the task restricted to the given sample ids."""
    from inspect_ai.dataset import MemoryDataset

    keep = set(ids)
    samples = [
        s for i, s in enumerate(task.dataset) if str(s.id if s.id is not None else i) in keep
    ]
    task.dataset = MemoryDataset(samples, name=getattr(task.dataset, "name", None))
    return task


# --------------------------------------------------------------------------
# Whole sweep
# --------------------------------------------------------------------------


def sweep(
    *,
    only: list[str] | None = None,
    n_samples: int = 25,
    seed: int = 0,
    timeout: int = 300,
    on_task: Callable[[TaskSweep], None] | None = None,
) -> dict[str, Any]:
    """Enumerate, filter, and sweep. Returns the full record, findings or not."""
    refs = enumerate_tasks()
    kept, excluded = static_filter(refs)
    if only:
        wanted = set(only)
        kept = [r for r in kept if r.name in wanted]

    results: list[TaskSweep] = []
    for ref in kept:
        result = sweep_task_isolated(ref, n_samples=n_samples, seed=seed, timeout=timeout)
        results.append(result)
        if on_task is not None:
            on_task(result)

    return {
        "scope": installed_scope(),
        "config": {"n_samples": n_samples, "seed": seed, "timeout_s": timeout, "only": only},
        "n_registered_tasks": len(refs),
        "n_static_excluded": len(excluded),
        "n_attempted": len(kept),
        "out_of_scope": [e.to_dict() for e in out_of_scope_tasks()],
        "static_exclusions": [e.to_dict() for e in excluded],
        "tasks": [r.to_dict() for r in results],
    }
