/**
 * Beat 4 - the changelog. The brief asks for it briefly, so this is short: the
 * shape of the log and the fact that failures are kept in it.
 *
 * The row count is derived from the repo at build time. An earlier draft said
 * "forty-five entries" in the narration and was already stale at 48 -- and a
 * number baked into audio cannot be corrected without re-recording.
 */
import React from "react";
import { GridGround, Panel } from "../components/GridGround";
import { Source } from "../components/DataPanel";
import { FACTS } from "../data/results";
import { T } from "../theme";
import { interpolate, useCurrentFrame } from "remotion";

const ROWS = [
  { stage: "Slice 1", tried: "Core adapter protocol, 9 probe families, 12 fixture environments.", decision: "Kept.", kept: true },
  { stage: "Slice 1a", tried: "Probes 2 and 3 compared policies per task.", decision: "Revised to aggregate.", kept: true },
  { stage: "Slice 20a", tried: "Added the three missing trivial baselines.", decision: "The harder floor is not harder.", kept: true },
  { stage: "Slice 28", tried: "Two BenchJack classes written as shell policies.", decision: "Kept. Closed both misses.", kept: true },
  { stage: "Slice 31", tried: "ScienceAgentBench metadata rules.", decision: "Removed. Flag-everything in disguise.", kept: false },
];

export const SceneChangelog: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <GridGround>
      <Panel
        eyebrow={`${FACTS.changelogSliceRows} rows · ${FACTS.changelogFragments} fragments`}
        title="Every experiment that moved a number has a row."
        wide
      >
        <div style={{ width: 1620 }}>
          <div
            style={{
              display: "flex",
              paddingBottom: 12,
              borderBottom: `1.5px solid ${T.text}`,
              fontFamily: T.mono,
              fontSize: 19,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: T.textMuted,
            }}
          >
            <div style={{ width: 190 }}>Stage</div>
            <div style={{ flex: 1 }}>What was tried and why</div>
            <div style={{ width: 520 }}>Decision / learning</div>
          </div>
          {ROWS.map((r, i) => {
            const o = interpolate(frame, [10 + i * 8, 26 + i * 8], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={r.stage}
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  padding: "18px 0",
                  borderBottom: `1px solid ${T.border}`,
                  opacity: o,
                  transform: `translateY(${(1 - o) * 10}px)`,
                }}
              >
                <div style={{ width: 190, fontFamily: T.mono, fontSize: 24, color: T.text }}>
                  {r.stage}
                </div>
                <div style={{ flex: 1, fontFamily: T.font, fontSize: 24, color: T.textMuted, paddingRight: 40 }}>
                  {r.tried}
                </div>
                <div
                  style={{
                    width: 520,
                    fontFamily: T.font,
                    fontSize: 24,
                    fontWeight: 600,
                    color: r.kept ? T.text : T.accent,
                  }}
                >
                  {r.decision}
                </div>
              </div>
            );
          })}
        </div>
        <Source file="docs/CHANGELOG.md" detail="the ones that failed are kept in it" />
      </Panel>
    </GridGround>
  );
};
