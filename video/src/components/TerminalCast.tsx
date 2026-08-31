/**
 * Replays a real asciinema cast, frame-exactly.
 *
 * The casts under public/casts are genuine runs recorded by
 * capture/record-casts.mjs. This component only ever plays back what is in the
 * file: it never types, never invents a line, and never reorders output. Where
 * a run is too slow to sit through, it is ramped -- `speed` scales the cast
 * clock and the badge says so on screen, so no frame is dropped and no run is
 * cut.
 *
 * Supports asciicast v2 (absolute event times) and v3 (intervals between
 * events); the header's `version` picks the reader.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  continueRender,
  delayRender,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { T } from "../theme";

const ESC = "\x1b";

interface CastHeader {
  version: number;
  width: number;
  height: number;
  command?: string;
  title?: string;
}

interface CastEvent {
  t: number;
  kind: string;
  data: string;
}

export interface Cast {
  header: CastHeader;
  events: CastEvent[];
  duration: number;
}

export const parseCast = (text: string): Cast => {
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  const header = JSON.parse(lines[0]!) as CastHeader;
  const events: CastEvent[] = [];
  let clock = 0;
  for (const line of lines.slice(1)) {
    const row = JSON.parse(line) as [number, string, string];
    // v2 stores absolute times; v3 stores the interval since the last event.
    clock = header.version >= 3 ? clock + row[0] : row[0];
    events.push({ t: clock, kind: row[1], data: row[2] });
  }
  return {
    header,
    events,
    duration: events.length ? events[events.length - 1]!.t : 0,
  };
};

/**
 * ANSI colours remapped for a light ground. The recorded escape codes are
 * untouched; only their rendering is chosen, so pytest's greens and reds stay
 * legible on #f3f3ed and agree with the series palette instead of fighting it.
 */
const ANSI: Record<number, string> = {
  30: "#171717",
  31: "#c93d1e",
  32: "#1f7a3d",
  33: "#9a6700",
  34: "#4361ee",
  35: "#8250df",
  36: "#0e7490",
  37: "#6b6b6b",
  90: "#a3a3a3",
  91: "#d4553a",
  92: "#2f9455",
  93: "#b08200",
  94: "#5f78f0",
  95: "#9a68e3",
  96: "#2b8ba3",
  97: "#171717",
};

interface Cell {
  ch: string;
  fg: string;
  bold: boolean;
}

const blank = (): Cell => ({ ch: " ", fg: T.text, bold: false });

