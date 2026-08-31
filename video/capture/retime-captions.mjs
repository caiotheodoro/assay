/**
 * Retimes caption cues against the generated narration.
 *
 * Cue times in narration.json start as estimates. Once the audio exists, its
 * real duration is known, so cues are redistributed across it in proportion to
 * their character count -- an approximation of speaking time, not forced
 * alignment. It gets the cues close; drift is visible on review and is fixed by
 * hand in narration.json.
 *
 * Usage: node capture/retime-captions.mjs comparison
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const VIDEO = resolve(HERE, "..");
const NARRATION = join(VIDEO, "src", "data", "narration.json");

/** Milliseconds of silence before the first cue and between cues. */
const LEAD_MS = 350;
const GAP_MS = 140;

const duration = (file) =>
  Math.round(
    Number(
      execFileSync("ffprobe", [
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        file,
      ]).toString().trim(),
    ) * 1000,
  );

const narration = JSON.parse(readFileSync(NARRATION, "utf8"));
const RATES = JSON.parse(
  readFileSync(join(VIDEO, "src", "data", "voice-rates.json"), "utf8"),
).wpm;
const wanted = process.argv.slice(2);
const scenes = Object.keys(narration).filter(
  (k) => !k.startsWith("_") && (!wanted.length || wanted.includes(k)),
);

for (const scene of scenes) {
  const mp3 = join(VIDEO, "public", "voice", `${scene}.mp3`);
  const cuesFor = narration[scene];
  const words = cuesFor.reduce((a, c) => a + c.text.split(/\s+/).length, 0);

  /**
   * With no audio yet, predict from the block's own measured rate so the
   * timeline stays previewable and scene sub-beats land roughly right. These
   * are estimates and are overwritten the moment the mp3 exists -- the point is
   * that nothing silently collapses to frame zero.
   */
  const measured = existsSync(mp3);
  const total = measured
    ? duration(mp3)
    : Math.round((words / (RATES[scene] ?? 130)) * 60 * 1000);
  const cues = narration[scene];
  const weights = cues.map((c) => c.text.length);
  const sum = weights.reduce((a, b) => a + b, 0);
  const speakable = total - LEAD_MS - GAP_MS * (cues.length - 1);

  let t = LEAD_MS;
  cues.forEach((cue, i) => {
    const span = Math.round((weights[i] / sum) * speakable);
    cue.startMs = t;
    cue.endMs = t + span;
    t += span + GAP_MS;
  });

  console.log(
    `${scene}: ${measured ? "MEASURED" : "predicted"} ${cues.length} cues over ${(total / 1000).toFixed(1)}s ` +
      `(${cues.reduce((a, c) => a + c.text.split(/\s+/).length, 0)} words, ` +
      `${Math.round((cues.reduce((a, c) => a + c.text.split(/\s+/).length, 0) / (total / 60000)))} wpm)`,
  );
}

writeFileSync(NARRATION, `${JSON.stringify(narration, null, 2)}\n`);
