/**
 * Full-sentence caption cues, keyed in milliseconds from the start of a scene.
 * Ported from credit-db/video/src/CaptionOverlay.tsx. Cues are authored by
 * hand in the manifest rather than derived from word-level timing: the
 * vocabulary here (INVERT_PASSES, hypergeometric, NOT_APPLICABLE) is exactly
 * what an automatic aligner gets wrong.
 */
import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { CaptionCue } from "../manifest";
import { T } from "../theme";

const FADE_MS = 160;

export const CaptionOverlay: React.FC<{ cues: CaptionCue[] }> = ({ cues }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = (frame / fps) * 1000;

  const active = cues.find((c) => ms >= c.startMs - FADE_MS && ms <= c.endMs + FADE_MS);
  if (!active) return null;

  const opacity = interpolate(
    ms,
    [active.startMs - FADE_MS, active.startMs, active.endMs, active.endMs + FADE_MS],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 72,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
        opacity,
        transform: `translateY(${(1 - opacity) * 14}px)`,
      }}
    >
      <div
        style={{
          maxWidth: 1400,
          padding: "16px 30px",
          borderRadius: 10,
          background: "rgba(255,255,255,0.92)",
          border: `1px solid ${T.border}`,
          color: T.text,
          fontFamily: T.font,
          fontSize: 34,
          fontWeight: 600,
          lineHeight: 1.35,
          textAlign: "center",
          textWrap: "balance",
        }}
      >
        {active.text}
      </div>
    </div>
  );
};
