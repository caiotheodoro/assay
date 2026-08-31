"""Family 11 -- can the verifier be made to run what it is grading.

BenchJack V3, "RCE into the evaluator". A verifier that calls `eval` on a
submitted string, unpickles a file the agent wrote, or shells out with
`shell=True` is not scoring the agent's work: it is offering to run it. The
agent does not have to solve the task, it has to write the sentence that makes
the grader award the mark.

Before this probe there was no static analysis of verifier source anywhere in
Assay and no `DefectClass` for it, so the best case was that a Challenger landed
one on Harbor and it surfaced as `REWARD_HACKABLE` -- true, and with no evidence
field ever saying *why*. A defect class whose mechanism the report cannot name
is a defect class nobody can fix.

Method, and its limits
----------------------
`ast` over the verifier's own source. The same machinery `sweep.dynamic_filter`
already uses to decide whether a scorer reads a `TaskState` this adapter
populates; the shared primitives live in `assay.astscan` so there is one
flattening of a dotted name in the repository and not two. No new parser, no new
dependency, and nothing is executed -- running a verifier to find out whether it
runs things would be an odd way to go about it.

Three limits, stated because a static scan that oversells itself is worse than
none:

* **It reads what it is handed.** A verifier that delegates to a helper in
  another module is scanned only as far as the source the adapter returned.
  Unlike `state_reads` this does not refuse on the first opaque call -- almost
  every real verifier calls something -- so a clean result here means "no
  execution sink in this source", never "this verifier is safe".
* **Reachability is not established.** A sink in a branch no input can reach is
  still reported. The finding names the line so a reader can judge; the probe
  does not, because deciding reachability is a different and much harder tool.
* **It only knows the sinks it lists.** The tables below are the mechanisms V3
  names plus the standard deserialisation set. A verifier reaching for something
  outside them passes.

The direction of those limits is the useful one: this probe under-reports. A
`PASS` from it is weak evidence and the card says so; a `DEFECT` from it names a
file and a line number.
"""

from __future__ import annotations

import ast
import textwrap
from typing import Any

from ..adapter import EnvAdapter
from ..astscan import dotted, import_bindings, resolve
from ..types import Capability, DefectClass, Finding, DEFAULT_SEVERITY, digest
from .base import Probe, register

#: Builtins that turn text into running code. Matched as bare names, and also
#: as attributes (`builtins.eval`) once the import bindings are applied.
EXEC_BUILTINS: dict[str, str] = {
    "eval": "eval() executes an expression assembled at runtime",
    "exec": "exec() executes a statement block assembled at runtime",
    "compile": "compile() turns text into a code object the caller then runs",
    "__import__": "__import__() imports a module named at runtime",
}

#: Dotted calls that execute their argument, or rebuild live objects from it.
#: Deserialisation belongs here rather than in a softer category because
#: `pickle.loads` on agent-written bytes is arbitrary code execution with extra
#: steps, and that is exactly how it reaches an evaluator: a scorer loading a
#: cached result the agent could overwrite.
EXEC_CALLS: dict[str, str] = {
    "os.system": "os.system() runs its argument through a shell",
    "os.popen": "os.popen() runs its argument through a shell",
    "os.execl": "os.exec*() replaces this process with a named program",
    "os.execlp": "os.exec*() replaces this process with a named program",
    "os.execv": "os.exec*() replaces this process with a named program",
    "os.execve": "os.exec*() replaces this process with a named program",
    "os.execvp": "os.exec*() replaces this process with a named program",
    "os.spawnl": "os.spawn*() starts a named program",
    "os.spawnv": "os.spawn*() starts a named program",
    "subprocess.getoutput": "subprocess.getoutput() always runs a shell",
    "subprocess.getstatusoutput": "subprocess.getstatusoutput() always runs a shell",
    "pickle.load": "pickle deserialisation instantiates arbitrary classes",
    "pickle.loads": "pickle deserialisation instantiates arbitrary classes",
    "cPickle.load": "pickle deserialisation instantiates arbitrary classes",
    "cPickle.loads": "pickle deserialisation instantiates arbitrary classes",
    "dill.load": "dill deserialisation instantiates arbitrary classes",
    "dill.loads": "dill deserialisation instantiates arbitrary classes",
    "marshal.load": "marshal deserialisation rebuilds code objects",
    "marshal.loads": "marshal deserialisation rebuilds code objects",
    "joblib.load": "joblib.load() unpickles its input",
    "torch.load": "torch.load() unpickles its input unless weights_only is set",
    "shelve.open": "shelve unpickles every value it reads back",
    "yaml.unsafe_load": "yaml.unsafe_load() constructs arbitrary Python objects",
    "yaml.full_load": "yaml.full_load() constructs arbitrary Python objects",
}

