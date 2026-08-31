/**
 * How far the one underived constant can be wrong.
 *
 * Every published figure scales linearly with the price of a missed CRITICAL
 * defect, and nothing measures that price -- research-run.yaml simply asserts
 * 120 engineer-hours. So the honest visual is not the headline; it is the
 * distance between the value we shipped and the value at which the answer
 * changes. Bound to results/cost_sensitivity.json.
 */
import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { CROSSOVER } from "../data/results";
import { SERIES, T, VERDICT } from "../theme";
import { Source } from "./DataPanel";

const EASE = Easing.bezier(0.25, 0.46, 0.45, 0.94);
const W = 1500;
const MAX = 1100; // domain ceiling, comfortably past the crossover

export const Crossover: React.FC<{ at?: number }> = ({ at = 0 }) => {
  const frame = useCurrentFrame();
  const x = (v: number) => (v / MAX) * W;

  const grow = interpolate(frame, [at, at + 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE,
  });
  const flipIn = interpolate(frame, [at + 26, at + 44], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE,
  });

  const Marker: React.FC<{ v: number; label: string; sub: string; colour: string; o: number }> = ({
    v, label, sub, colour, o,
  }) => (
    <g opacity={o}>
      <line x1={x(v)} x2={x(v)} y1={16} y2={96} stroke={colour} strokeWidth={2} />
      <circle cx={x(v)} cy={96} r={7} fill={colour} />
      <text
        x={x(v)}
        y={0}
        textAnchor="middle"
        style={{ fill: colour, fontSize: 34, fontFamily: T.mono, fontWeight: 700 }}
      >
        {label}
      </text>
      <text
        x={x(v)}
        y={130}
        textAnchor="middle"
        style={{ fill: T.textMuted, fontSize: 21, fontFamily: T.font }}
      >
        {sub}
      </text>
    </g>
  );

  return (
    <div>
      <svg width={W + 40} height={190} style={{ display: "block", overflow: "visible" }}>
        <g transform="translate(10 34)">
          {/* the band in which Assay still wins */}
          <rect
            x={0}
            y={88}
            width={x(CROSSOVER.crossover) * grow}
            height={8}
            rx={4}
            fill={SERIES[0]}
            opacity={0.22}
          />
          <line x1={0} x2={W * grow} y1={96} y2={96} stroke={T.border} strokeWidth={2} />
          <Marker
            v={CROSSOVER.shipped}
            label={String(CROSSOVER.shipped)}
            sub="what we ship"
            colour={SERIES[0]}
            o={grow}
          />
          <Marker
            v={CROSSOVER.crossover}
            label={String(CROSSOVER.crossover)}
            sub="the answer changes here"
            colour={VERDICT.INVALID}
            o={flipIn}
          />
        </g>
      </svg>

      <div
        style={{
          fontFamily: T.font,
          fontSize: 27,
          color: T.text,
          marginTop: 24,
          maxWidth: 1350,
          lineHeight: 1.45,
          opacity: flipIn,
        }}
      >
        The price of a missed critical defect is a guess. It would have to be{" "}
        <strong>{CROSSOVER.ratio.toFixed(2)}× larger</strong> before flagging everything wins.
      </div>
      <Source
        file="results/cost_sensitivity.json"
        detail="engineer-hours per missed CRITICAL · severity shape held fixed"
      />
    </div>
  );
};
