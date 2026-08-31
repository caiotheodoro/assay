/**
 * Design tokens for the Assay solution video.
 *
 * Mirrored as literals from the site's own system
 * (`cv-related/cv/src/styles/global.css` + `src/lib/diagramTheme.ts`) for the
 * same reason `diagramTheme.ts` exists over there: `var(--color-…)` does not
 * resolve inside a headless Remotion bundle, where SVG attributes and canvas
 * measurement both need concrete values. Keep the two in sync.
 */
export const T = {
  text: "#171717", // --color-text
  textMuted: "#6b6b6b", // --color-text-secondary
  textFaint: "#a3a3a3", // --color-text-tertiary
  accent: "#c93d1e", // --color-accent
  accentPress: "#a83218", // --color-accent-hover
  bg: "#ffffff", // --color-bg
  bgSubtle: "#f8f8f7", // --color-bg-subtle
  codeBg: "#f3f3ed", // --color-code-bg
  border: "#e8e8e4", // --color-border
  borderStrong: "#d4d4cf", // --color-border-strong
  font: '"Plus Jakarta Sans", system-ui, sans-serif',
  mono: '"Geist Mono", ui-monospace, monospace',
} as const;

/**
 * Categorical series colours, validated against the light surface: lightness
 * band, chroma floor, CVD separation, normal-vision floor and contrast all
 * pass. The worst all-pairs CVD distance (chart3 vs chart1, dE 7.1 protan)
 * sits in the 6-8 band, which is only legal with secondary encoding -- so
 * every series must carry a direct value label, never colour alone.
 *
 * Assign in fixed order. Never cycle, never re-map on filtering.
 */
export const SERIES = ["#c93d1e", "#4361ee", "#1f7a3d"] as const;

/** Neutral for reference/baseline marks that carry no identity. */
export const NEUTRAL = "#a3a3a3"; // --color-text-tertiary

/**
 * Verdict colours quoted from `src/assay/card/render.py:150-154`.
 *
 * These are the artifact's own colours and they exist here ONLY so a
 * reproduced Environment Card matches the card the tool actually emits. They
 * are never used as chart encodings -- SERIES owns that -- because #cf222e and
 * #1a7f37 sit too close to SERIES[0] and SERIES[2] to carry separate meaning
 * in the same frame.
 */
export const VERDICT = {
  VALID: "#1a7f37",
  DEFECTIVE: "#9a6700",
  INVALID: "#cf222e",
  UNVERIFIED: "#8250df",
  INCONCLUSIVE: "#6e7781",
} as const;

/** Grid + axis styling, from `cv/src/components/ui/chart.tsx:41-50`. */
export const GRID = { stroke: T.border, dasharray: "2 4" } as const;

/** fadeUp from `cv/src/styles/animations.css`, as frames at 30fps. */
export const MOTION = {
  easeOut: [0.25, 0.46, 0.45, 0.94] as const,
  fadeFrames: 17, // 0.55s
  staggerFrames: 2, // ~70ms
};
