#!/usr/bin/env bash
# EC2 user-data for the spot trainer.
#
# @@VARS@@ are substituted by aws_spot_train.sh before launch. The placeholder
# syntax is deliberately not shell syntax, so nothing in this file is ambiguous
# about whether it expands on the laptop or on the instance.
#
# Fails loudly and early. A bootstrap that half-works produces a run whose
# corpus quietly shrank, and a shrunken corpus reported as a clean one is the
# exact failure this project exists to catch.
set -euxo pipefail
exec > >(tee -a /var/log/assay-train.log) 2>&1

# Quoted, every one of them. ONLY is a space-separated list, and an unquoted
# `ONLY=fixture harbor` in a sourced file runs `harbor` as a command.
cat >/etc/assay.env <<ENV
BUCKET="@@BUCKET@@"
NAME="@@NAME@@"
REPO_URL="@@REPO_URL@@"
BRANCH="@@BRANCH@@"
MODEL="@@MODEL@@"
STEPS="@@STEPS@@"
GROUP_SIZE="@@GROUP_SIZE@@"
LR="@@LR@@"
ONLY="@@ONLY@@"
HOLDOUT="@@HOLDOUT@@"
ENV
set -a && . /etc/assay.env && set +a

echo "=== assay challenger bootstrap $(date -Is) ==="
nvidia-smi

# Spot reclamation gives ~120s of warning. Catch it and flush, rather than
# losing the run: an interrupted run with its reward log intact is still a
# result, an interrupted run with nothing written is not.
cat >/usr/local/bin/assay-spot-watch <<'WATCH'
#!/usr/bin/env bash
set -a && . /etc/assay.env && set +a
while true; do
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    http://169.254.169.254/latest/meta-data/spot/instance-action || echo 000)
  if [ "$code" = "200" ]; then
    echo "SPOT RECLAIM NOTICE $(date -Is) -- flushing artifacts"
    aws s3 sync /opt/assay/checkpoints "s3://${BUCKET}/${NAME}/checkpoints/" || true
    aws s3 cp /var/log/assay-train.log "s3://${BUCKET}/${NAME}/assay-train.log" || true
    exit 0
  fi
  sleep 5
done
WATCH
chmod +x /usr/local/bin/assay-spot-watch
nohup /usr/local/bin/assay-spot-watch >/var/log/assay-spot-watch.log 2>&1 &

# Docker: the Harbor half of the training corpus runs its verifiers in
# containers. Without it the reward falls back to the toy fixtures alone, so
# check rather than hope -- that would be a different experiment.
systemctl start docker || true
docker info >/dev/null || { echo "FATAL: no docker daemon; the Harbor fixtures cannot run"; exit 1; }
docker pull alpine:3.20

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:$PATH"

mkdir -p /opt/assay/repo && cd /opt/assay
if [ -n "$REPO_URL" ]; then
  rm -rf repo && git clone --branch "$BRANCH" --depth 1 "$REPO_URL" repo
else
  aws s3 cp "s3://${BUCKET}/${NAME}/src.tar.gz" /tmp/src.tar.gz
  tar -xzf /tmp/src.tar.gz -C /opt/assay/repo
fi
cd /opt/assay/repo
uv sync --extra dev --extra adapters --extra train

flush() {
  aws s3 sync /opt/assay/checkpoints "s3://${BUCKET}/${NAME}/checkpoints/" || true
  aws s3 cp /var/log/assay-train.log "s3://${BUCKET}/${NAME}/assay-train.log" || true
}
trap flush EXIT

# The reward is proved before the GPU is used for anything. If the exploit gap
# is wrong, no amount of training makes the resulting adapter mean anything,
# and finding that out at step 300 costs a GPU-hour to learn nothing.
uv run --extra adapters --extra train pytest tests/test_grpo_reward.py -q

# What the reward can pay, per environment, before any model is involved. This
# is what makes a later "it did not converge" claim checkable: a corpus that
# was flat here was never going to teach, which is a different finding from an
# optimiser that failed.
mkdir -p /opt/assay/checkpoints
uv run --extra adapters python scripts/reward_landscape.py \
  --only $ONLY --holdout "$HOLDOUT" \
  --out /opt/assay/checkpoints/reward_landscape.json
flush

# Wiring gate on the real model and the real GPU, before the real run.
uv run --extra adapters --extra train python -m assay.train.run --smoke \
  --model "$MODEL" --only fixture --out /opt/assay/checkpoints/smoke
flush

uv run --extra adapters --extra train python -m assay.train.run \
  --model "$MODEL" \
  --steps "$STEPS" \
  --group-size "$GROUP_SIZE" \
  --learning-rate "$LR" \
  --only $ONLY \
  --holdout "$HOLDOUT" \
  --out /opt/assay/checkpoints/grpo
flush

# The ablation is the point of the artifact: does the trained Challenger find
# the HELD-OUT exploit that the scripted one provably cannot? `--models` with
# no argument drops the ollama arms, which are not installed here.
uv run --extra adapters --extra train python scripts/challenger_ablation.py \
  --task self-graded \
  --grpo-adapter /opt/assay/checkpoints/grpo/final \
  --grpo-model "$MODEL" \
  --models \
  --out /opt/assay/checkpoints/ablation.json || true

echo "=== done $(date -Is) ==="
flush

# Spot instances bill by the second and this one has nothing left to do.
shutdown -h now
