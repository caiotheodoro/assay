/**
 * Beat 3 - the comparison. The spine of the video.
 *
 * 3a  every arm, as a table with an inline interval per row
 * 3b  the paired differences, against the zero rule -- the whole argument
 * 3c  the four cost profiles, including the one that does not separate
 *
 * Evidence is cited, not dumped. An earlier cut replayed the raw
 * scripts/intervals.py output here; twenty-five rows of monospace proves
 * nothing to a viewer and reads as a wall. The numbers are set properly and
 * each panel names the file underneath it, which is what provenance actually
 * requires.
 *
 * No figure is written in this file. Everything, including every
 * separated/crosses-zero label, comes through src/data/results.ts from
 * results/intervals*.json -- `separated` is a boolean in the data, not a
 * judgement made here.
 */
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Beat, OVERLAP } from "../components/Beat";
import { GridGround, Panel } from "../components/GridGround";
import { Forest, ForestRow } from "../components/Forest";
import { Column, Row, Source, Table, ci } from "../components/DataPanel";
import { Crossover } from "../components/Crossover";
import {
  ARM_LABEL,
  PROFILE_LABEL,
  PROFILE_ORDER,
  arm,
  research,
  saved,
} from "../data/results";
import { T } from "../theme";
import { beats } from "../beats";

const SUB = beats("comparison");

/**
 * The one orchestrated moment in the video.
 *
 * Both interval panels pin value 0 to the same fraction of their plot, so the
 * rule can be drawn once at beat level and hold position while the rows swap
 * around it. The instrument stays; the measurements change. Everything else in
 * the cut stays deliberately quiet so this reads as intent rather than effect.
 */
const ZERO_F = 0.17;
const PLOT_LEFT = 120 + 340 + 8; // panel padding + Forest LABEL_W + PAD.left
const PLOT_W = 1620 - 170 - 30 - 340 - 8; // width - VALUE_W - PAD.right - LABEL_W - PAD.left
const ZERO_X = PLOT_LEFT + ZERO_F * PLOT_W;

const HeldZeroRule: React.FC<{ from: number; until: number }> = ({ from, until }) => {
  const frame = useCurrentFrame();
  const draw = interpolate(frame, [from, from + 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  // Retires with the last panel that has an axis; the crossover panel does not.
  const leave = interpolate(frame, [until - OVERLAP, until], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const shown = Math.min(draw, leave);
  if (shown <= 0) return null;
  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: shown }}>
      <div
        style={{
          position: "absolute",
          left: ZERO_X,
          top: 330,
          width: 2,
          height: 420 * draw,
          background: T.text,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: ZERO_X - 10,
          top: 330 + 420 * draw + 8,
          fontFamily: T.mono,
          fontSize: 22,
          fontWeight: 600,
          color: T.text,
          opacity: draw,
        }}
      >
        0
      </div>
    </AbsoluteFill>
  );
};

/**
 * The label is read off the interval, not off `separated`. Both of the
 * non-separated rows in this video used to print "crosses zero", but
 * check_env vs flag_nothing is [0, 40] -- it *touches* zero -- while
 * production-training is [-108, 652], which genuinely crosses it. Same words
 * for two different facts is exactly the imprecision this project audits.
 */
const note = (d: { ci95: [number, number]; separated: boolean }): string => {
  if (d.separated) return "separated";
  return d.ci95[0] < 0 ? "crosses zero" : "touches zero";
};

