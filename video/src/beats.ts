/**
 * Sub-beat boundaries, derived from the narration audio rather than guessed.
 *
 * A cue tagged with `beat` marks where that beat starts; its startMs -- written
 * by capture/retime-captions.mjs from the real mp3 -- becomes the frame. Change
 * the voice and the visuals follow it, so they cannot drift apart.
 */
import narration from "./data/narration.json";
import { FPS } from "./manifest";

type Cue = { startMs: number; endMs: number; beat?: string; text: string };
const script = narration as unknown as Record<string, Cue[] | string>;

export const beats = (scene: string): Record<string, number> => {
  const cues = script[scene];
  if (!Array.isArray(cues)) throw new Error(`no narration for scene "${scene}"`);
  if (cues.every((c) => c.startMs === 0 && c.endMs === 0)) {
    throw new Error(
      `narration for "${scene}" has not been timed -- every sub-beat would ` +
        "collapse to frame 0. Run `node capture/retime-captions.mjs`.",
    );
  }
  const out: Record<string, number> = { start: 0 };
  for (const c of cues) {
    if (c.beat) out[c.beat] = Math.round((c.startMs / 1000) * FPS);
  }
  return out;
};

/** Frame at which the narration for a scene finishes. */
export const narrationEnd = (scene: string): number => {
  const cues = script[scene];
  if (!Array.isArray(cues)) return 0;
  return Math.round((cues[cues.length - 1]!.endMs / 1000) * FPS);
};

/**
 * Ordered beat ranges for a scene: each beat runs until the next one starts.
 *
 * Beats used to carry hand-written `from`/`to` pairs, and inserting one in the
 * middle left the preceding beat's `to` pointing past it — two panels drawn on
 * top of each other for 5.7 seconds, shipped in a render. Bounds are derived
 * here so that cannot happen: add or move a beat and its neighbours follow.
 *
 *   const R = ranges("problem");
 *   <Beat {...R.openenv} name="…">
 */
export const ranges = (scene: string): Record<string, { from: number; to?: number }> => {
  const cues = script[scene];
  if (!Array.isArray(cues)) throw new Error(`no narration for scene "${scene}"`);
  const b = beats(scene);
  const ordered = Object.entries(b).sort((a, c) => a[1] - c[1]);
  const out: Record<string, { from: number; to?: number }> = {};
  ordered.forEach(([name, from], i) => {
    const next = ordered[i + 1];
    out[name] = next ? { from, to: next[1] } : { from };
  });
  return out;
};
