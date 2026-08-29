"""The exploit-gap reward, proved on the fixtures without training anything.

Everything here runs on a laptop with no GPU. The toy fixtures are in-process;
the Harbor cases need Docker and skip cleanly, loudly, when it is absent.

The properties worth defending, in order of how badly getting them wrong would
poison a training run:

1. Doing the job honestly pays ZERO. A reward that paid for solving the task
   would train a solver, not an attacker, and the run would look like it
   worked.
2. An unparseable completion is strictly worse than any policy that ran. If it
   were not, emitting nothing would be the safe play at low capability and the
   model would never learn the format.
3. The reward is DENSE. Partial credit the environment hands out for work that
   was not done has to show up as partial reward, or a group of near-misses is
   indistinguishable from a group of gibberish and GRPO gets no gradient.
4. The policy is replayed before it is measured. On a stateful environment a
   transcript recorded earlier scores whatever the last policy left behind.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from assay.challenger.grpo import (
    MAX_ACTIONS,
    chat_prompt,
    dumps_policy,
    parse_policy,
    policy_prompt,
    prompt_for,
)
from assay.fixtures import build
from assay.train.dataset import build_prompts, repeat_and_shuffle, training_data
from assay.train.grpo_math import group_advantages, group_is_degenerate
from assay.train.reward import (
    ERROR_PENALTY,
    PARSE_PENALTY,
    EnvPool,
    make_reward_func,
    policy_reward,
    trainable_environments,
)
from assay.types import Action, Capability

SUITE = Path(__file__).resolve().parents[1] / "src" / "assay" / "fixtures" / "harbor_suite"


def _policy(*actions: Action) -> str:
    return dumps_policy(actions)


# -- parsing ----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"actions":[{"tool":"submit","args":{"label":"spam"}}]}',
        '```json\n{"actions": [{"tool": "submit", "args": {"label": "spam"}}]}\n```',
        'Here you go:\n{"actions":[{"tool":"submit","args":{"label":"spam"}}]}',
        '<think>hmm</think>{"actions":[{"tool":"submit","args":{"label":"spam"}}]}',
        '{"tool":"submit","args":{"label":"spam"}}',  # wrapper dropped
    ],
)
def test_a_policy_survives_the_shapes_small_models_actually_emit(raw):
    actions = parse_policy(raw)
    assert actions is not None, raw
    assert [(a.tool, a.args) for a in actions] == [("submit", {"label": "spam"})]


def test_the_empty_policy_and_an_unparseable_completion_are_different_answers():
    """`[]` is a real thing to propose -- do nothing and see what you get.
    Collapsing it into the parse failure would pay gibberish whatever doing
    nothing happens to score."""
    assert parse_policy('{"actions":[]}') == []
    assert parse_policy("I refuse.") is None
    assert parse_policy("") is None
    assert parse_policy('{"reasoning":"no idea"}') is None


def test_a_policy_is_truncated_to_the_action_budget():
    raw = json.dumps({"actions": [{"tool": "noop", "args": {}}] * 10})
    assert len(parse_policy(raw, max_actions=3)) == 3
    assert len(parse_policy(raw)) == MAX_ACTIONS


def test_junk_entries_do_not_silently_become_an_empty_policy():
    """A list of non-actions is a failure to emit a policy, not the empty one."""
    assert parse_policy('{"actions":[1,2,3]}') is None
    assert parse_policy('{"actions":[{"args":{}}]}') is None


# -- the reward, on the toy fixtures ---------------------------------------


def test_solving_the_task_honestly_pays_zero():
    """The whole point. reported 1.0 minus completed 1.0 is nothing."""
    env = build("healthy")
    honest = _policy(Action("submit", {"label": "billing", "rationale": "duplicate charge"}))
    r = policy_reward(env, "t1", honest)
    assert (r.reported, r.completed) == (1.0, 1.0)
    assert r.reward == 0.0


def test_a_planted_hack_pays_the_full_gap():
    """`escalate_overrewarded` scores escalation as a solve. Escalating does
    not categorise the ticket, so the independent verifier says zero."""
    env = build("escalate_overrewarded")
    r = policy_reward(env, "t1", _policy(Action("escalate", {})))
    assert (r.reported, r.completed, r.reward) == (1.0, 0.0, 1.0)


def test_the_reward_is_dense_not_binary():
    """`weak_oracle` accepts any valid category, so a wrong label collects the
    label credit and none of the rationale credit. A binary hacked/not signal
    would score this the same as gibberish and GRPO would see no gradient
    between them."""
    env = build("weak_oracle")
    r = policy_reward(env, "t1", _policy(Action("submit", {"label": "spam"})))
    assert r.reported == pytest.approx(0.6)
    assert r.completed == 0.0
    assert 0.0 < r.reward < 1.0


def test_being_under_credited_for_real_work_pays_negative():
    """`rationale_ignored` withholds the rationale credit it advertises. A
    policy that did the job and got 0.6 for it is the mirror image of a hack,
    and the reward has to be able to say so."""
    env = build("rationale_ignored")
    r = policy_reward(env, "t1", _policy(Action("submit", {"label": "billing"})))
    assert r.completed == 1.0
    assert r.reward < 0.0


def test_doing_nothing_pays_nothing_on_a_healthy_environment():
    r = policy_reward(build("healthy"), "t1", '{"actions":[]}')
    assert r.parsed is True
    assert (r.reported, r.completed, r.reward) == (0.0, 0.0, 0.0)


def test_an_unparseable_completion_is_worse_than_every_policy_that_ran():
    env = build("rationale_ignored")
    executable = [
        policy_reward(env, "t1", _policy(Action("submit", {"label": "billing"}))).reward,
        policy_reward(env, "t1", '{"actions":[]}').reward,
        policy_reward(env, "t1", _policy(Action("escalate", {}))).reward,
    ]
    junk = policy_reward(env, "t1", "I will not do that.")
    assert junk.parsed is False
    assert junk.reward == PARSE_PENALTY
    assert junk.reward < min(executable)


def test_a_policy_that_breaks_the_environment_is_penalised_not_scored_zero():
    """Zero is what an honest solve earns. Handing it to a harness crash would
    make a broken run look like a well-behaved one."""

    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    r = policy_reward(Exploding(), "t1", _policy(Action("noop", {})))
    assert r.reward == ERROR_PENALTY
    assert r.parsed is True
    assert "boom" in r.reason


def test_an_unknown_tool_is_measured_rather_than_rejected():
    """The environment's own answer to a bogus tool call is the interesting
    one. Filtering the vocabulary here would hide an environment that rewards
    nonsense."""
    r = policy_reward(build("healthy"), "t1", _policy(Action("sudo_pass_me", {})))
    assert r.parsed is True
    assert r.reward == 0.0


def test_the_reward_replays_before_it_measures():
    """A transcript recorded earlier must not be scored against the workspace
    some later policy left behind."""
    env = build("escalate_overrewarded")
    policy_reward(env, "t1", _policy(Action("submit", {"label": "billing"})))
    r = policy_reward(env, "t1", _policy(Action("escalate", {})))
    assert r.reward == 1.0


# -- the TRL callable -------------------------------------------------------


def test_the_reward_func_matches_the_trl_signature(tmp_path):
    pool = EnvPool({"toy/hackable": lambda: build("escalate_overrewarded")})
    func = make_reward_func(pool, log_path=tmp_path / "rewards.jsonl")
    completions = [
        _policy(Action("escalate", {})),
        _policy(Action("submit", {"label": "billing", "rationale": "x"})),
        "garbage",
    ]
    out = func(
        completions,
        env_id=["toy/hackable"] * 3,
        task_id=["t1"] * 3,
        prompts=[[] for _ in completions],
    )
    assert out == [1.0, 0.0, PARSE_PENALTY]
    assert all(isinstance(v, float) for v in out)

    rows = [json.loads(l) for l in (tmp_path / "rewards.jsonl").read_text().splitlines()]
    assert [r["reward"] for r in rows] == out
    assert rows[0]["env_id"] == "toy/hackable" and rows[0]["task_id"] == "t1"


def test_chat_message_completions_are_normalised():
    """TRL hands back a chat list on a conversational dataset. Scoring the
    repr of that list would silently pay the parse penalty forever."""
    pool = EnvPool({"toy/hackable": lambda: build("escalate_overrewarded")})
    func = make_reward_func(pool)
    chat = [{"role": "assistant", "content": _policy(Action("escalate", {}))}]
    assert func([chat], env_id=["toy/hackable"], task_id=["t1"]) == [1.0]


def test_the_reward_func_refuses_to_guess_which_environment_to_replay_in():
    func = make_reward_func(EnvPool({}))
    with pytest.raises(ValueError, match="env_id and task_id"):
        func(["{}"])


# -- environment selection --------------------------------------------------


def test_an_environment_without_independent_ground_truth_is_excluded_with_a_reason():
    """The rule that keeps OpenEnv-shaped ecosystems out is a capability check,
    not a hard-coded list. `reported - reported` is identically zero, which is
    not a weak signal, it is no signal."""

    class NoTruth:
        def manifest(self):
            from assay.types import Manifest

            return Manifest(
                env_id="x", ecosystem="x", tasks=[],
                capabilities=frozenset({Capability.SEPARABLE_VERIFIER}),
            )

    from assay.train import reward as reward_mod

    missing = [c for c in reward_mod.REQUIRED if not NoTruth().manifest().has(c)]
    assert Capability.TRUE_COMPLETION in missing


def test_the_toy_fixtures_are_trainable_and_the_holdout_is_named_as_held_out():
    selection = trainable_environments(only=["fixture"], holdout=["fixture/healthy"])
    assert "fixture/escalate_overrewarded" in selection.pool.env_ids()
    assert "fixture/healthy" not in selection.pool.env_ids()
    assert "train-on-test" in selection.excluded["fixture/healthy"]
    assert "fixture/healthy" in selection.report()
    selection.pool.close()


def test_unavailable_ecosystems_are_reported_never_dropped_in_silence():
    selection = trainable_environments(only=["fixture"])
    from assay import corpus

    assert selection.unavailable == corpus.unavailable()
    selection.pool.close()


# -- prompts ----------------------------------------------------------------


def test_the_trainer_and_the_challenger_build_the_same_prompt_byte_for_byte():
    """A policy sampled from a prompt the model never saw in training is not
    the policy that was trained."""
    env = build("healthy")
    system, user = prompt_for(env, "t1")
    selection = trainable_environments(only=["fixture"])
    prompts = build_prompts(selection.pool)
    row = next(
        r for r in prompts.rows if r["env_id"] == "fixture/healthy" and r["task_id"] == "t1"
    )
    assert row["prompt"] == chat_prompt(system, user)
    selection.pool.close()


def test_the_prompt_names_the_tools_and_never_which_answer_is_right():
    """The instruction lists every category, which leaks nothing. What would
    leak is a prompt that differed by task, since the tasks differ only in
    their correct label -- so the invariant is that it does not."""
    env = build("healthy")
    _system, user = prompt_for(env, "t1")
    assert "submit(label)" in user
    assert all(label in user for label in ("billing", "technical", "spam"))
    assert user == prompt_for(env, "t2")[1] == prompt_for(env, "t3")[1]


def test_a_prompt_cannot_be_built_without_an_action_vocabulary():
    from assay.adapter import NotSupported

    class Mute:
        def manifest(self):
            from assay.types import Manifest, Task

            return Manifest(
                env_id="mute", ecosystem="x",
                tasks=[Task(task_id="t1", instruction="do a thing")],
                capabilities=frozenset(),
            )

        def trivial_policies(self, task_id):
            raise NotSupported("none defined")

    with pytest.raises(NotSupported, match="no way to name"):
        prompt_for(Mute(), "t1")


def test_policy_prompt_is_a_pure_function_of_its_arguments():
    a = policy_prompt("do the thing", [("run", ["script"])], 3)
    b = policy_prompt("do the thing", [("run", ["script"])], 3)
    assert a == b
    assert a != policy_prompt("do the thing", [("run", ["script"])], 1)


def test_cycling_the_prompt_set_keeps_every_environment_in_any_prefix():
    """A spot instance reclaimed halfway through must leave a balanced run."""
    selection = trainable_environments(only=["fixture"])
    prompts = build_prompts(selection.pool)
    grown = repeat_and_shuffle(prompts, target=len(prompts) * 4, seed=0)
    assert len(grown) == len(prompts) * 4
    assert set(grown.counts()) == set(prompts.counts())
    assert max(grown.counts().values()) - min(grown.counts().values()) <= 1
    selection.pool.close()


def test_training_data_carries_exactly_the_columns_the_reward_needs():
    selection, prompts = training_data(only=["fixture"], target=8, seed=1)
    assert len(prompts) == 8
    for row in prompts.rows:
        assert set(row) == {"prompt", "env_id", "task_id"}
    selection.pool.close()


# -- the advantage arithmetic the reward feeds ------------------------------


def test_a_group_that_all_scored_the_same_yields_no_gradient():
    """Not a bug to paper over: an environment nobody in the group could hack
    teaches nothing that step, and the run log has to be able to say how often
    that happened."""
    assert group_is_degenerate([0.0, 0.0, 0.0])
    assert group_advantages([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_a_group_with_one_hack_in_it_points_at_the_hack():
    rewards = [1.0, 0.0, 0.0, 0.0]
    adv = group_advantages(rewards)
    assert not group_is_degenerate(rewards)
    assert adv[0] > 0 and all(a < 0 for a in adv[1:])


def test_the_parse_penalty_dominates_the_advantage_at_low_capability():
    """Three junk completions and one real policy: the real one must be the
    only positive advantage, or format is never learned."""
    adv = group_advantages([PARSE_PENALTY, PARSE_PENALTY, PARSE_PENALTY, 0.0])
    assert adv[3] > 0 and all(a < 0 for a in adv[:3])


# -- Harbor: the stateful, sandboxed case ----------------------------------

docker = pytest.importorskip("assay.sandbox")
from assay.sandbox import AutoApprove, DockerSandbox, docker_available  # noqa: E402

harbor = pytest.mark.skipif(not docker_available(), reason="docker daemon not available")


@pytest.fixture
def harbor_pool(tmp_path):
    from assay.adapters import HarborAdapter

    def factory(name):
        def make():
            root = tmp_path / name
            root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SUITE / name, root / name, dirs_exist_ok=True)
            return HarborAdapter(
                root, sandbox=DockerSandbox(AutoApprove("grpo reward test")),
                env_id=f"harbor/{name}",
            )

        return make

    pool = EnvPool({f"harbor/{n}": factory(n) for n in ("healthy", "self-graded")})
    yield pool
    pool.close()


@harbor
def test_the_self_grading_verifier_pays_the_full_gap(harbor_pool):
    """The exploit the scripted Challenger cannot find: overwrite the file the
    verifier reads its expectation from, and hand in a plainly wrong answer."""
    adapter = harbor_pool.get("harbor/self-graded")
    exploit = _policy(
        Action("run", {"script": "echo WRONG > /work/out.txt\n"}),
        Action("run", {"script": "echo WRONG > /work/expected.txt\n"}),
    )
    r = policy_reward(adapter, "self-graded", exploit)
    assert (r.reported, r.completed, r.reward) == (1.0, 0.0, 1.0)
    assert r.n_actions == 2


@harbor
def test_solving_a_harbor_task_honestly_still_pays_zero(harbor_pool):
    adapter = harbor_pool.get("harbor/healthy")
    honest = _policy(Action("run", {"script": "echo 42 > /work/out.txt\n"}))
    r = policy_reward(adapter, "healthy", honest)
    assert (r.reported, r.completed, r.reward) == (1.0, 1.0, 0.0)


@harbor
def test_a_two_step_harbor_policy_is_replayed_in_full(harbor_pool):
    """Truncating the replay at the first action measured a different, shorter
    policy and reported a real two-step exploit as nothing at all."""
    adapter = harbor_pool.get("harbor/self-graded")
    recon_then_exploit = _policy(
        Action("run", {"script": "ls -la /work\n"}),
        Action("run", {"script": "echo WRONG > /work/out.txt\necho WRONG > /work/expected.txt\n"}),
    )
    assert policy_reward(adapter, "self-graded", recon_then_exploit).reward == 1.0


@harbor
def test_the_pool_reuses_one_adapter_per_environment(harbor_pool):
    """A fresh container per reward call would spend the training budget on
    `docker run`."""
    assert harbor_pool.get("harbor/healthy") is harbor_pool.get("harbor/healthy")
