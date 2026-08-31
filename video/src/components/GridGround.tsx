/**
 * The page ground, from `cv/src/styles/global.css`: a 36px drafting grid at
 * 0.04 alpha on white, with the fixed bottom fade from `body::before`.
 * At 1920x1080 the grid is scaled up so it reads at video distance rather
 * than dissolving into texture.
 */
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { T } from "../theme";

const CELL = 48; // 36px on a ~1440 page, held to the same visual density here

export const GridGround: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ backgroundColor: T.bg }}>
    <AbsoluteFill
      style={{
        backgroundImage: `linear-gradient(rgba(0,0,0,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.04) 1px, transparent 1px)`,
        backgroundSize: `${CELL}px ${CELL}px`,
      }}
    />
    <AbsoluteFill
      style={{ background: `linear-gradient(to bottom, transparent 50%, ${T.bg} 100%)` }}
    />
    <AbsoluteFill>{children}</AbsoluteFill>
  </AbsoluteFill>
);

/** Section eyebrow: the repo's own vocabulary, in mono. Never a number. */
export const Eyebrow: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({
  children,
  style,
}) => (
  <div
    style={{
      fontFamily: T.mono,
      fontSize: 22,
      letterSpacing: "0.14em",
      textTransform: "uppercase",
      color: T.accent,
      ...style,
    }}
  >
    {children}
  </div>
);

/** The standard scene frame: eyebrow, title, then content. */
export const Panel: React.FC<{
  eyebrow: string;
  title?: string;
  children: React.ReactNode;
  wide?: boolean;
}> = ({ eyebrow, title, children, wide }) => {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ padding: "80px 120px 210px", justifyContent: "center" }}>
      <div style={{ opacity: enter, transform: `translateY(${(1 - enter) * 16}px)` }}>
        <Eyebrow>{eyebrow}</Eyebrow>
        {title ? (
          <Title style={{ marginTop: 14, marginBottom: wide ? 40 : 46, maxWidth: 1500 }}>
            {title}
          </Title>
        ) : null}
      </div>
      {children}
    </AbsoluteFill>
  );
};

export const Title: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({
  children,
  style,
}) => (
  <div
    style={{
      fontFamily: T.font,
      fontSize: 58,
      fontWeight: 700,
      letterSpacing: "-0.02em",
      lineHeight: 1.1,
      color: T.text,
      ...style,
    }}
  >
    {children}
  </div>
);
