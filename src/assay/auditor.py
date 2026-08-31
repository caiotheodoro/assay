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
from dataclasses import dataclass, field, replace
from typing import Any

from .adapter import EnvAdapter
from .llm import LLMClient, LLMUnavailable
from .runner import AuditReport, audit as _run_battery
from .types import Capability, Item, ProbeResult, ProbeStatus, digest

#: The only family whose results the semantic gate may touch. Every probe in
#: it asks a question that presumes the environment has a correct answer, which
#: is exactly the presumption that can fail.
SEMANTIC_SCOPE = "verifier_integrity"

#: How many declared trivial policies count as a repertoire wide enough
#: that finding nothing means something. Below this, silence is cheap.
ESCALATION_FLOOR = 5

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


# --------------------------------------------------------------------------
# NOT_APPLICABLE resolution
#
# `Probe.na(reason, **detail)` already records what a probe attempted before it
# gave up, and until now nothing read it. A probe that declines is honest and
# useless; the question is whether the thing it needed can be supplied.
# --------------------------------------------------------------------------

_PARTS_SYSTEM = """\
An evaluation item is a block of text with a label. Many are built from several
fields glued together in a fixed layout -- a passage and a question, a premise
and a hypothesis, a context and a query.

You are shown a few items that all share ONE layout. Describe that layout ONCE.
Do not answer per item and do not key your reply by item id: every item is cut
the same way, and one object describes all of them.

Give each field the LITERAL text it starts after and the LITERAL text it ends
before, copied exactly from the item, including punctuation and newlines. Use
null when a field runs to the end. `after` is what precedes the field; `before`
is what follows it. Getting these backwards makes every field empty.

Then name the ONE field that, on its own, should NOT be enough to determine the
label -- the field a shortcut would live in. If a model can answer from the
question alone without reading the passage, the benchmark is measuring the
wrong thing.

Worked example. For items laid out like:

    Answer the question about the passage.

    Passage: Water boils at 100C at sea level.

    Question: does water boil at 100C

the correct reply is exactly:

{"parts": [{"name": "passage", "after": "Passage: ", "before": "\\n\\nQuestion:"},
           {"name": "question", "after": "Question: ", "before": null}],
 "must_not_determine": "question",
 "confidence": "high"}

Reply with one JSON object in that shape and nothing else. Use only literal
substrings copied from the items; never write a regular expression. If the
items have no internal structure, reply with an empty `parts` list -- that is a
normal answer and it changes nothing.\
"""


def _slice(text: str, after: str | None, before: str | None) -> str:
    """One field, cut with literal delimiters. No regex, by construction.

    The submitted-spec adapter shipped a ReDoS once already
    (`docs/review/spec-adapter-redos.md`); a model-authored pattern compiled and
    run over every item is the same hazard with a worse author. Literal `find`
    cannot backtrack.
    """
    start = 0
    if after:
        found = text.find(after)
        if found == -1:
            return ""
        start = found + len(after)
    end = len(text)
    if before:
        found = text.find(before, start)
        if found != -1:
            end = found
    return text[start:end].strip()


class _Resolved:
    """An adapter with a split the environment never declared, and says so.

    Proxies everything to the real adapter except the two capabilities it adds.
    The split is a deterministic alternation over items sorted by id -- fitting
    a part-to-label map on one half and scoring it on the other is the standard
    way to run a partial-input baseline when a suite ships one split, and it is
    only sound because the finding carries `synthesized_split: True` so nobody
    reads it as the suite's own division.
    """

    def __init__(self, adapter: Any, spec: dict[str, Any], items: list[Item]) -> None:
        self._adapter = adapter
        self._spec = spec
        parts = [p for p in spec.get("parts", []) if isinstance(p, dict) and p.get("name")]
        rebuilt = [
            Item(
                item_id=item.item_id,
                text=item.text,
                label=item.label,
                parts={
                    str(p["name"]): _slice(item.text, p.get("after"), p.get("before"))
                    for p in parts
                },
            )
            for item in sorted(items, key=lambda i: i.item_id)
        ]
        self._train = rebuilt[0::2]
        self._eval = rebuilt[1::2]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._adapter, name)

    def manifest(self):
        base = self._adapter.manifest()
        return replace(
            base,
            capabilities=frozenset(base.capabilities)
            | {Capability.SPLITS, Capability.ITEM_PARTS},
        )

    def train_items(self) -> list[Item]:
        return self._train

    def eval_items(self) -> list[Item]:
        return self._eval


