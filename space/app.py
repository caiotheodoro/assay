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

BLANK = """<div class="assay-idle">
Paste a spec, or load an example, then press <b>Audit</b>.
</div>"""


def _banner(report) -> str:
    cov = report.coverage
    colour = VERDICT_COLOUR[report.verdict]
    return f"""
<div class="assay-banner" style="border-left:6px solid {colour}">
  <div class="assay-verdict" style="background:{colour}">{report.verdict}</div>
  <div class="assay-meaning">{VERDICT_MEANING[report.verdict]}</div>
  <div class="assay-coverage">
    <span><b>{cov['PASS']}</b> passed</span>
    <span><b>{cov['DEFECT']}</b> found defects</span>
    <span class="assay-skip"><b>{cov['NOT_APPLICABLE']}</b> could not run</span>
    <span><b>{cov['ERROR']}</b> errored</span>
  </div>
  <div class="assay-exit">Exit code <code>{report.exit_code}</code> &mdash;
    nonzero for anything that is not <code>VALID</code>, including
    <code>UNVERIFIED</code>. No defects found is not the same as no defects.</div>
</div>"""


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
        f"<tr><td><code>{r.probe}</code></td><td>{r.reason}</td></tr>"
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
            where = f" &mdash; <code>{f.task_id}</code>" if f.task_id else ""
            note = f.evidence.get("note")
            ev = "; ".join(
                f"<code>{k}</code>: {str(v)[:160]}"
                for k, v in f.evidence.items()
                if k not in {"note", "attacker_trace"}
            )
            items.append(
                f"<li><b>{f.defect.value}</b>{where}"
                + (f"<blockquote>{note}</blockquote>" if note else "")
                + (f"<div class='assay-ev'>{ev}</div>" if ev else "")
                + "</li>"
            )
        blocks.append(
            f"<h4 class='sev-{severity.value.lower()}'>{severity.value}</h4>"
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
            f'<div class="assay-error"><b>The spec could not be read.</b><br>{exc}</div>',
            "",
            "",
        )
    except Exception:  # noqa: BLE001 -- a crash here is ours, and is reported as ours
        return (
            '<div class="assay-error"><b>Assay crashed reading that spec.</b> That is '
            "a bug in Assay, not a verdict about your environment.<pre>"
            f"{traceback.format_exc()[-1200:]}</pre></div>",
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
            )
            spec = gr.Code(label="Environment spec (JSON)", language="json", lines=22)
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
