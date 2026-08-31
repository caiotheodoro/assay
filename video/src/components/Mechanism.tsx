/**
 * What Assay is, in one frame.
 *
 * The video previously never showed the shape of the tool -- it went straight
 * from a broken benchmark to a running command, so a viewer had to infer the
 * product from its output. This is the missing picture: something goes in, a
 * battery of probes runs, a verdict comes out.
 *
 * The UNVERIFIED branch is the point, and it is drawn last and left highlighted.
 * Two of the three verdicts are ordinary; the third is a tool declining to
 * answer, and that is the thing nothing else in this space does.
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { T, VERDICT } from "../theme";

const EASE = Easing.bezier(0.25, 0.46, 0.45, 0.94);
const rise = (f: number, at: number, len = 16) =>
  interpolate(f, [at, at + len], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE,
  });

const Box: React.FC<{
  children: React.ReactNode;
  at: number;
  width: number;
  accent?: boolean;
}> = ({ children, at, width, accent }) => {
  const o = rise(useCurrentFrame(), at);
  return (
    <div
      style={{
        width,
        border: `1px solid ${accent ? T.accent : T.border}`,
        borderRadius: 10,
        background: T.bg,
        padding: "20px 26px",
        opacity: o,
        transform: `translateY(${(1 - o) * 12}px)`,
      }}
    >
      {children}
    </div>
  );
};

const Arrow: React.FC<{ at: number }> = ({ at }) => {
  const g = rise(useCurrentFrame(), at, 12);
  return (
    <svg width={44} height={90} style={{ display: "block", margin: "0 auto" }}>
      <line x1={22} y1={0} x2={22} y2={70 * g} stroke={T.borderStrong} strokeWidth={2} />
      {g > 0.9 ? (
        <path d="M14 62 L22 74 L30 62" fill="none" stroke={T.borderStrong} strokeWidth={2} />
      ) : null}
    </svg>
  );
};

const VERDICTS = [
  { name: "VALID", exit: "exit 0", note: "every probe ran, none found a defect" },
  { name: "INVALID", exit: "exit 1", note: "a critical defect was found" },
  { name: "UNVERIFIED", exit: "exit 1", note: "no defect found, but not every probe could run" },
] as const;

export const Mechanism: React.FC<{ at?: number }> = ({ at = 0 }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 1620 }}>
      <Box at={at} width={430}>
        <div style={{ fontFamily: T.mono, fontSize: 26, color: T.text, textAlign: "center" }}>
          an environment
        </div>
        <div
          style={{
            fontFamily: T.font,
            fontSize: 20,
            color: T.textMuted,
            textAlign: "center",
            marginTop: 6,
          }}
        >
          RL environment or eval suite
        </div>
      </Box>

      <Arrow at={at + 10} />

      <Box at={at + 16} width={880}>
        <div
          style={{
            fontFamily: T.mono,
            fontSize: 22,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: T.accent,
            textAlign: "center",
          }}
        >
          nine probe families
        </div>
        <div
          style={{
            fontFamily: T.font,
            fontSize: 23,
            color: T.textMuted,
            textAlign: "center",
            marginTop: 10,
            lineHeight: 1.45,
          }}
        >
          gold passes · a no-op fails · an inverted spec fails · contamination ·
          shortcut leakage · determinism · <span style={{ color: T.text }}>the Challenger</span>
        </div>
      </Box>

      <Arrow at={at + 28} />

      <div style={{ display: "flex", gap: 22 }}>
        {VERDICTS.map((v, i) => {
          const isKey = v.name === "UNVERIFIED";
          const o = rise(frame, at + 34 + i * 7);
          // The differentiator gets a beat of its own, after the other two.
          const glow = isKey ? rise(frame, at + 58, 20) : 0;
          return (
            <div
              key={v.name}
              style={{
                width: 400,
                border: `1px solid ${isKey ? VERDICT.UNVERIFIED : T.border}`,
                borderRadius: 10,
                padding: "18px 22px",
                background: isKey ? `rgba(130,80,223,${0.05 * glow})` : T.bg,
                opacity: o,
                transform: `translateY(${(1 - o) * 10}px)`,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span
                  style={{
                    fontFamily: T.mono,
                    fontSize: 22,
                    fontWeight: 600,
                    color: "#fff",
                    background: VERDICT[v.name],
                    borderRadius: 5,
                    padding: "4px 12px",
                  }}
                >
                  {v.name}
                </span>
                <span style={{ fontFamily: T.mono, fontSize: 21, color: T.textMuted }}>
                  {v.exit}
                </span>
              </div>
              <div
                style={{
                  fontFamily: T.font,
                  fontSize: 21,
                  color: isKey ? T.text : T.textMuted,
                  marginTop: 12,
                  lineHeight: 1.4,
                  minHeight: 58,
                }}
              >
                {v.note}
              </div>
              {isKey ? (
                <div
                  style={{
                    fontFamily: T.font,
                    fontSize: 21,
                    fontWeight: 600,
                    color: VERDICT.UNVERIFIED,
                    marginTop: 4,
                    opacity: glow,
                  }}
                >
                  it can refuse to answer
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
};
