/**
 * Beat 7 - reproducibility, the self-audit, and the hot take.
 *
 * The reproduction timings are quoted rather than bound: they exist only as
 * prose in docs/REPRODUCTION.md, no script emits them, and that document has a
 * documented history of going stale. Showing them as a citation rather than as
 * computed data is the honest treatment.
 */
import React from "react";
import { Beat } from "../components/Beat";
import { GridGround, Panel } from "../components/GridGround";
import { Quote } from "../components/Panels";
import { Source } from "../components/DataPanel";
import { FACTS, TAU2 } from "../data/results";
import { PUBLISHED } from "../manifest";
import { beats } from "../beats";
import { T, VERDICT } from "../theme";
import { interpolate, useCurrentFrame } from "remotion";

const B = beats("close");

const SelfAudit: React.FC = () => {
  const frame = useCurrentFrame();
  const bars = [
    { label: "broken", n: FACTS.redTeamBrokenClaims, colour: VERDICT.INVALID },
    { label: "partial", n: FACTS.redTeamPartialClaims, colour: VERDICT.DEFECTIVE },
    { label: "survived", n: FACTS.redTeamSurvivedClaims, colour: VERDICT.VALID },
  ];
  const total = bars.reduce((a, b) => a + b.n, 0);
  return (
    <Panel eyebrow="we ran the audit on ourselves" title="Twelve of our published claims broke.">
      <div style={{ display: "flex", width: 1500, height: 76, borderRadius: 8, overflow: "hidden" }}>
        {bars.map((b, i) => {
          const w = interpolate(frame, [8 + i * 6, 30 + i * 6], [0, (b.n / total) * 1500], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          return (
            <div
              key={b.label}
              style={{
                width: w,
                background: b.colour,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#fff",
                fontFamily: T.mono,
                fontSize: 30,
                fontWeight: 600,
              }}
            >
              {b.n}
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", width: 1500, marginTop: 14 }}>
        {bars.map((b) => (
          <div
            key={b.label}
            style={{
              width: `${(b.n / total) * 100}%`,
              fontFamily: T.font,
              fontSize: 23,
              color: T.textMuted,
            }}
          >
            {b.label}
          </div>
        ))}
      </div>
      <div
        style={{
          fontFamily: T.font,
          fontSize: 26,
          color: T.text,
          marginTop: 46,
          maxWidth: 1400,
          lineHeight: 1.5,
        }}
      >
        And the external number was chance: recall {TAU2.all.recall.toFixed(3).replace(/^0/, "")} on
        tau2-bench, {TAU2.all.observed} true positives where flagging the same{" "}
        {TAU2.all.nFlagged} tasks at random gives {TAU2.all.expected}. p ={" "}
        {TAU2.all.p.toFixed(3).replace(/^0/, "")}.
      </div>
      <Source file="docs/RED-TEAM.md · results/tau2_recall.json" detail="counts derived, not typed" />
    </Panel>
  );
};

const HotTake: React.FC = () => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [6, 26], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const links = interpolate(frame, [70, 92], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Panel eyebrow="the hot take" title="">
      <div
        style={{
          opacity: o,
          transform: `translateY(${(1 - o) * 16}px)`,
          fontFamily: T.font,
          fontSize: 62,
          fontWeight: 700,
          lineHeight: 1.2,
          letterSpacing: "-0.02em",
          color: T.text,
          maxWidth: 1560,
        }}
      >
        An auditing tool is not exempt from the thing it audits.
      </div>
      <div style={{ opacity: links, marginTop: 80, display: "flex", flexWrap: "wrap", gap: "14px 60px" }}>
        {Object.entries(PUBLISHED).map(([k, url]) => (
          <div key={k} style={{ fontFamily: T.mono, fontSize: 23 }}>
            <span style={{ color: T.accent }}>{k} </span>
            <span style={{ color: T.text }}>{url}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
};

export const SceneClose: React.FC = () => (
  <GridGround>
    <Beat from={0} to={B.selfaudit} name="7a reproducibility">
      <Panel eyebrow="from a clean checkout" title="One sync, then one command per result.">
        <Quote cite="docs/REPRODUCTION.md:60 · measured, cold cache" at={8}>
          52 s, 759 MB downloaded, 566 MB venv, 351 packages. Re-running against a warm
          cache is 2 s.
        </Quote>
        <div style={{ marginTop: 44, fontFamily: T.mono, fontSize: 26, color: T.textMuted }}>
          {FACTS.testsCollected} tests across {FACTS.testFiles} files
        </div>
        <Source file="src/data/repo-facts.json" detail="collected from the tree, not transcribed" />
      </Panel>
    </Beat>
    <Beat from={B.selfaudit} to={B.hottake} name="7b the self-audit">
      <SelfAudit />
    </Beat>
    <Beat from={B.hottake} name="7c hot take">
      <HotTake />
    </Beat>
  </GridGround>
);
