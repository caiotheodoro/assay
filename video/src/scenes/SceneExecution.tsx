/**
 * Beat 2 - one realistic execution, start to finish. The brief's largest ask.
 *
 * The approval gate is shown as what it is. An interactive prompt was removed
 * from this codebase as dead code, so a shot of one would be a false claim
 * about the software: the gate is a default-deny approver, and the exported
 * trajectory puts the same request to both approvers.
 */
import React from "react";
import { Beat } from "../components/Beat";
import { GridGround, Panel } from "../components/GridGround";
import { CardFrame, Checklist, SplitScore } from "../components/Panels";
import { Mechanism } from "../components/Mechanism";
import { Source } from "../components/DataPanel";
import { TerminalCast } from "../components/TerminalCast";
import { EXPLOIT } from "../data/exploit";
import { useAuditRun } from "../data/auditRun";
import { beats } from "../beats";
import { T, VERDICT } from "../theme";

const B = beats("execution");

const PROBES = [
  "does the gold solution pass",
  "does a no-op fail",
  "does an inverted spec fail",
  "does a known-wrong policy fail",
  "can a trivial policy win",
  "contamination",
  "shortcut leakage",
  "determinism",
  "the Challenger",
];

const Gate: React.FC = () => (
  <Panel eyebrow="the human checkpoint" title="Nothing runs unless an approver says yes.">
    <div style={{ display: "flex", gap: 40, maxWidth: 1580 }}>
      {[
        { name: "DenyAll", sub: "the default", result: "nothing ran", ok: false,
          detail: "requests recorded as approved: 0" },
        { name: "AutoApprove(reason)", sub: "explicit standing approval", result: "exit 0", ok: true,
          detail: "an approval nobody can account for is the same as no approval" },
      ].map((a) => (
        <div
          key={a.name}
          style={{
            flex: 1,
            border: `1px solid ${T.border}`,
            borderRadius: 10,
            padding: "26px 30px",
            background: a.ok ? T.bg : T.bgSubtle,
          }}
        >
          <div style={{ fontFamily: T.mono, fontSize: 30, color: T.text }}>{a.name}</div>
          <div style={{ fontFamily: T.font, fontSize: 22, color: T.textMuted, marginTop: 6 }}>
            {a.sub}
          </div>
          <div
            style={{
              fontFamily: T.mono,
              fontSize: 34,
              fontWeight: 600,
              marginTop: 26,
              color: a.ok ? VERDICT.VALID : VERDICT.INVALID,
            }}
          >
            {a.result}
          </div>
          <div style={{ fontFamily: T.font, fontSize: 21, color: T.textMuted, marginTop: 12, lineHeight: 1.45 }}>
            {a.detail}
          </div>
        </div>
      ))}
    </div>
    <Source
      file="results/trajectories/08-sandbox-approval-gate-harbor-self-graded.md"
      detail="the identical request, put to both"
    />
  </Panel>
);

export const SceneExecution: React.FC = () => {
  const run = useAuditRun();
  return (
  <GridGround>
    <Beat from={0} to={B.run} name="2a what it is">
      <Panel eyebrow="an agentic auditor" title="">
        <Mechanism at={4} />
      </Panel>
    </Beat>

    <Beat from={B.run} to={B.probes} name="2b one run">
      <Panel eyebrow="assay audit harbor/self-graded" title="Here is one run.">
        <TerminalCast src="audit" fontSize={19} />
      </Panel>
    </Beat>

    <Beat from={B.probes} to={B.gate} name="2c nine probes">
      <Panel eyebrow="nine probe families" title="Every one of them is a deterministic program.">
        <Checklist items={PROBES} at={8} columns={2} accentIndex={8} />
      </Panel>
    </Beat>

    <Beat from={B.gate} to={B.exploit} name="2d the gate">
      <Gate />
    </Beat>

    <Beat from={B.exploit} to={B.card} name="2e the exploit">
      <Panel
        eyebrow={`the Challenger · turn ${EXPLOIT.turn} of ${EXPLOIT.attempts}`}
        title="It wrote the answer into the file the verifier checks against."
      >
        <SplitScore
          commands={EXPLOIT.commands}
          reported={EXPLOIT.reportedScore}
          actual={EXPLOIT.trueCompletion}
          at={6}
        />
        <Source
          file="results/trajectories/03-challenger-claude-cli-harbor-self-graded-found.json"
          detail={`exploit gap ${EXPLOIT.gap.toFixed(1)}`}
        />
      </Panel>
    </Beat>

    <Beat from={B.card} to={B.choices} name="2f the card">
      <Panel eyebrow="the environment card" title="It found the exploit. And it says what it could not check.">
        {run ? <CardFrame run={run} at={6} /> : null}
      </Panel>
    </Beat>

    <Beat from={B.choices} name="2g the design choices">
      <Panel eyebrow="which choices did the work" title="Three, and none of them is the model.">
        <Checklist
          items={[
            "an independent verifier, separate from the environment's own",
            "a sandbox that denies by default, network off, read-only root",
            "deterministic probes — the model is only ever the attacker",
          ]}
          at={8}
        />
      </Panel>
    </Beat>
  </GridGround>
  );
};
