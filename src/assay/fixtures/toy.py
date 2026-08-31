"""Deliberately defective environments, one planted defect family each.

A ticket-triage environment: read a support ticket, submit a category, and
optionally a rationale. Small enough to hold in your head, real enough that
every probe has something honest to bite on.

Ground truth is exact because the defects are planted. Where one injection
genuinely causes two defects -- over-rewarding escalation is both a trivial-
floor breach and a reward-hacking surface -- the variant declares both rather
than pretending real environments fail one axis at a time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from ..adapter import BaseAdapter, NotSupported
from ..types import (
    Action,
    Capability,
    DefectClass,
    Item,
    Manifest,
    MountSpec,
    Observation,
    SandboxPosture,
    Score,
    StepResult,
    Task,
    Transcript,
)

#: The deployment this fixture models, declared the way a real one would be.
#:
#: The fixture is an in-process object, so this is modelled rather than
#: measured -- the same status as its splits and its gold trajectory, which are
#: also written here rather than read off a running system. What it must be is
#: *minimal*: no network for a task with no network step, a read-only root, a
#: workspace the policy can write, and the verifier mounted outside it. That
#: keeps family 10 applicable on `healthy` without planting anything, which is
#: the whole point -- `tests/test_report.py` requires an environment on which
#: every probe in the battery can actually run, and a battery with a probe that
#: no fixture can feed has no such environment left.
#:
#: Deliberately NOT parameterised into a defective variant. A defective variant
#: is a new entry in `CATALOG`, `CATALOG` is the scored fixture corpus, and an
#: environment added to a scored corpus moves a published number. The planted
#: postures live in `tests/test_dead_zone_probes.py` instead.
TOY_POSTURE = SandboxPosture(
    network_enabled=False,
    network_required=False,
    read_only_root=True,
    user="1000",
    root_required=False,
    mounts=(
        MountSpec("toy-workspace", "/work", read_only=False),
        MountSpec("toy-verifier", "/verifier", read_only=True),
    ),
    verifier_paths=("/verifier",),
    declared_by="assay.fixtures.toy.TOY_POSTURE",
)

CATEGORIES = ["billing", "technical", "spam"]

#: Real tickets run to a paragraph. Length matters here: 5-word shingles need
#: enough text that a one-word edit is a near-duplicate rather than a rewrite,
#: and a fixture shorter than its own detector is a fixture that proves nothing.
TICKETS: list[tuple[str, str, str, str]] = [
    (
        "t1",
        "billing",
        "I was charged twice for my annual subscription this month and the second "
        "charge appeared three days after the first one cleared my account. I have "
        "checked my statement carefully and both amounts are identical down to the "
        "cent, so this does not look like a currency conversion difference or a "
        "pending authorisation that will drop off later. Please reverse the "
        "duplicate charge and confirm in writing when the refund has been issued.",
        "Your system billed my company card for the enterprise plan a second time "
        "even though our finance team already paid the invoice by bank transfer "
        "last week. We now have two payments recorded against a single quarter and "
        "our accountant will not close the books until one of them is reversed. "
        "Could you please cancel the card payment and leave the transfer in place.",
    ),
    (
        "t2",
        "technical",
        "The export button returns a five hundred server error whenever the report "
        "contains more than roughly ten thousand rows, and the browser console "
        "shows the request timing out after exactly sixty seconds. Smaller exports "
        "from the same screen complete without any problem at all, which makes me "
        "think this is a timeout on your side rather than anything to do with my "
        "network connection or the particular filters I have applied to the view.",
        "Every time I try to attach a file larger than about twenty megabytes the "
        "upload progress bar reaches the end and then the page silently returns me "
        "to the empty form with no error message displayed anywhere on screen. "
        "Smaller attachments work perfectly well on the same connection and in the "
        "same browser session, so I suspect there is an undocumented size limit "
        "that is failing without telling the user what actually went wrong.",
    ),
    (
        "t3",
        "spam",
        "CONGRATULATIONS you have been selected as our grand prize winner and a "
        "free luxury cruise for two is waiting to be claimed in your name today. "
        "Simply click the secure link below and confirm your banking details "
        "within the next twenty four hours to release the funds immediately. This "
        "exclusive offer cannot be extended and will be passed to another lucky "
        "recipient if you do not respond, so act now and claim what is yours.",
        "URGENT NOTICE your account has been flagged for an unclaimed inheritance "
        "payout of several million dollars held in an offshore escrow facility. "
        "Reply to this message with your full name, date of birth and account "
        "number so our legal department can begin the transfer without any further "
        "delay whatsoever. Failure to respond promptly will result in the entire "
        "sum being permanently forfeited to the treasury of the issuing state.",
    ),
]

#: Correct label earns this; a rationale earns the rest. The split is what
#: lets a healthy environment separate a strong policy from a lazy one.
LABEL_CREDIT = 0.6
RATIONALE_CREDIT = 0.4


@dataclass
class ToyEnv(BaseAdapter):
    """One environment. `defects` names what was planted, for scoring."""

    variant: str = "healthy"
    defects: frozenset[DefectClass] = frozenset()
    _task_id: str | None = field(default=None, init=False)
    _seed: int = field(default=0, init=False)
    _flaky: random.Random | None = field(default=None, init=False)

    # -- helpers -----------------------------------------------------------

    def _has(self, name: str) -> bool:
        return self.variant == name

    def _target(self, task_id: str) -> str:
        return next(label for tid, label, _, _ in TICKETS if tid == task_id)

    def _ticket(self, task_id: str) -> str:
        return next(text for tid, _, text, _ in TICKETS if tid == task_id)

    @staticmethod
    def _submission(transcript: Transcript) -> tuple[str | None, bool, bool]:
        """(label, has_rationale, escalated) from the last submit."""
        label, rationale, escalated = None, False, False
        for action in transcript.actions:
            if action.tool == "submit":
                label = action.args.get("label")
                rationale = bool(action.args.get("rationale"))
            elif action.tool == "escalate":
                escalated = True
        return label, rationale, escalated

    # -- manifest ----------------------------------------------------------

    def manifest(self) -> Manifest:
        caps = {
            Capability.SEPARABLE_VERIFIER,
            Capability.LIVE_STEPPING,
            Capability.SEEDED_RESET,
            Capability.GOLD_TRAJECTORY,
            Capability.INVERTIBLE_SPEC,
            Capability.KNOWN_WRONG,
            Capability.SPLITS,
            Capability.ITEM_PARTS,
            Capability.TRUE_COMPLETION,
            Capability.TRIVIAL_POLICIES,
            Capability.GRADED_POLICIES,
            Capability.SANDBOX_POSTURE,
            Capability.VERIFIER_SOURCE,
        }
        return Manifest(
            env_id=f"toy-triage/{self.variant}",
            ecosystem="fixture",
            version="0.1.0",
            source="assay.fixtures.toy",
            capabilities=frozenset(caps),
            tasks=[
                Task(
                    task_id=tid,
                    instruction=(
                        f"Read the support ticket and submit its category "
                        f"(one of {', '.join(CATEGORIES)}), with a short rationale."
                    ),
                    metadata={"ticket": text},
                )
                for tid, _, text, _ in TICKETS
            ],
        )

    # -- episode -----------------------------------------------------------

    def reset(self, task_id: str, seed: int = 0) -> Observation:
        self._task_id = task_id
        self._seed = seed
        self._flaky = random.Random() if self._has("flaky") else None
        return Observation(ok=True, data={"ticket": self._ticket(task_id)})

    def step(self, action: Action) -> StepResult:
        if action.tool not in {"submit", "escalate", "noop"}:
            return StepResult(
                Observation(ok=False, code="UNKNOWN_TOOL", message=action.tool), done=False
            )
        data: dict[str, Any] = {"accepted": action.tool}
        if self._flaky is not None:
            # A real flake: an unseeded source of variation the caller cannot control.
            data["queue_position"] = self._flaky.randint(0, 10_000)
        return StepResult(Observation(ok=True, data=data), done=action.tool != "noop")

    # -- verifier ----------------------------------------------------------

    def verify(self, transcript: Transcript, spec: Any | None = None) -> Score:
        target = spec if spec is not None else self._target(transcript.task_id)
        if self._has("unfalsifiable"):
            # Ignores the spec override entirely, so an inverted spec still passes.
            target = self._target(transcript.task_id)

        label, rationale, escalated = self._submission(transcript)

        if self._has("solved_at_reset"):
            return Score(True, 1.0, {"note": "verifier passes before anything happens"})

        if escalated and self._has("escalate_overrewarded"):
            return Score(True, 1.0, {"note": "escalation treated as a solve"})

        correct = label == target
        if self._has("weak_oracle") and label in CATEGORIES:
            # Over-broad oracle: any plausible category is accepted.
            correct = True

        reward = 0.0
        if correct:
            reward = LABEL_CREDIT
            if rationale and not self._has("rationale_ignored"):
                reward += RATIONALE_CREDIT
            elif self._has("rationale_ignored"):
                reward = LABEL_CREDIT
        return Score(
            passed=correct,
            reward=reward,
            profile={"label": label, "rationale": rationale, "escalated": escalated},
        )

    def true_completion(self, transcript: Transcript) -> float:
        label, _, _ = self._submission(transcript)
        return 1.0 if label == self._target(transcript.task_id) else 0.0

    # -- optional capabilities --------------------------------------------

    def gold_actions(self, task_id: str) -> list[Action]:
        label = self._target(task_id)
        if self._has("gold_broken"):
            label = next(c for c in CATEGORIES if c != label)
        return [Action("submit", {"label": label, "rationale": "matches the ticket content"})]

    def invert_spec(self, task_id: str) -> Any:
        # The LAST non-target category, while gold_broken uses the first, so an
        # environment with broken gold does not also look unfalsifiable.
        target = self._target(task_id)
        return [c for c in CATEGORIES if c != target][-1]

    def known_wrong_actions(self, task_id: str) -> list[Action]:
        target = self._target(task_id)
        wrong = next(c for c in CATEGORIES if c != target)
        return [Action("submit", {"label": wrong, "rationale": "confidently incorrect"})]

    def trivial_policies(self, task_id: str) -> dict[str, list[Action]]:
        return {
            "always_abstain": [Action("noop", {})],
            "always_escalate": [Action("escalate", {})],
            "majority_class": [Action("submit", {"label": "spam"})],
        }

    def graded_policies(self, task_id: str) -> dict[str, list[Action]]:
        target = self._target(task_id)
        return {
            "strong": [Action("submit", {"label": target, "rationale": "cites the ticket"})],
            "weak": [Action("submit", {"label": target})],
        }

    def sandbox_posture(self, task_id: str) -> SandboxPosture:
        return TOY_POSTURE

    def verifier_source(self, task_id: str) -> str:
        """`verify` is the verifier, so its own source is what family 11 reads.

        Handed over as source rather than described, because a description of
        what a verifier is believed to do would make the static analysis a
        statement about this docstring.
        """
        import inspect as pyinspect

        return pyinspect.getsource(type(self).verify)

    def verifier_asserts(self, task_id: str) -> list[str]:
        base = ["submitted category equals the ticket category", "a rationale is present"]
        if self._has("drifted_asserts"):
            base.append("the response includes a refund authorization code")
        return base

    # -- splits ------------------------------------------------------------

    @staticmethod
    def _bucket(text: str) -> str:
        return "long" if len(text.split()) > 65 else "short"

    def train_items(self) -> list[Item]:
        items = [
            Item(
                item_id=f"train-{tid}",
                text=train_text,
                label=label,
                parts={"length_bucket": self._bucket(train_text)},
            )
            for tid, label, train_text, _ in TICKETS
        ]
        if self._has("artifact_splits"):
            # Planted artifact: the bucket alone determines the label.
            items = [
                Item(i.item_id, i.text, i.label, {"length_bucket": str(i.label)}) for i in items
            ]
        return items

    def eval_items(self) -> list[Item]:
        if self._has("leaky_splits"):
            # Byte-identical to train: exact-hash contamination.
            return [
                Item(f"eval-{tid}", train_text, label, {"length_bucket": self._bucket(train_text)})
                for tid, label, train_text, _ in TICKETS
            ]
        if self._has("paraphrased_splits"):
            # One word changed. Exact hashing cannot see this; MinHash can.
            return [
                Item(
                    f"eval-{tid}",
                    train_text.replace("the", "teh", 1),
                    label,
                    {"length_bucket": self._bucket(train_text)},
                )
                for tid, label, train_text, _ in TICKETS
            ]
        if self._has("artifact_splits"):
            return [
                Item(f"eval-{tid}", eval_text, label, {"length_bucket": str(label)})
                for tid, label, _, eval_text in TICKETS
            ]
        return [
            Item(
                item_id=f"eval-{tid}",
                text=eval_text,
                label=label,
                parts={"length_bucket": self._bucket(eval_text)},
            )
            for tid, label, _, eval_text in TICKETS
        ]


#: variant name -> defects deliberately planted in it
CATALOG: dict[str, frozenset[DefectClass]] = {
    "healthy": frozenset(),
    "gold_broken": frozenset({DefectClass.GOLD_FAILS}),
    # A verifier that passes before anything happens is broken on every axis at
    # once, and the ground truth says so rather than pretending otherwise.
    "solved_at_reset": frozenset(
        {
            DefectClass.NOOP_PASSES,
            DefectClass.INVERT_PASSES,
            DefectClass.KNOWN_WRONG_PASSES,
            DefectClass.SEPARABILITY_LOSS,
            DefectClass.TRIVIAL_FLOOR_BREACH,
            DefectClass.REWARD_HACKABLE,
        }
    ),
    "unfalsifiable": frozenset({DefectClass.INVERT_PASSES}),
    # An oracle that accepts any plausible category also accepts an inverted
    # spec, and hands a wrong answer full marks.
    "weak_oracle": frozenset(
        {
            DefectClass.KNOWN_WRONG_PASSES,
            DefectClass.INVERT_PASSES,
            DefectClass.REWARD_HACKABLE,
        }
    ),
    "escalate_overrewarded": frozenset(
        {DefectClass.TRIVIAL_FLOOR_BREACH, DefectClass.REWARD_HACKABLE}
    ),
    "rationale_ignored": frozenset({DefectClass.SEPARABILITY_LOSS}),
    "leaky_splits": frozenset({DefectClass.CONTAMINATION_EXACT}),
    "paraphrased_splits": frozenset({DefectClass.CONTAMINATION_NEARDUP}),
    "artifact_splits": frozenset({DefectClass.SHORTCUT_LEAK}),
    "drifted_asserts": frozenset({DefectClass.SPEC_VERIFIER_MISMATCH}),
    "flaky": frozenset({DefectClass.NONDETERMINISM}),
}


def build(variant: str) -> ToyEnv:
    if variant not in CATALOG:
        raise KeyError(f"unknown fixture variant: {variant}")
    return ToyEnv(variant=variant, defects=CATALOG[variant])


def all_fixtures() -> list[ToyEnv]:
    return [build(v) for v in CATALOG]
