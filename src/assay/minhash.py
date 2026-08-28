"""A small, dependency-free, deterministic MinHash.

Parameters match the contamination spec used across this methodology:
5-word shingles, 128 permutations, Jaccard >= 0.8. Deterministic because the
permutation coefficients are derived from a fixed seed, not from Python's
per-process string hash -- a near-dup audit that changes between runs is not
an audit.
"""

from __future__ import annotations

import hashlib
import random
import re

_MERSENNE = (1 << 61) - 1
_MAX32 = (1 << 32) - 1

_WORD = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def shingles(text: str, size: int = 5) -> set[str]:
    words = normalize(text)
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def _coefficients(num_perm: int, seed: int = 7) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    return [(rng.randint(1, _MERSENNE - 1), rng.randint(0, _MERSENNE - 1)) for _ in range(num_perm)]


def _token_hash(token: str) -> int:
    return int.from_bytes(hashlib.sha1(token.encode("utf-8")).digest()[:4], "big")


def signature(text: str, shingle_size: int = 5, num_perm: int = 128) -> tuple[int, ...]:
    grams = shingles(text, shingle_size)
    if not grams:
        return tuple([_MAX32] * num_perm)
    coeffs = _coefficients(num_perm)
    hashes = [_token_hash(g) for g in grams]
    return tuple(
        min(((a * h + b) % _MERSENNE) & _MAX32 for h in hashes) for a, b in coeffs
    )


def estimated_jaccard(sig_a: tuple[int, ...], sig_b: tuple[int, ...]) -> float:
    if not sig_a or len(sig_a) != len(sig_b):
        raise ValueError("signatures must be same non-zero length")
    return sum(1 for x, y in zip(sig_a, sig_b) if x == y) / len(sig_a)


def exact_signature(text: str) -> str:
    """Content hash for exact-leak detection, normalization-insensitive."""
    return hashlib.sha256(" ".join(normalize(text)).encode("utf-8")).hexdigest()
