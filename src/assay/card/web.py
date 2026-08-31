"""The Environment Card as an HTML fragment, for anything with an audience.

This is `space/app.py`'s renderer, lifted out of it. It moved because it grew a
second caller: the browser build of the demo runs the same probe battery under
Pyodide and has to render the same card, and two copies of an escaping renderer
is exactly how the injection in slice 36 happened -- `card/render.py` escaped,
`space/app.py` did not, and nothing compared them. One renderer, in the package,
under the same tests.

`render.py` renders a *document*: a whole page, or the Markdown a card is filed
as. This renders the *fragment* a live UI drops into a panel. Both escape.

The design constraint that shapes it: **an empty card must never read as a
clean bill of health.** The probes that could NOT run are rendered above the
findings, at the same visual weight, and the verdict banner says `UNVERIFIED`
rather than anything green when a probe was skipped. Someone who pastes three
lines of JSON and sees "no findings" has to be told, on the same screen, that
most of the battery never ran and why.
"""

from __future__ import annotations

import html as html_mod
import traceback

from ..types import ProbeStatus, Severity

VERDICT_COLOUR = {
    "VALID": "#1a7f37",
    "DEFECTIVE": "#9a6700",
    "INVALID": "#cf222e",
    "UNVERIFIED": "#8250df",
    "INCONCLUSIVE": "#6e7781",
}

VERDICT_MEANING = {
    "VALID": "Every probe ran and none found a defect.",
    "DEFECTIVE": "Defects were found. None of them invalidate the environment outright.",
    "INVALID": (
        "A critical defect was found. Scores from this environment do not mean what "
        "they appear to."
    ),
    "UNVERIFIED": (
        "No defect was found, but not every probe could run. "
        "<b>This is not a clean bill of health.</b>"
    ),
    "INCONCLUSIVE": "A probe errored. The audit did not complete.",
}

SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]

#: The one probe that can never run in a hosted demo, because it needs a
#: rollout sampler. Named rather than inferred so the banner can say *why* a
#: clean submission still cannot reach VALID.
SAMPLER_ONLY = "difficulty_band"


def escape(value: object, limit: int | None = None) -> str:
    """Everything that reaches the page from a submitted spec goes through here.

    A spec is a stranger's JSON on a public host, and every string in it --
    task ids, verifier names, the text of a `SpecError` quoting the offending
    value -- was being interpolated raw into HTML. A `task_id` of
    `<img src=x onerror=...>` rendered verbatim and executed. `card/render.py`
    has escaped since it was written; the Space renderer never did, and the
    Space renderer is the one with an audience.

    Escaping and truncation belong together because both bound what a
    submission can do to the page: without the cap a 20,000-character task id
    is a denial-of-service on the reader rather than on the server.
    """
    text = str(value)
    if limit is not None and len(text) > limit:
        text = text[:limit] + "…"
    return html_mod.escape(text, quote=True)


def ceiling(report) -> str:
    """Say when UNVERIFIED is the best this Space can do, and why.

    `VALID` requires that every probe ran, and `difficulty_band` needs a
    rollout sampler that a Space without Docker does not have -- so a
    submission with nothing whatever wrong with it still comes back purple.
    Showing that to someone whose eval is genuinely fine, with no explanation,
    teaches them the tool is broken rather than that the check was skipped.
    Only shown when the sampler is the *only* thing missing; if other probes
    were skipped too, the honest message is the ordinary one.
    """
    skipped = {r.probe for r in report.by_status(ProbeStatus.NOT_APPLICABLE)}
    errored = report.by_status(ProbeStatus.ERROR)
    if errored or skipped != {SAMPLER_ONLY} or report.findings:
        return ""
    return (
        '  <div class="assay-ceiling">Nothing was found wrong with this '
        "submission. <b>VALID is still out of reach here</b>, and that is a "
        "limit of this Space rather than a reservation about your "
        "environment: <code>difficulty_band</code> needs a rollout sampler, "
        "which a Space without Docker cannot provide. Run Assay locally with a "
        "sampler to close the last probe.</div>\n"
    )


def banner(report) -> str:
    cov = report.coverage
    colour = VERDICT_COLOUR[report.verdict]
    return f"""
<div class="assay-banner" style="border-left:6px solid {colour}">
  <div class="assay-verdict" style="background:{colour}">{escape(report.verdict)}</div>
  <div class="assay-meaning">{VERDICT_MEANING[report.verdict]}</div>
  <div class="assay-coverage">
    <span><b>{cov['PASS']}</b> passed</span>
    <span><b>{cov['DEFECT']}</b> found defects</span>
    <span class="assay-skip"><b>{cov['NOT_APPLICABLE']}</b> could not run</span>
    <span><b>{cov['ERROR']}</b> errored</span>
  </div>
{ceiling(report)}  <div class="assay-exit">Exit code <code>{escape(report.exit_code)}</code> &mdash;
    nonzero for anything that is not <code>VALID</code>, including
    <code>UNVERIFIED</code>. No defects found is not the same as no defects.</div>
</div>"""


