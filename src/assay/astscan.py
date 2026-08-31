"""Shared AST walking for the two places that read somebody else's source.

`sweep.state_reads` walks a scorer to establish which `TaskState` attributes it
reads. `probes/evaluator.py` walks a verifier to establish whether it can
execute attacker-controlled content. Both need the same two primitives -- the
maximal dotted name a node spells, and the import bindings that say what a bare
name in that source actually refers to -- and both keep the same discipline:
read the source in front of you, and refuse rather than guess when it stops
being readable.

This module exists so the flattening is written down once. There is no second
parser here and no new dependency: `ast` is the same machinery `sweep.py`
already used, lifted to where a probe can reach it without importing the sweep,
whose module graph pulls in an adapter a core probe has no business needing.
"""

from __future__ import annotations

import ast


def dotted(node: ast.AST) -> str | None:
    """The maximal dotted name a node spells, or None if its root is not a Name.

    `os.path.join` becomes ``"os.path.join"`` and `state.output.completion`
    becomes ``"state.output.completion"``. A chain rooted in anything else --
    `f().attr`, `d["k"].attr` -- returns None, because there is no name to
    attribute the access to and inventing one would be the guess this module
    refuses to make.
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    return None


def import_bindings(tree: ast.AST) -> dict[str, str]:
    """Local name -> the dotted path it was imported from.

    `import yaml as y` binds ``y -> "yaml"``; `from os import system` binds
    ``system -> "os.system"``. Without this, a scan for `os.system` misses the
    `from`-import spelling of exactly the same call -- which is the spelling
    somebody writing that call deliberately would reach for.

    Relative imports (`from . import x`) are recorded under their own name with
    no package prefix, because the prefix is not in the source being read and
    this module does not resolve modules it cannot see.
    """
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    root = alias.name.split(".")[0]
                    bindings[root] = root
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                target = f"{module}.{alias.name}" if module else alias.name
                bindings[alias.asname or alias.name] = target
    return bindings


def resolve(name: str, bindings: dict[str, str]) -> str:
    """Rewrite a dotted name's root through the import bindings.

    ``resolve("y.safe_load", {"y": "yaml"})`` is ``"yaml.safe_load"``. A root
    with no binding comes back unchanged -- it may be a builtin, a parameter, or
    something defined out of sight, and all three are the caller's problem to
    handle rather than this function's to assume away.
    """
    root, sep, rest = name.partition(".")
    bound = bindings.get(root)
    if bound is None:
        return name
    return f"{bound}.{rest}" if sep else bound