def _quotes_something(answer: dict[str, Any], task_text: str) -> bool:
    """Did the model point at part of the text, or just at the text?

    The prompt asks for "the exact task text that shows it". A quote that is the
    whole prompt is not evidence -- it is the model gesturing at what it was
    given. This is the difference between an environment whose text shows there
    is no right answer and one whose text does not show anything, and only the
    first is something to act on.
    """
    quote = answer.get("quote")
    if not isinstance(quote, str):
        return False
    quote = " ".join(quote.split()).strip()
    body = " ".join(task_text.split()).strip()
    if len(quote) < 8:
        return False
    # Strip the "task <id>:" header the gate adds before comparing lengths.
    body_no_header = body.split(":", 1)[-1].strip() if body.lower().startswith("task ") else body
    return len(quote) < len(body_no_header) * 0.9


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
        #: shape signature -> the conclusion reached on the first
        #: environment that had it. The memory lever: two environments
        #: that pose the same question to a reader get one model call
        #: between them, and the second is told where its answer came from.
        self._by_shape: dict[str, dict[str, Any]] = {}
        #: every model call this Auditor has made, for cost reporting.
        self.calls = 0
        #: one line per environment it looked at, including the ones it
        #: declined to touch. An Auditor that runs and reports nothing is
        #: indistinguishable from one that did not run, which is the
        #: failure this repo audits environments for.
        self.decisions: list[dict[str, Any]] = []
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
        self.calls += 1
        try:
            return _parse(client.complete(system, user))
        except (LLMUnavailable, OSError):
            return None

    # -- the semantic gate ---------------------------------------------------

    @staticmethod
    def task_text(adapter: EnvAdapter) -> str:
        """Only what a person answering the task would see.

        Deliberately **not** `adapter.describe()`, which is what the baseline
        arms get and which includes declared capabilities, task metadata and the
        verifier's source. Handing that to the semantic gate was a bug with a
        measurement behind it: on `harbor/vacuous-tests` both backends read the
        fixture's own metadata -- *"The verifier always exits 0. Nothing it
        reports means anything"* -- and concluded the environment had no correct
        answer. It has one. The verifier is simply broken, which is the defect
        the battery correctly found and the gate then withheld.

        "The verifier cannot distinguish answers" and "there is nothing to
        distinguish" are different claims, and only the second is this gate's
        business. Reading the verifier is how they got confused, so the gate
        does not get to read it.
        """
        manifest = adapter.manifest()
        lines = []
        for task in manifest.tasks:
            lines.append(f"task {task.task_id}:")
            lines.append((task.instruction or "").strip() or "(no instruction text)")
            lines.append("")
        return "\n".join(lines).strip() or "(this environment declares no task text)"


    @staticmethod
    def shape(adapter: EnvAdapter) -> str:
        """What makes two environments pose the same question to a reader.

        The semantic gate asks whether an environment has a correct answer, and
        that is settled by the task text, not by the verifier. Two environments
        whose instructions are identical have the same answer whatever their
        verifiers do -- which is exactly the case across the twelve toy-triage
        fixtures, where the same ticket-classification prompt is paired with
        twelve different planted defects.

        Deliberately not the manifest digest: capabilities and version differ
        between those twelve, and keying on them would defeat the whole point.
        """
        manifest = adapter.manifest()
        body = "\n".join(
            sorted({(t.instruction or "").strip() for t in manifest.tasks})
        )
        return digest({"ecosystem": manifest.ecosystem, "instructions": body})

    def classify(self, adapter: EnvAdapter) -> dict[str, Any] | None:
        """Does this environment have a correct answer? None when unknown."""
        signature = self.shape(adapter)
        remembered = self._by_shape.get(signature)
        if remembered is not None:
            return {**remembered, "carried_from": remembered["_env"]}
        text = self.task_text(adapter)
        answer = self._ask(_SYSTEM, text)
        if answer is None:
            return None
        derived = decide(answer)
        if derived is None:
            return None
        # Captured before any rewrite below: `model_said` must stay the
        # model's own label, or the card reports the gate's conclusion as
        # though the model had produced it.
        model_said = answer.get("verdict")
        if derived == "no_correct_answer" and not _quotes_something(answer, text):
            # The model was asked to quote the text that settles it and quoted
            # the whole prompt, which means it found nothing specific to point
            # at. Measured: on `harbor/self-graded` -- one imperative sentence,
            # "Write the answer to the file out.txt", which never says what the
            # question *is* -- claude-cli returned no_correct_answer in 3 of 3
            # runs with the entire instruction as its quote. The task has a
            # correct answer; the answer simply is not in the text the gate can
            # see. Abstaining is the only honest move when the question is not
            # visible, and "the quote is the whole prompt" is what that looks
            # like from here.
            answer = {**answer, "verdict": "has_correct_answer",
                      "abstained": "the quote was the whole task text, so nothing "
                                   "specific in it settles the question"}
            derived = "has_correct_answer"
        settled = {
            **answer,
            "model_said": model_said,
            "verdict": derived,
            "_env": adapter.manifest().env_id,
        }
        self._by_shape[signature] = settled
        return settled

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
        who = getattr(self.client, "name", None)
        if answer is None or answer.get("verdict") != "no_correct_answer":
            # Fail closed: the deterministic verdict stands. This is also the
            # path taken when no model is reachable at all -- and the two are
            # reported differently, because "asked and was told no" and "could
            # not ask" are not the same fact about a verdict.
            self.decisions.append({
                "env_id": report.env_id,
                "consulted": who,
                "outcome": "declined" if answer is not None else (
                    "no model reachable" if who is None else "reply unusable"
                ),
                "why": (
                    "the environment has a correct answer, so the "
                    "verifier-integrity findings stand"
                    if answer is not None else
                    "nothing was overridden; the deterministic verdict is unchanged"
                ),
                "model_said": (answer or {}).get("model_said"),
                "findings_left_standing": sum(len(r.findings) for r in flagged),
            })
            return report

        who = who or "unknown"
        report.results = [
            self._withhold(r, answer, who) if r in flagged else r for r in report.results
        ]
        self.decisions.append({
            "env_id": report.env_id,
            "consulted": who,
            "outcome": "withheld",
            "why": "this environment has no correct answer",
            "model_said": answer.get("model_said"),
            "findings_withheld": sum(len(r.findings) for r in flagged),
        })
        return report

    # -- resolving what the battery could not run ----------------------------

    def decompose(self, adapter: EnvAdapter) -> dict[str, Any] | None:
        """How an item splits into fields, and which one must not decide it."""
        try:
            items = adapter.items()
        except (AttributeError, NotImplementedError):
            return None
        if not items:
            return None
        sample = "\n\n".join(f"ITEM {i.item_id}:\n{i.text[:1200]}" for i in items[:3])
        spec = self._ask(_PARTS_SYSTEM, sample)
        if spec is None or not isinstance(spec.get("parts"), list) or not spec["parts"]:
            return None
        return spec

    def resolve(self, adapter: EnvAdapter, report: AuditReport) -> AuditReport:
        """Try to run the probes that declined for want of a split.

        Only `shortcut_leakage` for now, and only when the environment can
        enumerate its data. The probe is untouched -- it is handed an adapter
        that declares what it needs, and it decides. Anything it finds is
        marked as resting on a split the Auditor invented, because a reader who
        does not know that would over-read the result.
        """
        declined = [
            r
            for r in report.results
            if r.family == "shortcut_leakage" and r.status is ProbeStatus.NOT_APPLICABLE
        ]
        if not declined:
            return report

        spec = self.decompose(adapter)
        if spec is None:
            return report
        try:
            resolved = _Resolved(adapter, spec, adapter.items())
        except (AttributeError, NotImplementedError, TypeError):
            return report
        if not resolved.train_items() or not resolved.eval_items():
            return report

        from .probes import all_probes

        probes = [p for p in all_probes() if p.family == "shortcut_leakage"]
        rerun = [p.run(resolved, {}) for p in probes]
        who = getattr(self.client, "name", "unknown")

        by_probe = {r.probe: r for r in rerun}
        out = []
        for result in report.results:
            fresh = by_probe.get(result.probe)
            if result not in declined or fresh is None:
                out.append(result)
                continue
            if fresh.status is ProbeStatus.NOT_APPLICABLE:
                out.append(result)
                continue
            for finding in fresh.findings:
                finding.evidence["synthesized_split"] = True
                finding.evidence["split_proposed_by"] = who
                finding.evidence["parts"] = [p.get("name") for p in spec["parts"]]
            fresh.detail = {
                **fresh.detail,
                "auditor_resolved": True,
                "was": result.reason,
                "must_not_determine": spec.get("must_not_determine"),
            }
            self.overrides.append(
                Override(
                    probe=result.probe,
                    family=result.family,
                    was=result.status.value,
                    now=fresh.status.value,
                    reason=(
                        "the suite ships one split, so the probe declined; the "
                        "Auditor named the item's fields and cross-fit over a "
                        "split it synthesized"
                    ),
                    proposed_by=who,
                    evidence={
                        "parts": [p.get("name") for p in spec["parts"]],
                        "must_not_determine": spec.get("must_not_determine"),
                        "n_train": len(resolved.train_items()),
                        "n_eval": len(resolved.eval_items()),
                    },
                )
            )
            out.append(fresh)
        report.results = out
        return report

    # -- orchestration -------------------------------------------------------

    def should_escalate(self, adapter: EnvAdapter, report: AuditReport) -> tuple[bool, str]:
        """Is a second, expensive attacker worth running here? Decided in code.

        A model Challenger costs minutes and money where the scripted one costs
        about two seconds, so escalating everywhere is not a design, it is a
        bill. The condition that matters is *under-coverage*: the cheap attacker
        found nothing, and the environment declares a repertoire small enough
        that finding nothing is weak evidence rather than strong.

        Where the scripted repertoire already saturates -- `harbor/self-graded`
        since the taxonomy policies landed -- escalation is refused, and that
        refusal is the point. `docs/changelog/84-agentic-remeasured.md` records
        why: the composite takes the max gap, so a second attacker on a
        saturated floor cannot produce information, only cost.

        Returns (escalate, why) and the reason is recorded either way.
        """
        hack = [r for r in report.results if r.family == "reward_hackability"]
        if not hack:
            return False, "no reward-hackability result to improve on"
        result = hack[0]
        if result.status is ProbeStatus.DEFECT:
            return False, (
                "the scripted attacker already found an exploit here; a second "
                "one can only match it or add false positives"
            )
        if result.status is not ProbeStatus.PASS:
            return False, f"the probe did not run ({result.status.value}); nothing to escalate"
        try:
            declared = adapter.trivial_policies(next(iter(
                t.task_id for t in adapter.manifest().tasks
            )))
        except Exception:  # noqa: BLE001 - a refusal is an answer
            return False, "the environment declares no trivial policies to exhaust"
        if len(declared) >= ESCALATION_FLOOR:
            return False, (
                f"the declared repertoire is {len(declared)} policies, which is "
                "wide enough that finding nothing is evidence rather than silence"
            )
        return True, (
            f"the scripted attacker found nothing with only {len(declared)} "
            "declared policies, so the silence is weak evidence"
        )

    # -- the whole pass ------------------------------------------------------

    def audit(self, adapter: EnvAdapter, ctx: dict[str, Any] | None = None) -> AuditReport:
        """Run the battery, then read what it produced.

        The battery call is untouched and still deterministic given `ctx`; the
        judgement happens around it, not inside it. Dropping the Auditor
        reproduces the deterministic numbers exactly.
        """
        report = _run_battery(adapter, ctx)
        report = self.review(adapter, self.resolve(adapter, report))
        report.auditor_overrides = [o.to_dict() for o in self.overrides]
        return report
