"""Matching a pattern somebody else wrote, without handing them the process.

Python's `re` backtracks, so a short pattern can take arbitrarily long on a
short input. `(a+)+$` against 31 characters takes about 100 seconds here. That
is fine when the pattern is yours and fatal when it arrives over the network:
the submitted-spec adapter accepts a regex verifier, and a public Space running
it in-process is a denial of service with a dozen-byte payload.

Catching `re.error` does not help. That fires when a pattern fails to compile.
A pattern that compiles cleanly and runs forever is not an error.

So the match runs in a subprocess under a wall clock, which is the same
boundary `sandbox.py` already draws around untrusted environment code — a
timeout is only enforceable where something else can kill the thing that
overran. No new dependency, and about 30ms per call, which is affordable for a
verifier that runs once per item and unaffordable for nothing else here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

DEFAULT_TIMEOUT = 2.0

_CHILD = r"""
import json, re, sys
payload = json.load(sys.stdin)
try:
    hit = re.search(payload["pattern"], payload["text"]) is not None
except re.error as exc:
    print(json.dumps({"error": str(exc)}))
else:
    print(json.dumps({"hit": hit}))
"""


class PatternTooSlow(RuntimeError):
    """The pattern did not finish inside its budget.

    Reported rather than swallowed. A verifier that cannot decide is not a
    verifier that said no, and an environment whose scoring hangs is itself a
    finding worth surfacing.
    """


class PatternInvalid(ValueError):
    """The pattern does not compile."""


def search(pattern: str, text: str, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """True if `pattern` matches `text`. Raises rather than hanging."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD],
            input=json.dumps({"pattern": pattern, "text": text}),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PatternTooSlow(
            f"pattern {pattern[:60]!r} did not finish within {timeout}s against "
            f"{len(text)} characters"
        ) from exc
    if proc.returncode != 0:
        raise PatternTooSlow(f"pattern evaluation failed: {proc.stderr.strip()[:200]}")
    result = json.loads(proc.stdout)
    if "error" in result:
        raise PatternInvalid(result["error"])
    return bool(result["hit"])
