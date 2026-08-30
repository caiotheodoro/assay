"""Assay on Hugging Face Spaces: submit an environment, get an Environment Card.

The design constraint that shapes this file: **an empty card must never read as
a clean bill of health**. The probes that could NOT run are rendered first, in
the same visual weight as the findings, and the verdict banner says
`UNVERIFIED` rather than anything green when a probe was skipped. Someone who
pastes three lines of JSON and sees "no findings" has to be told, on the same
screen, that nine of twelve probes never ran and why.

Environments arrive as data, not as code. Executing a stranger's Python on a
public host would be a different project; `assay.adapters.spec` turns a JSON
description into an adapter the probe battery can drive.
"""

from __future__ import annotations

import html as html_mod
import json
import traceback
from pathlib import Path

import gradio as gr

from assay.adapters.spec import SpecError, build
from assay.card import to_markdown
from assay.runner import audit
from assay.types import ProbeStatus, Severity

HERE = Path(__file__).parent
EXAMPLES = json.loads((HERE / "examples.json").read_text())

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

#: The one probe that can never run here, because it needs a rollout sampler.
#: Named rather than inferred so the banner can say *why* a clean submission
#: still cannot reach VALID.
SAMPLER_ONLY = "difficulty_band"


def _e(value: object, limit: int | None = None) -> str:
    """Everything that reaches the page from a submitted spec goes through here.

    A spec is a stranger's JSON on a public host, and every string in it --
    task ids, verifier names, the text of a `SpecError` quoting the offending
    value -- was being interpolated raw into HTML. A `task_id` of
    `<img src=x onerror=...>` rendered verbatim and executed. `card/render.py`
    has escaped since it was written; this file never did, and this file is the
    one with an audience.

    Escaping and truncation belong together because both bound what a
    submission can do to the page: without the cap a 20,000-character task id
    is a denial-of-service on the reader rather than on the server.
    """
    text = str(value)
    if limit is not None and len(text) > limit:
        text = text[:limit] + "\u2026"
    return html_mod.escape(text, quote=True)

#: The example the page opens on. Not the healthy one: a visitor who lands on
#: an environment with nothing wrong learns what the UI looks like and nothing
#: about why the tool exists.
PRELOADED = "3 \u2014 Substring verifier: one constant string answers both labels"

BLANK = """<div class="assay-idle">
Paste a spec, or load an example, then press <b>Audit</b>.
</div>"""


def _banner(report) -> str:
    cov = report.coverage
    colour = VERDICT_COLOUR[report.verdict]
    return f"""
<div class="assay-banner" style="border-left:6px solid {colour}">
  <div class="assay-verdict" style="background:{colour}">{_e(report.verdict)}</div>
  <div class="assay-meaning">{VERDICT_MEANING[report.verdict]}</div>
  <div class="assay-coverage">
    <span><b>{cov['PASS']}</b> passed</span>
    <span><b>{cov['DEFECT']}</b> found defects</span>
    <span class="assay-skip"><b>{cov['NOT_APPLICABLE']}</b> could not run</span>
    <span><b>{cov['ERROR']}</b> errored</span>
  </div>
{_ceiling(report)}  <div class="assay-exit">Exit code <code>{_e(report.exit_code)}</code> &mdash;
    nonzero for anything that is not <code>VALID</code>, including
    <code>UNVERIFIED</code>. No defects found is not the same as no defects.</div>
</div>"""


def _ceiling(report) -> str:
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


def _not_run(report) -> str:
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
        f"<tr><td><code>{_e(r.probe)}</code></td><td>{_e(r.reason, 400)}</td></tr>"
        for r in skipped + errored
    )
    return f"""<div class="assay-section assay-notrun">
  <h3>What could not be checked &mdash; {len(skipped) + len(errored)} probes</h3>
  <p>These probes did not run. <b>Nothing below them was verified</b>, and the
     verdict reflects that rather than assuming the best.</p>
  <table><thead><tr><th>Probe</th><th>Why not</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>"""


def _findings(report) -> str:
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
            where = f" &mdash; <code>{_e(f.task_id, 120)}</code>" if f.task_id else ""
            note = _e(f.evidence["note"], 600) if f.evidence.get("note") else ""
            ev = "; ".join(
                f"<code>{_e(k, 80)}</code>: {_e(v, 160)}"
                for k, v in f.evidence.items()
                if k not in {"note", "attacker_trace"}
            )
            items.append(
                f"<li><b>{_e(f.defect.value)}</b>{where}"
                + (f"<blockquote>{note}</blockquote>" if note else "")
                + (f"<div class='assay-ev'>{ev}</div>" if ev else "")
                + "</li>"
            )
        blocks.append(
            f"<h4 class='sev-{_e(severity.value.lower())}'>{_e(severity.value)}</h4>"
            f"<ul>{''.join(items)}</ul>"
        )
    return f"<div class='assay-section'><h3>Findings</h3>{''.join(blocks)}</div>"


def run_audit(spec_text: str):
    if not (spec_text or "").strip():
        return (
            '<div class="assay-error">Nothing submitted. An empty submission is not '
            "an environment with no defects; it is not an environment.</div>",
            "",
            "",
        )
    try:
        adapter = build(spec_text)
    except SpecError as exc:
        return (
            f'<div class="assay-error"><b>The spec could not be read.</b><br>{_e(exc, 800)}</div>',
            "",
            "",
        )
    except Exception:  # noqa: BLE001 -- a crash here is ours, and is reported as ours
        return (
            '<div class="assay-error"><b>Assay crashed reading that spec.</b> That is '
            "a bug in Assay, not a verdict about your environment.<pre>"
            f"{_e(traceback.format_exc()[-1200:])}</pre></div>",
            "",
            "",
        )

    report = audit(adapter)
    html = _banner(report) + _not_run(report) + _findings(report)
    return html, to_markdown(report), report.to_json()


