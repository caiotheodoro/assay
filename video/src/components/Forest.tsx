/**
 * Forest plot: a point estimate plus its confidence interval, one row per arm.
 *
 * A port of `cv-related/cv/src/components/blog/PostChart.tsx:88-158`
 * (`ForestPanelChart`), keeping its geometry, its token usage and its rules.
 * It is hand-rolled SVG rather than Recharts because every mark here has to be
 * a pure function of the frame -- Recharts owns its own animation clock and
 * measures asynchronously, neither of which survives a deterministic headless
 * render. Layout constants are the blog's, scaled for 1080p.
 *
 * The blog's rule carries over unchanged: the palette's worst colour-vision
 * pair sits in the 6-8 dE band, so every row carries a direct value label in
 * the right-hand value column. Identity is never colour alone. Do not remove
 * those labels.
 */
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { GRID, NEUTRAL, SERIES, T } from "../theme";
import { MOTION } from "../theme";

export type ColorRef = number | "neutral";

export interface ForestRow {
  label: string;
  point: number;
  ci?: [number, number];
  color?: ColorRef;
  /** Short trailing note, e.g. "separated" or "crosses zero". */
  note?: string;
  /** Draws the row at full text weight; everything else recedes. */
  emphasis?: boolean;
}

export interface ForestProps {
  metric: string;
  rows: ForestRow[];
  domain?: [number, number];
  /** Draw the zero rule. The whole argument is which intervals clear it. */
  zero?: boolean;
  /** Frame this figure begins animating, relative to the enclosing Sequence. */
  startFrame?: number;
  width?: number;
  /** Row pitch. Drop it below the default when a panel carries many arms. */
  rowHeight?: number;
  /**
   * Pin value 0 to this fraction of the plot width and let the scene draw the
   * rule itself. Two panels sharing a fraction share a zero position, so the
   * axis can hold still while the rows change around it.
   */
  zeroFraction?: number;
}

// Geometry: the blog's values, scaled ~1.9x for a 1920x1080 frame.
const ROW_H_DEFAULT = 88;
const LABEL_W = 340;
const VALUE_W = 170;
const PAD = { top: 8, right: 30, bottom: 46, left: 8 };
const CAP = 11; // ErrorBar cap half-height; blog uses width 5
const DOT_R = 9;

export const colorOf = (c?: ColorRef): string =>
  c === "neutral" ? NEUTRAL : SERIES[(typeof c === "number" ? c : 0) % SERIES.length]!;

/**
 * The blog's `fmt` renders sub-1 values at three decimals with the leading
 * zero stripped, everything else at two. Expected-loss figures here are whole
 * numbers, where a trailing ".00" is noise, so integers print bare.
 */
export const fmt = (v: number): string => {
  if (Math.abs(v) < 1 && v !== 0) return v.toFixed(3).replace(/^(-?)0/, "$1");
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(1);
};

/**
 * Ticks on a 1-2-5 ladder. Evenly dividing the padded domain produced labels
 * like -58.7 and 273.8, which read as noise next to a value column carrying
 * the real figures.
 */
export const niceTicks = (d0: number, d1: number, target = 5): number[] => {
  const span = d1 - d0;
  if (!Number.isFinite(span) || span <= 0) return [d0];
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const first = Math.ceil(d0 / step) * step;
  const out: number[] = [];
  for (let v = first; v <= d1 + step * 1e-9; v += step) {
    out.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toFixed(6)));
  }
  return out;
};

