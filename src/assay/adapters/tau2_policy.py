"""A deterministic policy oracle for the tau2 retail and airline domains.

Every rule below is a transcription of one sentence of the domain's own
`policy.md`, and carries that sentence verbatim so a reader can check the
transcription rather than trust it. No rule consults a model, and no rule
knows which tasks `tau2-bench-verified` fixed.

Why this exists at all: tau2's tools already refuse the constraints they can
see locally -- exchanging a non-delivered order, refunding to a payment method
that is not the order's own. The constraints the tools deliberately leave to
the agent are the ones the policy states and the API does not check ("The API
does not check these for the agent, so the agent must make sure the rules apply
before calling the API!"). A gold action sequence that breaks one of those
executes cleanly and is then scored as correct. That is the defect class
`tau2-bench-verified` calls policy compliance, and nothing that only replays
the gold trajectory can see it.

Provenance, stated because it affects how much these numbers are worth: the
rules were written after reading FIXES.md. They are not derived from it -- each
is a policy sentence, applied to all 164 tasks -- but the author had seen the
answers, so `docs/changelog/60-tau2-recall.md` reports how many tasks each rule
fires on. A rule that fires on exactly the tasks FIXES.md names, and no others,
should be read as a rule fitted to the answer key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

#: `policy.md` opens with "The current time is 2024-05-15 15:00:00 EST." The
#: airline database is frozen against that instant, so the 24-hour
#: cancellation window and "already flown" are both decidable.
AIRLINE_NOW = datetime(2024, 5, 15, 15, 0, 0)

VALID_CANCELLATION_REASONS = ("no longer needed", "ordered by mistake")


@dataclass(frozen=True)
class Violation:
    rule: str
    quote: str
    detail: str
    action_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "policy_quote": self.quote,
            "detail": self.detail,
            "action_id": self.action_id,
        }


@dataclass
class Context:
    """Everything a rule may look at: the task, its gold actions, and the DB."""

    task: dict
    actions: list[dict]
    db: dict

    def calls(self, *names: str) -> list[dict]:
        return [a for a in self.actions if a.get("name") in names]


@dataclass(frozen=True)
class Rule:
    name: str
    check: Callable[[Context], list[Violation]]


def _arg(action: dict, key: str, default: Any = None) -> Any:
    return (action.get("arguments") or {}).get(key, default)


# --------------------------------------------------------------------------
# retail
# --------------------------------------------------------------------------

_EXCHANGE_TOOLS = ("exchange_delivered_order_items", "modify_pending_order_items")


def _retail_item_index(db: dict) -> dict[str, str]:
    """item_id -> product_id, for the one rule that needs to tell them apart."""
    index: dict[str, str] = {}
    for product_id, product in (db.get("products") or {}).items():
        for item_id in product.get("variants") or {}:
            index[item_id] = product_id
    return index


def _rule_exchange_same_option(ctx: Context) -> list[Violation]:
    out = []
    for action in ctx.calls(*_EXCHANGE_TOOLS):
        for a, b in zip(_arg(action, "item_ids") or [], _arg(action, "new_item_ids") or []):
            if a == b:
                out.append(
                    Violation(
                        "retail.exchange_same_option",
                        "each item can be exchanged to an available new item of the same "
                        "product but of different product option",
                        f"item {a} is exchanged for itself, which is not a different "
                        "product option",
                        action.get("action_id"),
                    )
                )
    return out


def _rule_exchange_cross_product(ctx: Context) -> list[Violation]:
    index = _retail_item_index(ctx.db)
    out = []
    for action in ctx.calls(*_EXCHANGE_TOOLS):
        for a, b in zip(_arg(action, "item_ids") or [], _arg(action, "new_item_ids") or []):
            pa, pb = index.get(a), index.get(b)
            if pa and pb and pa != pb:
                out.append(
                    Violation(
                        "retail.exchange_cross_product",
                        "There cannot be any change of product types, e.g. modify shirt "
                        "to shoe.",
                        f"item {a} (product {pa}) is exchanged for {b} (product {pb})",
                        action.get("action_id"),
                    )
                )
    return out


def _rule_exchange_unavailable(ctx: Context) -> list[Violation]:
    products = ctx.db.get("products") or {}
    index = _retail_item_index(ctx.db)
    out = []
    for action in ctx.calls(*_EXCHANGE_TOOLS):
        for item_id in _arg(action, "new_item_ids") or []:
            product_id = index.get(item_id)
            if product_id is None:
                continue
            variant = (products[product_id].get("variants") or {}).get(item_id) or {}
            if variant.get("available") is False:
                out.append(
                    Violation(
                        "retail.exchange_unavailable",
                        "each item can be exchanged to an available new item of the "
                        "same product",
                        f"new item {item_id} is not available",
                        action.get("action_id"),
                    )
                )
    return out


def _rule_refund_destination(ctx: Context) -> list[Violation]:
    orders = ctx.db.get("orders") or {}
    users = ctx.db.get("users") or {}
    out = []
    for action in ctx.calls("return_delivered_order_items"):
        order = orders.get(_arg(action, "order_id") or "")
        if order is None:
            continue
        target = _arg(action, "payment_method_id")
        originals = {p.get("payment_method_id") for p in order.get("payment_history") or []}
        if target in originals:
            continue
        user = users.get(order.get("user_id") or "") or {}
        method = (user.get("payment_methods") or {}).get(target) or {}
        if method.get("source") == "gift_card":
            continue
        out.append(
            Violation(
                "retail.refund_destination",
                "The refund must either go to the original payment method, or an "
                "existing gift card.",
                f"refund is directed to {target}, which is neither the order's original "
                "payment method nor a gift card on the profile",
                action.get("action_id"),
            )
        )
    return out


def _rule_cancel_reason(ctx: Context) -> list[Violation]:
    out = []
    for action in ctx.calls("cancel_pending_order"):
        reason = _arg(action, "reason")
        if reason not in VALID_CANCELLATION_REASONS:
            out.append(
                Violation(
                    "retail.cancel_reason",
                    "The user needs to confirm the order id and the reason (either 'no "
                    "longer needed' or 'ordered by mistake') for cancellation. Other "
                    "reasons are not acceptable.",
                    f"cancellation reason {reason!r} is not one of the two accepted",
                    action.get("action_id"),
                )
            )
    return out


def _rule_one_change_per_order(ctx: Context) -> list[Violation]:
    seen: dict[str, int] = {}
    out = []
    for action in ctx.calls(*_EXCHANGE_TOOLS):
        order_id = _arg(action, "order_id") or ""
        seen[order_id] = seen.get(order_id, 0) + 1
        if seen[order_id] > 1:
            out.append(
                Violation(
                    "retail.one_change_per_order",
                    "Exchange or modify order tools can only be called once per order.",
                    f"order {order_id} is modified {seen[order_id]} times",
                    action.get("action_id"),
                )
            )
    return out


def _rule_product_item_confusion(ctx: Context) -> list[Violation]:
    """A product id that is really an item id.

    Read-only lookups in a gold sequence do fail legitimately -- the simulated
    user gives a wrong email first and the agent tries again. This rule fires
    only when the argument is a valid identifier of the *other kind*, which no
    amount of user confusion produces.
    """
    products = ctx.db.get("products") or {}
    index = _retail_item_index(ctx.db)
    out = []
    for action in ctx.calls("get_product_details"):
        product_id = _arg(action, "product_id")
        if product_id in products or product_id not in index:
            continue
        out.append(
            Violation(
                "retail.product_item_confusion",
                "Note: Product ID and Item ID have no relations and should not be "
                "confused!",
                f"get_product_details is called with {product_id}, which is an item id "
                f"of product {index[product_id]}, not a product id",
                action.get("action_id"),
            )
        )
    return out


RETAIL_RULES = (
    Rule("retail.exchange_same_option", _rule_exchange_same_option),
    Rule("retail.exchange_cross_product", _rule_exchange_cross_product),
    Rule("retail.exchange_unavailable", _rule_exchange_unavailable),
    Rule("retail.refund_destination", _rule_refund_destination),
    Rule("retail.cancel_reason", _rule_cancel_reason),
    Rule("retail.one_change_per_order", _rule_one_change_per_order),
    Rule("retail.product_item_confusion", _rule_product_item_confusion),
)


# --------------------------------------------------------------------------
# airline
# --------------------------------------------------------------------------

def _reservations_named(ctx: Context) -> list[dict]:
    """Every reservation the gold actions name."""
    reservations = ctx.db.get("reservations") or {}
    out, seen = [], set()
    for action in ctx.actions:
        rid = _arg(action, "reservation_id")
        if rid and rid in reservations and rid not in seen:
            seen.add(rid)
            out.append(reservations[rid])
    return out


def _users_named(ctx: Context) -> list[dict]:
    users = ctx.db.get("users") or {}
    out, seen = [], set()
    for action in ctx.actions:
        uid = _arg(action, "user_id")
        if uid and uid not in seen and uid in users:
            seen.add(uid)
            out.append(users[uid])
    for reservation in _reservations_named(ctx):
        uid = reservation.get("user_id")
        if uid and uid not in seen and uid in users:
            seen.add(uid)
            out.append(users[uid])
    return out


def _rule_compensation_ineligible(ctx: Context) -> list[Violation]:
    certificates = ctx.calls("send_certificate")
    users = _users_named(ctx)
    if not certificates or not users:
        return []
    reservations = _reservations_named(ctx)
    eligible = any(u.get("membership") in ("silver", "gold") for u in users) or any(
        r.get("insurance") == "yes" or r.get("cabin") == "business" for r in reservations
    )
    if eligible:
        return []
    return [
        Violation(
            "airline.compensation_ineligible",
            "Do not compensate if the user is regular member and has no travel "
            "insurance and flies (basic) economy.",
            "a certificate is issued to a regular member with no insurance on any "
            "reservation the task names and no business cabin",
            certificates[0].get("action_id"),
        )
    ]


def _rule_certificate_without_change(ctx: Context) -> list[Violation]:
    """A delay certificate is conditional on the change actually happening.

    The two compensation bullets differ in amount as well as in condition --
    $100 per passenger for a cancelled flight, $50 per passenger for a delay --
    so the amount says which bullet a certificate is claiming, and only the
    delay bullet requires a change or cancellation first.
    """
    certificates = ctx.calls("send_certificate")
    if not certificates or ctx.calls("update_reservation_flights", "cancel_reservation"):
        return []
    counts = {len(r.get("passengers") or []) for r in _reservations_named(ctx)} or {1}
    out = []
    for action in certificates:
        amount = _arg(action, "amount")
        if not isinstance(amount, (int, float)):
            continue
        if any(abs(amount - 50 * n) < 1e-6 for n in counts):
            out.append(
                Violation(
                    "airline.certificate_without_change",
                    "If the user complains about delayed flights in a reservation and "
                    "wants to change or cancel the reservation, the agent can offer a "
                    "certificate as a gesture after confirming the facts and changing "
                    "or cancelling the reservation",
                    f"a ${amount:.0f} certificate (the delay rate of $50 per passenger) "
                    "is issued although the gold sequence never changes or cancels the "
                    "reservation",
                    action.get("action_id"),
                )
            )
    return out


def _rule_certificate_amount(ctx: Context) -> list[Violation]:
    counts = {len(r.get("passengers") or []) for r in _reservations_named(ctx)}
    if not counts:
        return []
    allowed = {rate * n for n in counts for rate in (50, 100)}
    out = []
    for action in ctx.calls("send_certificate"):
        amount = _arg(action, "amount")
        if not isinstance(amount, (int, float)):
            continue
        if not any(abs(amount - a) < 1e-6 for a in allowed):
            out.append(
                Violation(
                    "airline.certificate_amount",
                    "the amount being $100 times the number of passengers ... the "
                    "amount being $50 times the number of passengers",
                    f"certificate amount ${amount:.0f} is not $50 or $100 times any "
                    f"passenger count in {sorted(counts)}",
                    action.get("action_id"),
                )
            )
    return out


def _segments(flights: list) -> list[tuple]:
    return [(f.get("flight_number"), f.get("date")) for f in flights or []]


def _rule_basic_economy_modify(ctx: Context) -> list[Violation]:
    """Changing the *flights* of a basic economy reservation, not its cabin.

    `update_reservation_flights` is the tool for both -- it takes the cabin and
    the complete new segment list together -- and the policy treats them
    oppositely: "Basic economy flights cannot be modified" sits next to "In
    other cases, all reservations, including basic economy, can change cabin
    without changing the flights." Firing on the tool name alone flagged two
    airline tasks whose gold answer changes only the cabin and leaves every
    segment identical, which the policy expressly allows. So the rule compares
    the segments.
    """
    reservations = ctx.db.get("reservations") or {}
    out = []
    for action in ctx.calls("update_reservation_flights"):
        reservation = reservations.get(_arg(action, "reservation_id") or "")
        if reservation is None or reservation.get("cabin") != "basic_economy":
            continue
        if _segments(_arg(action, "flights")) == _segments(reservation.get("flights")):
            continue
        out.append(
            Violation(
                "airline.basic_economy_modify",
                "Basic economy flights cannot be modified.",
                f"reservation {reservation.get('reservation_id')} is basic economy and "
                "its flight segments are changed",
                action.get("action_id"),
            )
        )
    return out


def _rule_add_insurance(ctx: Context) -> list[Violation]:
    reservations = ctx.db.get("reservations") or {}
    out = []
    for action in ctx.calls("update_reservation_baggages"):
        reservation = reservations.get(_arg(action, "reservation_id") or "")
        if reservation is None:
            continue
        if _arg(action, "add_insurance") == "yes" and reservation.get("insurance") != "yes":
            out.append(
                Violation(
                    "airline.add_insurance",
                    "The user cannot add insurance after initial booking.",
                    f"insurance is added to reservation "
                    f"{reservation.get('reservation_id')} after booking",
                    action.get("action_id"),
                )
            )
    return out


def _rule_remove_baggage(ctx: Context) -> list[Violation]:
    reservations = ctx.db.get("reservations") or {}
    out = []
    for action in ctx.calls("update_reservation_baggages"):
        reservation = reservations.get(_arg(action, "reservation_id") or "")
        if reservation is None:
            continue
        total, current = _arg(action, "total_baggages"), reservation.get("total_baggages")
        if isinstance(total, int) and isinstance(current, int) and total < current:
            out.append(
                Violation(
                    "airline.remove_baggage",
                    "The user can add but not remove checked bags.",
                    f"checked bags go from {current} to {total}",
                    action.get("action_id"),
                )
            )
    return out


def _rule_passenger_count(ctx: Context) -> list[Violation]:
    reservations = ctx.db.get("reservations") or {}
    out = []
    for action in ctx.calls("update_reservation_passengers"):
        reservation = reservations.get(_arg(action, "reservation_id") or "")
        if reservation is None:
            continue
        new, current = _arg(action, "passengers") or [], reservation.get("passengers") or []
        if len(new) != len(current):
            out.append(
                Violation(
                    "airline.passenger_count",
                    "The user can modify passengers but cannot modify the number of "
                    "passengers.",
                    f"passenger count goes from {len(current)} to {len(new)}",
                    action.get("action_id"),
                )
            )
    return out


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _rule_cancel_ineligible(ctx: Context) -> list[Violation]:
    reservations = ctx.db.get("reservations") or {}
    flights = ctx.db.get("flights") or {}
    out = []
    for action in ctx.calls("cancel_reservation"):
        reservation = reservations.get(_arg(action, "reservation_id") or "")
        if reservation is None:
            continue
        created = _parse_date(reservation.get("created_at"))
        within_24h = (
            created is not None
            and 0 <= (AIRLINE_NOW - created).total_seconds() <= 24 * 3600
        )
        airline_cancelled = any(
            ((flights.get(seg.get("flight_number")) or {}).get("dates") or {})
            .get(seg.get("date"), {})
            .get("status")
            == "cancelled"
            for seg in reservation.get("flights") or []
        )
        if (
            within_24h
            or airline_cancelled
            or reservation.get("cabin") == "business"
            or reservation.get("insurance") == "yes"
        ):
            continue
        out.append(
            Violation(
                "airline.cancel_ineligible",
                "flight can be cancelled if any of the following is true: The booking "
                "was made within the last 24 hrs / The flight is cancelled by airline / "
                "It is a business flight / The user has travel insurance and the reason "
                "for cancellation is covered by insurance.",
                f"reservation {reservation.get('reservation_id')} meets none of the "
                "four cancellation conditions",
                action.get("action_id"),
            )
        )
    return out


def _rule_cancel_flown(ctx: Context) -> list[Violation]:
    reservations = ctx.db.get("reservations") or {}
    today = AIRLINE_NOW.replace(hour=0, minute=0, second=0)
    out = []
    for action in ctx.calls("cancel_reservation"):
        reservation = reservations.get(_arg(action, "reservation_id") or "")
        if reservation is None:
            continue
        for segment in reservation.get("flights") or []:
            departure = _parse_date(segment.get("date"))
            if departure is not None and departure < today:
                out.append(
                    Violation(
                        "airline.cancel_flown",
                        "If any portion of the flight has already been flown, the agent "
                        "cannot help and transfer is needed.",
                        f"segment {segment.get('flight_number')} on "
                        f"{segment.get('date')} is before the policy's current date "
                        f"{AIRLINE_NOW.date()}",
                        action.get("action_id"),
                    )
                )
                break
    return out


AIRLINE_RULES = (
    Rule("airline.compensation_ineligible", _rule_compensation_ineligible),
    Rule("airline.certificate_without_change", _rule_certificate_without_change),
    Rule("airline.certificate_amount", _rule_certificate_amount),
    Rule("airline.basic_economy_modify", _rule_basic_economy_modify),
    Rule("airline.add_insurance", _rule_add_insurance),
    Rule("airline.remove_baggage", _rule_remove_baggage),
    Rule("airline.passenger_count", _rule_passenger_count),
    Rule("airline.cancel_ineligible", _rule_cancel_ineligible),
    Rule("airline.cancel_flown", _rule_cancel_flown),
)

RULES: dict[str, tuple[Rule, ...]] = {"retail": RETAIL_RULES, "airline": AIRLINE_RULES}


def violations(domain: str, task: dict, actions: list[dict], db: dict) -> list[Violation]:
    ctx = Context(task=task, actions=actions, db=db)
    out: list[Violation] = []
    for rule in RULES.get(domain, ()):
        out.extend(rule.check(ctx))
    return out
