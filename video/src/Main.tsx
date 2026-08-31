import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile } from "remotion";
import { CaptionOverlay } from "./components/CaptionOverlay";
import { SceneChangelog } from "./scenes/SceneChangelog";
import { SceneClose } from "./scenes/SceneClose";
import { SceneComparison } from "./scenes/SceneComparison";
import { SceneContributed } from "./scenes/SceneContributed";
import { SceneExecution } from "./scenes/SceneExecution";
import { SceneProblem } from "./scenes/SceneProblem";
import { SceneRemoved } from "./scenes/SceneRemoved";
import { ScenePlaceholder } from "./scenes/ScenePlaceholder";
import { Scene, TOTAL_FRAMES, from, musicSrc, musicVolume, scenes, voiceOffsets } from "./manifest";
import { Dissolve, SCENE_OVERLAP } from "./components/Beat";
import { sansFamily } from "./fonts";
import { T } from "./theme";

const sceneContent = (scene: Scene): React.ReactNode => {
  switch (scene.id) {
    case "problem":
      return <SceneProblem />;
    case "execution":
      return <SceneExecution />;
    case "comparison":
      return <SceneComparison />;
    case "changelog":
      return <SceneChangelog />;
    case "contributed":
      return <SceneContributed />;
    case "removed":
      return <SceneRemoved />;
    case "close":
      return <SceneClose />;
    default:
      return <ScenePlaceholder id={scene.id} frames={scene.durationInFrames} />;
  }
};

/** Scenes whose narration has been generated into public/voice. */
/** Every scene is narrated. Sequences are trimmed to the scene, so a block
 *  longer than its scene loses its tail -- checked by scripts/check-fit. */
const VOICED: string[] = scenes.map((s) => s.id);

export const Main: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: T.bg, fontFamily: sansFamily }}>
    {scenes.map((scene, i) => {
      // Scenes overlap by SCENE_OVERLAP so chapter changes crossfade rather
      // than cut. The last one is not extended past the composition.
      const last = i === scenes.length - 1;
      const duration = scene.durationInFrames + (last ? 0 : SCENE_OVERLAP);
      return (
        <Sequence key={scene.id} from={from(i)} durationInFrames={duration} name={scene.id}>
          <Dissolve durationInFrames={last ? undefined : duration} overlap={SCENE_OVERLAP}>
            {sceneContent(scene)}
          </Dissolve>
          {scene.captions ? <CaptionOverlay cues={scene.captions} /> : null}
        </Sequence>
      );
    })}

    {scenes
      .filter((s) => VOICED.includes(s.id))
      .map((scene) => {
        const i = scenes.indexOf(scene);
        return (
          <Sequence
            key={`${scene.id}-voice`}
            from={from(i) + (voiceOffsets[scene.id] ?? 0)}
            name={`${scene.id} voice`}
          >
            <Audio src={staticFile(`voice/${scene.id}.mp3`)} />
          </Sequence>
        );
      })}

    {musicSrc ? (
      <Audio
        src={staticFile(musicSrc)}
        volume={(f) =>
          musicVolume *
          interpolate(f, [0, 45, TOTAL_FRAMES - 90, TOTAL_FRAMES - 10], [0, 1, 1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })
        }
      />
    ) : null}
  </AbsoluteFill>
);
