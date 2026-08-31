/**
 * Beat 1 - the problem, and the simple baseline. The brief asks the video to
 * begin here, so it does: a live defect in a shipping eval suite, then the only
 * automated tool that exists for catching it.
 */
import React from "react";
import { Beat } from "../components/Beat";
import { GridGround, Panel } from "../components/GridGround";
import { Checklist, Quote } from "../components/Panels";
import { TerminalCast } from "../components/TerminalCast";
import { OpenEnvSeed } from "../components/OpenEnvSeed";
import { Column, Row, Source, Table } from "../components/DataPanel";
import { PAWS, REAL_CHECKERS } from "../data/results";
import { ranges } from "../beats";
import { T, VERDICT } from "../theme";

const R = ranges("problem");

/** How a substring scorer is taken by a single constant. */
const Receipt: React.FC = () => (
  <Panel eyebrow={`inspect_evals · ${PAWS.task}`} title="The scorer accepts any answer containing the target.">
    <div style={{ display: "flex", gap: 70, alignItems: "center" }}>
      <div>
        {Object.entries(PAWS.targets)
          .filter(([k]) => k !== "total")
          .map(([label, n]) => (
            <div key={label} style={{ display: "flex", gap: 20, alignItems: "baseline", padding: "10px 0" }}>
              <span style={{ fontFamily: T.mono, fontSize: 34, color: T.text, width: 90 }}>{label}</span>
              <span style={{ fontFamily: T.mono, fontSize: 24, color: T.textMuted }}>{n} items</span>
            </div>
          ))}
      </div>
      <div style={{ fontFamily: T.font, fontSize: 40, color: T.textFaint }}>→</div>
      <div>
        <div
          style={{
            fontFamily: T.mono,
            fontSize: 54,
            fontWeight: 600,
            background: T.codeBg,
            border: `1px solid ${T.border}`,
            borderRadius: 8,
            padding: "16px 30px",
            color: T.accent,
          }}
        >
          "yesno"
        </div>
        <div style={{ fontFamily: T.font, fontSize: 24, color: T.textMuted, marginTop: 14 }}>
          one constant, contains both
        </div>
      </div>
      <div style={{ fontFamily: T.font, fontSize: 40, color: T.textFaint }}>→</div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: T.mono, fontSize: 66, fontWeight: 700, color: VERDICT.INVALID }}>
          {PAWS.scored} / {PAWS.outOf}
        </div>
        <div style={{ fontFamily: T.font, fontSize: 26, color: T.textMuted, marginTop: 6 }}>
          {PAWS.severity} · {PAWS.defect} · {PAWS.verdict}
        </div>
      </div>
    </div>
    <div style={{ marginTop: 34, maxWidth: 1280 }}>
      <TerminalCast src="wild_findings" fontSize={17} speed={1} />
    </div>
    <Source file="results/wild_sweep_triage.json" detail="findings[0] · independently verified" />
  </Panel>
);

/**
 * The incumbent. Two things are true and both go on screen: the real checkers
 * catch 1 of 4 planted defects, and the corpus arm is a reimplementation of
 * them, not the tool itself.
 */
const Baseline: React.FC = () => {
  const columns: Column[] = [
    { key: "case", label: "planted defect", width: 340 },
    { key: "gym", label: "gymnasium", width: 200 },
    { key: "sb3", label: "stable_baselines3", width: 270 },
    { key: "caught", label: "caught", numeric: true, width: 130 },
  ];
  const rows: Row[] = Object.entries(REAL_CHECKERS.cases).map(([name, c]) => ({
    key: name,
    emphasis: c.defect_detected,
    muted: c.defect_present === null,
    cells: {
      case: c.defect_present ?? "none planted",
      gym: c.gymnasium.verdict,
      sb3: c.stable_baselines3.verdict,
      caught: c.defect_present === null ? "—" : c.defect_detected ? "yes" : "no",
    },
  }));
  return (
    <Panel
      eyebrow={`gymnasium ${REAL_CHECKERS.gymnasium} · the real checkers`}
      title={`Everything it checks — and ${REAL_CHECKERS.detected_by_real_checkers} of ${REAL_CHECKERS.planted_defects} defects caught.`}
      wide
    >
      <div style={{ display: "flex", gap: 50 }}>
        <div style={{ flex: "0 0 590px" }}>
          <Checklist
            items={[
              "the manifest declares at least one task",
              "reset() returns a well-formed observation",
              "step() returns a boolean done",
              "reward is not NaN or infinite",
              "an unknown tool is rejected",
              "same seed, same observation",
            ]}
            at={10}
            accentIndex={5}
          />
          <div
            style={{
              fontFamily: T.font,
              fontSize: 22,
              color: T.textMuted,
              marginTop: 20,
              lineHeight: 1.5,
            }}
          >
            Only the last one ever finds a defect.
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <Table columns={columns} rows={rows} width={950} />
          <Source file="results/real_check_env.json" detail="the real tools, on purpose-built shims" />
        </div>
      </div>
    </Panel>
  );
};

