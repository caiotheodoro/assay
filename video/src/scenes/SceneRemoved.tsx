/**
 * Beat 6 - one experiment removed. The brief asks for exactly one.
 *
 * The point is not that the rule failed to find defects -- it found five of
 * seven. It is that Assay's own trivial-floor rule, the one it applies to every
 * environment it audits, disqualified it.
 */
import React from "react";
import { Beat } from "../components/Beat";
import { GridGround, Panel } from "../components/GridGround";
import { Source } from "../components/DataPanel";
import { REJECTED_RULE } from "../data/results";
import { beats } from "../beats";
import { T, VERDICT } from "../theme";
import { interpolate, useCurrentFrame } from "remotion";

const B = beats("removed");

const Stat: React.FC<{
  value: string;
  label: string;
  tone?: "good" | "bad";
  at: number;
}> = ({ value, label, tone, at }) => {
  const o = interpolate(useCurrentFrame(), [at, at + 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ opacity: o, transform: `translateY(${(1 - o) * 12}px)` }}>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 84,
          fontWeight: 700,
          lineHeight: 1,
          color: tone === "bad" ? VERDICT.INVALID : tone === "good" ? T.text : T.text,
        }}
      >
        {value}
      </div>
      <div style={{ fontFamily: T.font, fontSize: 25, color: T.textMuted, marginTop: 14, maxWidth: 420 }}>
        {label}
      </div>
    </div>
  );
};

export const SceneRemoved: React.FC = () => (
  <GridGround>
    <Beat from={0} to={B.reject} name="6a it worked">
      <Panel
        eyebrow="ScienceAgentBench · a rejected experiment"
        title="Its instruction defects look detectable by rule."
      >
        <Stat
          value={`${REJECTED_RULE.recovered} of ${REJECTED_RULE.recoveredOf}`}
          label="instruction defects recovered by a single metadata rule"
          tone="good"
          at={8}
        />
        <Source file="results/sab_metadata_probe.json" detail="rules.R1_output_path_unstated" />
      </Panel>
    </Beat>
    <Beat from={B.reject} name="6b and it was flag-everything">
      <Panel eyebrow="and then the floor check ran" title="Flag-everything wearing a rule’s clothing.">
        <div style={{ display: "flex", gap: 130, alignItems: "flex-start" }}>
          <Stat
            value={`${REJECTED_RULE.firedOn} of ${REJECTED_RULE.ofTotal}`}
            label="tasks it fired on — nearly two in three"
            tone="bad"
            at={6}
          />
          <Stat
            value={REJECTED_RULE.precision.toFixed(3).replace(/^0/, "")}
            label="precision"
            tone="bad"
            at={16}
          />
        </div>
        <div
          style={{
            fontFamily: T.font,
            fontSize: 26,
            color: T.text,
            marginTop: 46,
            maxWidth: 1350,
            lineHeight: 1.5,
            borderLeft: `3px solid ${T.accent}`,
            paddingLeft: 26,
          }}
        >
          {REJECTED_RULE.verdict}
        </div>
        <Source file="results/sab_metadata_probe.json" detail="rejected, and kept in the repo as one" />
      </Panel>
    </Beat>
  </GridGround>
);
