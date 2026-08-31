/**
 * The video's numbers, imported from the repository's own result files.
 *
 * Nothing in `src/scenes` or `src/components` may contain a literal figure.
 * A previous revision of `docs/VIDEO.md` hardcoded every number and went stale
 * the moment twelve claims were corrected; this module is the structural fix
 * for that. If a number changes in `results/`, it changes on screen.
 *
 * `results/intervals.json` is canonical for the research-run profile: it
 * carries all eight arms, where `results/intervals-research-run.json` carries
 * six. Both agree on every shared value.
 */
import intervalsResearchRun from "../../../results/intervals.json";
import intervalsFlat from "../../../results/intervals-flat.json";
import intervalsProduction from "../../../results/intervals-production-training.json";
import intervalsBenchmark from "../../../results/intervals-benchmark-publication.json";

export interface Estimate {
  point: number;
  ci95: [number, number];
}

export interface PairedDiff extends Estimate {
  separated: boolean;
}

export interface Arm {
  expected_loss: Estimate;
  recall: Estimate;
  precision: Estimate;
  loss_saved_vs: Record<string, PairedDiff>;
}

export interface IntervalsFile {
  resamples: number;
  seed: number;
  cost_profile: string;
  n_environments: number;
  resampling_unit: string;
  why: string;
  arms: Record<string, Arm>;
}

const asFile = (raw: unknown) => raw as unknown as IntervalsFile;

export const INTERVALS = {
  "research-run": asFile(intervalsResearchRun),
  flat: asFile(intervalsFlat),
  "production-training": asFile(intervalsProduction),
  "benchmark-publication": asFile(intervalsBenchmark),
} as const;

export type ProfileName = keyof typeof INTERVALS;

/** Profiles in the order the video walks them: cheapest miss to most costly. */
export const PROFILE_ORDER: ProfileName[] = [
  "flat",
  "research-run",
  "production-training",
  "benchmark-publication",
];

export const research = INTERVALS["research-run"];

export const arm = (name: string, profile: ProfileName = "research-run"): Arm => {
  const found = INTERVALS[profile].arms[name];
  if (!found) {
    throw new Error(
      `arm "${name}" is absent from results/intervals for profile "${profile}" -- ` +
        `available: ${Object.keys(INTERVALS[profile].arms).join(", ")}`,
    );
  }
  return found;
};

/** Paired difference on a shared resample, e.g. saved("assay", "flag_everything"). */
export const saved = (
  a: string,
  b: string,
  profile: ProfileName = "research-run",
): PairedDiff => {
  const diff = arm(a, profile).loss_saved_vs[b];
  if (!diff) {
    throw new Error(`no paired difference "${a}" vs "${b}" in profile "${profile}"`);
  }
  return diff;
};

/** Human labels for arm ids. Names only -- never values. */
export const ARM_LABEL: Record<string, string> = {
  assay: "assay",
  flag_everything: "flag everything",
  flag_nothing: "flag nothing",
  check_env: "check_env",
  stratified_random: "stratified random",
  always_modal_defect: "always modal defect",
  agent_with_tools: "agent with tools",
  direct_prompt: "direct prompt",
};

export const PROFILE_LABEL: Record<ProfileName, string> = {
  flat: "flat",
  "research-run": "research run",
  "production-training": "production training",
  "benchmark-publication": "benchmark publication",
};

// ---------------------------------------------------------------------------
// The remaining scenes' sources. Same rule: imported, never transcribed.
// ---------------------------------------------------------------------------

import wildSweep from "../../../results/wild_sweep_triage.json";
import realCheckEnv from "../../../results/real_check_env.json";
import sabProbe from "../../../results/sab_metadata_probe.json";
import tau2 from "../../../results/tau2_recall.json";
import fullRun from "../../../results/full_run.json";
import repoFacts from "./repo-facts.json";

export const FACTS = repoFacts as {
  changelogFragments: number;
  changelogSliceRows: number;
  testFiles: number;
  testsCollected: number | null;
  redTeamBrokenClaims: number;
  redTeamSurvivedClaims: number;
  redTeamPartialClaims: number;
};

/** The paws finding: a constant string that scores every item. */
const paws = (wildSweep as {
  findings: {
    task: string;
    defect: string;
    verdict: string;
    severity: string;
    independent_verification: {
      target_distribution: { No: number; Yes: number; total: number };
    };
  }[];
}).findings.find((f) => f.task === "paws")!;

