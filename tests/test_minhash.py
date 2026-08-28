"""Exact hashing cannot see a one-character edit. That is the whole reason
MinHash is in the contamination probe, so it gets its own fixture."""

from __future__ import annotations

from assay.minhash import estimated_jaccard, exact_signature, signature

#: Long enough that a single edited word breaks 5 of ~66 shingles rather than
#: 5 of ~19. With 5-word shingles, "near duplicate" is only a meaningful claim
#: about text substantially longer than the shingle.
LONG = (
    "the quarterly reconciliation report must tie every schedule of values line "
    "to the corresponding invoice and lien waiver before any payment is certified "
    "by the project architect, and the retainage held back on each line has to "
    "match the percentage stated in the executed contract rather than the "
    "percentage used in the previous application, because a change order signed "
    "mid quarter can alter the scheduled value of a line without altering the "
    "retainage terms that apply to it for the remainder of the project"
)


def test_one_character_edit_defeats_exact_hashing():
    edited = LONG.replace("quarterly", "quarterly ")
    assert exact_signature(LONG) == exact_signature(edited), "normalisation should absorb spacing"
    edited_word = LONG.replace("quarterly", "quarterl")
    assert exact_signature(LONG) != exact_signature(edited_word)


def test_minhash_catches_the_near_duplicate_exact_hashing_misses():
    edited = LONG.replace("quarterly", "quarterlyy")
    assert exact_signature(LONG) != exact_signature(edited)
    j = estimated_jaccard(signature(LONG), signature(edited))
    assert j >= 0.8, f"near-dup not caught, jaccard={j}"


def test_unrelated_text_is_not_a_near_duplicate():
    other = "a customer reported that the export button returns a server error"
    j = estimated_jaccard(signature(LONG), signature(other))
    assert j < 0.8


def test_signatures_are_stable_across_calls():
    assert signature(LONG) == signature(LONG)
