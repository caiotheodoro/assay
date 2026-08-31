"""The Environment Card.

A model card describes a model. Nothing describes an environment, so this does:
what was probed, what was found, what could not be checked and why, and who has
to sign before the verdict counts.

Two rules shape the format.

Every claim carries its evidence. A finding without the numbers that produced
it is an assertion, and this whole project exists because assertions about
environment validity went unchecked for years.

Absence of evidence is reported as loudly as evidence. The `NOT_APPLICABLE`
section is not an appendix -- it is the part that stops a card with nothing in
it being read as a clean bill of health.

The same rule governs the approval section. An audit that ran unattended -- on
`--yes`, or on `ASSAY_APPROVE_ALL` in a CI job -- is a different artifact from
one a person watched, and the card has to say which it is before the reader
gets to the verdict. It also has to say when Assay ran third-party code
*outside* the container, because that is the part a reader would otherwise
assume was sandboxed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..runner import AuditReport
from ..types import ProbeStatus, Severity

VERDICT_MEANING = {
    "VALID": "Every probe ran and none found a defect.",
    "DEFECTIVE": "Defects were found. None of them invalidate the environment outright.",
    "INVALID": "A critical defect was found. Scores from this environment do not mean what they appear to.",
    "UNVERIFIED": "No defect was found, but not every probe could run. This is not a clean bill of health.",
    "INCONCLUSIVE": "A probe errored. The audit did not complete.",
}

SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]


def _fmt_evidence(evidence: dict) -> str:
    parts = []
    for key, value in evidence.items():
        if key in {"note", "attacker_trace"}:
            continue
        text = str(value)
        if len(text) > 160:
            text = text[:157] + "..."
        parts.append(f"`{key}`: {text}")
    return "; ".join(parts)


def _approval_section(report: AuditReport) -> list[str]:
    """Who approved what this audit executed, and whether anyone was there.

    A card that showed only the granted requests would record the gate opening
    and never it holding, so refusals are listed alongside.
    """
    approvals = list(getattr(report, "approvals", []) or [])
    lines = ["## Execution approval", ""]
    if not approvals:
        lines += [
            "Nothing here needed one. This audit started no container and ran no "
            "third-party code inside the auditor's process.",
            "",
        ]
        return lines

    granted = [a for a in approvals if a.get("granted")]
    refused = [a for a in approvals if not a.get("granted")]
    unattended = [a for a in granted if not a.get("interactive")]
    standing = sorted({a["approver"] for a in unattended})
    uncontained = [a for a in granted if not a.get("contained")]

    if standing:
        lines += [
            f"**This audit ran unattended.** {len(unattended)} of "
            f"{len(approvals)} request(s) were granted by a standing approval rather "
            f"than by a human answering at the time: {', '.join(f'`{s}`' for s in standing)}. "
            "Nobody saw the request below before it ran.",
            "",
        ]
    elif granted:
        lines += [
            f"A human was shown each request in full and approved "
            f"{len(granted)} of {len(approvals)}.",
            "",
        ]
    if refused and not granted:
        lines += [
            f"**Every request was refused and nothing executed.** "
            f"{len(refused)} request(s) were put to the approver and none was granted, "
            "so any probe that needed to run something reports ERROR rather than a "
            "result.",
            "",
        ]
    if uncontained:
        lines += [
            f"**{len(uncontained)} of these ran outside the sandbox.** An "
            "`inspect_ai` scorer is a Python closure and is called in the auditor's "
            "own process: no capability drop, no network namespace, no wall-clock "
            "cap. The rows marked `in-process` below are that code.",
            "",
        ]

    lines += ["| # | Approver | Answer | Containment | Request |", "|---|---|---|---|---|"]
    for i, a in enumerate(approvals, start=1):
        answer = "granted" if a.get("granted") else "**refused**"
        how = "at the keyboard" if a.get("interactive") else "standing"
        containment = "docker" if a.get("contained") else "**in-process**"
        lines.append(
            f"| {i} | `{a['approver']}` ({how}) | {answer} | {containment} | {a['what']} |"
        )
    lines.append("")

    seen: list[str] = []
    for a in approvals:
        if a["what"] in seen:
            continue
        seen.append(a["what"])
        lines += ["What the approver was shown:", "", "```"]
        lines += list(a.get("detail") or [])
        lines += ["```", ""]
    return lines


def to_markdown(report: AuditReport, *, signed_by: str | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = report.to_dict()

    lines = [
        f"# Environment Card — `{report.env_id}`",
        "",
        f"**Verdict: {report.verdict}**  ",
        VERDICT_MEANING[report.verdict],
        "",
        "| | |",
        "|---|---|",
        f"| Ecosystem | `{report.ecosystem}` |",
        f"| Environment version | `{report.env_version}` |",
        f"| Audited | {stamp} |",
        f"| Exit code | `{report.exit_code}` |",
        f"| Content digest | `{body['content_digest'][:32]}…` |",
        "",
    ]

    coverage = report.coverage
    lines += [
        "## Coverage",
        "",
        f"{coverage['PASS']} probes passed · {coverage['DEFECT']} found defects · "
        f"{coverage['NOT_APPLICABLE']} could not run · {coverage['ERROR']} errored",
        "",
    ]

    if report.findings:
        lines += ["## Findings", ""]
        for severity in SEVERITY_ORDER:
            group = [f for f in report.findings if f.severity is severity]
            if not group:
                continue
            lines.append(f"### {severity.value}")
            lines.append("")
            for finding in group:
                where = f" — `{finding.task_id}`" if finding.task_id else ""
                lines.append(f"**{finding.defect.value}**{where}")
                if finding.evidence.get("note"):
                    lines.append("")
                    lines.append(f"> {finding.evidence['note']}")
                detail = _fmt_evidence(finding.evidence)
                if detail:
                    lines += ["", detail]
                lines.append("")
    else:
        lines += ["## Findings", "", "None.", ""]

    lines += _approval_section(report)

    not_run = report.by_status(ProbeStatus.NOT_APPLICABLE)
    lines += [
        "## What could not be checked",
        "",
    ]
    if not_run:
        lines.append(
            "These probes did not run. Nothing below was verified, and the verdict "
            "reflects that rather than assuming the best."
        )
        lines += ["", "| Probe | Why not |", "|---|---|"]
        lines += [f"| `{r.probe}` | {r.reason} |" for r in not_run]
    else:
        lines.append("Nothing. Every probe ran.")
    lines.append("")

    errored = report.by_status(ProbeStatus.ERROR)
    if errored:
        lines += ["## Errors", "", "| Probe | Error |", "|---|---|"]
        lines += [f"| `{r.probe}` | {r.reason} |" for r in errored]
        lines.append("")

    lines += [
        "## Sign-off",
        "",
    ]
    if signed_by:
        lines.append(f"Reviewed and signed by **{signed_by}** on {stamp}.")
    else:
        lines.append(
            "_Unsigned._ This card blocks nothing until a human reviews it. "
            "The exit code is advisory input to that decision, not a substitute for it."
        )
    lines += [
        "",
        "---",
        "",
        f"Produced by Assay. Unkeyed content digest over the full probe output: "
        f"`{body['content_digest']}` — identifies this card and catches corruption, "
        f"but anyone who edits the body can recompute it."
        + (f" HMAC-SHA256: `{body['hmac_sha256']}`" if "hmac_sha256" in body else ""),
        "",
    ]
    return "\n".join(lines)


def to_html(report: AuditReport, *, signed_by: str | None = None) -> str:
    """Self-contained HTML, no external assets, readable in both themes."""
    import html as html_mod

    markdown = to_markdown(report, signed_by=signed_by)
    verdict_colour = {
        "VALID": "#1a7f37",
        "DEFECTIVE": "#9a6700",
        "INVALID": "#cf222e",
        "UNVERIFIED": "#8250df",
        "INCONCLUSIVE": "#6e7781",
    }[report.verdict]
    return f"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Environment Card — {html_mod.escape(report.env_id)}</title>
<style>
  :root {{ color-scheme: light dark; --fg:#1f2328; --bg:#fff; --muted:#656d76; --line:#d1d9e0; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e6edf3; --bg:#0d1117; --muted:#8b949e; --line:#30363d; }}
  }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",sans-serif; }}
  main {{ max-width:52rem; margin:0 auto; padding:2.5rem 1.25rem 4rem; }}
  .verdict {{ display:inline-block; padding:.3rem .7rem; border-radius:.4rem;
    background:{verdict_colour}; color:#fff; font-weight:600; letter-spacing:.02em; }}
  pre {{ white-space:pre-wrap; word-break:break-word; font:13px/1.55 ui-monospace,SFMono-Regular,monospace; }}
  hr {{ border:0; border-top:1px solid var(--line); margin:2rem 0; }}
</style>
<main>
<p><span class="verdict">{report.verdict}</span></p>
<pre>{html_mod.escape(markdown)}</pre>
</main>
"""