/** 3a - every arm, as a table. Precise, scannable, sourced. */
const AllArms: React.FC = () => {
  const order = Object.keys(research.arms).sort(
    (a, b) => arm(a).expected_loss.point - arm(b).expected_loss.point,
  );
  const worst = Math.max(...order.map((id) => arm(id).expected_loss.ci95[1]));

  const columns: Column[] = [
    { key: "arm", label: "arm", width: 330 },
    { key: "loss", label: "exp. loss", numeric: true, width: 170 },
    { key: "__bar", label: "" },
    { key: "ci", label: "95% CI", numeric: true, width: 250 },
    { key: "recall", label: "recall", numeric: true, width: 140 },
    { key: "prec", label: "precision", numeric: true, width: 170 },
  ];

  const rows: Row[] = order.map((id) => {
    const a = arm(id);
    return {
      key: id,
      emphasis: id === "assay",
      muted: id === "flag_nothing",
      cells: {
        arm: ARM_LABEL[id] ?? id,
        loss: String(a.expected_loss.point),
        ci: ci(a.expected_loss.ci95[0], a.expected_loss.ci95[1]),
        recall: a.recall.point.toFixed(2),
        prec: a.precision.point.toFixed(2),
      },
      bar: { point: a.expected_loss.point, ci: a.expected_loss.ci95 },
    };
  });

  return (
    <Panel
      eyebrow="the incumbent is not the floor"
      title="Every arm, one corpus, one cost model."
    >
      <Table columns={columns} rows={rows} barDomain={[0, worst]} />
      <Source
        file="results/intervals.json"
        detail={`${research.n_environments} environments · ${research.resamples.toLocaleString()} resamples · seed ${research.seed}`}
      />
    </Panel>
  );
};

/** 3b - the paired differences. The money shot. */
const PairedDifferences: React.FC = () => {
  const ours = saved("assay", "flag_everything");
  const theirs = saved("check_env", "flag_nothing");
  const rows: ForestRow[] = [
    {
      label: "assay vs flag everything",
      point: ours.point,
      ci: ours.ci95,
      color: 0,
      note: note(ours),
      emphasis: true,
    },
    {
      label: "check_env vs flag nothing",
      point: theirs.point,
      ci: theirs.ci95,
      color: "neutral",
      note: note(theirs),
    },
  ];
  return (
    <Panel
      eyebrow="paired on a shared resample"
      title="The floor is flagging everything — not the incumbent."
    >
      <Forest metric="expected loss saved" rows={rows} zeroFraction={ZERO_F} width={1620} />
      <div
        style={{
          fontFamily: T.font,
          fontSize: 25,
          color: T.textMuted,
          marginTop: 30,
          maxWidth: 1250,
          lineHeight: 1.5,
        }}
      >
        Flagging everything catches every defect by construction. Beating it is the
        claim that costs something.
      </div>
      <Source file="results/intervals.json" detail="arms[].loss_saved_vs" />
    </Panel>
  );
};

/** 3c - the four cost profiles, including the one that does not separate. */
const CostProfiles: React.FC = () => {
  const rows: ForestRow[] = PROFILE_ORDER.map((p) => {
    const d = saved("assay", "flag_everything", p);
    return {
      label: PROFILE_LABEL[p],
      point: d.point,
      ci: d.ci95,
      color: 0,
      note: note(d),
      emphasis: d.separated,
    };
  });
  return (
    <Panel eyebrow="four cost profiles" title="Wins all four. Separates on three.">
      <Forest metric="expected loss saved vs flag everything" rows={rows} zeroFraction={ZERO_F} width={1620} />
      <Source
        file="results/intervals-*.json"
        detail="flat · research-run · production-training · benchmark-publication"
      />
    </Panel>
  );
};

export const SceneComparison: React.FC = () => (
  <GridGround>
    {/* Drawn once, held across both interval panels. The one orchestrated
        moment in the cut: the instrument stays, the measurements change. */}
    <HeldZeroRule from={SUB.paired} until={SUB.crossover} />
    <Beat from={SUB.start} to={SUB.paired} name="3a all arms">
      <AllArms />
    </Beat>
    <Beat from={SUB.paired} to={SUB.profiles} name="3b paired differences">
      <PairedDifferences />
    </Beat>
    <Beat from={SUB.profiles} to={SUB.crossover} name="3c cost profiles">
      <CostProfiles />
    </Beat>
    <Beat from={SUB.crossover} name="3d the constant nobody derived">
      <Panel eyebrow="sensitivity" title="It rests on one number nobody derived.">
        <Crossover at={6} />
      </Panel>
    </Beat>
  </GridGround>
);
