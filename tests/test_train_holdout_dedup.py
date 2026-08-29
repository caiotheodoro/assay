"""The GRPO holdout was not held out at the prompt level.

`harbor/self-graded` was excluded from training "so the ablation is not
train-on-test". That excluded the environment -- its verifier, and therefore
the reward. It did not exclude the prompt: every Harbor task in the corpus
presents the model with the same instruction and the same one-tool vocabulary,
so the prompt string is byte-identical across all five.

These tests pin the finding rather than the fix. It cannot quietly close in the
write-up, and if someone later differentiates the Harbor instructions the second
test fails and says so out loud.
"""

from __future__ import annotations

import pytest

from assay.challenger.grpo import prompt_for
from assay.minhash import estimated_jaccard, exact_signature, signature
from assay.sandbox import docker_available
from assay.train.reward import trainable_environments

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="docker daemon not available"
)

#: As trained, per results/assay-challenger-r{1,2}/run.json. `harbor/shared-tests`
#: did not exist yet and is deliberately not in this list.
TRAINED_HARBOR = ["harbor/broken-gold", "harbor/healthy", "harbor/vacuous-tests"]
HOLDOUT = "harbor/self-graded"


@pytest.fixture(scope="module")
def harbor_prompts():
    selection = trainable_environments(only=["harbor"])
    try:
        out = {}
        for env_id in selection.pool.env_ids():
            adapter = selection.pool.get(env_id)
            task = adapter.manifest().tasks[0]
            out[env_id] = prompt_for(adapter, task.task_id)[1]
        yield out
    finally:
        selection.pool.close()


def test_the_holdout_prompt_is_byte_identical_to_trained_prompts(harbor_prompts):
    """Exact SHA-256 overlap between train and holdout is 1, where
    hf-publication-specs.md 11.4 expects 0. MinHash is not even needed to see
    it -- which is the sharper half of the finding: the check had never been
    run, so a collision plain hashing would have caught went unnoticed."""
    held = harbor_prompts[HOLDOUT]
    colliding = [
        env for env in TRAINED_HARBOR if harbor_prompts[env] == held
    ]
    assert colliding == TRAINED_HARBOR, (
        "the holdout prompt no longer collides with every trained Harbor prompt; "
        "if the instructions were deliberately differentiated, update "
        "results/train_holdout_dedup.json and docs/changelog/62-rigour.md"
    )
    assert all(
        exact_signature(harbor_prompts[env]) == exact_signature(held)
        for env in colliding
    )


def test_minhash_agrees_with_exact_hashing_on_the_collision(harbor_prompts):
    """The audit reports both, so they have to be consistent on the easy case."""
    held = signature(harbor_prompts[HOLDOUT])
    for env in TRAINED_HARBOR:
        assert estimated_jaccard(held, signature(harbor_prompts[env])) == 1.0


def test_fixture_prompts_are_not_near_duplicates_of_the_holdout(harbor_prompts):
    """The in-process fixtures are a different shape of task, so a real
    near-duplicate audit must separate them from the Harbor ones. If everything
    came back at Jaccard 1.0 the audit would be measuring its own preprocessing
    rather than the corpus."""
    selection = trainable_environments(only=["fixture"])
    try:
        held = signature(harbor_prompts[HOLDOUT])
        for env_id in selection.pool.env_ids():
            adapter = selection.pool.get(env_id)
            for task in adapter.manifest().tasks:
                other = signature(prompt_for(adapter, task.task_id)[1])
                assert estimated_jaccard(held, other) < 0.8, env_id
    finally:
        selection.pool.close()