export const Forest: React.FC<ForestProps> = ({
  metric,
  rows,
  domain,
  zero = false,
  startFrame = 0,
  width = 1180,
  rowHeight = ROW_H_DEFAULT,
  zeroFraction,
}) => {
  const ROW_H = rowHeight;
  const frame = useCurrentFrame() - startFrame;

  const values = rows.flatMap((r) => [r.ci?.[0] ?? r.point, r.ci?.[1] ?? r.point]);
  if (zero) values.push(0);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo || 0.1) * 0.18;
  let [d0, d1] = domain ?? [lo - pad, hi + pad];

  if (zeroFraction !== undefined) {
    // Solve for the domain that puts 0 at `zeroFraction` while still covering
    // every value: the widest of the two constraints wins, plus headroom.
    const f = zeroFraction;
    const span = Math.max(lo < 0 ? -lo / f : 0, hi > 0 ? hi / (1 - f) : 0) * 1.12;
    d0 = -f * span;
    d1 = (1 - f) * span;
  }

  const plotLeft = LABEL_W + PAD.left;
  const plotRight = width - VALUE_W - PAD.right;
  const plotW = plotRight - plotLeft;
  const height = ROW_H * rows.length + PAD.top + PAD.bottom;

  const x = (v: number) => plotLeft + ((v - d0) / (d1 - d0 || 1)) * plotW;
  const rowY = (i: number) => PAD.top + ROW_H * i + ROW_H / 2;

  const ticks = niceTicks(d0, d1);

  const axisIn = interpolate(frame, [0, MOTION.fadeFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ fontFamily: T.font, width }}>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 22,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: T.textMuted,
          marginBottom: 14,
          opacity: axisIn,
        }}
      >
        {metric}
      </div>

      <svg width={width} height={height} style={{ display: "block", overflow: "visible" }}>
        {/* Vertical grid, dashed 2 4, matching the blog's gridProps. */}
        {ticks.map((t, i) => (
          <line
            key={`g${i}`}
            x1={x(t)}
            x2={x(t)}
            y1={PAD.top}
            y2={height - PAD.bottom}
            stroke={GRID.stroke}
            strokeDasharray={GRID.dasharray}
            opacity={axisIn}
          />
        ))}

        {ticks.map((t, i) => (
          <text
            key={`t${i}`}
            display={(zero || zeroFraction !== undefined) && t === 0 ? "none" : undefined}
            x={x(t)}
            y={height - PAD.bottom + 30}
            textAnchor="middle"
            style={{ fill: T.textMuted, fontSize: 20, fontFamily: T.font }}
            opacity={axisIn}
          >
            {fmt(t)}
          </text>
        ))}

        {/* The zero rule. Solid, full height, drawn before any interval so the
            question "does this clear zero" is posed before it is answered. */}
        {zero && zeroFraction === undefined && d0 <= 0 && d1 >= 0 ? (
          <>
            <line
              x1={x(0)}
              x2={x(0)}
              y1={PAD.top - 6}
              y2={interpolate(frame, [0, 20], [PAD.top - 6, height - PAD.bottom + 6], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              })}
              stroke={T.text}
              strokeWidth={2}
            />
            <text
              x={x(0)}
              y={height - PAD.bottom + 30}
              textAnchor="middle"
              style={{ fill: T.text, fontSize: 22, fontFamily: T.mono, fontWeight: 600 }}
              opacity={axisIn}
            >
              0
            </text>
          </>
        ) : null}

        {rows.map((r, i) => {
          const enter = interpolate(
            frame,
            [22 + i * (MOTION.staggerFrames + 4), 22 + i * (MOTION.staggerFrames + 4) + MOTION.fadeFrames],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          );
          // The interval grows outward from the point estimate, so the eye
          // lands on the estimate first and the uncertainty arrives after.
          const grow = interpolate(
            frame,
            [30 + i * (MOTION.staggerFrames + 4), 30 + i * (MOTION.staggerFrames + 4) + 20],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          );
          const y = rowY(i);
          const fill = colorOf(r.color);
          const ciLo = r.ci ? r.point - (r.point - r.ci[0]) * grow : r.point;
          const ciHi = r.ci ? r.point + (r.ci[1] - r.point) * grow : r.point;

          return (
            <g key={r.label} opacity={enter} transform={`translate(0 ${(1 - enter) * 14})`}>
              <text
                x={LABEL_W}
                y={y}
                textAnchor="end"
                dominantBaseline="central"
                style={{
                  fill: r.emphasis ? T.text : T.textMuted,
                  fontSize: 26,
                  fontFamily: T.mono,
                  fontWeight: r.emphasis ? 600 : 400,
                }}
              >
                {r.label}
              </text>

              {r.ci ? (
                <>
                  <line
                    x1={x(ciLo)}
                    x2={x(ciHi)}
                    y1={y}
                    y2={y}
                    stroke={T.textMuted}
                    strokeWidth={2}
                  />
                  <line x1={x(ciLo)} x2={x(ciLo)} y1={y - CAP} y2={y + CAP} stroke={T.textMuted} strokeWidth={2} />
                  <line x1={x(ciHi)} x2={x(ciHi)} y1={y - CAP} y2={y + CAP} stroke={T.textMuted} strokeWidth={2} />
                </>
              ) : null}

              <circle cx={x(r.point)} cy={y} r={DOT_R} fill={fill} stroke={T.bg} strokeWidth={2} />

              {/* Value column. Never remove: identity is never colour alone. */}
              <text
                x={width - 12}
                y={y}
                textAnchor="end"
                dominantBaseline="central"
                style={{
                  fill: T.text,
                  fontSize: 28,
                  fontFamily: T.mono,
                  fontWeight: 600,
                }}
              >
                {fmt(r.point)}
              </text>

              {r.note ? (
                <text
                  x={width - 12}
                  y={y + 30}
                  textAnchor="end"
                  dominantBaseline="central"
                  style={{ fill: T.textMuted, fontSize: 18, fontFamily: T.font }}
                >
                  {r.note}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
};
