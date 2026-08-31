/**
 * Generates the narration from src/data/narration.json.
 *
 * The spoken text is not duplicated here: it is read from the same file the
 * manifest imports for captions, so a script edit changes both or neither.
 *
 * The API key is read from the credit-db capture env file rather than copied
 * into this repo. That file holds a live key in plaintext and must not be
 * committed anywhere.
 *
 * Usage:
 *   node capture/generate-voice.mjs --list          # available voices
 *   node capture/generate-voice.mjs comparison      # one scene
 *   node capture/generate-voice.mjs                 # every scene with text
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const VIDEO = resolve(HERE, "..");
const OUT = join(VIDEO, "public", "voice");

const ENV_FILE =
  process.env.ASSAY_VOICE_ENV ??
  resolve(VIDEO, "..", "..", "..", "personal-non-ml", "credit-db", "video", ".env.capture");

const readKey = () => {
  if (process.env.ELEVENLABS_API_KEY) return process.env.ELEVENLABS_API_KEY;
  if (!existsSync(ENV_FILE)) {
    throw new Error(
      `no ELEVENLABS_API_KEY in the environment and no env file at ${ENV_FILE}`,
    );
  }
  const m = /^ELEVENLABS_API_KEY=(.+)$/m.exec(readFileSync(ENV_FILE, "utf8"));
  if (!m) throw new Error(`ELEVENLABS_API_KEY not found in ${ENV_FILE}`);
  return m[1].trim();
};

const KEY = readKey();
const API = "https://api.elevenlabs.io/v1";

/** Dry and measured: low stability drift, no stylistic push. */
const VOICE_SETTINGS = {
  stability: 0.55,
  similarity_boost: 0.75,
  style: 0.0,
  use_speaker_boost: true,
  speed: 1.05,
};
const MODEL = process.env.ELEVEN_MODEL ?? "eleven_multilingual_v2";

if (process.argv.includes("--list")) {
  const res = await fetch(`${API}/voices`, { headers: { "xi-api-key": KEY } });
  if (!res.ok) throw new Error(`voices: ${res.status} ${await res.text()}`);
  const { voices } = await res.json();
  for (const v of voices) {
    const l = v.labels ?? {};
    console.log(
      `${v.voice_id}  ${v.name.padEnd(18)} ${[l.accent, l.gender, l.age, l.descriptive ?? l.use_case]
        .filter(Boolean)
        .join(" · ")}`,
    );
  }
  process.exit(0);
}

/**
 * The narration voice, chosen by the author. Recorded here rather than passed
 * on the command line so a re-run cannot silently pick a different read.
 * Override with ELEVEN_VOICE_ID only to audition alternatives.
 */
const VOICE_ID = process.env.ELEVEN_VOICE_ID ?? "pVnrL6sighQX7hVz89cp";

const narration = JSON.parse(readFileSync(join(VIDEO, "src", "data", "narration.json"), "utf8"));
const scenes = Object.keys(narration).filter((k) => !k.startsWith("_"));
const wanted = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const todo = wanted.length ? scenes.filter((s) => wanted.includes(s)) : scenes;

mkdirSync(OUT, { recursive: true });

for (const scene of todo) {
  /**
   * `spoken` overrides `text` for the voice only -- an identifier the reader
   * should not say literally, or a form that mispronounces. A cue that starts a
   * new beat is preceded by a blank line, so the pause between beats is a real
   * paragraph break rather than something inferred from punctuation.
   */
  const text = narration[scene]
    .map((c, i) => (c.beat && i > 0 ? "\n\n" : i > 0 ? " " : "") + (c.spoken ?? c.text))
    .join("");
  const words = text.split(/\s+/).length;
  process.stdout.write(`${scene}: ${words} words ... `);

  const res = await fetch(`${API}/text-to-speech/${VOICE_ID}`, {
    method: "POST",
    headers: { "xi-api-key": KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ text, model_id: MODEL, voice_settings: VOICE_SETTINGS }),
  });
  if (!res.ok) throw new Error(`tts ${scene}: ${res.status} ${await res.text()}`);

  const out = join(OUT, `${scene}.mp3`);
  writeFileSync(out, Buffer.from(await res.arrayBuffer()));
  console.log(`-> public/voice/${scene}.mp3`);
}
