# Draft — `huggingface/OpenEnv`

**Status: DRAFT. Not filed. Do not post without approval.**

- **Repo:** https://github.com/huggingface/OpenEnv
- **Kind:** issue (bug)
- **Verified against:** `main` (re-checked at `envs/textarena_env/server/environment.py`), pinned locally at `e059726`
- **Suggested title:** `textarena_env`: `reset()` accepts a `seed` and discards it, so runs are not reproducible

---

`TextArenaEnvironment.reset()` takes a `seed` parameter and never passes it on.
It calls the underlying TextArena env's `reset(num_players=...)` without the
seed, so the seed has no effect.

Six consecutive calls to `reset(seed=1234)` return six different secret Wordle
words:

```
earth, north, south, bread, tight, stage
```

A caller reading the signature reasonably concludes the episode is
reproducible. It is not, and nothing reports that — which is the part I think
matters most: a silently ignored seed is worse than an unsupported one, because
the caller has no way to find out except by testing for it.

### This is a one-word omission, not an upstream limitation

Upstream TextArena's own `reset` **does** accept a seed:

```python
def reset(self, num_players: int, seed: Optional[int] = None)
```

So the parameter exists on the object being wrapped, and the wrapper simply
does not forward it.

### Why I'm filing rather than assuming it's known

I searched the issue tracker and found nothing reporting this. The nearest is
**#183**, an open feature request about passing parameters through to `reset` —
which is the only reading under which someone might consider this already
tracked. I'd argue it is a distinct problem: #183 asks for a capability that
does not exist, whereas here the signature already advertises the capability
and drops it.

For comparison, `gymnasium`'s `check_env` raises on exactly this shape
(`Deterministic step observations are not equivalent for the same seed and
action`) as of 1.3.0. I mention it only because it suggests the failure mode is
considered worth catching in a neighbouring ecosystem, not as a criticism of
OpenEnv's scope.

### Suggested fix

Forward the seed:

```python
self._ta_env.reset(num_players=..., seed=seed)
```

If forwarding is not always correct for every wrapped TextArena game, then
raising on a non-`None` seed would still be better than silently ignoring it.
Happy to open a PR either way.

### Reproduction

Pinned as a test in <REPO_URL> (`tests/test_openenv_ground_truth.py`), which
asserts against TextArena's own game state rather than through any tooling of
mine.
