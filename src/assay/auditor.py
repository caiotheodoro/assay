"""The Auditor: the judgement the probe battery deliberately does not make.

`runner.audit` is dumb on purpose -- it applies every registered probe and
records what happened. Its docstring has said since the first commit that
"deciding which probes are worth running, and reading the results, is the
Auditor agent's job". This module is that agent. Until now it did not exist,
and the comment described a seam nobody had filled.

What lives here is the work a script provably cannot do, and nothing else.
The division is the whole argument:

    The script owns mechanism. The model owns meaning.

A probe can establish that a verifier accepts an inverted spec. That is a
mechanical fact and a program should decide it, because a program decides it
the same way every time. What a probe cannot establish is whether accepting an
inverted spec is a *defect* -- and on a personality inventory it is not, because
the question has no correct answer and a format check is the right design.
`docs/COVERAGE.md` works through that case at length and ends: "The right fix is
a capability an eval can withhold -- 'this environment has no correct answer' --
and it does not exist yet." This supplies it.

Three properties make that safe enough to ship:

1. **The model proposes; a deterministic guard decides what it may touch.**
   Only `verifier_integrity` results are in scope, only DEFECT may move, and
   only to NOT_APPLICABLE. The model can never turn a defect into a pass, and
   it can never reach a probe family it was not given.
2. **Fail closed.** No model, an unreachable one, or a reply that does not
   parse means no override. The deterministic verdict stands unchanged. A
   degraded Auditor loses recall, never precision.
3. **Nothing is silent.** Every override is recorded with the model that
   proposed it, the evidence it quoted, and the verdict it replaced, and it is
   printed on the Environment Card. A reader who disagrees can see exactly what
   was changed and undo it by dropping one flag.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .adapter import EnvAdapter
from .llm import LLMClient, LLMUnavailable
from .runner import AuditReport, audit as _run_battery
from .types import ProbeResult, ProbeStatus

#: The only family whose results the semantic gate may touch. Every probe in
#: it asks a question that presumes the environment has a correct answer, which
#: is exactly the presumption that can fail.
SEMANTIC_SCOPE = "verifier_integrity"

_SYSTEM = """\
You read one evaluation environment and answer one concrete question about it:

    Could two DIFFERENT responses to the same task both be legitimately correct,
    such that a fair scorer ought to accept both?

Answer that question first, with an example, and let the verdict follow from it.

If no -- one response is right and the others are wrong -- the environment
has a correct answer. Maths, code, question answering, classification.

If yes -- two different responses are both legitimately correct -- the
environment has no correct answer. It is eliciting an opinion, a preference, a
self-report, a personality trait, or an open-ended piece of writing. On these a
scorer that only checks the response FORMAT is correct design, not a bug: the
result is computed from the response, not graded against a key.

Reply with one JSON object and nothing else:

{"both_valid_example": "<two different responses that would both be fair, or 'none'>",
 "verdict": "has_correct_answer" | "no_correct_answer",
 "elicitation": "<what the environment elicits, three words>",
 "quote": "<the exact task text that shows it>",
 "confidence": "high" | "low"}

