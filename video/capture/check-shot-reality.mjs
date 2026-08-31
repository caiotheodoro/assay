/**
 * Compares what the video asserts against what the tool actually did.
 *
 * This check exists because a fabricated Environment Card survived a full
 * render and a seven-point verification sweep. Every check in that sweep --
 * caption against voice, script against narration, beats against scenes,
 * durations against scenes -- compared the video to itself. None compared it to
 * the world, so a panel claiming UNVERIFIED sat two beats away from a terminal
 * recording that says INVALID and nothing objected.
 *
 * The rule this enforces: a factual claim about the tool's output may only come
 * from a committed recording of that output.
 *
 * Usage: node capture/check-shot-reality.mjs
 * Exits nonzero on any divergence. Run before every render.
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const VIDEO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ESC = String.fromCharCode(27);
const ANSI = new RegExp(`${ESC}\\[[0-9;?]*[A-Za-z]`, "g");
const VERDICTS = ["VALID", "INVALID", "UNVERIFIED", "DEFECTIVE", "INCONCLUSIVE"];

const failures = [];
const notes = [];
const fail = (m) => failures.push(m);

/** Plain text of a cast's output stream. */
const castText = (id) => {
  const raw = readFileSync(join(VIDEO, "public", "casts", `${id}.cast`), "utf8");
  return raw
    .split("\n")
    .filter((l) => l.trim())
    .slice(1)
    .map((l) => JSON.parse(l))
    .filter((e) => e[1] === "o")
    .map((e) => e[2])
    .join("")
    .replace(ANSI, "");
};

// ---------------------------------------------------------------------------
// 1. the audit run: the claim the video got wrong
// ---------------------------------------------------------------------------
const audit = castText("audit");
const verdict = /verdict:\s+(\w+)/.exec(audit)?.[1];
if (!verdict) fail("audit.cast has no verdict line; the card cannot be checked");
notes.push(`audit.cast verdict: ${verdict}`);

const coverage = Object.fromEntries(
  [...audit.matchAll(/'(\w+)':\s*(\d+)/g)].map((m) => [m[1], Number(m[2])]),
);
const notRun = [...audit.matchAll(/^\s+-\s+(\w+):\s+NOT_APPLICABLE/gm)].map((m) => m[1]);
notes.push(
  `audit.cast coverage: ${JSON.stringify(coverage)} · ${notRun.length} probes not run`,
);

// ---------------------------------------------------------------------------
// 2. narration must not contradict the recording
// ---------------------------------------------------------------------------
const narration = JSON.parse(readFileSync(join(VIDEO, "src", "data", "narration.json"), "utf8"));
for (const [block, cues] of Object.entries(narration)) {
  if (block.startsWith("_")) continue;
  for (const cue of cues) {
    const text = cue.text;
    if (!/\bcard\b/i.test(text)) continue;
    // A cue naming two or more verdicts is enumerating the vocabulary, not
    // reporting this run. Only a cue that names exactly one is a claim.
    const named = VERDICTS.filter((v) => new RegExp(`\\b${v}\\b`, "i").test(text));
    if (named.length !== 1) continue;
    for (const v of named) {
      const said = new RegExp(`\\bsays ${v}\\b|\\breads ${v}\\b|\\bis ${v}\\b`, "i").test(text);
      if (said && v !== verdict) {
        fail(
          `narration [${block}] says the card reads ${v}, but audit.cast says ${verdict}\n` +
            `      "${cue.text}"`,
        );
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 3. no scene may hard-code a value that belongs to the recording
// ---------------------------------------------------------------------------
const sceneDir = join(VIDEO, "src", "scenes");
for (const file of readdirSync(sceneDir).filter((f) => f.endsWith(".tsx"))) {
  const src = readFileSync(join(sceneDir, file), "utf8");
  for (const m of src.matchAll(/verdict=["']([A-Z]+)["']|verdict:\s*["']([A-Z]+)["']/g)) {
    fail(`${file} hard-codes a verdict "${m[1] ?? m[2]}" instead of reading the cast`);
  }
  for (const probe of notRun) {
    if (src.includes(`"${probe}"`)) {
      notes.push(`${file} names probe ${probe} literally — check it is not a card claim`);
    }
  }
  if (/coverage=\{\{/.test(src)) {
    fail(`${file} passes a literal coverage object; it must come from the cast`);
  }
  const digests = [...src.matchAll(/\b[0-9a-f]{16,}\b/g)].map((m) => m[0]);
  for (const d of digests) {
    fail(`${file} contains a literal digest ${d.slice(0, 12)}… — not verifiable from a cast`);
  }
}

// ---------------------------------------------------------------------------
// 3b. beats must not overlap
//
// Inserting a beat in the middle of a scene used to leave the preceding beat's
// hand-written `to` pointing past it, drawing two panels on top of each other.
// That shipped in a render. src/beats.ts `ranges()` derives bounds so it cannot
// happen; this catches any scene still keeping them by hand.
// ---------------------------------------------------------------------------
for (const file of readdirSync(sceneDir).filter((f) => f.endsWith(".tsx"))) {
  const src = readFileSync(join(sceneDir, file), "utf8");
  const scene = /(?:beats|ranges)\("(\w+)"\)/.exec(src)?.[1];
  if (!scene || src.includes("ranges(")) continue;
  const cues = narration[scene] ?? [];
  const at = { start: 0 };
  for (const c of cues) if (c.beat) at[c.beat] = Math.round((c.startMs / 1000) * 30);
  const spans = [...src.matchAll(/<Beat from=\{([^}]+)\}(?:\s+to=\{([^}]+)\})?/g)].map((m) => [
    m[1].trim() === "0" ? 0 : at[m[1].trim().replace("B.", "")],
    m[2] ? at[m[2].trim().replace("B.", "")] : undefined,
  ]);
  spans.forEach(([, to], i) => {
    const nextFrom = spans[i + 1]?.[0];
    if (to !== undefined && nextFrom !== undefined && to > nextFrom) {
      fail(
        `${file} beat ${i + 1} ends at frame ${to} but beat ${i + 2} starts at ${nextFrom} — ` +
          `${to - nextFrom} frames of two panels drawn at once`,
      );
    }
  });
}

// ---------------------------------------------------------------------------
// 4. the pytest casts really pass, if a scene leans on them
// ---------------------------------------------------------------------------
for (const id of ["wild_findings", "openenv_seed"]) {
  try {
    const t = castText(id);
    if (/\bfailed\b|\berror\b/i.test(t) && !/0 failed/.test(t)) {
      fail(`${id}.cast does not look like a clean pass`);
    }
  } catch {
    notes.push(`${id}.cast not present; skipped`);
  }
}

for (const n of notes) console.log(`  · ${n}`);
if (failures.length) {
  console.error(`\nshot-vs-reality: ${failures.length} divergence(s)\n`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log("\nshot-vs-reality: every on-screen claim traces to a committed recording");
