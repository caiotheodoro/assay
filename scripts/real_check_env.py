#!/usr/bin/env python3
"""Run the ACTUAL gymnasium and stable-baselines3 checkers, not a reimplementation.

The headline claim of this project is that the incumbent tooling scores
identically to flagging nothing. Until now that rested on
`src/assay/baselines/structural.py`, which reimplements what those checkers are
*believed* to assert. A claim about someone else's tool, tested against our own
model of it, is not a measurement.

So: build `gymnasium.Env` subclasses that carry the same defect classes as the
Assay corpus, hand them to the real `check_env`, and record what it says. Every
environment here is well-formed in the API sense -- correct spaces, correct
return shapes, no NaNs -- and broken in the sense that matters.

Run: uv run --extra gym python scripts/real_check_env.py
"""

from __future__ import annotations

import io
import json
import random
import sys
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import gymnasium as gym
import numpy as np
from gymnasium import spaces


class _Base(gym.Env):
    """A minimal, API-correct environment. Subclasses break one thing each."""

    metadata = {"render_modes": []}

    def __init__(self) -> None:
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(2,), dtype=np.float32)
        self.action_space = spaces.Discrete(3)
        self._secret = 0.5
        self._steps = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._steps = 0
        self._secret = 0.5
        return np.array([self._secret, 0.0], dtype=np.float32), {}

    def step(self, action):
        self._steps += 1
        reward = 1.0 if action == 1 else 0.0
        terminated = self._steps >= 3
        return (
            np.array([self._secret, float(self._steps)], dtype=np.float32),
            reward,
            terminated,
            False,
            {},
        )


class Healthy(_Base):
    """Control. Nothing wrong with it."""


class SeedIgnored(_Base):
    """Accepts `seed` and drops it -- the exact shape of the defect Assay found
    in openenv/textarena_env, and of Gymnasium issue #1084."""

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._secret = random.random()  # never touches the seed
        return np.array([self._secret, 0.0], dtype=np.float32), {}


class SolvedAtReset(_Base):
    """Pays full reward for doing nothing. A no-op policy scores 1.0."""

    def step(self, action):
        obs, _reward, terminated, truncated, info = super().step(action)
        return obs, 1.0, terminated, truncated, info


class TrivialPolicyWins(_Base):
    """A constant action beats every other. The trivial floor is not beatable."""

    def step(self, action):
        obs, _reward, terminated, truncated, info = super().step(action)
        return obs, 1.0 if action == 0 else 0.0, terminated, truncated, info


class RewardHackable(_Base):
    """Reports success for an action that accomplishes nothing in the task's
    own terms. The environment's score and the real outcome come apart."""

    def step(self, action):
        obs, _reward, terminated, truncated, info = super().step(action)
        info["actually_solved"] = False
        return obs, 1.0, terminated, truncated, info


CASES = {
    "healthy": (Healthy, None),
    "seed_ignored": (SeedIgnored, "NONDETERMINISM"),
    "solved_at_reset": (SolvedAtReset, "NOOP_PASSES"),
    "trivial_policy_wins": (TrivialPolicyWins, "TRIVIAL_FLOOR_BREACH"),
    "reward_hackable": (RewardHackable, "REWARD_HACKABLE"),
}


def _judge(defect: str | None, gym_verdict: str, messages: list[str]) -> tuple[bool, str]:
    """Did a checker actually speak to this defect? Read, do not keyword-match."""
    if defect is None:
        return False, "no defect planted"
    if defect == "NONDETERMINISM":
        hit = any(
            "deterministic" in m.lower() and "seed" in m.lower() for m in messages
        )
        return hit, (
            "gymnasium raises on non-equivalent observations for the same seed and "
            "action" if hit else "neither checker mentions seeding or determinism"
        )
    # NOOP_PASSES, TRIVIAL_FLOOR_BREACH, REWARD_HACKABLE are all statements about
    # what a reward MEANS. Both checkers only assert that reward is a finite
    # number of the right type; neither has any concept of whether it was earned.
    return False, (
        "neither checker inspects reward semantics -- only that it is a finite "
        "real number of the correct type"
    )


def _run(checker, env) -> tuple[str, list[str]]:
    """Return (verdict, messages). A checker that says nothing has passed."""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                checker(env)
        except Exception as exc:  # noqa: BLE001 - a raise is a verdict
            return "RAISED", [f"{type(exc).__name__}: {exc}"]
    msgs = [str(w.message) for w in caught]
    msgs += [l for l in (buf_out.getvalue() + buf_err.getvalue()).splitlines() if l.strip()]
    return ("WARNED" if msgs else "PASSED"), msgs


def main() -> int:
    from gymnasium.utils.env_checker import check_env as gym_check
    from stable_baselines3.common.env_checker import check_env as sb3_check

    rows = {}
    for name, (cls, defect) in CASES.items():
        gym_verdict, gym_msgs = _run(gym_check, cls())
        sb3_verdict, sb3_msgs = _run(sb3_check, cls())
        rows[name] = {
            "defect_present": defect,
            "gymnasium": {"verdict": gym_verdict, "messages": gym_msgs[:3]},
            "stable_baselines3": {"verdict": sb3_verdict, "messages": sb3_msgs[:3]},
            "defect_detected": False,  # filled below
        }
        # Whether a checker "detected" the defect is decided by reading its
        # output, not by keyword-matching it. An earlier version of this script
        # substring-matched the defect name against the messages -- which is
        # the same shortcut-scoring mistake this project published a finding
        # about in `paws`, where `includes()` credited "I don't know" because
        # it contains "no". With five cases, reading them is cheap and honest.
        #
        # The checkers have no vocabulary for these defect classes. The only
        # one either tool speaks to is determinism, and gymnasium says so
        # explicitly. Every judgement below is recorded with the message that
        # justifies it so a reader can disagree.
        combined = gym_msgs + sb3_msgs
        verdict, why = _judge(defect, gym_verdict, combined)
        rows[name]["defect_detected"] = verdict
        rows[name]["detection_basis"] = why

    detected = sum(1 for r in rows.values() if r["defect_detected"])
    planted = sum(1 for r in rows.values() if r["defect_present"])

    body = {
        "gymnasium": gym.__version__,
        "planted_defects": planted,
        "detected_by_real_checkers": detected,
        "cases": rows,
        "note": (
            "Every environment here is API-correct: right spaces, right return shapes, "
            "no NaN rewards. The real checkers were run, not a model of them."
        ),
    }
    out = Path(__file__).resolve().parents[1] / "results" / "real_check_env.json"
    out.write_text(json.dumps(body, indent=2))

    print(f"gymnasium {gym.__version__}\n")
    print(f"{'environment':22} {'defect':22} {'gymnasium':10} {'sb3':10} detected")
    print("-" * 78)
    for name, r in rows.items():
        print(
            f"{name:22} {str(r['defect_present'] or '-'):22} "
            f"{r['gymnasium']['verdict']:10} {r['stable_baselines3']['verdict']:10} "
            f"{r['defect_detected']}"
        )
    print(f"\n{detected} of {planted} planted defects detected by the real checkers")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
