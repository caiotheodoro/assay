# Review finding — ReDoS in the submitted-spec adapter

**Status:** OPEN — and now a MERGE BLOCKER. Found by review, not by a test.
**File:** `src/assay/adapters/spec.py` (branch `worker/hf`), `_matches`, `kind == "regex"`.

## What

`spec.py` exists so a stranger can submit an environment to a public Space as
*data* rather than as code — a good decision, and the module is otherwise clean:
no `eval`, `exec`, `__import__`, `subprocess` or `pickle`, and hard caps on
tasks (200), items (2000) and text length (20000).

But the `regex` matcher runs a submitter-controlled pattern:

```python
return re.search(target, answer) is not None
```

Python's `re` backtracks. A short pattern well inside every declared cap hangs
the process:

```
pattern "(a+)+$" against 31 characters -> 100.7 seconds
```

The surrounding `except re.error` catches patterns that fail to *compile*. A
pattern that compiles fine and runs forever is not an error, so it passes
straight through.

For a public endpoint this is a denial of service with a payload of a dozen
bytes.

## Why the matcher cannot simply be dropped

`regex` is not decorative. `inspect_evals`' `boolq` scores with
`pattern(r"(Yes|No).?\Z")`, and the narrower-leak finding in
`docs/changelog/30-wild-sweep.md` depends on being able to express exactly that.
A spec format that cannot represent a regex verifier cannot represent the evals
this project audits.

## Options

1. **Subprocess with a wall-clock cap.** Consistent with how untrusted
   environment code is already handled in `sandbox.py`, which caps cpu, memory,
   pids and wall clock. Costs a process per match.
2. **A linear-time engine** (`google-re2`). No catastrophic backtracking by
   construction, and a new dependency for one matcher.
3. **Drop `regex`.** Cheapest, and it removes the ability to describe a real
   class of eval — including one this project has already published a finding
   about.

Preference is (1): it reuses a boundary the project already trusts, and it needs
no new dependency. Whatever is chosen, a test must exhibit the hang and assert
it is bounded — a fix asserted rather than demonstrated is how this got here.


## Update — the exposed path is now complete

`worker/hf` has since shipped `space/app.py`, so the route from a stranger's
input to `re.search` exists end to end:

```
$ grep -n 're\.search\|safe_regex\|timeout' src/assay/adapters/spec.py
74:            return re.search(target, answer) is not None      # unguarded

$ grep -nE 'timeout|re\.search|safe_regex|MAX|limit' space/app.py
(no matches)
```

A submitted spec with `verifier.kind: regex` and `target: "(a+)+$"` hangs the
Space. The worker did not know — this was found by review after it had started,
and a dispatched tmux worker has no inbound channel.

**Do not merge `worker/hf` without this fix.** `src/assay/safe_regex.py` is on
`main`, tested, and needs two things at merge:

1. `spec.py` calls `safe_regex.search(target, answer)` instead of `re.search`.
2. `PatternTooSlow` becomes a reported outcome, not a crash. A verifier that
   cannot decide inside its budget is itself worth surfacing on the card —
   `NOT_APPLICABLE` with the pattern and the budget in the reason. Letting it
   raise into the Space would trade a hang for a stack trace.
