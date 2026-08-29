"""The tau2 ground truth: what counts as a labelled defect, and why.

These tests run everywhere. They exercise the label rule, the FIXES.md parser
and the policy oracle against hand-written fixtures, so a change to any of them
fails here rather than silently moving the recall number in
`results/tau2_recall.json`. The tests that need the two pinned snapshots live
in `test_tau2_adapter.py` and skip with a reason when the cache is absent.
"""

from __future__ import annotations

from assay.adapters import tau2_policy
from assay.tau2_truth import (
    categorise,
    changed_fields,
    mechanical_category,
    parse_fixes,
    _anchors,
)


def test_reward_basis_alone_is_not_a_defect():
    """The fork dropped `reward_basis` from all 164 tasks.

    Counting a schema change as a per-task fix would label every task a
    positive and make recall meaningless, so it is excluded by name.
    """
    base = {"id": "1", "evaluation_criteria": {"reward_basis": ["DB"], "actions": []}}
    fixed = {"id": "1", "evaluation_criteria": {"actions": []}}
    assert changed_fields(base, fixed) == []


def test_a_real_field_change_is_a_defect():
    base = {"id": "1", "user_scenario": {"instructions": {"reason_for_call": "a"}}}
    fixed = {"id": "1", "user_scenario": {"instructions": {"reason_for_call": "b"}}}
    assert changed_fields(base, fixed) == [
        "/user_scenario/instructions/reason_for_call"
    ]


def test_added_field_counts_as_changed():
    assert changed_fields({"a": 1}, {"a": 1, "b": 2}) == ["/b"]


def test_mechanical_category_splits_answer_from_instruction():
    assert mechanical_category(["/evaluation_criteria/actions[0]/name"]) == (
        "ground_truth_annotation"
    )
    assert mechanical_category(
        ["/user_scenario/instructions/reason_for_call"]
    ) == "instruction_underspecification"
    # A fix that touches both is an annotation fix: the graded answer moved.
    assert mechanical_category(
        ["/user_scenario/instructions/reason_for_call", "/evaluation_criteria/actions[0]"]
    ) == "ground_truth_annotation"


def test_categorise_prefers_the_more_specific_evidence():
    # An identical-item exchange cites a policy rule, but the defect is the
    # impossibility, not the citation.
    assert categorise("Exchanging for the identical item is not allowed", True) == (
        "logical_consistency"
    )
    assert categorise("In the database, item 123 is cheaper", False) == (
        "database_accuracy"
    )
    assert categorise("The change was made for consistency", True) == (
        "policy_compliance"
    )
    assert categorise("Emphasis added to clarify the exception", False) == (
        "evaluation_ambiguity"
    )
    # No signal at all is reported as ambiguity, the weakest claim, not as a
    # policy violation.
    assert categorise("", False) == "evaluation_ambiguity"


def test_anchors_strip_the_editorial_markup():
    """FIXES.md emphasis and ellipses never appear in the task files."""
    got = _anchors(['Added: "...you want to change your user address and all orders..."'])
    assert "you want to change your user address and all orders" in got


def test_anchors_extract_item_ids():
    got = _anchors(['`new_item_ids: ["8069050545"]` (blue leather)'])
    assert '"8069050545"' in got


def test_anchors_drop_fragments_too_short_to_be_a_fingerprint():
    assert _anchors(["Added: yes"]) == []


FIXES_SAMPLE = """
## Retail Domain Fixes

### Task: Office Chair Exchange (Task 17 - Mei Davis)

**Location:** `new_item_ids` in actions

**Change to expected action:**
- **Before:** `new_item_ids: ["8069050545"]` (blue leather)
- **After:** `new_item_ids: ["3609437808"]` (red leather)

**Why:** In the database, item `8069050545` is the **same item** the user
already has. Exchanging for the identical item is not allowed.

> **Policy Reference (Retail - Exchange delivered order):**
> *"each item can be exchanged to an available new item of the same product"*

---

## Airline Domain Fixes

### Task: Delayed Flight Complaint (Task 2 - Noah Muller)

**Change:**
- **Before:** "You want compensation for the delay of at least $200 per person."
- **After:** "You want compensation for the delay, but you do not want to change."

**Why:** Policy states a certificate is only issued after changing or
cancelling the reservation.
"""