def not_run(report) -> str:
    """Rendered ABOVE the findings, deliberately. This is the section that
    stops a thin submission reading as a pass."""
    skipped = report.by_status(ProbeStatus.NOT_APPLICABLE)
    errored = report.by_status(ProbeStatus.ERROR)
    if not skipped and not errored:
        return (
            '<div class="assay-section"><h3>What could not be checked</h3>'
            "<p>Nothing. Every probe ran.</p></div>"
        )
    rows = "".join(
        f"<tr><td><code>{escape(r.probe)}</code></td><td>{escape(r.reason, 400)}</td></tr>"
        for r in skipped + errored
    )
    return f"""<div class="assay-section assay-notrun">
  <h3>What could not be checked &mdash; {len(skipped) + len(errored)} probes</h3>
  <p>These probes did not run. <b>Nothing below them was verified</b>, and the
     verdict reflects that rather than assuming the best.</p>
  <table><thead><tr><th>Probe</th><th>Why not</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>"""


def findings(report) -> str:
    if not report.findings:
        return (
            '<div class="assay-section"><h3>Findings</h3><p>None. Read the section '
            "above before concluding anything from that.</p></div>"
        )
    blocks = []
    for severity in SEVERITY_ORDER:
        group = [f for f in report.findings if f.severity is severity]
        if not group:
            continue
        items = []
        for f in group:
            where = f" &mdash; <code>{escape(f.task_id, 120)}</code>" if f.task_id else ""
            note = escape(f.evidence["note"], 600) if f.evidence.get("note") else ""
            ev = "; ".join(
                f"<code>{escape(k, 80)}</code>: {escape(v, 160)}"
                for k, v in f.evidence.items()
                if k not in {"note", "attacker_trace"}
            )
            items.append(
                f"<li><b>{escape(f.defect.value)}</b>{where}"
                + (f"<blockquote>{note}</blockquote>" if note else "")
                + (f"<div class='assay-ev'>{ev}</div>" if ev else "")
                + "</li>"
            )
        blocks.append(
            f"<h4 class='sev-{escape(severity.value.lower())}'>{escape(severity.value)}</h4>"
            f"<ul>{''.join(items)}</ul>"
        )
    return f"<div class='assay-section'><h3>Findings</h3>{''.join(blocks)}</div>"


def card(report) -> str:
    """The whole fragment: banner, then what could not be checked, then findings.

    The order is the argument. Coverage before findings, always.
    """
    return banner(report) + not_run(report) + findings(report)


def error(title: str, detail: str = "") -> str:
    body = f"<br>{detail}" if detail else ""
    return f'<div class="assay-error"><b>{title}</b>{body}</div>'


def audit_spec(spec_text: str) -> tuple[str, str, str]:
    """Submitted JSON in, `(fragment, markdown, signed JSON)` out.

    Every failure mode returns rendered HTML rather than raising: this runs
    behind a text box on a public page, and a traceback on the console is not
    an answer to the person who pasted something.
    """
    from ..adapters.spec import SpecError, build
    from ..runner import audit
    from .render import to_markdown

    if not (spec_text or "").strip():
        return (
            error(
                "Nothing submitted.",
                "An empty submission is not an environment with no defects; it is "
                "not an environment.",
            ),
            "",
            "",
        )
    try:
        adapter = build(spec_text)
    except SpecError as exc:
        return error("The spec could not be read.", escape(exc, 800)), "", ""
    except Exception:  # noqa: BLE001 -- a crash here is ours, and is reported as ours
        return (
            error(
                "Assay crashed reading that spec.",
                "That is a bug in Assay, not a verdict about your environment."
                f"<pre>{escape(traceback.format_exc()[-1200:])}</pre>",
            ),
            "",
            "",
        )

    report = audit(adapter)
    return card(report), to_markdown(report), report.to_json()


#: The card's own styling, with no host framework assumed. `var(--...)` lookups
#: fall back so the same string works inside Gradio's theme and on a bare page.
CSS = """
.assay-banner { padding: 1rem 1.1rem; margin: .5rem 0 1rem; border-radius: .4rem;
  background: var(--block-background-fill, rgba(127,127,127,.06)); }
.assay-verdict { display:inline-block; padding:.25rem .7rem; border-radius:.3rem;
  color:#fff; font-weight:700; letter-spacing:.03em; }
.assay-meaning { margin-top:.6rem; }
.assay-coverage { margin-top:.7rem; display:flex; gap:1.4rem; flex-wrap:wrap;
  font-size:.92rem; }
.assay-coverage .assay-skip { color:#8250df; }
.assay-exit { margin-top:.6rem; font-size:.85rem; opacity:.75; }
.assay-section { margin: 1.2rem 0; }
.assay-section h3 { margin-bottom:.4rem; }
.assay-notrun { border:1px solid #8250df55; border-radius:.4rem; padding:.9rem 1.1rem;
  background:#8250df0d; }
.assay-notrun table { width:100%; border-collapse:collapse; margin-top:.6rem; }
.assay-notrun td, .assay-notrun th { text-align:left; padding:.3rem .5rem;
  border-bottom:1px solid var(--border-color-primary, rgba(127,127,127,.3));
  font-size:.9rem; }
.assay-ev { font-size:.85rem; opacity:.8; margin:.2rem 0 .6rem; }
.sev-critical { color:#cf222e; } .sev-high { color:#9a6700; }
.assay-error { padding:1rem; border-radius:.4rem; border:1px solid #cf222e55;
  background:#cf222e0d; }
.assay-idle { padding:1.5rem; opacity:.7; }
.assay-ceiling { margin-top:.7rem; padding:.6rem .8rem; border-radius:.3rem;
  background:#1a7f3714; border:1px solid #1a7f3733; font-size:.92rem; }
"""