/** Replays every event up to `time` into a fixed grid. */
const screenAt = (cast: Cast, time: number): Cell[][] => {
  const { width, height } = cast.header;
  const grid: Cell[][] = Array.from({ length: height }, () =>
    Array.from({ length: width }, blank),
  );
  let row = 0;
  let col = 0;
  let fg: string = T.text;
  let bold = false;

  const scroll = () => {
    grid.shift();
    grid.push(Array.from({ length: width }, blank));
    row = height - 1;
  };

  const put = (ch: string) => {
    if (col >= width) {
      col = 0;
      row += 1;
    }
    while (row >= height) scroll();
    grid[row]![col] = { ch, fg, bold };
    col += 1;
  };

  for (const ev of cast.events) {
    if (ev.t > time) break;
    if (ev.kind !== "o") continue;
    const s = ev.data;
    for (let i = 0; i < s.length; i += 1) {
      const c = s[i]!;
      if (c === "\r") {
        col = 0;
        continue;
      }
      if (c === "\n") {
        row += 1;
        while (row >= height) scroll();
        continue;
      }
      if (c === "\b") {
        col = Math.max(0, col - 1);
        continue;
      }
      if (c === ESC) {
        const m = /^\[([0-9;?]*)([A-Za-z])/.exec(s.slice(i + 1));
        if (!m) continue;
        const args = (m[1] ?? "").split(";").filter(Boolean).map(Number);
        const final = m[2];
        if (final === "m") {
          if (args.length === 0) {
            fg = T.text;
            bold = false;
          }
          for (const a of args) {
            if (a === 0) {
              fg = T.text;
              bold = false;
            } else if (a === 1) bold = true;
            else if (a === 22) bold = false;
            else if (a === 39) fg = T.text;
            else if (ANSI[a]) fg = ANSI[a]!;
          }
        } else if (final === "K") {
          const from = args[0] === 1 ? 0 : col;
          const to = args[0] === 1 ? col : width;
          for (let x = from; x < to; x += 1) grid[row]![x] = blank();
        } else if (final === "J") {
          for (let y = row; y < height; y += 1) {
            for (let x = 0; x < width; x += 1) grid[y]![x] = blank();
          }
        } else if (final === "H") {
          row = Math.max(0, (args[0] ?? 1) - 1);
          col = Math.max(0, (args[1] ?? 1) - 1);
        } else if (final === "C") {
          col = Math.min(width - 1, col + (args[0] ?? 1));
        } else if (final === "D") {
          col = Math.max(0, col - (args[0] ?? 1));
        }
        i += m[0].length;
        continue;
      }
      if (c < " ") continue;
      put(c);
    }
  }
  return grid;
};

/** Rows that actually hold output, so a tall window never pads the panel. */
const usedRows = (grid: Cell[][]): number => {
  let last = 0;
  grid.forEach((line, y) => {
    if (line.some((cell) => cell.ch !== " ")) last = y;
  });
  return last + 1;
};

export interface TerminalCastProps {
  /** Basename under public/casts, without the extension. */
  src: string;
  /** Cast-clock multiplier. Shown on screen whenever it is not 1. */
  speed?: number;
  startFrame?: number;
  fontSize?: number;
  /** Pin the panel to a fixed row count instead of tracking used rows. */
  rows?: number;
}

export const TerminalCast: React.FC<TerminalCastProps> = ({
  src,
  speed = 1,
  startFrame = 0,
  fontSize = 21,
  rows,
}) => {
  const frame = useCurrentFrame() - startFrame;
  const { fps } = useVideoConfig();
  const [cast, setCast] = useState<Cast | null>(null);
  const [handle] = useState(() => delayRender(`cast ${src}`));

  useEffect(() => {
    fetch(staticFile(`casts/${src}.cast`))
      .then((r) => r.text())
      .then((t) => {
        setCast(parseCast(t));
        continueRender(handle);
      })
      .catch((e) => {
        throw new Error(`could not read casts/${src}.cast: ${String(e)}`);
      });
  }, [src, handle]);

  const castTime = Math.max(0, (frame / fps) * speed);
  const grid = useMemo(() => (cast ? screenAt(cast, castTime) : null), [cast, castTime]);

  if (!cast || !grid) return null;

  const height = rows ?? usedRows(grid);
  const shown = grid.slice(0, height);
  const elapsed = Math.min(castTime, cast.duration);
  const running = castTime < cast.duration;

  return (
    <div
      style={{
        background: T.codeBg,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: "22px 26px 18px",
        fontFamily: T.mono,
        fontSize,
        lineHeight: 1.45,
        color: T.text,
        position: "relative",
      }}
    >
      {cast.header.command ? (
        <div style={{ marginBottom: 14, whiteSpace: "pre" }}>
          <span style={{ color: T.accent }}>$ </span>
          {cast.header.command}
        </div>
      ) : null}

      {shown.map((line, y) => (
        <div key={y} style={{ whiteSpace: "pre", height: fontSize * 1.45 }}>
          {line.map((cell, x) => (
            <span key={x} style={{ color: cell.fg, fontWeight: cell.bold ? 600 : 400 }}>
              {cell.ch}
            </span>
          ))}
        </div>
      ))}

      {/* Wall clock and ramp badge: whatever was compressed, said on screen. */}
      <div
        style={{
          position: "absolute",
          top: 18,
          right: 22,
          display: "flex",
          gap: 12,
          alignItems: "center",
          fontFamily: T.mono,
          fontSize: fontSize * 0.8,
          color: T.textMuted,
        }}
      >
        {speed !== 1 ? (
          <span
            style={{
              color: T.accent,
              border: `1px solid ${T.accent}`,
              borderRadius: 4,
              padding: "1px 7px",
            }}
          >
            {"×"}
            {speed}
          </span>
        ) : null}
        <span>
          {elapsed.toFixed(1)}s{running ? " …" : ""}
        </span>
      </div>
    </div>
  );
};
