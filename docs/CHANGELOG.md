# Improvement Changelog

One row per meaningful experiment, including the ones that were removed.
Evidence is a command anyone can rerun.

| Stage | What was tried and why | Evidence | Decision / learning |
|---|---|---|---|
| Slice 1 | Core adapter protocol, 9 probe families, 12 fixture environments with planted defects. Establish that every probe fires on something real before writing any adapter against a real ecosystem. | `uv run pytest -q` → 27 passed | **Kept.** Detection matches ground truth exactly on all 12 fixtures. |
| Slice 1a | Probes 2 (trivial floor) and 3 (separability) compared policies **per task**. | `rationale_ignored` reported a spurious `TRIVIAL_FLOOR_BREACH`; `escalate_overrewarded` was correct | **Revised to aggregate over the task set.** Per task, a trivial policy wins wherever the trivial answer happens to be right — that is small-n noise, not a property of the environment. This is the same "tyranny of the average" trap read from the other direction: the average is wrong for reporting a profile, and right for a floor claim. |
| Slice 1b | First MinHash fixture used a 23-word sentence with 5-word shingles. | estimated Jaccard 0.789 < 0.80 threshold; near-dup not caught | **Fixture was wrong, not the detector.** A one-word edit in a 23-word text really is a rewrite: it breaks 5 of ~19 shingles. Lengthened the fixture to ~70 words (5 of ~66). Recorded because it is a live trap for anyone applying a shingle-5 near-dup audit to short items — the detector silently under-reports on short text. |
| Slice 1c | Test asserted a healthy environment yields verdict `VALID`. | verdict was `UNVERIFIED`, because the difficulty probe cannot run without a solve-rate estimate | **The code was right and the test was wrong.** No defects found is not the same as no defects. An environment with a probe that could not run is `UNVERIFIED` and still exits nonzero. Fail closed. |
| Slice 1d | Test asserted planted defects were a **subset** of detected. | passed, but would also pass for a probe that flags everything | **Tightened to exact match.** Recall alone cannot separate detection from guessing. Two fixtures then legitimately gained defect labels: a verifier that passes at reset is broken on every axis, and an over-broad oracle also accepts an inverted spec. |