Quote real text from the environment. If you cannot find text that settles it,
answer has_correct_answer with low confidence -- that is the safe direction,
because it changes nothing.\
"""


@dataclass
class Override:
    """One judgement the Auditor made, and everything needed to check it."""

    probe: str
    family: str
    was: str
    now: str
    reason: str
    proposed_by: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe": self.probe,
            "family": self.family,
            "was": self.was,
            "now": self.now,
            "reason": self.reason,
            "proposed_by": self.proposed_by,
            "evidence": self.evidence,
        }


def _parse(reply: str) -> dict[str, Any] | None:
    """The first JSON object in the reply, or None.

    Small models wrap JSON in prose and fenced blocks however they like. This
    tolerates that and refuses everything else -- a reply that does not parse
    is a reply that changes nothing.
    """
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


_NONE = {"none", "none.", "n/a", "na", "", "-", "null"}


def decide(answer: dict[str, Any]) -> str | None:
    """Two independent signals, and an override only when both agree.

    The model is asked for a label and, separately, for a concrete example of
    two different responses that would both be fair. Neither is trustworthy
    alone, and the measurements say so:

    * The label alone misses. `qwen3:8b` labels `personality_BFI`
      `has_correct_answer` in 3 of 3 runs, right after writing a genuinely
      valid pair ("Yes, I tend to be disorganized" / "No, I am usually
      organized") into the example field. It contradicts its own evidence.
    * The example alone over-fires. Deriving the verdict from "is there an
      example" turns 10 of the 12 toy-triage fixtures into
      `no_correct_answer`; the model will invent a both-valid pair for an
      ordinary ticket-classification task if the field is there to fill.

    So the gate is the conjunction, and the conjunction is the point. A model
    too weak to hold the two together produces no override at all, which is
    the degradation this design wants: a weak Auditor loses recall and cannot
    lose precision. `qwen3:8b` fires on nothing. `claude-cli` fires on
    `personality_BFI` and nothing else.

    Returns None when the reply is unusable, which also changes nothing.
    """
    label = answer.get("verdict")
    example = answer.get("both_valid_example")
    if label not in ("has_correct_answer", "no_correct_answer"):
        return None
    if not isinstance(example, str):
        return None
    evidence_says_no_answer = example.strip().lower().strip(".") not in _NONE
    if label == "no_correct_answer" and evidence_says_no_answer:
        return "no_correct_answer"
    return "has_correct_answer"


class Auditor:
    """Reads an environment and the battery's results, and applies judgement.

    Stateful across environments by design: `seen` is the memory that lets a
    scorer shape recognised in one package be looked for in the next. That is
    how the `paws` defect generalises -- one `includes()` scorer that credits
    any completion containing both labels is a bug; the same shape in four more
    packages is a pattern, and only something carrying state across the run can
    say so.
    """

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client
        #: env_id -> what was concluded there. The memory lever, and the thing
        #: that makes a second environment cheaper to judge than the first.
        self.seen: dict[str, dict[str, Any]] = {}
        self.overrides: list[Override] = []

    # -- the model -----------------------------------------------------------

    @property
    def client(self) -> LLMClient | None:
        if self._client is None:
            try:
                from .llm import default_client

                self._client = default_client()
            except LLMUnavailable:
                return None
        return self._client

    def _ask(self, system: str, user: str) -> dict[str, Any] | None:
        client = self.client
        if client is None:
            return None
        try:
            return _parse(client.complete(system, user))
        except (LLMUnavailable, OSError):
            return None

    # -- the semantic gate ---------------------------------------------------

    def classify(self, adapter: EnvAdapter) -> dict[str, Any] | None:
        """Does this environment have a correct answer? None when unknown."""
        answer = self._ask(_SYSTEM, adapter.describe())
        if answer is None:
            return None
        derived = decide(answer)
        if derived is None:
            return None
        return {**answer, "model_said": answer.get("verdict"), "verdict": derived}

    def _withhold(self, result: ProbeResult, answer: dict[str, Any], who: str) -> ProbeResult:
        reason = (
            "this environment has no correct answer, so a verifier that cannot "
            "separate targets is the right design rather than a defect "
            f"({answer.get('elicitation', 'unstated')})"
        )
        self.overrides.append(
            Override(
                probe=result.probe,
                family=result.family,
                was=result.status.value,
                now=ProbeStatus.NOT_APPLICABLE.value,
                reason=reason,
                proposed_by=who,
                evidence={
                    "quote": answer.get("quote", ""),
                    "confidence": answer.get("confidence", "unstated"),
                    "withheld_findings": [f.summary() for f in result.findings],
                },
            )
        )
        return ProbeResult(
            family=result.family,
            probe=result.probe,
            status=ProbeStatus.NOT_APPLICABLE,
            reason=reason,
            detail={**result.detail, "auditor_override": True},
        )

    def review(self, adapter: EnvAdapter, report: AuditReport) -> AuditReport:
        """Apply judgement to a finished report. Never widens what was found."""
        flagged = [
            r
            for r in report.results
            if r.family == SEMANTIC_SCOPE and r.status is ProbeStatus.DEFECT
        ]
        if not flagged:
            return report

        answer = self.classify(adapter)
        self.seen[report.env_id] = {
            "classified": (answer or {}).get("verdict", "unknown"),
            "flagged_by_battery": len(flagged),
        }
        if answer is None or answer.get("verdict") != "no_correct_answer":
            # Fail closed: the deterministic verdict stands. This is also the
            # path taken when no model is reachable at all.
            return report

        who = getattr(self.client, "name", "unknown")
        report.results = [
            self._withhold(r, answer, who) if r in flagged else r for r in report.results
        ]
        return report

    # -- the whole pass ------------------------------------------------------

    def audit(self, adapter: EnvAdapter, ctx: dict[str, Any] | None = None) -> AuditReport:
        """Run the battery, then read what it produced.

        The battery call is untouched and still deterministic given `ctx`; the
        judgement happens around it, not inside it. Dropping the Auditor
        reproduces the deterministic numbers exactly.
        """
        return self.review(adapter, _run_battery(adapter, ctx))
