/**
 * Beat 5 - the change that contributed most.
 *
 * The before state is stated qualitatively on purpose. README:236 attaches "an
 * interval straddling zero" to a margin of 36.0, but the only straddle-zero
 * interval this repo ever published, [-309, 295], belongs to 50.0 at n=24. No
 * interval was ever computed for 36.0, so quoting one would inherit that
 * inconsistency into the video.
 */
import React from "react";
import { Beat } from "../components/Beat";
import { GridGround, Panel } from "../components/GridGround";
import { Forest, ForestRow } from "../components/Forest";
import { Source } from "../components/DataPanel";
import { saved } from "../data/results";
import { beats } from "../beats";
import { T } from "../theme";

const B = beats("contributed");

const Delta: React.FC = () => {
  const now = saved("assay", "flag_everything");
  const rows: ForestRow[] = [
    {
      label: "before the taxonomy fix",
      point: 0,
      color: "neutral",
      note: "not distinguishable",
    },
    {
      label: "after",
      point: now.point,
      ci: now.ci95,
      color: 0,
      note: now.separated ? "separated" : "crosses zero",
      emphasis: true,
    },
  ];
  return (
    <Panel eyebrow="four lines of shell" title="It was not the agent.">
      <Forest metric="expected loss saved vs flagging everything" rows={rows} zero width={1620} />
      <div
        style={{
          fontFamily: T.font,
          fontSize: 25,
          color: T.textMuted,
          marginTop: 30,
          maxWidth: 1300,
          lineHeight: 1.5,
        }}
      >
        Two classes from someone else’s published taxonomy of benchmark flaws, written
        against the mechanism. The agent found the exploit first; the script finds it in
        two seconds, because the discovery was written down.
      </div>
      <Source
        file="results/intervals.json · docs/changelog/79-taxonomy-policies.md"
        detail="prior state is prose only — stated qualitatively"
      />
    </Panel>
  );
};

export const SceneContributed: React.FC = () => (
  <GridGround>
    <Beat from={0} to={B.delta} name="5a not the agent">
      <Panel
        eyebrow="the change that contributed most"
        title="We read someone else’s taxonomy, and wrote two of its classes down."
      >
        <div style={{ fontFamily: T.mono, fontSize: 27, color: T.textMuted, lineHeight: 2 }}>
          BenchJack V7 — trusting untrusted output
          <br />
          BenchJack V1 — isolation failure
        </div>
        <Source file="docs/changelog/79-taxonomy-policies.md" detail="arXiv 2605.12673, Fig. 2" />
      </Panel>
    </Beat>
    <Beat from={B.delta} name="5b the delta">
      <Delta />
    </Beat>
  </GridGround>
);
