/**
 * A beat that is scripted but not yet built. Renders its id and length so the
 * timeline is always complete and a partial render never silently omits time.
 */
import React from "react";
import { AbsoluteFill } from "remotion";
import { Eyebrow, GridGround } from "../components/GridGround";
import { T } from "../theme";

export const ScenePlaceholder: React.FC<{ id: string; frames: number }> = ({ id, frames }) => (
  <GridGround>
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <Eyebrow style={{ color: T.textFaint }}>not yet built</Eyebrow>
      <div style={{ fontFamily: T.mono, fontSize: 46, color: T.textMuted, marginTop: 16 }}>
        {id}
      </div>
      <div style={{ fontFamily: T.mono, fontSize: 24, color: T.textFaint, marginTop: 10 }}>
        {frames} frames · {(frames / 30).toFixed(1)}s
      </div>
    </AbsoluteFill>
  </GridGround>
);