export const PAWS = {
  task: paws.task,
  defect: paws.defect,
  verdict: paws.verdict,
  severity: paws.severity,
  /**
   * The scorer credits any answer containing the target substring, so a single
   * constant contains both targets and takes every item. Only `total` is a
   * number in the source; "8000/8000" is prose there, so the score is built
   * from `total` rather than transcribed.
   */
  targets: paws.independent_verification.target_distribution,
  scored: paws.independent_verification.target_distribution.total,
  outOf: paws.independent_verification.target_distribution.total,
};

/**
 * The real gymnasium and stable_baselines3 checkers, run on purpose-built
 * shims. This is the honest incumbent measurement; `baselines/structural.py` is
 * a reimplementation of what they assert and its own docstring says so.
 */
export const REAL_CHECKERS = realCheckEnv as {
  gymnasium: string;
  planted_defects: number;
  detected_by_real_checkers: number;
  cases: Record<
    string,
    {
      defect_present: string | null;
      gymnasium: { verdict: string };
      stable_baselines3: { verdict: string };
      defect_detected: boolean;
      detection_basis: string;
    }
  >;
};

export const CHECK_ENV_CORPUS = {
  recall: (fullRun as { arms: Record<string, { recall: number }> }).arms.check_env.recall,
  missed: (fullRun as { arms: Record<string, { n_missed: number }> }).arms.check_env.n_missed,
  planted: (fullRun as { total_planted_defects: number }).total_planted_defects,
  get detected() {
    return this.planted - this.missed;
  },
};

/** The rejected ScienceAgentBench metadata rule. */
const r1 = (sabProbe as {
  n_tasks: number;
  rules: Record<
    string,
    {
      fired_on: number;
      of_total: number;
      fire_rate: number;
      hits_inst_subset: number[];
      recall_vs_inst: string;
      precision: number;
      verdict: string;
    }
  >;
}).rules.R1_output_path_unstated;

export const REJECTED_RULE = {
  firedOn: r1.fired_on,
  ofTotal: r1.of_total,
  fireRate: r1.fire_rate,
  precision: r1.precision,
  verdict: r1.verdict,
  /** Stored as the string "5/7"; the numerator is also len(hits_inst_subset). */
  recovered: r1.hits_inst_subset.length,
  recoveredOf: Number(r1.recall_vs_inst.split("/")[1]),
};

/** The external measurement, and the row that is indistinguishable from chance. */
const t2 = tau2 as {
  combined: {
    rates: { recall: number; precision: number };
    significance: {
      n_tasks: number;
      n_positives: number;
      n_flagged: number;
      base_rate: number;
      expected_tp_if_flagged_at_random: number;
      observed_tp: number;
      p_one_sided: number;
      "beats_random_at_0.05": boolean;
    };
  };
  combined_excluding_advisory_probe: {
    rates: { recall: number; precision: number };
    significance: { p_one_sided: number; "beats_random_at_0.05": boolean };
  };
};

export const TAU2 = {
  all: {
    recall: t2.combined.rates.recall,
    precision: t2.combined.rates.precision,
    observed: t2.combined.significance.observed_tp,
    expected: t2.combined.significance.expected_tp_if_flagged_at_random,
    p: t2.combined.significance.p_one_sided,
    beatsRandom: t2.combined.significance["beats_random_at_0.05"],
    nFlagged: t2.combined.significance.n_flagged,
    nTasks: t2.combined.significance.n_tasks,
  },
  narrower: {
    recall: t2.combined_excluding_advisory_probe.rates.recall,
    precision: t2.combined_excluding_advisory_probe.rates.precision,
    p: t2.combined_excluding_advisory_probe.significance.p_one_sided,
    beatsRandom: t2.combined_excluding_advisory_probe.significance["beats_random_at_0.05"],
  },
};

import costSensitivity from "../../../results/cost_sensitivity.json";

/**
 * How much the headline depends on the one constant nothing derives.
 *
 * research-run.yaml prices a missed CRITICAL at 120 engineer-hours and no
 * measurement produces that number. Every published figure scales linearly
 * with it, so the only honest thing to show is how far it can be wrong before
 * the ranking changes.
 */
const cs = costSensitivity as {
  shipped_value: number;
  false_alarm: number;
  exact_crossover_critical_cost: number;
  n_environments: number;
  margin: { shipped: number; crossover: number; ratio: number; reading: string };
};

export const CROSSOVER = {
  shipped: cs.shipped_value,
  crossover: cs.exact_crossover_critical_cost,
  ratio: cs.margin.ratio,
  reading: cs.margin.reading,
};
