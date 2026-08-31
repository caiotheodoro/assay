/**
 * The second wild defect: a seed that is accepted and ignored.
 *
 * One broken scorer is an anecdote. The same class of bug in a second
 * ecosystem, on an environment people train against, is the argument. The
 * picture is the repetition -- six identical calls, six different answers --
 * so the six words are set as cells and land one at a time.
 *
 * Quoted from README.md:185-188 rather than bound: the six words are recorded
 * in prose, not in any results file.
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { T, VERDICT } from "../theme";
import { Source } from "./DataPanel";

const WORDS = ["earth", "north", "south", "bread", "tight", "stage"];
const EASE = Easing.bezier(0.25, 0.46, 0.45, 0.94);

export const OpenEnvSeed: React.FC<{ at?: number }> = ({ at = 0 }) => {
  const frame = useCurrentFrame();
  return (
    <div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 30,
          color: T.text,
          background: T.codeBg,
          border: `1px solid ${T.border}`,
          borderRadius: 8,
          padding: "18px 26px",
          display: "inline-block",
          marginBottom: 40,
        }}
      >
        <span style={{ color: T.accent }}>$ </span>
        env.reset(seed=1234)
        <span style={{ color: T.textMuted }}> × 6</span>
      </div>

      <div style={{ display: "flex", gap: 20 }}>
        {WORDS.map((w, i) => {
          const o = interpolate(frame, [at + i * 9, at + i * 9 + 14], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: EASE,
          });
          return (
            <div
              key={w}
              style={{
                flex: 1,
                border: `1px solid ${T.border}`,
                borderRadius: 8,
                padding: "24px 0",
                textAlign: "center",
                background: T.bg,
                opacity: o,
                transform: `translateY(${(1 - o) * 12}px)`,
              }}
            >
              <div style={{ fontFamily: T.mono, fontSize: 20, color: T.textFaint }}>
                reset {i + 1}
              </div>
              <div
                style={{
                  fontFamily: T.mono,
                  fontSize: 36,
                  fontWeight: 600,
                  color: VERDICT.INVALID,
                  marginTop: 10,
                }}
              >
                {w}
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          fontFamily: T.font,
          fontSize: 27,
          color: T.text,
          marginTop: 36,
          opacity: interpolate(frame, [at + 60, at + 78], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        Same seed. Six different secret words.
      </div>
      <Source file="README.md:185" detail="verified against upstream, Assay out of the loop" />
    </div>
  );
};