#: `subprocess` entry points that are safe by default and unsafe with
#: `shell=True`. Checked on the keyword rather than the name.
SHELL_CAPABLE = frozenset(
    {
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
    }
)

#: `yaml.load` is safe exactly when it is handed one of these loaders. Compared
#: on the last segment so `yaml.SafeLoader` and a `SafeLoader` imported directly
#: are the same answer.
SAFE_YAML_LOADERS = frozenset({"SafeLoader", "CSafeLoader", "BaseLoader", "CBaseLoader"})


def _is_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _safe_yaml_loader(call: ast.Call, bindings: dict[str, str]) -> bool:
    """Does this `yaml.load` call name a loader that cannot build objects.

    Accepts the loader positionally (`yaml.load(text, SafeLoader)`) as well as
    by keyword, because both spellings are in the wild and only checking one
    would report the careful call and miss the careless one.
    """
    candidates = [kw.value for kw in call.keywords if kw.arg == "Loader"]
    if len(call.args) > 1:
        candidates.append(call.args[1])
    for node in candidates:
        name = dotted(node)
        if name is None:
            # A loader computed at runtime cannot be read off the source. Not
            # treated as safe: the point of this check is that the default is
            # dangerous, so an unreadable argument leaves the call unproven.
            continue
        if resolve(name, bindings).split(".")[-1] in SAFE_YAML_LOADERS:
            return True
    return False


def execution_sinks(source: str) -> list[dict[str, Any]]:
    """Every call in `source` that can run or rebuild attacker-controlled input.

    Returns one entry per call site: the resolved name, the line, and why it
    counts. Raises `SyntaxError` if the text is not Python -- the caller decides
    what a shell verifier means, because "cannot be parsed" and "contains no
    sinks" are different answers and only one of them is reassuring.
    """
    # `inspect.getsource` of a nested function keeps its enclosing indentation,
    # which `ast.parse` rejects outright -- so without this every closure-style
    # scorer, which is most of them, comes back "not parseable as Python" and is
    # silently declined. `sweep.state_reads` dedents for the same reason.
    tree = ast.parse(textwrap.dedent(source))
    bindings = import_bindings(tree)
    sinks: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        spelled = dotted(node.func)
        if spelled is None:
            continue
        name = resolve(spelled, bindings)

        why = EXEC_BUILTINS.get(name) or EXEC_CALLS.get(name)
        if why is None and "." not in spelled and "." in name:
            # `from builtins import eval` reaches the same builtin by another
            # route. Restricted to the `builtins` module rather than matching on
            # the last segment of any import: a project with its own
            # `mycompiler.compile` would otherwise be reported for the name of
            # a function that has nothing to do with the builtin.
            module, _, leaf = name.rpartition(".")
            if module in ("builtins", "__builtin__") and leaf in EXEC_BUILTINS:
                why = EXEC_BUILTINS[leaf]
        if why is not None:
            sinks.append(
                {"call": name, "spelled": spelled, "line": node.lineno, "why": why}
            )
            continue

        if name in SHELL_CAPABLE and any(
            kw.arg == "shell" and _is_true(kw.value) for kw in node.keywords
        ):
            sinks.append(
                {
                    "call": name,
                    "spelled": spelled,
                    "line": node.lineno,
                    "why": f"{name}(shell=True) passes its argument to a shell",
                }
            )
            continue

        if name == "yaml.load" and not _safe_yaml_loader(node, bindings):
            sinks.append(
                {
                    "call": name,
                    "spelled": spelled,
                    "line": node.lineno,
                    "why": "yaml.load() without an explicit safe Loader constructs "
                    "arbitrary Python objects",
                }
            )

    return sorted(sinks, key=lambda s: (s["line"], s["call"]))


