/**
 * The video, as data.
 *
 * Copy edits and retiming happen HERE, never inside a scene component. Scenes
 * read their beat from this file and own no timing of their own.
 *
 * Word budget is the hard constraint. `docs/VIDEO.md` ran to 1151 spoken words
 * (~7:25 of TTS at ~155 wpm) against a 5:00 hard cap. This cut targets ~664
 * words across 4:30: the voice states the claim, the screen carries the digits.
 */

import narration from "./data/narration.json";

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export interface CaptionCue {
  /** Milliseconds from the start of the scene. */
  startMs: number;
  endMs: number;
  text: string;
}

export interface CastSegment {
  /** Frames into the cast to begin this segment. */
  trimBefore: number;
  /** Playback multiplier. A ramp drops no frames, so no run is ever cut. */
  playbackRate: number;
  /** How many frames of the scene this segment occupies. */
  sceneFrames: number;
}

export interface Cast {
  /** File under public/casts, recorded by capture/record-casts.mjs. */
  src: string;
  segments?: CastSegment[];
}

export interface Scene {
  id: string;
  durationInFrames: number;
  captions?: CaptionCue[];
  cast?: Cast;
}

export const scenes: Scene[] = [
  { id: "problem", durationInFrames: 1470,
    captions: narration.problem,
  },
  { id: "execution", durationInFrames: 1835,
    captions: narration.execution,
  },
  { id: "comparison", durationInFrames: 1925,
    captions: narration.comparison,
  },
  { id: "changelog", durationInFrames: 530,
    captions: narration.changelog,
  },
  { id: "contributed", durationInFrames: 795,
    captions: narration.contributed,
  },
  { id: "removed", durationInFrames: 715,
    captions: narration.removed,
  },
  { id: "close", durationInFrames: 1010,
    captions: narration.close,
  },
];

/** Frame offset of scene `i`, as a prefix sum. */
export const from = (index: number): number =>
  scenes.slice(0, index).reduce((acc, s) => acc + s.durationInFrames, 0);

export const TOTAL_FRAMES = scenes.reduce((acc, s) => acc + s.durationInFrames, 0);

/** Frames into each scene at which its narration begins. */
export const voiceOffsets: Record<string, number> = {
  problem: 15,
  execution: 15,
  comparison: 15,
  changelog: 15,
  contributed: 15,
  removed: 15,
  close: 15,
};

export const musicSrc: string | null = null; // audio/music.mp3 once chosen
export const musicVolume = 0.22;

export const PUBLISHED = {
  code: "github.com/caiotheodoro/assay",
  dataset: "huggingface.co/datasets/caiotheodoro/assay-corpus",
  model: "huggingface.co/caiotheodoro/assay-challenger-grpo",
  collection:
    "huggingface.co/collections/caiotheodoro/assay-auditing-rl-environments-with-error-bars-6a946953e05a8669da74ee65",
} as const;
