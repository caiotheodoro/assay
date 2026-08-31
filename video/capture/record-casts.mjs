/**
 * Records the video's terminal shots as real asciinema casts.
 *
 * Every cast is a genuine run. Nothing here is typed out or reconstructed --
 * a repository whose argument is that a claim is not a result until it is
 * checked does not get to fake its own terminal.
 *
 * Runs happen in a detached worktree, never in the published tree, because
 * full_run.py and intervals.py both write into results/ and the published
 * numbers must not move. Two footguns this script encodes so they cannot be
 * repeated by hand:
 *   - intervals.py --profile X always takes --out results/intervals-X.json,
 *     or it silently overwrites the research-run file
 *   - never two full_run.py processes at once; they share results/
 *
 * Usage:  node capture/record-casts.mjs [id ...]
 *         node capture/record-casts.mjs            # all of them
 */
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const VIDEO = resolve(HERE, "..");
const OUT = join(VIDEO, "public", "casts");
const WORKTREE =
  process.env.ASSAY_CAPTURE_TREE ?? resolve(VIDEO, "..", "..", "assay-video-capture");

/** 120x28 keeps output unwrapped and legible when scaled to 1080p. */
const WINDOW = process.env.CAST_WINDOW ?? "120x28";

const CASTS = [
  {
    id: "selftest",
    title: "every probe family fires",
    cmd: "uv run --extra adapters assay selftest",
  },
  {
    id: "intervals",
    title: "bootstrap confidence intervals",
    cmd: "uv run --extra adapters python scripts/intervals.py --resamples 10000 --seed 11",
  },
  {
    id: "full_run",
    title: "every arm over the corpus",
    cmd: "uv run --extra adapters --extra openenv python scripts/full_run.py",
  },
  {
    id: "audit",
    title: "one realistic execution",
    cmd: "uv run --extra adapters assay audit harbor/self-graded --card card.html",
  },
  {
    id: "wild_findings",
    title: "defects nobody planted",
    cmd: "uv run --extra adapters --extra sweep pytest tests/test_wild_findings.py -p no:warnings",
  },
  {
    id: "openenv_seed",
    title: "a seed accepted and dropped",
    cmd: "uv run --extra adapters --extra openenv pytest tests/test_openenv_ground_truth.py -p no:warnings",
  },
];

const wanted = process.argv.slice(2);
const todo = wanted.length ? CASTS.filter((c) => wanted.includes(c.id)) : CASTS;

if (!todo.length) {
  console.error(`no cast matched. known ids: ${CASTS.map((c) => c.id).join(", ")}`);
  process.exit(1);
}
if (!existsSync(WORKTREE)) {
  console.error(
    `capture worktree missing: ${WORKTREE}\n` +
      `create it with: git worktree add ${WORKTREE} HEAD`,
  );
  process.exit(1);
}

mkdirSync(OUT, { recursive: true });

for (const cast of todo) {
  const out = join(OUT, `${cast.id}.cast`);
  process.stdout.write(`recording ${cast.id} ... `);
  const started = Date.now();
  execFileSync(
    "asciinema",
    [
      "rec",
      "--overwrite",
      "--headless",
      "--window-size", WINDOW,
      "--output-format", "asciicast-v2",
      "--title", cast.title,
      "--command", cast.cmd,
      out,
    ],
    { cwd: WORKTREE, stdio: ["ignore", "ignore", "inherit"] },
  );
  console.log(`${((Date.now() - started) / 1000).toFixed(1)}s -> public/casts/${cast.id}.cast`);

  // The audit writes a card. Keep it: it is the artifact the panel reproduces,
  // and when it lived only in the worktree the panel's fields got invented.
  if (cast.id === "audit") {
    const card = join(WORKTREE, "card.html");
    if (existsSync(card)) {
      mkdirSync(join(VIDEO, "public", "captures"), { recursive: true });
      copyFileSync(card, join(VIDEO, "public", "captures", "audit-card.html"));
      console.log("  kept card.html -> public/captures/audit-card.html");
    }
  }
}
