"""The static Space runs the battery in the visitor's browser. What holds it up.

The hosted demo exists because of one property of this package: **the audit
path imports nothing outside the standard library**. `assay` declares exactly
one runtime dependency, `pyyaml`, and only `assay.costs` reaches it -- no probe
does. So Pyodide needs no `micropip`, no wheel index and no network beyond the
Space's own files, and the whole thing boots in under two seconds.

That property is invisible. Nothing about `import numpy` in a new probe looks
like it breaks a deployment, and by the time anyone notices, the page is a
white screen for every visitor. The first test here is the tripwire.

The rest cover the browser entry point: it renders the same card the Gradio app
renders, it escapes what a stranger submits, and it refuses the one verifier a
browser genuinely cannot run rather than quietly running it unguarded.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSER = ROOT / "space" / "static" / "browser.py"
SRC = ROOT / "src"

sys.path.insert(0, str(BROWSER.parent))
sys.path.insert(0, str(ROOT / "space"))  # for the Gradio app, in the one test that needs it

import browser  # noqa: E402

PAYLOAD = '<img src=x onerror="alert(1)">'

#: What the Space is built to drive. `assay.card.web` is on the list because it
#: is the renderer both front doors call.
AUDIT_ENTRY_POINTS = (
    "assay",
    "assay.adapters.spec",
    "assay.runner",
    "assay.card",
    "assay.card.web",
    "assay.types",
)


def _module_path(name: str) -> Path | None:
    flat = SRC / (name.replace(".", "/") + ".py")
    if flat.exists():
        return flat
    pkg = SRC / name.replace(".", "/") / "__init__.py"
    return pkg if pkg.exists() else None


def _top_level_imports(tree: ast.Module):
    """Only what runs at import time.

    A `import torch` inside a function body costs a Pyodide page nothing, and
    `assay.challenger.grpo` has several. Walking the whole tree would flag them
    and the tripwire would be permanently red, which is the same as absent.
    Class bodies execute on import, so they count; function bodies do not.
    """
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        for field in ("body", "orelse", "finalbody", "handlers"):
            stack.extend(getattr(node, field, []) or [])


def _reachable_imports() -> dict[str, set[str]]:
    """`{third-party module: {assay modules that import it at module scope}}`."""
    seen: set[str] = set()
    foreign: dict[str, set[str]] = {}

    def walk(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        path = _module_path(name)
        if path is None:
            return
        tree = ast.parse(path.read_text())
        is_pkg = path.name == "__init__.py"
        package = name if is_pkg else name.rsplit(".", 1)[0]
        for node in _top_level_imports(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    (walk(alias.name) if alias.name.startswith("assay")
                     else foreign.setdefault(alias.name.split(".")[0], set()).add(name))
                continue
            if node.level:  # a relative import
                base = package
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0]
                target = f"{base}.{node.module}" if node.module else base
            elif node.module and node.module.startswith("assay"):
                target = node.module
            else:
                if node.module:
                    foreign.setdefault(node.module.split(".")[0], set()).add(name)
                continue
            walk(target)
            for alias in node.names:  # `from . import verifier` names a module
                walk(f"{target}.{alias.name}")

    for entry in AUDIT_ENTRY_POINTS:
        walk(entry)
    return foreign


def test_the_audit_path_imports_nothing_outside_the_standard_library():
    """The load-bearing claim of the whole static Space.

    If this goes red, the hosted demo is broken for every visitor and no other
    test in the suite will say so: a probe importing `numpy` passes locally,
    passes in CI, and white-screens a browser that has no wheel to fetch.
    Either make the new import lazy, or accept that the demo now needs
    `micropip` and say so on the page.
    """
    foreign = _reachable_imports()
    outside = {
        mod: sorted(users)
        for mod, users in foreign.items()
        if mod not in sys.stdlib_module_names and mod != "__future__"
    }
    assert not outside, (
        "the audit path now needs a third-party package at import time, which "
        f"the in-browser build cannot fetch: {outside}"
    )


def test_the_browser_entry_point_does_not_need_gradio():
    """Checked by denying the import, not by reading the source.

    `space/app.py` imports gradio; the browser build shares its renderer and
    must not. A subprocess with `gradio` blocked at the meta path is the only
    version of this test that cannot pass by accident -- this test process has
    usually imported gradio already.
    """
    script = (
        "import sys\n"
        "class Deny:\n"
        "    def find_module(self, name, path=None):\n"
        "        if name == 'gradio' or name.startswith('gradio.'):\n"
        "            raise ImportError('gradio is not available in a browser')\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        return self.find_module(name, path)\n"
        "sys.meta_path.insert(0, Deny())\n"
        f"sys.path[:0] = [{str(SRC)!r}, {str(BROWSER.parent)!r}]\n"
        "import json, browser\n"
        "spec = json.dumps({'env_id': 'x/y', 'verifier': 'includes', 'tasks': "
        "[{'task_id': 'q1', 'instruction': 'Answer Yes or No', 'target': 'Yes', "
        "'gold': 'Yes', 'known_wrong': 'No'}]})\n"
        "out = json.loads(browser.audit(spec))\n"
        "assert 'assay-banner' in out['html'], out['html'][:200]\n"
        "assert 'gradio' not in sys.modules\n"
        "print('ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert proc.stdout.strip().endswith("ok")


def test_a_task_id_cannot_inject_html_through_the_browser_build():
    """The slice-36 defect, re-asked at the second front door.

    It survived the first time because nothing imported the file that had it.
    A second renderer would have been a second chance to reintroduce it, which
    is why there is one renderer and why this test exists next to the one in
    `test_space_app.py` rather than instead of it.
    """
    out = json.loads(browser.audit(json.dumps({
        "env_id": "you/eval",
        "verifier": "includes",
        "tasks": [{"task_id": PAYLOAD, "instruction": "Answer Yes or No",
                   "target": "Yes", "gold": "Yes", "known_wrong": "No"}],
    })))
    assert "<img src=x" not in out["html"], "a submitted task id reached the page as live HTML"
    assert "&lt;img src=x" in out["html"], "the id should still be shown, escaped"


def test_the_regex_verifier_is_refused_rather_than_run_unguarded():
    """Emscripten has no processes, and `safe_regex` needs one.

    The wrong fix is a bare `re.search`: `assay.safe_regex` exists because a
    submitted pattern can hang the process, and the page it would hang is the
    one whose whole premise is "paste an environment you did not write".
    """
    out = json.loads(browser.audit(json.dumps({
        "env_id": "you/eval", "verifier": "regex",
        "tasks": [{"task_id": "q1", "instruction": "i", "target": "^Yes$"}],
    })))
    assert "assay-error" in out["html"]
    assert "subprocess" in out["html"], "the refusal has to say why, or it reads as a bug"
    assert out["json"] == "", "a refused submission has no probe output to sign"


def test_the_refusal_does_not_swallow_a_malformed_spec():
    """A guess about the verifier must not pre-empt a real diagnosis."""
    out = json.loads(browser.audit("{not json"))
    assert "could not be read" in out["html"]
    assert "subprocess" not in out["html"]


def test_an_empty_submission_is_not_an_environment_with_no_defects():
    out = json.loads(browser.audit("   "))
    assert "Nothing submitted" in out["html"]


def test_the_two_front_doors_render_the_same_card():
    """One renderer, asserted rather than intended.

    The Gradio app and the browser build produce byte-identical HTML for the
    same spec. This is the property the pre-rendered gallery depends on: the
    seven cards baked into the page are what the button produces, not a
    mock-up of what it produces.
    """
    gradio_app = pytest.importorskip("app", reason="needs gradio installed")
    spec = json.dumps({
        "env_id": "you/eval",
        "verifier": "includes",
        "tasks": [{"task_id": "q1", "instruction": "Answer Yes or No", "target": "Yes",
                   "gold": "Yes", "known_wrong": "No"}],
    })
    assert json.loads(browser.audit(spec))["html"] == gradio_app.run_audit(spec)[0]


def test_every_bundled_example_renders_a_card_in_the_browser_build():
    """A broken example is the first thing a visitor sees, and on this page it
    is baked into the HTML rather than produced on demand -- so a break ships."""
    examples = json.loads((ROOT / "space" / "examples.json").read_text())
    assert len(examples) == 7
    for example in examples:
        out = json.loads(browser.audit(json.dumps(example["spec"], indent=2)))
        assert "assay-banner" in out["html"], f"{example['name']} rendered no verdict"
        assert "Assay crashed" not in out["html"], f"{example['name']} crashed the auditor"
        assert out["json"], f"{example['name']} produced no signed probe output"