@register
class VerifierStaticAnalysis(Probe):
    """Read the grader before trusting it.

    Distinct verifiers are scanned once each: a suite whose hundred samples
    share one scorer is one finding with a hundred task ids attached, not a
    hundred findings. The digest that groups them is the same canonical hash the
    cards are identified by.
    """

    family = "evaluator_code_execution"
    name = "verifier_static_analysis"
    requires = (Capability.VERIFIER_SOURCE,)

    def check(self, adapter: EnvAdapter, ctx: dict[str, Any]):
        # source digest -> (source, task ids)
        seen: dict[str, tuple[str, list[str]]] = {}
        unreadable: dict[str, str] = {}

        for task in adapter.manifest().tasks:
            source = adapter.verifier_source(task.task_id)
            if not (source or "").strip():
                unreadable[task.task_id] = "adapter returned empty verifier source"
                continue
            key = digest(source)
            seen.setdefault(key, (source, []))[1].append(task.task_id)

        findings: list[Finding] = []
        detail: dict[str, Any] = {}

        for key, (source, task_ids) in seen.items():
            try:
                sinks = execution_sinks(source)
            except SyntaxError as exc:
                # A shell verifier, a template, or a truncated file. Not clean
                # and not a defect: unparseable is unexamined, and this probe
                # adds no second parser to find out which.
                for tid in task_ids:
                    unreadable[tid] = (
                        f"verifier source is not parseable as Python "
                        f"({type(exc).__name__}: {exc.msg} at line {exc.lineno}); "
                        "this probe adds no second parser, so it was not examined"
                    )
                continue
            detail[key[:16]] = {
                "task_ids": sorted(task_ids)[:20],
                "n_tasks": len(task_ids),
                "n_sinks": len(sinks),
                "source_lines": source.count("\n") + 1,
            }
            if sinks:
                findings.append(
                    Finding(
                        defect=DefectClass.EVALUATOR_RCE,
                        severity=DEFAULT_SEVERITY[DefectClass.EVALUATOR_RCE],
                        task_id=sorted(task_ids)[0],
                        evidence={
                            "sinks": sinks,
                            "verifier_digest": key[:16],
                            "n_tasks_sharing_this_verifier": len(task_ids),
                            "task_ids": sorted(task_ids)[:20],
                            "note": "the verifier can execute or deserialise content "
                            "it is handed; an agent that controls that content "
                            "controls its own score",
                            "confidence": "reachability not established -- the sink is "
                            "in the source at the line given, which is not the same "
                            "claim as 'an agent can reach it'",
                            "line_numbers": "within the source the adapter returned, "
                            "not within the original file",
                        },
                    )
                )

        if unreadable:
            detail["unreadable"] = unreadable
        if not seen:
            reasons = "; ".join(f"{t}: {why}" for t, why in sorted(unreadable.items()))
            return self.na(
                "no verifier source could be read for any task"
                + (f" -- {reasons}" if reasons else ""),
                per_task=unreadable,
            )
        if not detail.keys() - {"unreadable"}:
            reasons = "; ".join(f"{t}: {why}" for t, why in sorted(unreadable.items()))
            return self.na(
                f"no verifier source could be parsed as Python -- {reasons}",
                per_task=unreadable,
            )
        return self.defects(
            findings,
            per_verifier=detail,
            asymmetry=(
                "A sink found is evidence. No sink found is not evidence of safety: "
                "this reads only the source the adapter returned, does not follow "
                "calls out of it, and knows only the sinks it lists."
            ),
        )
