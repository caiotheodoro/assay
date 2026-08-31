# Draft — `huggingface/OpenEnv`

**Status: reviewed by a second reader. Ready to file.**

- **Repo:** https://github.com/huggingface/OpenEnv
- **Kind:** issue (bug)
- **Verified against:** `main` (re-checked at `envs/textarena_env/server/environment.py`), pinned locally at `e059726`
- **Suggested title:** `textarena_env`: `reset()` accepts a `seed` and discards it, so runs are not reproducible

---

`TextArenaEnvironment.reset()` takes a `seed` parameter and never passes it on.
It calls the underlying TextArena env's `reset(num_players=...)` without the
seed, so the seed has no effect.

This isn't a stray keyword argument. OpenEnv's own base class declares it --
`openenv.core.env_server.interfaces.Environment.reset` is
`reset(self, seed: Optional[int] = None, episode_id: Optional[str] = None, **kwargs)`
-- so `seed` is part of the interface every environment implements, and
`textarena_env` is the implementation that accepts it and drops it.

Six consecutive calls to `reset(seed=1234)` on `Wordle-v0` return six different
secret words. One run:

```
earth, north, south, bread, tight, stage
```

The words are drawn at random, so that exact list is one run rather than a
fixture -- rerunning gives a different six.

A caller reading the signature reasonably concludes the episode is
reproducible. It is not, and nothing reports that — which is the part I think
matters most: a silently ignored seed is worse than an unsupported one, because
the caller has no way to find out except by testing for it.

### The parameter exists on the object being wrapped

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
self._ta_env.reset(num_players=self.num_players, seed=seed)
```

I checked this actually fixes it rather than just passing the argument along:
with the seed forwarded, six resets at `seed=1234` give the same secret word
every time (`slope`), and the word is stable across freshly constructed
environments. TextArena's own seeding does reach the Wordle word list.

One note for whoever picks this up: `__init__` also calls
`self._ta_env.reset(num_players=self.num_players)` to leave the env in a valid
state before the first `step()`, so there are two call sites rather than one.

If forwarding is not always correct for every wrapped TextArena game, then
raising on a non-`None` seed would still be better than silently ignoring it.
Happy to open a PR either way.

### Reproduction

Pinned as a test in https://github.com/caiotheodoro/assay
(`tests/test_openenv_ground_truth.py`), which reads the secret word off
TextArena's own game state rather than through any tooling of mine. It asserts
that the word varies under a fixed seed, not that all six draws differ -- the
six-distinct run above is illustrative.