def load_example(name: str):
    for ex in EXAMPLES:
        if ex["name"] == name:
            return json.dumps(ex["spec"], indent=2)
    return ""


CSS = """
.assay-banner { padding: 1rem 1.1rem; margin: .5rem 0 1rem; border-radius: .4rem;
  background: var(--block-background-fill); }
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
  border-bottom:1px solid var(--border-color-primary); font-size:.9rem; }
.assay-ev { font-size:.85rem; opacity:.8; margin:.2rem 0 .6rem; }
.sev-critical { color:#cf222e; } .sev-high { color:#9a6700; }
.assay-error { padding:1rem; border-radius:.4rem; border:1px solid #cf222e55;
  background:#cf222e0d; }
.assay-idle { padding:1.5rem; opacity:.7; }
.assay-ceiling { margin-top:.7rem; padding:.6rem .8rem; border-radius:.3rem;
  background:#1a7f3714; border:1px solid #1a7f3733; font-size:.92rem; }
"""

INTRO = """
# Assay

Submit an environment. Get an **Environment Card**: a validity verdict where
every claim is tied to a probe result — and **every probe that could not run,
with the reason**.

That second half is the point. A card with no findings is not a clean bill of
health, and this Space will not render one as if it were.

**No LLM judge scores anything here.** Every oracle is a deterministic program.
"""

FORMAT_HELP = """
### The spec format

```json
{
  "env_id": "you/your-eval",
  "verifier": "exact",
  "tasks": [
    {"task_id": "q1", "instruction": "Answer Yes or No: ...", "target": "Yes",
     "gold": "Yes", "known_wrong": "No", "asserts": ["the answer equals Yes"]}
  ],
  "train": [{"item_id": "tr1", "text": "...", "label": "Yes"}],
  "eval":  [{"item_id": "ev1", "text": "...", "label": "No",
             "parts": {"hypothesis": "..."}}]
}
```

| field | what it does | leave it out and… |
|---|---|---|
| `target` | what the task actually asks for | required |
| `verifier` | the rule the environment applies: `exact`, `exact_ci`, `includes`, `regex`, `always_pass`, `always_fail` | defaults to `exact` |
| `gold` | a correct answer | the gold-passes and inverted-spec probes cannot run |
| `known_wrong` | a wrong answer | the known-wrong and separability probes cannot run |
| `asserts` | what the verifier really checks, in words | the spec↔verifier probe cannot run |
| `train` / `eval` | the two splits | the contamination probe cannot run |
| `parts` | fields a partial-input baseline may see | the shortcut-leakage probe cannot run |
| `trivial_answers` | extra input-ignoring answers to try | only `empty` and the modal target are tried |

`target` and `verifier` are separate **on purpose**. The target is what the
task asks for; the verifier is the rule the environment happens to apply. Every
eval defect worth finding lives in the gap between them — a substring verifier
against the target `No` credits `"I don't know"`.

Capabilities are **derived from what you submit**, never claimed. A
`"capabilities"` key is not even read. You cannot talk a probe into passing,
and leaving a field out does not hide a probe — it prints the omission.

### What this cannot do here

- **Single-turn, string-answer environments only.** Multi-turn shell
  environments — where the interesting exploits live — need Docker, which this
  Space does not have. `harbor/self-graded`, the one environment in the corpus
  that Assay itself misses, cannot be expressed in this format.
- The **difficulty-band** probe needs a rollout sampler and always reports
  `NOT_APPLICABLE` here.
- Caps: 200 tasks, 2,000 split items, 20,000 characters per item.

### Synthetic, and not production-validated

The examples are synthetic fixtures with defects planted on purpose. Assay is
**not production-validated** — it has been measured against defects its own
authors planted, which is a lower bar than defects found in the wild. On that
corpus it **does not separate from a policy that flags every environment
unread**, and under a production-training cost profile that policy beats it
outright. Both numbers, with 95% intervals, are on
[`caiotheodoro/assay-corpus`](https://huggingface.co/datasets/caiotheodoro/assay-corpus).

A `VALID` verdict here is not sign-off on anything that matters. The card stays
unsigned until a human signs it.
"""

with gr.Blocks(title="Assay", css=CSS) as demo:
    gr.Markdown(INTRO)
    with gr.Row():
        with gr.Column(scale=5):
            picker = gr.Dropdown(
                [e["name"] for e in EXAMPLES],
                label="Load an example",
                info="Each one is a fixture with a known defect, or a deliberately thin spec.",
                value=PRELOADED,
            )
            spec = gr.Code(
                label="Environment spec (JSON)",
                language="json",
                lines=22,
                # Pre-loaded rather than blank. An empty box asks a visitor to
                # supply the argument for the tool before they have seen it
                # make one; this example IS the argument -- a substring
                # verifier where the single string "Yes, I think so" is
                # credited for both labels, so a policy that ignores the input
                # entirely scores 100%. Landing on the thesis costs one click
                # less than reaching it.
                value=load_example(PRELOADED),
            )
            go = gr.Button("Audit", variant="primary")
        with gr.Column(scale=6):
            out = gr.HTML(BLANK)
    with gr.Accordion("The spec format, and what this cannot check", open=False):
        gr.Markdown(FORMAT_HELP)
    with gr.Accordion("Card as Markdown", open=False):
        md = gr.Code(label="", language="markdown", lines=24)
    with gr.Accordion("Signed probe output (JSON)", open=False):
        raw = gr.Code(label="", language="json", lines=18)

    picker.change(load_example, picker, spec)
    go.click(run_audit, spec, [out, md, raw])

if __name__ == "__main__":
    demo.launch()
