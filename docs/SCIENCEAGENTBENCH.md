# ScienceAgentBench — what Assay can and cannot check

## Status

Two of the three defect families BenchGuard reports are **out of reach for Assay by design**,
and the third needs one manual download. Both facts are results, not excuses.

## What was tried and rejected

`scripts/sab_metadata_probe.py` tests whether instruction defects fall out of the metadata
ScienceAgentBench publishes per task. They do not:

| Rule | INST recall | Fires on | Precision |
|---|---|---|---|
| output path the instruction never names | 5/7 | **61 / 102** | 0.08 |
| input file absent from the dataset tree | 0/7 | 0 / 102 | — |

Measured only against BenchGuard's 12 known-defective tasks, the first rule reads as a
success. Measured against the whole benchmark it flags 60% of it — the flag-everything
trivial policy in disguise, caught by Assay's own trivial-floor rule.

**Conclusion: Assay structurally cannot find instruction defects.** "This instruction is
ambiguous" and "this requirement is infeasible" are judgements, and Assay scores nothing
with a judge. Assay and BenchGuard find **disjoint** classes of defect — instruction quality
needs judgement, verifier defects need execution — and neither subsumes the other.

## The manual step, if you want the execution probes

The GT and EVAL defects need SAB's gold programs and eval scripts. Those are not on the Hub;
they are in a password-protected archive behind a SharePoint link that requires a browser
session, so this cannot be scripted end to end.

1. Open the benchmark artifacts link in
   [the ScienceAgentBench README](https://github.com/OSU-NLP-Group/ScienceAgentBench)
   (`benchmark_verified.zip`).
2. Unzip with the password `scienceagentbench`.
3. Place the result at `third_party/ScienceAgentBench/benchmark/`.

Then the SAB adapter can drive its Docker execute-and-diff harness the way the Harbor
adapter drives `tests/test.sh`.

**Redistribution:** the upstream README says plainly *"Please DO NOT redistribute the
unzipped data files online."* Nothing from that archive goes into `caiotheodoro/assay-corpus`
or any other published artifact. Only derived per-task verdicts — which contain no benchmark
content — may be published.

## A conflict worth stating

Some ScienceAgentBench tasks (the data-visualization ones) are scored by an LLM judge
(`gpt4_visual_judge.py`). Assay's probes assume the verifier is a deterministic function of
the transcript. Against a judge, `inverted_fails` and `known_wrong_fails` are not measuring
verifier integrity — they are measuring a model's mood on the day.

Those tasks must be excluded from any execution audit, with the reason recorded per task,
rather than quietly scored. An environment Assay cannot honestly probe is reported as
`NOT_APPLICABLE`, which is the whole design.