export const SceneProblem: React.FC = () => (
  <GridGround>
    <Beat {...R.start} name="1a the problem">
      <Panel eyebrow="the problem" title="Nobody QAs the benchmark.">
        <div
          style={{
            fontFamily: T.font,
            fontSize: 34,
            color: T.textMuted,
            maxWidth: 1250,
            lineHeight: 1.45,
          }}
        >
          Labs and vendors buy reinforcement learning environments and eval suites as
          products. Nothing checks whether they measure what they claim.
        </div>
      </Panel>
    </Beat>
    <Beat {...R.define} name="1b what it is">
      {/* Deliberately NOT the spoken sentence. The caption already carries the
          words; the screen carries the identity and what comes back. */}
      <Panel eyebrow="an agentic auditor for RL environments and eval suites" title="">
        <div
          style={{
            fontFamily: T.font,
            fontSize: 132,
            fontWeight: 700,
            letterSpacing: "-0.045em",
            lineHeight: 1,
            color: T.text,
          }}
        >
          Assay
        </div>
        <div style={{ display: "flex", gap: 18, marginTop: 46 }}>
          {(["VALID", "INVALID", "UNVERIFIED"] as const).map((v) => (
            <span
              key={v}
              style={{
                fontFamily: T.mono,
                fontSize: 26,
                fontWeight: 600,
                color: "#fff",
                background: VERDICT[v],
                borderRadius: 6,
                padding: "8px 18px",
              }}
            >
              {v}
            </span>
          ))}
        </div>
        <div
          style={{
            fontFamily: T.font,
            fontSize: 27,
            color: T.textMuted,
            marginTop: 22,
          }}
        >
          a verdict, an exit code, and the evidence behind both
        </div>
        {/* The tool running, under its own name. A judge should not watch a
            video about a tool for a minute without seeing the tool execute. */}
        <div style={{ marginTop: 34, maxWidth: 1150 }}>
          <TerminalCast src="selftest" fontSize={19} speed={1} />
        </div>
      </Panel>
    </Beat>

    <Beat {...R.receipt} name="1c the receipt">
      <Receipt />
    </Beat>
    <Beat {...R.openenv} name="1d a second ecosystem">
      <Panel eyebrow="OpenEnv · textarena" title="And it is not one scorer.">
        <OpenEnvSeed at={6} />
        <div style={{ marginTop: 26, maxWidth: 1280 }}>
          <TerminalCast src="openenv_seed" fontSize={17} speed={1} />
        </div>
      </Panel>
    </Beat>

    <Beat {...R.manual} name="1e today the fix is people">
      <Panel eyebrow="how it gets caught today" title="By hand.">
        <Quote cite="README.md:129-133 · prior art, prose only" at={6}>
          SWE-bench: ~2/3 of instances unusable, found by 93 developers hand-triaging.
          7.8% of “passing” patches are wrong-but-pass. WebArena’s substring evaluator
          produced false negatives. tau2-bench took 75+ ad hoc fixes across labs.
        </Quote>
      </Panel>
    </Beat>

    <Beat {...R.baseline} name="1f the baseline">
      <Baseline />
    </Beat>
  </GridGround>
);
