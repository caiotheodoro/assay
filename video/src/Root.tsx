import React from "react";
import { Composition } from "remotion";
import { Main } from "./Main";
import { FPS, HEIGHT, TOTAL_FRAMES, WIDTH } from "./manifest";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Assay"
    component={Main}
    durationInFrames={TOTAL_FRAMES}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
);
