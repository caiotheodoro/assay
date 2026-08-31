# Disclosures — both filed

Two upstream bug reports, **both filed 2026-08-31**:

| Report | Recipient | Finding | Filed |
|---|---|---|---|
| [`inspect_evals-paws-scorer.md`](inspect_evals-paws-scorer.md) | `UKGovernmentBEIS/inspect_evals` | scorer defect found by the wild sweep | [#2331](https://github.com/UKGovernmentBEIS/inspect_evals/issues/2331) |
| [`openenv-textarena-seed.md`](openenv-textarena-seed.md) | `huggingface/OpenEnv` | seed handling, pinned by a test here | [#1102](https://github.com/huggingface/OpenEnv/issues/1102) |

Both now cite a real repository (`https://github.com/caiotheodoro/assay`), so a
maintainer can check the tests behind each claim. That was the blocker; it is
gone.

## Still not sent, on purpose

Filing is the author's decision, not a step this repo takes on its own. Nothing
has been submitted and no maintainer has been contacted.

Two things to do before either goes out:

- **Check the line references.** Cross-references drift. `docs/REPRODUCTION.md`
  moved from `:51` to `:53` once already.
- **Get a second reader.** Neither draft has been reviewed by anyone but its
  author. A disclosure is a claim about someone else's code, which is the case
  where an independent check matters most.

Both findings are correctness bugs in public benchmarks — a scorer that accepts
wrong answers, and seed handling that does not vary the episode. Neither is a
security issue, and both are already described in `docs/RED-TEAM.md` and the
wild-sweep results, so publishing this repo does not disclose anything the rest
of it does not.
