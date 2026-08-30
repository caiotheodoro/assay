# Disclosure drafts — not sent

Two drafts, both written to go upstream, **neither filed**:

| Draft | Recipient | Finding |
|---|---|---|
| [`inspect_evals-paws-scorer.md`](inspect_evals-paws-scorer.md) | `UKGovernmentBEIS/inspect_evals` | scorer defect found by the wild sweep |
| [`openenv-textarena-seed.md`](openenv-textarena-seed.md) | `huggingface/OpenEnv` | seed handling, pinned by a test here |

## Before either can be sent

Both cite `<REPO_URL>` for the tests that back them, and **there is no remote**
(`git remote -v` is empty). A disclosure that points a maintainer at a
placeholder is worse than no disclosure: it asks them to trust a claim and
then gives them nothing to check it against. The substitution list, complete,
so it is not rediscovered at send time:

- `<REPO_URL>` → the published repository URL, in **both** files (line 68 of each).
- Cross-references to `docs/REPRODUCTION.md:51` have drifted; the setup block is
  now at **`:53`**. Check line numbers against the file at send time rather than
  trusting these.
- Neither draft has been reviewed by anyone but its author. A finding sent
  upstream is a claim about someone else's code, which is the case where the
  validator-independence rule matters most.

Filing is a decision the author makes, not a step this repo takes on its own.
Nothing here has been submitted, and no maintainer has been contacted.
