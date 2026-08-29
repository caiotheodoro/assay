# cloud/ — one spot g5.xlarge, one training run

The Challenger is trained with GRPO against the exploit-gap reward
(`assay.train.reward`). What makes the job unusual is that **the reward runs
the environment**: every rollout is replayed in a real workspace — a Docker
container for the Harbor fixtures — and scored twice, by the environment's own
verifier and by an independent one the attacker cannot reach. So the instance
needs a GPU *and* a Docker daemon, and wall clock is dominated by the
environment rather than by the model.

## Files

- `aws_spot_train.sh` — launcher. Deep Learning OSS AMI, spot `g5.xlarge`
  (1× A10G 24GB), SSM-only with **no inbound ports and no key pair**. Creates
  the IAM role, instance profile, security group and S3 bucket on first use.
- `bootstrap.sh` — EC2 user-data. `@@VARS@@` are substituted by the launcher;
  the placeholder syntax is deliberately not shell syntax so nothing is
  ambiguous about whether it expands on the laptop or on the instance.

## Run it

```sh
DRY=1 ./cloud/aws_spot_train.sh          # price and plan, launches nothing
./cloud/aws_spot_train.sh                # launch
STEPS=600 GROUP_SIZE=8 ./cloud/aws_spot_train.sh
```

Tunables via environment: `AWS_REGION`, `AWS_INSTANCE`, `MODEL`, `STEPS`,
`GROUP_SIZE`, `LR`, `ONLY`, `HOLDOUT`, `MAX_PRICE`, `DISK_GB`, `BUCKET`.

Source ships as a tarball through the run's own S3 bucket. Cloning a git remote
is supported (`REPO_URL=...`) but not required: this repo may not have one, and
pushing it somewhere public just to launch a training job is a publication
decision, not a deployment detail.

## What the instance does, in order

1. `nvidia-smi`, then start Docker and **fail hard** if there is no daemon. A
   run that silently trained on the toy fixtures alone is a different
   experiment from the one the write-up would claim.
2. `pytest tests/test_grpo_reward.py` — the reward is proved **before the GPU
   is used for anything**. If the exploit gap is wrong, no amount of training
   makes the adapter mean anything, and learning that at step 300 costs a
   GPU-hour to learn nothing.
3. `scripts/reward_landscape.py` — what the reward can pay, per environment,
   with no model involved. This is what makes a later "it did not converge"
   claim checkable: a corpus that was flat here was never going to teach, which
   is a different finding from an optimiser that failed.
4. `--smoke` on the real model and the real GPU: two steps, save, reload.
5. The real run.
6. `scripts/challenger_ablation.py` against **`harbor/self-graded`**, which is
   held out of training. Training on it and then reporting that the trained
   Challenger cracks it would be train-on-test.

## Spot, honestly

Spot instances are reclaimed with about two minutes' warning and no resume. A
watcher polls the interruption endpoint and flushes `checkpoints/` and the log
to S3 when the notice arrives, and every stage flushes as it finishes.

`run.json` is written **only on a clean finish**. That is how you tell a short
run from a killed one — the reward log alone cannot say which, and a truncated
run reported as a completed one is a fabricated result.

## Cost

At the time of writing, `g5.xlarge` spot in `us-east-1` was **$0.46/hr**. A
300-step run at group size 8 is roughly one hour including model download and
setup, so about **$0.50**. `DRY=1` prints the live price before committing.

## Not required for anything else

The trained adapter is an **optional artifact**. `uv run --extra adapters
pytest` and `scripts/full_run.py` need none of this, the scripted Challenger is
the floor and needs no model at all, and the reproduction guide never asks for
a GPU.
