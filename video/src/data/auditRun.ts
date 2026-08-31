/**
 * The audit run, parsed from the cast that recorded it.
 *
 * This module exists because the Environment Card panel was previously written
 * by hand and every field was wrong: it claimed UNVERIFIED where the tool emits
 * INVALID, invented a coverage split, listed probes that did run as not-run, and
 * carried a content digest copied from a different environment's example card.
 * A full render and a seven-point verification sweep did not catch it, because
 * every check compared the video to itself.
 *
 * So the card is no longer described; it is read. public/casts/audit.cast is a
 * committed recording of the real command, and the terminal shot the viewer
 * sees is the same bytes this parser reads. They cannot diverge.
 */
import { useEffect, useState } from "react";
import { continueRender, delayRender, staticFile } from "remotion";
import { parseCast } from "../components/TerminalCast";

const ESC = "\u001b";
const ANSI = new RegExp(`${ESC}\\[[0-9;?]*[A-Za-z]`, "g");

export interface Finding {
  severity: string;
  defectClass: string;
  task?: string;
}

export interface NotRun {
  probe: string;
  why: string;
}

export interface AuditRun {
  command: string;
  environment: string;
  adapter: string;
  verdict: string;
  coverage: { pass: number; defect: number; notApplicable: number; error: number };
  findings: Finding[];
  notRun: NotRun[];
}

export const parseAuditRun = (castText: string): AuditRun => {
  const cast = parseCast(castText);
  const out = cast.events
    .filter((e) => e.kind === "o")
    .map((e) => e.data)
    .join("")
    .replace(ANSI, "");

  const verdictLine = /^(\S+)\s+\[(\w+)\]\s+verdict:\s+(\w+)\s*$/m.exec(out);
  if (!verdictLine) throw new Error("audit cast has no verdict line");

  const cov = /^coverage:\s*\{(.+)\}\s*$/m.exec(out);
  if (!cov) throw new Error("audit cast has no coverage line");
  const num = (key: string) => {
    const m = new RegExp(`'${key}':\\s*(\\d+)`).exec(cov[1]!);
    if (!m) throw new Error(`coverage line has no ${key}`);
    return Number(m[1]);
  };

  const findings: Finding[] = [
    ...out.matchAll(/^\s+\[(\w+)\]\s+([A-Z_]+)(?:\s+on\s+(\S+))?\s*$/gm),
  ].map((m) => ({ severity: m[1]!, defectClass: m[2]!, task: m[3] }));

  const notRun: NotRun[] = [
    ...out.matchAll(/^\s+-\s+(\w+):\s+NOT_APPLICABLE\s+\((.+)\)\s*$/gm),
  ].map((m) => ({ probe: m[1]!, why: m[2]! }));

  if (findings.length === 0 && notRun.length === 0) {
    throw new Error("audit cast parsed to no findings and no not-run probes");
  }

  return {
    command: cast.header.command ?? "",
    environment: verdictLine[1]!,
    adapter: verdictLine[2]!,
    verdict: verdictLine[3]!,
    coverage: {
      pass: num("PASS"),
      defect: num("DEFECT"),
      notApplicable: num("NOT_APPLICABLE"),
      error: num("ERROR"),
    },
    findings,
    notRun,
  };
};

/**
 * Loads the committed cast and parses it, for components that render the card.
 * Async because the cast is a static asset; the render blocks until it lands so
 * a missing or unparseable cast fails the render rather than drawing a blank.
 */
export const useAuditRun = (src = "audit"): AuditRun | null => {
  const [run, setRun] = useState<AuditRun | null>(null);
  const [handle] = useState(() => delayRender(`audit run ${src}`));

  useEffect(() => {
    fetch(staticFile(`casts/${src}.cast`))
      .then((r) => r.text())
      .then((t) => {
        setRun(parseAuditRun(t));
        continueRender(handle);
      })
      .catch((e) => {
        throw new Error(`could not derive the audit run from casts/${src}.cast: ${String(e)}`);
      });
  }, [src, handle]);

  return run;
};
