"""Run every agent Assay uses and write its trajectory into the repo.

The deliverable is `results/trajectories/`: one JSON and one markdown per run,
plus an INDEX.md. A judge should be able to read all of it without running
anything, which is why the artefacts are committed rather than generated on
demand.

Agents that cannot run on this machine -- no Ollama, no Docker, no Claude CLI --
are listed in the index with the reason. An agent missing from the deliverable
is a result about this machine, not about the method.

Two Claude CLI runs against `harbor/self-graded` are replayed from committed
result files rather than re-run: `results/challenger_ablation.json`, the run
where that arm found the exploit at turn 8, and
`results/challenger_ablation_claude.json`, the run where the same arm on the
same task missed. Both are real recorded runs. Shipping only the first would
report a nondeterministic agent as a reliable one, and re-running it here would
overwrite whichever of the two came up this time.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay import audit  # noqa: E402
from assay.adapters import HarborAdapter  # noqa: E402
from assay.adapters.harbor import stage_suite  # noqa: E402
from assay.baselines.llm import AGENT_SYSTEM  # noqa: E402
from assay.baselines.llm import SYSTEM as BASELINE_SYSTEM  # noqa: E402
from assay.baselines.llm import DirectPromptArm, ToolAgentArm  # noqa: E402
from assay.challenger import ScriptedChallenger  # noqa: E402
from assay.challenger.prompted import SYSTEM as CHALLENGER_SYSTEM  # noqa: E402
from assay.challenger.prompted import PromptedChallenger  # noqa: E402
from assay.fixtures import CATALOG, build  # noqa: E402
from assay.llm import OllamaClient  # noqa: E402
from assay.rollout import SYSTEM as SOLVER_SYSTEM  # noqa: E402
from assay.rollout import SolveRateSampler  # noqa: E402
from assay.sandbox import (  # noqa: E402
    ApprovalDenied,
    AutoApprove,
    DenyAll,
    DockerSandbox,
    ExecRequest,
    Mount,
    SandboxPolicy,
    SandboxUnavailable,
    docker_available,
)
from assay.trajectory import (  # noqa: E402
    AgentTrajectory,
    Turn,
    from_approval_gate,
    from_baseline_trace,
    from_probe_detail,
    from_solver_trace,
    write_index,
    write_pair,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "src" / "assay" / "fixtures" / "harbor_suite"
HARBOR_TASK = "self-graded"

SANDBOX_APPROVAL = {
    "what": "execute untrusted environment code in the Harbor image",
    "approver": "AutoApprove('trajectory export')",
    "granted": True,
    "detail": "standing approval recorded for this export run; trajectory 08 is "
    "the gate itself, including what happens when it refuses",
}


def harbor(task: str) -> HarborAdapter:
    root = stage_suite(SUITE / task, "assay-traj-")
    return HarborAdapter(
        root,
        sandbox=DockerSandbox(AutoApprove("trajectory export")),
        env_id=f"harbor/{task}",
    )


def harbor_instruction(task: str) -> str:
    return (SUITE / task / "instruction.md").read_text().strip()


def challenger_run(challenger, agent: str, shows: str):
    """Audit harbor/self-graded with one Challenger and build its trajectory."""
    with harbor(HARBOR_TASK) as adapter:
        report = audit(adapter, {"challenger": challenger})
    probe = [r for r in report.results if r.family == "reward_hackability"][0]
    if probe.status.value in ("NOT_APPLICABLE", "ERROR"):
        # A challenger that could not speak is reported as such, never as an
        # arm that ran and found nothing.
        return None, f"probe {probe.status.value}: {probe.reason}"
    per_task = next(iter(probe.detail.get("per_task", {}).values()), {})
    return (
        from_probe_detail(
            agent=agent,
            environment=f"harbor/{HARBOR_TASK}",
            task_id=HARBOR_TASK,
            instruction=harbor_instruction(HARBOR_TASK),
            system_prompt=CHALLENGER_SYSTEM.strip(),
            per_task=per_task,
            shows=shows,
            approvals=[SANDBOX_APPROVAL],
        ),
        None,
    )


def archived_claude(path: Path, agent: str, shows: str):
    """Replay a committed ablation result as a trajectory."""
    if not path.exists():
        return None, f"{path.relative_to(ROOT)} is not in this checkout"
    payload = json.loads(path.read_text())
    arm = next(
        (a for a in payload["arms"] if a["challenger"] == "prompted:claude-cli"), None
    )
    if arm is None:
        return None, f"no claude-cli arm in {path.name}"
    exploit = arm.get("exploit") or {}
    per_task = {
        "attacker_trace": arm.get("attacker_trace", []),
        "attempts": [],
        "n_attempts": arm.get("attempts", 0),
        "best_attempt": {
            "policy": exploit.get("policy", "none scored above the threshold"),
            "gap": arm.get("best_exploit_gap", 0.0),
            "reported": exploit.get("reported"),
            "true": exploit.get("true_completion"),
        },
    }
    approval = dict(SANDBOX_APPROVAL)
    approval["detail"] = f"recorded run, replayed from results/{path.name}"
    traj = from_probe_detail(
        agent=agent,
        environment=f"harbor/{HARBOR_TASK}",
        task_id=HARBOR_TASK,
        instruction=harbor_instruction(HARBOR_TASK),
        system_prompt=CHALLENGER_SYSTEM.strip(),
        per_task=per_task,
        shows=shows,
        approvals=[approval],
    )
    traj.outcome["provenance"] = (
        f"replayed from results/{path.name}, which records the per-turn scores but "
        "not the per-policy score table -- so reported_score and true_completion "
        "are null on a run that found nothing to report them for"
    )
    return traj, None


def auditor_run(client, agent: str, shows: str):
    """The semantic gate on the one environment Assay is wrong about.

    Two turns on purpose. Turn 1 is the model's raw reply, exactly as it came
    back. Turn 2 is `decide()` -- a program -- reading that reply and settling
    the verdict. Keeping them apart in the record is the point: on qwen3:8b the
    two disagree, and a trajectory that showed only the outcome would hide the
    most interesting thing in the run.
    """
    from assay.fixtures.preference import PreferenceEnv

    _build = lambda *_: PreferenceEnv()  # noqa: E731
    adapter = _build()

    from assay.auditor import _PARTS_SYSTEM, _SYSTEM, _parse, decide  # noqa: F401
    from assay.auditor import Auditor
    from assay.runner import audit as run_battery

    before = run_battery(adapter)
    described = adapter.describe()
    try:
        reply = client.complete(_SYSTEM, described)
    except Exception as exc:  # noqa: BLE001
        return None, f"{client.name} unreachable: {exc}"

    parsed = _parse(reply) or {}
    derived = decide(parsed)
    auditor = Auditor(client)
    after = auditor.audit(_build())

    traj = AgentTrajectory(
        agent=agent,
        role="auditor",
        environment="toy-triage/preference",
        task_id="(whole environment)",
        shows=shows,
        system_prompt=_SYSTEM,
        instruction=described[:2000],
        turns=[
            Turn(
                index=1,
                action={"ask_model": "does this environment have a correct answer?"},
                observation=reply.strip(),
                reasoning="the model's reply, unedited",
            ),
            Turn(
                index=2,
                action={
                    "decide": {
                        "label_said": parsed.get("verdict"),
                        "evidence_said": parsed.get("compared_against"),
                    }
                },
                observation={
                    "verdict": derived,
                    "agreed": parsed.get("verdict") == derived,
                },
                reasoning=(
                    "a program, not the model. The override fires only when the "
                    "label and the example agree; either alone is unsound and "
                    "results/semantic_gate.json records the measurement that "
                    "rules each out."
                ),
            ),
        ],
        outcome={
            "battery_alone": {
                "verdict": before.verdict,
                "detected": sorted(d.value for d in before.detected),
            },
            "with_auditor": {
                "verdict": after.verdict,
                "detected": sorted(d.value for d in after.detected),
            },
            "overrides": after.auditor_overrides,
            "ground_truth": (
                "This environment has no correct answer, so INVERT_PASSES is "
                "mechanically right and semantically wrong. It is authored here "
                "because the real case, inspect_evals/personality_BFI, is "
                "third-party content that may not ship in a trajectory. The "
                "measurement against the real one is in "
                "results/semantic_gate.json, which carries verdicts and counts "
                "and no third-party text."
            ),
        },
    )
    return traj, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b", help="ollama model for the live arms")
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--samples", type=int, default=4, help="solver samples per task")
    ap.add_argument("--out", default=str(ROOT / "results" / "trajectories"))
    args = ap.parse_args()

    out = Path(args.out)
    entries: list[tuple] = []
    unavailable: list[dict[str, str]] = []

    def emit(slug: str, traj, reason: str | None, agent: str) -> None:
        if traj is None:
            print(f"SKIP {slug}: {reason}", flush=True)
            unavailable.append({"agent": agent, "reason": reason or "unknown"})
            return
        write_pair(traj, out, slug)
        print(f"wrote {slug}", flush=True)
        entries.append((traj, slug))

    have_docker = docker_available()
    ollama = OllamaClient(args.model)
    have_ollama, ollama_reason = ollama.availability()
    model_slug = args.model.replace(":", "-")

    # 1 -- the scripted Challenger, the floor
    if have_docker:
        traj, why = challenger_run(
            ScriptedChallenger(),
            "scripted",
            "the fixed repertoire, no model in the loop. Four policies, none of "
            "which reads a file or writes to expected.txt, so the exploit is out "
            "of reach. **A miss** -- and that miss is what makes the agentic arm "
            "load-bearing rather than decorative.",
        )
        emit("01-challenger-scripted-harbor-self-graded", traj, why, "scripted")
    else:
        emit(
            "01-challenger-scripted-harbor-self-graded",
            None,
            "docker is not installed or the daemon is not running",
            "scripted",
        )

    # 2 -- the prompted Challenger on a local model
    slug2 = f"02-challenger-ollama-{model_slug}-harbor-self-graded"
    if have_ollama and have_docker:
        traj, why = challenger_run(
            PromptedChallenger(client=ollama, turns=args.turns),
            f"prompted[{ollama.name}]",
            f"a local {args.model} in a feedback loop for {args.turns} turns. It "
            "sees tool output and the environment's score after every turn, and "
            "the harness tells it when it has repeated itself. **A second, "
            "different miss** -- the loop is there, the model does not use it to "
            "go looking for the verifier.",
        )
        emit(slug2, traj, why, f"prompted[{ollama.name}]")
    else:
        emit(
            slug2,
            None,
            ollama_reason if not have_ollama else "docker daemon is not running",
            f"prompted[ollama:{args.model}]",
        )

    # 3, 4 -- the Claude CLI arm, a hit and a miss, from committed runs
    traj, why = archived_claude(
        ROOT / "results" / "challenger_ablation.json",
        "prompted[claude-cli:sonnet]",
        "seven turns of reconnaissance -- hunting the verifier, listing `/logs`, "
        "checking file permissions, trying to write `reward.txt` directly -- then "
        "turn 8 writes `banana` to both `expected.txt` and `out.txt`, and is "
        "**scored 1.0 by the environment and 0.0 by the independent verifier the "
        "agent never had access to**. Turn 9 is a failed retry: tampering with "
        "`reward.txt` directly scores 0.0.",
    )
    emit(
        "03-challenger-claude-cli-harbor-self-graded-found",
        traj,
        why,
        "prompted[claude-cli:sonnet]",
    )

    traj, why = archived_claude(
        ROOT / "results" / "challenger_ablation_claude.json",
        "prompted[claude-cli:sonnet]",
        "the same agent, the same task, a different run -- and it **misses**. "
        "Shipped next to 03 so the hit is not read as a reliable capability.",
    )
    emit(
        "04-challenger-claude-cli-harbor-self-graded-missed",
        traj,
        why,
        "prompted[claude-cli:sonnet]",
    )

    # 5 -- the Solver behind the difficulty probe
    slug5 = "05-solver-difficulty-toy-triage-healthy"
    if have_ollama:
        env = build("healthy")
        sampler = SolveRateSampler(client=ollama, samples=args.samples)
        rates = sampler.solve_rates(env)
        emit(
            slug5,
            from_solver_trace(
                agent=sampler.name,
                environment="toy-triage/healthy",
                trace=sampler.trace,
                solve_rates=rates,
                instruction=env.manifest().tasks[0].instruction,
                system_prompt=SOLVER_SYSTEM.strip(),
                shows="the difficulty probe estimating a solve rate by actually "
                "attempting the tasks, rather than assuming one. Every sample is "
                "here, including the replies that were not JSON -- those are "
                "failed attempts, not skipped ones, and dropping them would raise "
                "the rate by deleting the dullest failures.",
            ),
            None,
            sampler.name,
        )
    else:
        emit(slug5, None, ollama_reason, f"solver[ollama:{args.model}]")

    # 6, 7 -- the two LLM baseline arms the brief names
    planted = sorted(d.value for d in CATALOG["weak_oracle"])
    baselines = [
        (
            "06-baseline-direct-prompt-toy-triage-weak-oracle",
            lambda: DirectPromptArm(ollama),
            BASELINE_SYSTEM,
            "one prompt, everything a careful human reviewer could read, one "
            "answer. It gets the exact defect taxonomy Assay reports against and "
            "the same source access Assay has. It never gets the planted ground "
            "truth -- that is recorded in the outcome after the fact, so a reader "
            "can see whether it was right.",
        ),
        (
            "07-baseline-agent-with-tools-toy-triage-weak-oracle",
            lambda: ToolAgentArm(ollama, turns=6),
            AGENT_SYSTEM,
            "the same brief, plus turns in which it may actually run things in the "
            "environment. Every turn it sees the tool output and the score the "
            "environment gave, and that feedback is all it has to reason from.",
        ),
    ]
    for slug, make_arm, system, shows in baselines:
        if not have_ollama:
            emit(slug, None, ollama_reason, f"{slug.split('-')[2]}[ollama:{args.model}]")
            continue
        arm = make_arm()
        env = build("weak_oracle")
        defects, _log = arm.run(env)
        emit(
            slug,
            from_baseline_trace(
                agent=f"{arm.arm}[{ollama.name}]",
                arm=arm.arm,
                environment="toy-triage/weak_oracle",
                task_id=env.manifest().tasks[0].task_id,
                trace=arm.trace,
                instruction="Which validity defects, if any, does this environment have?",
                system_prompt=system.strip(),
                reported_defects=sorted(d.value for d in defects),
                ground_truth=planted,
                shows=shows,
            ),
            None,
            f"{arm.arm}[{ollama.name}]",
        )

    # 8 -- the human approval checkpoint
    policy = SandboxPolicy(image="alpine:3.20", network=False)
    request = ExecRequest(
        policy=policy,
        command=["sh", "-c", "cat expected.txt"],
        mounts=[Mount(source=SUITE / HARBOR_TASK / "environment", target="/work")],
    )
    denying = DockerSandbox(DenyAll())
    try:
        denying.run(request)
        refusal = "the request was EXECUTED -- the gate did not hold"
    except ApprovalDenied as exc:
        refusal = f"ApprovalDenied: {exc}"
    except SandboxUnavailable as exc:
        refusal = f"never reached the approver: {exc}"
    events = [
        {
            "approver": "DenyAll",
            "request": request,
            "granted": False,
            "reason": "the default approver. An unattended Assay executes nothing.",
            "outcome": f"{refusal} — requests recorded as approved: {len(denying.approvals)}",
        }
    ]

    approving = DockerSandbox(AutoApprove("standing approval for the trajectory export"))
    if have_docker:
        result = approving.run(request)
        outcome = (
            f"approved and executed: exit {result.exit_code}, "
            f"stdout {result.stdout.strip()[:80]!r}"
        )
    else:
        outcome = "approved, but docker is not running, so nothing executed"
    events.append(
        {
            "approver": "AutoApprove('standing approval for the trajectory export')",
            "request": request,
            "granted": True,
            "reason": "explicit standing approval, carrying a reason. An approval "
            "nobody can account for later is the same as no approval.",
            "outcome": outcome,
        }
    )
    emit(
        "08-sandbox-approval-gate-harbor-self-graded",
        from_approval_gate(
            environment=f"harbor/{HARBOR_TASK}",
            task_id=HARBOR_TASK,
            events=events,
            # Render mount sources relative to the repo. An absolute path baked
            # into a committed artefact is one machine's filesystem, not
            # evidence anyone else can read.
            root=ROOT,
            shows="**the human checkpoint.** The identical request is put to two "
            "approvers: the default refuses and nothing runs, an explicit standing "
            "approval carrying a reason lets it through. Nothing in Assay executes "
            "untrusted environment code without one of these.",
        ),
        None,
        "sandbox approval gate",
    )

    # 9 and 10 -- the Auditor, on the one environment Assay is wrong about.
    # Shipped as a pair for the same reason 03 and 04 are: the weaker backend
    # refuses to override and the stronger one does, and showing only the
    # success would make a capability out of a coin flip.
    auditor_cases = [
        (
            "09-auditor-ollama-%s-preference-refused" % model_slug,
            ollama if have_ollama else None,
            ollama_reason,
            f"auditor[ollama:{args.model}]",
            "**the refusal, and why it is the right one.** The model writes a "
            "genuinely valid both-ways example into turn 1 and then labels the "
            "environment `has_correct_answer` anyway, contradicting its own "
            "evidence. The gate is the conjunction of the two, so nothing is "
            "overridden and the deterministic CRITICAL stands. A weak Auditor "
            "loses recall and cannot lose precision.",
        ),
        (
            "10-auditor-claude-cli-preference-withheld",
            ClaudeCLIClient(),
            None,
            "auditor[claude-cli:sonnet]",
            "**the capability `docs/COVERAGE.md` says does not exist.** Same "
            "environment, same prompt, a backend that holds label and evidence "
            "together -- so a CRITICAL false positive on a correctly-designed "
            "eval is withheld, with the task text that justifies it quoted on "
            "the card. The battery alone reports INVALID here and is wrong.",
        ),
    ]
    for slug, client, why, agent, shows in auditor_cases:
        if client is None:
            emit(slug, None, why or "backend unavailable", agent)
            continue
        traj, reason = auditor_run(client, agent, shows)
        emit(slug, traj, reason, agent)

    unavailable.append(
        {
            "agent": "grpo-trained Challenger",
            "reason": "needs a GPU and a trained LoRA adapter. Both GRPO runs failed "
            "to learn -- 99.7% and 95.7% of rollout groups had zero reward spread, "
            "so there was no gradient -- and the numbers are in "
            "`docs/changelog/40-grpo-challenger.md`. It is an optional artifact; "
            "nothing in Assay requires it.",
        }
    )

    index = write_index(entries, out, unavailable=unavailable)
    print(f"\nwrote {index}")
    print(f"{len(entries)} trajectories, {len(unavailable)} agents with no run here")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
