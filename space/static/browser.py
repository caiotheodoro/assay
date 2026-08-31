"""The half of the demo that runs in the visitor's browser, under Pyodide.

The Space this ships to is a **static** Space: Hugging Face serves the files and
runs no compute, which is why it is free where a Gradio Space is not. The probe
battery still runs -- it runs on the visitor's machine, in a WebAssembly CPython,
against the same vendored `assay` package the Gradio app would have used. The
audit is real; only the host is different.

That is possible because the audit path is **pure standard library**. `assay`
declares exactly one runtime dependency, `pyyaml`, and it is reached only by
`assay.costs`, which no probe touches. Nothing between `adapters.spec.build()`
and `runner.audit()` imports anything Pyodide has to fetch, so this page needs
no `micropip`, no wheel index, and no network beyond its own files.

One thing genuinely does not work here, and it is not a gap to paper over --
see `REGEX_UNAVAILABLE`.

The JS side calls `audit()` and gets a JSON *string* back. Deliberately: a
string crosses the boundary with no proxy to free and no lifetime to get wrong,
and the page has one job with the result, which is to put the HTML in a panel.
"""

from __future__ import annotations

import json

from assay.card import web

#: Emscripten has no processes. `assay.safe_regex` needs one.
#:
#: Python's regex engine backtracks, so `(a+)+$` against 31 characters takes
#: about 100 seconds. On a page whose whole premise is "paste an environment
#: you did not write", that is a denial of service with a payload of a dozen
#: bytes, and `safe_regex` answers it the only way a timeout is enforceable:
#: the match runs in a subprocess under a wall clock, where something else can
#: kill what overran. `subprocess` under Pyodide raises
#: `OSError: [Errno 138] emscripten does not support processes.`
#:
#: So the browser build refuses `verifier: "regex"` up front rather than
#: letting eight probes error out one at a time, and it refuses rather than
#: falling back to a bare `re.search`. Dropping the guard to make the box work
#: here would reinstate the exact defect this project shipped `safe_regex` to
#: fix, on the exact page that defect was about.
REGEX_UNAVAILABLE = (
    "This spec declares <code>verifier: \"regex\"</code>, and that is the one "
    "verifier this in-browser build will not run."
    "<p>Not a WebAssembly limitation being worked around. Python's engine "
    "backtracks, so a submitted pattern like <code>(a+)+$</code> against 31 "
    "characters takes about 100 seconds — a denial of service on a public page "
    "with a dozen bytes. <code>assay.safe_regex</code> bounds that the only way "
    "a timeout is enforceable, by running the match in a subprocess under a "
    "wall clock, and Emscripten has no processes "
    "(<code>OSError: [Errno 138]</code>). Falling back to an unguarded "
    "<code>re.search</code> would put the defect back, on the page it was "
    "about.</p>"
    "<p>Every other verifier — <code>exact</code>, <code>exact_ci</code>, "
    "<code>includes</code>, <code>always_pass</code>, <code>always_fail</code> — "
    "runs here in full. For <code>regex</code>, run the same battery locally: "
    "<code>python space/app.py</code>.</p>"
)


def _declares_regex_verifier(spec_text: str) -> bool:
    """True only when the submission asks for the regex matcher.

    Anything unparseable answers False, so a malformed spec still reaches
    `SpecError` and gets the ordinary "the spec could not be read" message
    naming the field -- a guess about the verifier is not worth pre-empting a
    real diagnosis.
    """
    try:
        raw = json.loads(spec_text)
    except (TypeError, ValueError):
        return False
    if not isinstance(raw, dict):
        return False
    verifier = raw.get("verifier")
    if isinstance(verifier, dict):
        verifier = verifier.get("kind")
    return verifier == "regex"


def audit(spec_text: str) -> str:
    """Submitted JSON in, `{"html", "markdown", "json"}` out, as a JSON string."""
    if _declares_regex_verifier(spec_text):
        return json.dumps({
            "html": web.error("The regex verifier needs a subprocess.", REGEX_UNAVAILABLE),
            "markdown": "",
            "json": "",
        })
    html, markdown, signed = web.audit_spec(spec_text)
    return json.dumps({"html": html, "markdown": markdown, "json": signed})