def test_parse_fixes_splits_by_heading_and_keeps_the_domain():
    records = parse_fixes(FIXES_SAMPLE)
    assert [r.domain for r in records] == ["retail", "airline"]
    assert records[0].title.startswith("Task: Office Chair Exchange")


def test_parse_fixes_keeps_the_policy_quote_and_categorises():
    retail, airline = parse_fixes(FIXES_SAMPLE)
    assert retail.policy_quote is not None
    assert retail.category == "logical_consistency"
    assert airline.policy_quote is None
    assert airline.category == "policy_compliance"


# --------------------------------------------------------------------------
# the policy oracle
# --------------------------------------------------------------------------

RETAIL_DB = {
    "products": {
        "P1": {
            "variants": {
                "1111111111": {"available": True, "price": 10.0},
                "2222222222": {"available": True, "price": 12.0},
                "3333333333": {"available": False, "price": 9.0},
            }
        },
        "P2": {"variants": {"4444444444": {"available": True, "price": 30.0}}},
    },
    "orders": {
        "#W1": {
            "user_id": "u1",
            "payment_history": [{"payment_method_id": "credit_card_1"}],
        }
    },
    "users": {
        "u1": {
            "payment_methods": {
                "credit_card_1": {"source": "credit_card"},
                "credit_card_2": {"source": "credit_card"},
                "gift_card_1": {"source": "gift_card"},
            }
        }
    },
}


def _retail(actions):
    return [v.rule for v in tau2_policy.violations("retail", {}, actions, RETAIL_DB)]


def test_exchanging_an_item_for_itself_is_a_violation():
    rules = _retail(
        [
            {
                "action_id": "a",
                "name": "exchange_delivered_order_items",
                "arguments": {
                    "order_id": "#W1",
                    "item_ids": ["1111111111"],
                    "new_item_ids": ["1111111111"],
                    "payment_method_id": "credit_card_1",
                },
            }
        ]
    )
    assert "retail.exchange_same_option" in rules


def test_exchanging_for_a_different_option_is_clean():
    assert (
        _retail(
            [
                {
                    "action_id": "a",
                    "name": "exchange_delivered_order_items",
                    "arguments": {
                        "order_id": "#W1",
                        "item_ids": ["1111111111"],
                        "new_item_ids": ["2222222222"],
                        "payment_method_id": "credit_card_1",
                    },
                }
            ]
        )
        == []
    )


def test_exchanging_across_products_and_to_an_unavailable_item():
    rules = _retail(
        [
            {
                "action_id": "a",
                "name": "exchange_delivered_order_items",
                "arguments": {
                    "order_id": "#W1",
                    "item_ids": ["1111111111", "1111111111"],
                    "new_item_ids": ["4444444444", "3333333333"],
                    "payment_method_id": "credit_card_1",
                },
            }
        ]
    )
    assert "retail.exchange_cross_product" in rules
    assert "retail.exchange_unavailable" in rules


def test_refund_to_a_third_credit_card_is_a_violation_but_a_gift_card_is_not():
    def refund(target):
        return _retail(
            [
                {
                    "action_id": "a",
                    "name": "return_delivered_order_items",
                    "arguments": {"order_id": "#W1", "payment_method_id": target},
                }
            ]
        )

    assert "retail.refund_destination" in refund("credit_card_2")
    assert refund("credit_card_1") == []
    assert refund("gift_card_1") == []


def test_a_product_id_that_is_really_an_item_id():
    rules = _retail(
        [
            {
                "action_id": "a",
                "name": "get_product_details",
                "arguments": {"product_id": "1111111111"},
            }
        ]
    )
    assert rules == ["retail.product_item_confusion"]


def test_a_genuinely_unknown_product_id_is_not_flagged():
    """A wrong guess is not a defect; a valid id of the wrong kind is."""
    assert (
        _retail(
            [
                {
                    "action_id": "a",
                    "name": "get_product_details",
                    "arguments": {"product_id": "0000000000"},
                }
            ]
        )
        == []
    )


