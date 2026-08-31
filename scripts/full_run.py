#!/usr/bin/env python3
"""Run every arm over the audited corpus and write the evidence tree.

Arms available without an API key or a GPU:
  assay            the full probe battery
  check_env        the incumbent structural linter (gymnasium/SB3 equivalent)
  flag_nothing     trivial detector
  flag_everything  trivial detector

The LLM arms (one direct prompt, one general agent with tools) are added by
`--arms` once credentials are configured; they are deliberately not required
to reproduce the headline comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.baselines import DirectPromptArm, StructuralCheckArm, ToolAgentArm  # noqa: E402
from assay.corpus import (  # noqa: E402
    availability,
    entries,
    scored_entries,
    scored_ground_truth,
    unavailable,
    unscored,
)
from assay.costs import all_profiles, load  # noqa: E402
from assay.metrics import ArmResult, Outcome, normalized_loss, trivial_arms  # noqa: E402


def _closing(adapter):
    """Some adapters hold a container open; give them the chance to clean up."""
    return adapter if hasattr(adapter, "__enter__") else _NullCtx(adapter)


class _NullCtx:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *exc):
        return False


def run_assay(corpus, ctx: dict | None = None, label: str = "assay") -> ArmResult:
    arm = ArmResult(label)
    for env_id, factory, planted in corpus:
        with _closing(factory()) as adapter:
            report = audit(adapter, ctx)
        arm.outcomes.append(
            Outcome(env_id, planted, frozenset(report.detected),
                    frozenset(report.unchecked))
        )
        print(f"  {label}: {env_id} -> {sorted(d.value for d in report.detected) or '-'}",
              flush=True)
    return arm


def run_auditor_arm(
    corpus, client, label: str = "assay+auditor", gate_input: str = "instructions"
) -> tuple[ArmResult, dict]:
    """The same battery, read by the Auditor before the verdict is recorded.

    This exists to answer one criticism directly: every number this submission
    leads with is produced with the agent switched off. Here is the number with
    it on, on the same corpus, so the comparison is a row rather than an
    argument.

    One Auditor across the whole run, not one per environment, because the
    memory is the point -- `results/auditor_memory.json` measures the twelve
    toy-triage fixtures costing one model call between them.
    """
    from assay.auditor import Auditor

    auditor = Auditor(client, gate_input=gate_input)
    result = ArmResult(label)
    for env_id, factory, planted in corpus:
        with _closing(factory()) as adapter:
            report = auditor.audit(adapter)
        result.outcomes.append(
            Outcome(env_id, planted, frozenset(report.detected),
                    frozenset(report.unchecked))
        )
        print(f"  {label}: {env_id} -> {sorted(d.value for d in report.detected) or '-'}",
              flush=True)
    return result, {
        "backend": getattr(client, "name", "unknown"),
        "gate_input": gate_input,
        "model_calls": auditor.calls,
        "decisions": auditor.decisions,
        "overrides": [o.to_dict() for o in auditor.overrides],
    }


def run_arm(corpus, arm) -> tuple[ArmResult, dict]:
    """Any baseline exposing .run(adapter) -> (detected, log)."""
    result = ArmResult(arm.arm)
    logs = {}
    for env_id, factory, planted in corpus:
        with _closing(factory()) as adapter:
            detected, log = arm.run(adapter)
        result.outcomes.append(Outcome(env_id, planted, frozenset(detected)))
        logs[env_id] = log
    return result, logs


def run_check_env(corpus) -> tuple[ArmResult, dict]:
    arm = ArmResult("check_env")
    issues = {}
    checker = StructuralCheckArm()
    for env_id, factory, planted in corpus:
        with _closing(factory()) as adapter:
            detected, found = checker.run(adapter)
        arm.outcomes.append(Outcome(env_id, planted, detected))
        issues[env_id] = found
    return arm, issues


def _eco(env_id: str) -> str:
    """Ecosystem from an env id. The manifest is authoritative in general, but
    every corpus id is `<ecosystem>/<name>` by registry convention and this
    runs over outcomes, which do not carry a manifest."""
    return env_id.split("/", 1)[0]


def _refuse_to_shrink(path: Path, arms: dict) -> None:
    """Never let a reproduction run delete evidence from the file it replaces.

    The command quoted in every document is `scripts/full_run.py` with no
    `--out`, so it writes `results/full_run.json` in place. That file carries
    eight arms; the quoted command produces six, because the two LLM baselines
    need `--llm-arms` and a live Ollama. A judge reproducing the headline
    therefore *destroyed* the baseline evidence for the section they had just
    read -- 523 deletions, 0 insertions -- and nothing said so.

    Refuse instead. The number is reproducible either way; what is not
    recoverable is an arm nobody re-ran.
    """
    if not path.exists():
        return
    try:
        previous = json.loads(path.read_text()).get("arms", {})
    except (OSError, ValueError):
        return
    lost = sorted(set(previous) - set(arms))
    if lost:
        raise SystemExit(
            f"refusing to overwrite {path}: it has {len(previous)} arms and this run "
            f"produced {len(arms)}, which would delete {lost}.\n"
            "Re-run with the missing arms, or write somewhere else:\n"
            f"  --llm-arms qwen3:8b        # restores {lost}\n"
            "  --out /tmp/check.json      # compare without replacing the artifact"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    ap.add_argument("--profile", default="research-run")
    ap.add_argument(
        "--skip", nargs="*", default=[], metavar="ECOSYSTEM",
        help="ecosystems to leave out (fixture, inspect_ai, harbor, ...)",
    )
    ap.add_argument(
        "--only", nargs="*", default=None, metavar="ECOSYSTEM",
        help="restrict the corpus to these ecosystems",
    )
    ap.add_argument(
        "--challenger",
        choices=["scripted", "ollama", "claude"],
        default="scripted",
        help="which Challenger the assay arm uses; the agentic component is ablatable "
        "and scripted is the default so the headline needs no model",
    )
    ap.add_argument("--challenger-model", default="qwen3:8b")
    ap.add_argument("--challenger-turns", type=int, default=10)
    ap.add_argument(
        "--llm-arms",
        metavar="MODEL",
        help="also run the two LLM baselines with this ollama model (e.g. qwen3:8b)",
    )
    ap.add_argument(
        "--allow-reduced",
        action="store_true",
        help="report a headline from a corpus missing a provider. Off by default: "
             "the environments that go missing are the ones Assay does worst on, so "
             "a reduced run reports a *better* number and calls it success.",
    )
    ap.add_argument(
        "--auditor-arm",
        metavar="BACKEND",
        help="also run `assay+auditor`: the same battery read by the Auditor "
             "before the verdict is recorded. An ollama tag, or 'claude'. The "
             "headline arm stays deterministic; this is the row that answers "
             "'every number here is produced with the agent switched off'.",
    )
    args = ap.parse_args()

    have = {name: reason for name, (_ok, reason) in availability().items()}
    # Audit everything; score only what has established labels. An unaudited
    # environment carries frozenset(), which is the same value a verified-clean
    # one carries and not the same claim -- and on this loss function the
    # difference is worth 14 x false_alarm to the trivial floor and nothing to
    # a truthful detector. Scoring them would grow the headline for work nobody
    # did. See docs/PRE-REGISTRATION.md.
    audited = entries(only=args.only, skip=args.skip)
    corpus = scored_entries(only=args.only, skip=args.skip)
    truth = scored_ground_truth(only=args.only, skip=args.skip)
    held_out = unscored(only=args.only, skip=args.skip)
    profile = load(args.profile)

    ctx: dict = {}
    label = "assay"
    if args.challenger != "scripted":
        from assay.challenger.prompted import PromptedChallenger
        from assay.llm import ClaudeCLIClient, OllamaClient

        client = ClaudeCLIClient() if args.challenger == "claude" else OllamaClient(
            args.challenger_model
        )
        usable, reason = client.availability()
        if not usable:
            print(f"SKIPPING prompted challenger: {reason}")
            print("an arm missing from a comparison is a result about the run, not the method")
        else:
            from assay.challenger import CompositeChallenger, ScriptedChallenger

            # Composed, never substituted: the prompted Challenger alone lost a
            # defect the fixed repertoire catches for free.
            ctx["challenger"] = CompositeChallenger(
                [
                    ScriptedChallenger(),
                    PromptedChallenger(client=client, turns=args.challenger_turns),
                ]
            )
            label = f"assay+{ctx['challenger'].name}"
            print(f"assay arm uses {label}\n", flush=True)

    arms = {label: run_assay(corpus, ctx or None, label)}
    check_arm, check_issues = run_check_env(corpus)
    arms["check_env"] = check_arm
    arms.update(trivial_arms(truth))

    arm_logs: dict[str, dict] = {"check_env": check_issues}
    if args.llm_arms:
        from assay.llm import OllamaClient

        client = OllamaClient(args.llm_arms)
        usable, reason = client.availability()
        if not usable:
            print(f"SKIPPING llm arms: {reason}")
            print("an arm missing from a comparison is a result about the run, not the method")
        else:
            for arm in (DirectPromptArm(client), ToolAgentArm(client)):
                print(f"running baseline arm: {arm.arm} ({client.name}) ...", flush=True)
                result, logs = run_arm(corpus, arm)
                arms[arm.arm] = result
                arm_logs[arm.arm] = logs

    if args.auditor_arm:
        from assay.llm import ClaudeCLIClient, OllamaClient

        client = (
            ClaudeCLIClient() if args.auditor_arm == "claude"
            else OllamaClient(args.auditor_arm)
        )
        usable, reason = client.availability()
        if not usable:
            print(f"SKIPPING auditor arm: {reason}")
            print("an arm missing from a comparison is a result about the run, not the method")
        else:
            print(f"running auditor arm ({client.name}) ...", flush=True)
            result, logs = run_auditor_arm(corpus, client)
            arms[result.arm] = result
            arm_logs[result.arm] = logs

    rows = {}
    for name, arm in arms.items():
        row = arm.profile_row(profile)
        row["normalized_loss"] = round(normalized_loss(arm, truth, profile), 4)
        rows[name] = row

    # --out takes a directory or a .json file. Passing a filename used to
    # create a directory with that name and write full_run.json inside it.
    out = Path(args.out)
    if out.suffix == ".json":
        out.parent.mkdir(parents=True, exist_ok=True)
        target = out
    else:
        out.mkdir(parents=True, exist_ok=True)
        target = out / "full_run.json"
    payload = {
        "runtime_availability": have,
        "unavailable": unavailable(),
        "corpus_size": len(corpus),
        "audited_size": len(audited),
        # Held out of every number above, with the reason. Reported as loudly
        # as `unavailable`, because a corpus that silently grew flatters an arm
        # exactly as much as one that silently shrank.
        "unscored": held_out,
        "total_planted_defects": sum(len(v) for v in truth.values()),
        "cost_profile": {"name": profile.name, "description": profile.description},
        "arms": rows,
        "per_env": {
            o.env_id: {
                "planted": sorted(d.value for d in o.planted),
                "assay_detected": sorted(d.value for d in o.detected),
                "missed": sorted(d.value for d in o.missed),
                "spurious": sorted(d.value for d in o.spurious),
            }
            for o in arms[label].outcomes
        },
        "arm_logs": arm_logs,
        # Every arm's per-environment detections, so downstream analysis reads
        # what an arm actually did instead of assuming. intervals.py used to
        # reconstruct check_env as detecting nothing, which silently discarded
        # the determinism check the real gymnasium checker performs.
        "arm_detections": {
            name: {
                o.env_id: sorted(d.value for d in o.detected) for o in arm.outcomes
            }
            for name, arm in arms.items()
        },
        # Per-ecosystem, so one ecosystem dominating the pooled number is
        # legible in the artifact rather than only in corpus_splits.py, which
        # is a separate script that CI does not run and the README does not
        # quote.
        "by_ecosystem": {
            eco: {
                "n_environments": sum(1 for o in arms[label].outcomes if _eco(o.env_id) == eco),
                "n_planted": sum(
                    len(o.planted) for o in arms[label].outcomes if _eco(o.env_id) == eco
                ),
                "arms": {
                    name: ArmResult(
                        name, [o for o in arm.outcomes if _eco(o.env_id) == eco]
                    ).profile_row(profile)
                    for name, arm in arms.items()
                },
            }
            for eco in sorted({_eco(o.env_id) for o in arms[label].outcomes})
        },
    }
    if unavailable() and not args.allow_reduced:
        raise SystemExit(
            "refusing to write a headline from a reduced corpus.\n"
            f"missing providers: {sorted(unavailable())}\n"
            "The environments a missing provider takes with it are the ones Assay "
            "does worst on, so a reduced run reports a BETTER number and exits 0 -- "
            "which is the shape of defect this tool exists to find. Measured: the "
            "documented command without `--extra sweep` gave 24 environments and "
            "assay 0.0 at recall 1.000, against the real 28 and 43.0.\n"
            "Install what is missing, or pass --allow-reduced to say you meant it."
        )
    _refuse_to_shrink(target, payload["arms"])
    target.write_text(json.dumps(payload, indent=2, sort_keys=True))

    width = max(len(n) for n in rows)
    print(f"corpus: {len(corpus)} environments, {payload['total_planted_defects']} planted defects")
    if len(audited) != len(corpus):
        print(f"        {len(audited)} audited, {len(held_out)} held out of scoring")
    missing = unavailable()
    for name, reason in missing.items():
        print(f"WARNING: {name} unavailable, corpus is reduced -- {reason}")
    for env_id, reason in sorted(held_out.items()):
        print(f"UNSCORED: {env_id} -- {reason}")
    print(f"cost profile: {profile.name}\n")
    header = f"{'arm':{width}}  {'exp.loss':>9} {'norm':>7} {'recall':>7} {'prec':>7} {'miss':>5} {'spur':>5}"
    print(header)
    print("-" * len(header))
    for name, row in sorted(rows.items(), key=lambda kv: kv[1]["expected_loss"]):
        print(
            f"{name:{width}}  {row['expected_loss']:>9.1f} {row['normalized_loss']:>7.3f} "
            f"{row['recall']:>7.3f} {row['precision']:>7.3f} "
            f"{row['n_missed']:>5} {row['n_spurious']:>5}"
        )
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
