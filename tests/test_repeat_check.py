"""The battery must give the same answer twice on the same tree.

`docs/REPRODUCTION.md` has claimed byte-identical reruns for most of this
project's life, and until now nothing that runs had checked it. The claim came
under suspicion when one `assay+auditor` run reported
`openenv/textarena-wordle` with no defects where four subsequent measurements
report NONDETERMINISM. No mechanism was ever found, which is precisely the
situation an instrument is for.

The fast gate here runs the fixture environments, which need no Docker daemon
and no network. `scripts/repeat_check.py` runs the same comparison over the
whole corpus and writes `results/repeat_check.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assay.corpus import scored_entries
from assay.runner import audit

ROOT = Path(__file__).resolve().parents[1]


def _twice(env_id, factory):
    seen = []
    for _ in range(2):
        adapter = factory()
        try:
            report = audit(adapter, None)
            seen.append((
                tuple(sorted(d.value for d in report.detected)),
                tuple(sorted((r.probe, r.status.value) for r in report.results)),
            ))
        finally:
            close = getattr(adapter, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass
    return seen


@pytest.mark.parametrize(
    "env_id",
    [e for e, _, _ in scored_entries() if e.startswith(("fixture/", "noanswer/", "toy-triage/"))],
)
def test_the_battery_gives_the_same_answer_twice(env_id):
    """Same tree, same environment, two audits in one process."""
    factory = next(f for e, f, _ in scored_entries() if e == env_id)
    first, second = _twice(env_id, factory)
    assert first[0] == second[0], (
        f"{env_id} reported different defects on two runs of the same tree: "
        f"{first[0]} then {second[0]}"
    )
    assert first[1] == second[1], (
        f"{env_id} reported the same defects but a different probe status on the "
        "second run, which is a divergence the detections alone would hide"
    )


def test_the_recorded_full_corpus_repeat_check_found_no_divergence():
    """`results/repeat_check.json` is the whole-corpus version of the gate above."""
    path = ROOT / "results/repeat_check.json"
    if not path.exists():
        pytest.skip("no recorded repeat check; run scripts/repeat_check.py")
    recorded = json.loads(path.read_text())
    assert recorded["n_divergences"] == 0, (
        "the recorded full-corpus repeat check found divergences:\n"
        + json.dumps(recorded["divergences"], indent=2)
    )
    assert recorded["passes"] >= 2
