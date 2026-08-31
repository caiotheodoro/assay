/**
 * Shared content panels.
 *
 * `Quote` exists to keep an honest distinction the rest of the pipeline
 * enforces automatically: most figures on screen are imported from results/,
 * but a few facts live only as prose in the repo (the reproduction timings, the
 * prior-art table). Those are shown as quotations with a file:line citation
 * rather than dressed up as computed data.
 */
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { SERIES, T, VERDICT } from "../theme";
import { AuditRun } from "../data/auditRun";

const rise = (frame: number, at: number) =>
  interpolate(frame, [at, at + 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

/** A fact that exists only as prose in the repo, shown as a citation. */
export const Quote: React.FC<{
  children: React.ReactNode;
  cite: string;
  at?: number;
}> = ({ children, cite, at = 0 }) => {
  const o = rise(useCurrentFrame(), at);
  return (
    <div style={{ opacity: o, transform: `translateY(${(1 - o) * 12}px)`, maxWidth: 1300 }}>
      <div
        style={{
          borderLeft: `3px solid ${T.accent}`,
          paddingLeft: 26,
          fontFamily: T.font,
          fontSize: 34,
          lineHeight: 1.4,
          color: T.text,
        }}
      >
        {children}
      </div>
      <div
        style={{ marginTop: 14, marginLeft: 29, fontFamily: T.mono, fontSize: 19, color: T.textMuted }}
      >
        {cite}
      </div>
    </div>
  );
};

/** Two verifiers, one policy, opposite verdicts. */
export const SplitScore: React.FC<{
  commands: string[];
  reported: number;
  actual: number;
  at?: number;
}> = ({ commands, reported, actual, at = 0 }) => {
  const frame = useCurrentFrame();
  /**
   * No ticks. A checkmark beside the environment's 1.0 reads as "correct",
   * which is exactly backwards -- that score is the defect. The deceived
   * scorer is marked in the defect colour and the truthful one is left plain.
   */
  const Row = ({
    label,
    value,
    deceived,
    delay,
  }: { label: string; value: number; deceived: boolean; delay: number }) => {
    const o = rise(frame, at + delay);
    return (
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 24,
          opacity: o,
          transform: `translateY(${(1 - o) * 10}px)`,
        }}
      >
        <div style={{ fontFamily: T.font, fontSize: 30, color: T.textMuted, width: 480 }}>
          {label}
        </div>
        <div
          style={{
            fontFamily: T.mono,
            fontSize: 54,
            fontWeight: 700,
            color: deceived ? VERDICT.INVALID : T.text,
          }}
        >
          {value.toFixed(1)}
        </div>
        <div style={{ fontFamily: T.font, fontSize: 26, color: T.textMuted }}>
          {deceived ? "deceived" : "the truth"}
        </div>
      </div>
    );
  };

  return (
    <div>
      <div
        style={{
          background: T.codeBg,
          border: `1px solid ${T.border}`,
          borderRadius: 8,
          padding: "22px 26px",
          fontFamily: T.mono,
          fontSize: 27,
          lineHeight: 1.7,
          marginBottom: 44,
          maxWidth: 1250,
        }}
      >
        {commands.map((c, i) => {
          const o = rise(frame, at + i * 10);
          return (
            <div key={c} style={{ opacity: o, whiteSpace: "pre" }}>
              <span style={{ color: T.accent }}>$ </span>
              {c}
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        <Row label="scored by the environment" value={reported} deceived delay={26} />
        <Row label="scored by an independent verifier" value={actual} deceived={false} delay={38} />
      </div>
    </div>
  );
};

/**
 * The Environment Card, read off the recorded run.
 *
 * Every field here used to be hand-written and every one was wrong -- it
 * claimed UNVERIFIED where the tool emits INVALID, invented the coverage split,
 * listed probes that had run as not-run, and carried a digest copied from a
 * different environment. Nothing is passed in now except the parsed cast, so
 * the panel and the terminal shot beside it are the same bytes.
 *
 * `to_html` only escapes the markdown into a <pre>, so this is a designed
 * reproduction of that structure rather than a screenshot. One rule carries
 * over exactly: severity groups are skipped when empty, but "What could not be
 * checked" always renders. It is what stops a card with nothing in it reading
 * as a clean bill of health.
 */
export const CardFrame: React.FC<{ run: AuditRun; at?: number }> = ({ run, at = 0 }) => {
  const frame = useCurrentFrame();
  const o = rise(frame, at);
  const verdict = (run.verdict in VERDICT ? run.verdict : "INCONCLUSIVE") as keyof typeof VERDICT;
  const { pass, defect, notApplicable, error } = run.coverage;

  return (
    <div
      style={{
        width: 1500,
        background: T.bg,
        border: `1px solid ${T.border}`,
        borderRadius: 10,
        overflow: "hidden",
        opacity: o,
        transform: `translateY(${(1 - o) * 14}px)`,
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "20px 30px",
          borderBottom: `1px solid ${T.border}`,
        }}
      >
        <div style={{ fontFamily: T.mono, fontSize: 25, color: T.text }}>
          Environment Card · {run.environment}
        </div>
        <div
          style={{
            fontFamily: T.mono,
            fontSize: 22,
            fontWeight: 600,
            color: "#fff",
            background: VERDICT[verdict],
            borderRadius: 5,
            padding: "5px 14px",
          }}
        >
          {run.verdict}
        </div>
      </div>

      <div style={{ padding: "18px 30px", fontFamily: T.font, fontSize: 23, color: T.textMuted }}>
        {pass} probes passed · <span style={{ color: T.text, fontWeight: 600 }}>{defect} found
        defects</span> · <span style={{ color: T.text, fontWeight: 600 }}>{notApplicable} could
        not run</span> · {error} errored
      </div>

      {run.findings.length ? (
        <div style={{ padding: "0 30px 18px" }}>
          <div
            style={{
              fontFamily: T.mono,
              fontSize: 20,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: T.textMuted,
              marginBottom: 10,
            }}
          >
            Findings
          </div>
          {run.findings.map((f, i) => {
            const ro = rise(frame, at + 14 + i * 7);
            const sev = f.severity === "CRITICAL" ? VERDICT.INVALID : VERDICT.DEFECTIVE;
            return (
              <div
                key={f.defectClass}
                style={{
                  display: "flex",
                  gap: 18,
                  alignItems: "center",
                  padding: "9px 0",
                  borderTop: `1px solid ${T.border}`,
                  opacity: ro,
                  fontSize: 23,
                }}
              >
                <span
                  style={{
                    fontFamily: T.mono,
                    fontSize: 18,
                    fontWeight: 600,
                    color: "#fff",
                    background: sev,
                    borderRadius: 4,
                    padding: "3px 10px",
                  }}
                >
                  {f.severity}
                </span>
                <span style={{ fontFamily: T.mono, color: T.text }}>{f.defectClass}</span>
                {f.task ? (
                  <span style={{ fontFamily: T.font, color: T.textMuted }}>on {f.task}</span>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}

      <div style={{ padding: "0 30px 22px" }}>
        <div
          style={{
            fontFamily: T.mono,
            fontSize: 20,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: T.accent,
            marginBottom: 10,
          }}
        >
          What could not be checked
        </div>
        {run.notRun.map((r, i) => {
          const ro = rise(frame, at + 30 + i * 5);
          return (
            <div
              key={r.probe}
              style={{
                display: "flex",
                gap: 22,
                padding: "8px 0",
                borderTop: `1px solid ${T.border}`,
                opacity: ro,
                fontSize: 21,
              }}
            >
              <div style={{ fontFamily: T.mono, color: T.text, width: 340 }}>{r.probe}</div>
              <div style={{ fontFamily: T.font, color: T.textMuted }}>{r.why}</div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          padding: "14px 30px",
          borderTop: `1px solid ${T.border}`,
          background: T.bgSubtle,
          fontFamily: T.mono,
          fontSize: 18,
          color: T.textMuted,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>exit 1</span>
        <span>{run.command}</span>
      </div>
    </div>
  );
};

/** A plain enumerated list, for check lists and probe families. */
export const Checklist: React.FC<{
  items: string[];
  at?: number;
  columns?: number;
  accentIndex?: number;
}> = ({ items, at = 0, columns = 1, accentIndex = -1 }) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${columns}, 1fr)`,
        columnGap: 60,
        rowGap: 4,
      }}
    >
      {items.map((it, i) => {
        const o = rise(frame, at + i * 5);
        const hot = i === accentIndex;
        return (
          <div
            key={it}
            style={{
              display: "flex",
              gap: 18,
              alignItems: "baseline",
              padding: "10px 0",
              borderBottom: `1px solid ${T.border}`,
              opacity: o,
              transform: `translateY(${(1 - o) * 8}px)`,
            }}
          >
            <span style={{ fontFamily: T.mono, fontSize: 20, color: hot ? T.accent : T.textFaint }}>
              {String(i + 1).padStart(2, "0")}
            </span>
            <span
              style={{
                fontFamily: T.font,
                fontSize: 27,
                color: hot ? T.text : T.textMuted,
                fontWeight: hot ? 600 : 400,
              }}
            >
              {it}
            </span>
          </div>
        );
      })}
    </div>
  );
};

export { SERIES };
