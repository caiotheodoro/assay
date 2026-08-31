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

The rendering itself lives in `assay.card.web`, not here. It moved when the
browser build (`space/static/`) became a second caller: two copies of an
escaping renderer is precisely how the slice-36 injection happened, and one
copy under one set of tests is the fix. This file is the Gradio shell over it.
"""

from __future__ import annotations

import json
from pathlib import Path

import gradio as gr

from assay.card import web

HERE = Path(__file__).parent
EXAMPLES = json.loads((HERE / "examples.json").read_text())

# Re-exported under the names the tests and the publication gates already use.
# The definitions are in `assay.card.web`; these are the aliases, not copies.
VERDICT_COLOUR = web.VERDICT_COLOUR
VERDICT_MEANING = web.VERDICT_MEANING
SEVERITY_ORDER = web.SEVERITY_ORDER
SAMPLER_ONLY = web.SAMPLER_ONLY
CSS = web.CSS
_e = web.escape

#: The example the page opens on. Not the healthy one: a visitor who lands on
#: an environment with nothing wrong learns what the UI looks like and nothing
#: about why the tool exists.
PRELOADED = "3 — Substring verifier: one constant string answers both labels"

BLANK = """<div class="assay-idle">
Paste a spec, or load an example, then press <b>Audit</b>.
</div>"""


def run_audit(spec_text: str):
    """`(card HTML, card as Markdown, signed probe JSON)`."""
    return web.audit_spec(spec_text)


def load_example(name: str):
    for ex in EXAMPLES:
        if ex["name"] == name:
            return json.dumps(ex["spec"], indent=2)
    return ""


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