AIRLINE_DB = {
    "users": {
        "u1": {"membership": "regular"},
        "u2": {"membership": "gold"},
    },
    "reservations": {
        "R1": {
            "reservation_id": "R1",
            "user_id": "u1",
            "cabin": "economy",
            "insurance": "no",
            "created_at": "2024-04-01T10:00:00",
            "total_baggages": 2,
            "passengers": [{"first_name": "A"}, {"first_name": "B"}],
            "flights": [{"flight_number": "HAT1", "date": "2024-05-20"}],
        },
        "R2": {
            "reservation_id": "R2",
            "user_id": "u1",
            "cabin": "basic_economy",
            "insurance": "no",
            "created_at": "2024-04-01T10:00:00",
            "total_baggages": 0,
            "passengers": [{"first_name": "A"}],
            "flights": [{"flight_number": "HAT2", "date": "2024-05-01"}],
        },
    },
    "flights": {},
}


def _airline(actions):
    return [v.rule for v in tau2_policy.violations("airline", {}, actions, AIRLINE_DB)]


def test_delay_certificate_without_a_change_is_a_violation():
    rules = _airline(
        [
            {"action_id": "a", "name": "get_reservation_details",
             "arguments": {"reservation_id": "R1"}},
            {"action_id": "b", "name": "send_certificate",
             "arguments": {"user_id": "u1", "amount": 100}},
        ]
    )
    assert "airline.certificate_without_change" in rules


def test_the_same_certificate_after_a_change_is_clean_of_that_rule():
    rules = _airline(
        [
            {"action_id": "a", "name": "get_reservation_details",
             "arguments": {"reservation_id": "R1"}},
            {"action_id": "b", "name": "cancel_reservation",
             "arguments": {"reservation_id": "R1"}},
            {"action_id": "c", "name": "send_certificate",
             "arguments": {"user_id": "u1", "amount": 100}},
        ]
    )
    assert "airline.certificate_without_change" not in rules


def test_changing_a_basic_economy_cabin_is_allowed_but_changing_its_flights_is_not():
    """The policy permits one and forbids the other through the same tool."""
    cabin_only = _airline(
        [
            {
                "action_id": "a",
                "name": "update_reservation_flights",
                "arguments": {
                    "reservation_id": "R2",
                    "cabin": "economy",
                    "flights": [{"flight_number": "HAT2", "date": "2024-05-01"}],
                },
            }
        ]
    )
    assert "airline.basic_economy_modify" not in cabin_only

    new_segments = _airline(
        [
            {
                "action_id": "a",
                "name": "update_reservation_flights",
                "arguments": {
                    "reservation_id": "R2",
                    "cabin": "basic_economy",
                    "flights": [{"flight_number": "HAT9", "date": "2024-05-30"}],
                },
            }
        ]
    )
    assert "airline.basic_economy_modify" in new_segments


def test_adding_insurance_and_removing_bags_after_booking():
    rules = _airline(
        [
            {
                "action_id": "a",
                "name": "update_reservation_baggages",
                "arguments": {
                    "reservation_id": "R1",
                    "total_baggages": 1,
                    "add_insurance": "yes",
                },
            }
        ]
    )
    assert "airline.add_insurance" in rules
    assert "airline.remove_baggage" in rules


def test_changing_the_number_of_passengers():
    rules = _airline(
        [
            {
                "action_id": "a",
                "name": "update_reservation_passengers",
                "arguments": {"reservation_id": "R1", "passengers": [{"first_name": "A"}]},
            }
        ]
    )
    assert "airline.passenger_count" in rules


def test_cancelling_a_flight_that_has_already_departed():
    rules = _airline(
        [
            {"action_id": "a", "name": "cancel_reservation",
             "arguments": {"reservation_id": "R2"}},
        ]
    )
    assert "airline.cancel_flown" in rules
    assert "airline.cancel_ineligible" in rules


def test_a_reservation_with_insurance_may_be_cancelled():
    db = {**AIRLINE_DB, "reservations": dict(AIRLINE_DB["reservations"])}
    db["reservations"]["R1"] = {**AIRLINE_DB["reservations"]["R1"], "insurance": "yes"}
    rules = [
        v.rule
        for v in tau2_policy.violations(
            "airline",
            {},
            [{"action_id": "a", "name": "cancel_reservation",
              "arguments": {"reservation_id": "R1"}}],
            db,
        )
    ]
    assert "airline.cancel_ineligible" not in rules
