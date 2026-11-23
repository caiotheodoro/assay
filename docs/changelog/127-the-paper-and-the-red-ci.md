# The paper, and the red CI

2026-11-23. `paper/assay.tex` is the first paper from this repository. Writing it with every number
tied to an artifact turned up four things the documents had wrong, and a CI failure that had been
red since 2026-09-19 turned out to be a test measuring the runner.

## The red CI

Two tests required the `inspect_evals` and `tau2` corpus providers, which CI's first job does not
install (`uv sync --extra dev --extra adapters --extra openenv`):
`test_the_corpus_now_contains_environments_the_gate_can_act_on` and
`test_every_environment_the_gate_measurement_names_can_actually_be_built`. Reproduced exactly by
running that extra set with the tau2 snapshots absent. Neither was an error in a published claim.
Both now skip with the extra named, and `the-doc-gates-actually-run` fails if either skips under the
documented command.

## What the paper's test found wrong

Recorded as retraction 22 in `docs/RETRACTIONS.md`:

- `docs/RESULTS.md` per-arm, paired and per-profile tables had drifted from `results/intervals*.json`
  (four arms' intervals, three recalls, every LLM-arm paired difference, three of the four profile rows);
  its provenance table still said 6 external environments and 22/3/3 labels, where the registry says 8
  and 25/5/3.
- `AGENTS.md` gave precision 0.9464 and three spurious findings; it is 0.7571 and seventeen.
  `docs/FOR_AGENTS.md` quoted a crossover of 1173.0 and a margin of 351.0.
- Three documents quoted 28.5% of 49 SWE-bench Verified tasks from the first version of arXiv
  2606.16062; the current version says 22.4%.
- `results/agentic_profile.json` names a replacement run, `results/agentic_runs/harbor_post_taxonomy.json`,
  that was never committed.

Not found wrong, and said in the paper rather than fixed: on the 8 external environments the saving over
`flag_everything` is 76.0, 95% CI [-4, 121], not separated, and `production-training` goes to the floor
there (250.0 against 242.0); the crossover on that split is a CRITICAL cost of 348, inside the
repair-effort range in `results/cost_unit.json`. The README now carries both.

## What is gated

`scripts/export_paper_tables.py` writes `paper/generated/` (macros, tables, figures) from `results/`.
`tests/test_paper.py` fails if that directory is stale, if a digit appears in the prose outside a short
allow-list of cited sources, if the committed PDF loses a number or a float, if the committed PDF is not
what the source builds (where `tectonic` is present), if a pre-registration was not committed before its
code, if `docs/RESULTS.md` tables differ from the committed intervals, if the deposit metadata and the
bibliography cite different works, or if a retired figure returns to a document.

## Deposit

Zenodo draft prepared, **not published**; `.zenodo.json` and `CITATION.cff` carry the metadata and name
no DOI, because none exists until the owner publishes. The record's date will be its real publication
date. The deposit is not the registration clock: the registrations are the four
`docs/PRE-REGISTRATION*.md` files, ordered before their code in git history, and they are commits by
the same author with no outside timestamp.

## Found, not fixed

`python scripts/merge_changelog.py --check` already fails at the commit this branched from:
`docs/CHANGELOG.md` is behind its fragments. Merging them is the documented process, and doing it
trips `test_the_retracted_k1_semantic_gate_figures_are_gone_including_from_help`, because two fragments
quote the retracted 1-of-1 figures verbatim. `docs/CHANGELOG.md` is left as committed and this
fragment is not merged into it; fixing the gate or the two fragments is a separate decision.

## Not done


The agentic Challenger was not re-run (about 45 minutes of paid sampling), a published auditor was not
run as an arm, no prevalence-aware floor was added, and the corpus was not re-labelled by a human. The
paper lists each as unrun.

## Reversal

If a figure in the paper or in the tables above is found wrong, the next entry corrects it and the
paper is re-deposited as a new version; this entry is not edited.
