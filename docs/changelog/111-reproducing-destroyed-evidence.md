## Slice 48: reproducing the headline deleted two arms from the artifact

**What and why.** Every document quoted the headline command without `--out`, so
it wrote `results/full_run.json` in place. That file carries **eight** arms. The
quoted command produces **six** — the two LLM baselines need `--llm-arms` and a
live Ollama.

So a judge who followed the reproduction guide, and reproduced the headline
exactly, **destroyed the baseline evidence for the section they had just read**:
523 deletions, 0 insertions, `direct_prompt` and `agent_with_tools` gone. Nothing
warned them, and the run reported success.

Found by a judge doing precisely that.

**Fix, both halves.** `full_run.py` now refuses to overwrite an artifact with
fewer arms than it has, and says which ones would be lost and the two ways to
proceed:

```
refusing to overwrite results/full_run.json: it has 8 arms and this run produced 6,
which would delete ['agent_with_tools', 'direct_prompt'].
  --llm-arms qwen3:8b        # restores ['agent_with_tools', 'direct_prompt']
  --out /tmp/check.json      # compare without replacing the artifact
```

And every quoted command in `README.md`, `AGENTS.md`, `docs/FOR_AGENTS.md` and
`docs/REPRODUCTION.md` now carries `--out /tmp/check.json`, which is the shape a
reproduction should have had all along: produce a fresh file, diff it against the
committed one, leave the committed one alone.

**Decision.** Both. The flag alone would have fixed the documents and left the
trap for anyone running from memory; the guard alone would have turned the
documented command into an error.

**What it cost to learn.** This repository has a CI job whose entire purpose is
re-running the corpus and diffing it against the committed artifact — and it
passes `--out /tmp/ci_run.json`, because whoever wrote it understood the problem
in that context and did not carry it back to the guide. The safe pattern existed
in the codebase the whole time, one file away from the documents that omitted it.
