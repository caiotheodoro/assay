/**
 * Designed data surfaces, and the source line that goes under them.
 *
 * Raw terminal output is not evidence to a viewer -- it is a wall. The claim
 * has to be legible first and traceable second, so numbers are set as a proper
 * table or plot and the file they came from is cited beneath it. The citation
 * is the provenance; the dump is not.
 */
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { NEUTRAL, SERIES, T } from "../theme";
import { fmt } from "./Forest";

/** Where the numbers above came from. Small, permanent, never decorative. */
export const Source: React.FC<{ file: string; detail?: string }> = ({ file, detail }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 12,
      marginTop: 26,
      fontFamily: T.mono,
      fontSize: 19,
      color: T.textMuted,
    }}
  >
    <span
      style={{
        display: "inline-block",
        width: 7,
        height: 7,
        borderRadius: 2,
        background: T.accent,
      }}
    />
    <span style={{ color: T.text }}>{file}</span>
    {detail ? <span style={{ color: T.textFaint }}>{detail}</span> : null}
  </div>
);

export interface Column {
  key: string;
  label: string;
  /** Right-align and set in mono. Numbers always are. */
  numeric?: boolean;
  width?: number;
}

export interface Row {
  key: string;
  cells: Record<string, string>;
  /** Inline interval drawn behind the row, on a shared scale. */
  bar?: { point: number; ci: [number, number] };
  emphasis?: boolean;
  muted?: boolean;
}

export interface TableProps {
  columns: Column[];
  rows: Row[];
  startFrame?: number;
  /** Shared domain for the inline bars. */
  barDomain?: [number, number];
  width?: number;
}

/**
 * A table with an inline interval per row. The bar is a reading aid on a
 * shared scale; the digits stay the source of truth, because the palette's
 * worst colour-vision pair means identity is never colour alone.
 */
export const Table: React.FC<TableProps> = ({
  columns,
  rows,
  startFrame = 0,
  barDomain,
  width = 1620,
}) => {
  const frame = useCurrentFrame() - startFrame;
  const ROW_H = 62;
  const barCol = columns.find((c) => c.key === "__bar");
  const textCols = columns.filter((c) => c.key !== "__bar");
  const fixed = textCols.reduce((a, c) => a + (c.width ?? 180), 0);
  const barW = barCol ? width - fixed - 40 : 0;

  const dom = barDomain ?? [0, 1];
  const x = (v: number) => ((v - dom[0]) / (dom[1] - dom[0] || 1)) * barW;

  return (
    <div style={{ width, fontFamily: T.font }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          paddingBottom: 12,
          borderBottom: `1.5px solid ${T.text}`,
          fontFamily: T.mono,
          fontSize: 19,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: T.textMuted,
        }}
      >
        {columns.map((c) =>
          c.key === "__bar" ? (
            <div key={c.key} style={{ width: barW + 40 }} />
          ) : (
            <div
              key={c.key}
              style={{ width: c.width ?? 180, textAlign: c.numeric ? "right" : "left" }}
            >
              {c.label}
            </div>
          ),
        )}
      </div>

      {rows.map((r, i) => {
        const enter = interpolate(frame, [8 + i * 5, 8 + i * 5 + 15], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const grow = interpolate(frame, [14 + i * 5, 14 + i * 5 + 18], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const colour = r.emphasis ? SERIES[0] : NEUTRAL;
        return (
          <div
            key={r.key}
            style={{
              display: "flex",
              alignItems: "center",
              height: ROW_H,
              borderBottom: `1px solid ${T.border}`,
              opacity: enter,
              transform: `translateY(${(1 - enter) * 10}px)`,
              background: r.emphasis ? T.bgSubtle : "transparent",
            }}
          >
            {columns.map((c) =>
              c.key === "__bar" ? (
                <div key={c.key} style={{ width: barW + 40, paddingLeft: 20 }}>
                  {r.bar ? (
                    <svg width={barW} height={22} style={{ display: "block" }}>
                      <line
                        x1={x(r.bar.point - (r.bar.point - r.bar.ci[0]) * grow)}
                        x2={x(r.bar.point + (r.bar.ci[1] - r.bar.point) * grow)}
                        y1={11}
                        y2={11}
                        stroke={T.textMuted}
                        strokeWidth={2}
                      />
                      <circle cx={x(r.bar.point)} cy={11} r={6} fill={colour} />
                    </svg>
                  ) : null}
                </div>
              ) : (
                <div
                  key={c.key}
                  style={{
                    width: c.width ?? 180,
                    textAlign: c.numeric ? "right" : "left",
                    fontFamily: c.numeric ? T.mono : T.font,
                    fontSize: c.numeric ? 27 : 26,
                    fontWeight: r.emphasis ? 700 : c.numeric ? 600 : 500,
                    color: r.muted ? T.textFaint : r.emphasis ? T.text : T.textMuted,
                  }}
                >
                  {r.cells[c.key] ?? ""}
                </div>
              ),
            )}
          </div>
        );
      })}
    </div>
  );
};

export const ci = (lo: number, hi: number): string => `[${fmt(lo)}, ${fmt(hi)}]`;
