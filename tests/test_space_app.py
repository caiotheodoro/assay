"""The Space renders a stranger's JSON into HTML on a public host.

It had **no tests at all**, which is the reason the injection below survived
review: `card/render.py` has escaped since it was written, `space/app.py` never
did, and nothing compared the two. A submitted spec is untrusted input by
definition -- the whole product is "paste an environment you did not write" --
so this file treats every string that reaches the page as hostile.

The rest is the gap between what the banner can say and what it could reach:
`VALID` requires every probe to have run, and one probe never can here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("gradio")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "space"))

import app as space_app  # noqa: E402

PAYLOAD = '<img src=x onerror="alert(1)">'


def _spec(**over) -> str:
    spec = {
        "env_id": "you/your-eval",
        "verifier": "includes",
        "tasks": [
            {"task_id": "q1", "instruction": "Answer Yes or No", "target": "Yes",
             "gold": "Yes", "known_wrong": "No"}
        ],
    }
    spec.update(over)
    return json.dumps(spec)


def _audit(spec_text: str) -> str:
    return space_app.run_audit(spec_text)[0]


def test_a_task_id_cannot_inject_html():
    """The confirmed defect: a task id rendered verbatim and executed.

    `includes` against target `Yes` is a real defect, so this submission
    reaches `_findings`, which interpolated `f.task_id` straight into a
    `<code>` element.
    """
    html = _audit(_spec(tasks=[
        {"task_id": PAYLOAD, "instruction": "Answer Yes or No", "target": "Yes",
         "gold": "Yes", "known_wrong": "No"}
    ]))
    assert "<img src=x" not in html, "a submitted task id reached the page as live HTML"
    assert "&lt;img src=x" in html, "the id should still be shown, escaped"


def test_a_malformed_spec_cannot_inject_html_through_its_error_message():
    """`SpecError` quotes the offending value, so the error path is a vector too."""
    html = _audit(json.dumps({"env_id": PAYLOAD, "tasks": []}))
    assert "<img src=x" not in html
    assert "onerror" not in html or "&lt;img" in html


def test_a_skipped_probe_reason_cannot_inject_html():
    """Reasons quote task ids, so `_not_run` carries submitted text as well."""
    html = _audit(_spec(tasks=[
        {"task_id": PAYLOAD, "instruction": "x", "target": "Yes"}
    ]))
    assert "<img src=x" not in html
    assert "could not be checked" in html


def test_every_verdict_colour_has_a_meaning():
    """A `KeyError` in the banner would be a crash on a public page."""
    assert set(space_app.VERDICT_COLOUR) == set(space_app.VERDICT_MEANING)


def test_a_clean_submission_is_told_why_valid_is_out_of_reach():
    """Otherwise a user whose eval is fine sees purple and concludes we are broken.

    `difficulty_band` needs a rollout sampler; a Space without Docker has none,
    so `VALID` is unreachable here no matter how good the submission is.
    """
    html = _audit(_spec(
        verifier="exact",
        tasks=[{"task_id": "q1", "instruction": "Answer Yes or No", "target": "Yes",
                "gold": "Yes", "known_wrong": "No"}],
        train=[{"item_id": "tr1", "text": "a", "label": "Yes"}],
        eval=[{"item_id": "ev1", "text": "b", "label": "No", "parts": {"h": "b"}}],
        asserts="the answer matches the target exactly",
    ))
    if "assay-ceiling" in html:
        assert "rollout sampler" in html
        assert "limit of this Space" in html
    else:
        # Something else was skipped too, in which case the ordinary
        # "what could not be checked" table is the honest message and the
        # ceiling note must stay quiet rather than claim the sampler is the
        # only gap.
        assert "could not be checked" in html


def test_the_ceiling_note_stays_quiet_when_a_defect_was_found():
    """Reassurance next to a critical finding would be the worst of both."""
    html = _audit(_spec())
    assert "assay-ceiling" not in html


def test_the_examples_all_load_and_audit():
    """A broken example is the first thing a visitor sees."""
    for example in space_app.EXAMPLES:
        text = space_app.load_example(example["name"])
        assert text, f"{example['name']} did not load"
        html = _audit(text)
        assert "Assay crashed" not in html, f"{example['name']} crashed the auditor"
