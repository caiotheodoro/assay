#!/usr/bin/env bash
# EC2 user-data for the spot trainer. Rendered by aws_spot_train.sh via
# envsubst, so $VARS below are substituted on the laptop, not on the instance.
#
# Fails loudly and early. A bootstrap that half-works produces a run whose
# corpus quietly shrank, and a shrunken corpus reported as a clean one is the
# exact failure this project exists to catch.
set -euxo pipefail
exec > >(tee -a /var/log/assay-train.log) 2>&1

echo "=== assay challenger bootstrap $(date -Is) ==="
nvidia-smi

# Spot reclamation gives ~120s. Catch it and flush artifacts rather than
# losing the run: an interrupted run with its reward log intact is still a
# result, an interrupted run with nothing written is not.
cat >/usr/local/bin/assay-spot-watch <<'WATCH'
#!/usr/bin/env bash
while true; do
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    http://169.254.169.254/latest/meta-data/spot/instance-action || echo 000)
  if [ "$code" = "200" ]; then
    echo "SPOT RECLAIM NOTICE $(date -Is) -- flushing artifacts"
    aws s3 sync /opt/assay/checkpoints "s3://$BUCKET/$NAME/checkpoints/" || true
    aws s3 cp /var/log/assay-train.log "s3://$BUCKET/$NAME/assay-train.log" || true
    exit 0
  fi
  sleep 5
done
WATCH
sed -i "s|\$BUCKET|${BUCKET}|g; s|\$NAME|${NAME}|g" /usr/local/bin/assay-spot-watch
chmod +x /usr/local/bin/assay-spot-watch
nohup /usr/local/bin/assay-spot-watch >/var/log/assay-spot-watch.log 2>&1 &

# Docker: the Harbor half of the training corpus runs its verifiers in
# containers. Without it the reward silently falls back to the toy fixtures
# alone, so check rather than hope.
systemctl start docker || true
docker info >/dev/null || { echo "FATAL: no docker daemon; the Harbor fixtures cannot run"; exit 1; }
docker pull alpine:3.20

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:$PATH"

mkdir -p /opt/assay && cd /opt/assay
git clone --branch "$BRANCH" --depth 1 "$REPO_URL" repo
cd repo
uv sync --extra dev --extra adapters --extra train

# The reward is proved before the GPU is used for anything. If the exploit gap
# is wrong, no amount of training makes the resulting adapter mean anything,
# and finding that out after 300 steps costs a GPU-hour to learn nothing.
uv run --extra adapters --extra train pytest tests/test_grpo_reward.py -q
aws s3 cp /var/log/assay-train.log "s3://$BUCKET/$NAME/assay-train.log" || true

# Wiring gate on the real model before the real run.
uv run --extra adapters --extra train python -m assay.train.run --smoke \
  --model "$MODEL" --out /opt/assay/checkpoints/smoke

uv run --extra adapters --extra train python -m assay.train.run \
  --model "$MODEL" \
  --steps "$STEPS" \
  --group-size "$GROUP_SIZE" \
  --learning-rate "$LR" \
  --only $ONLY \
  --holdout "$HOLDOUT" \
  --out /opt/assay/checkpoints/grpo

# The ablation is the point of the artifact: does the trained Challenger find
# the held-out exploit that the scripted one provably cannot?
uv run --extra adapters --extra train python scripts/challenger_ablation.py \
  --task self-graded \
  --grpo-adapter /opt/assay/checkpoints/grpo/final \
  --grpo-model "$MODEL" \
  --models \
  --out /opt/assay/checkpoints/grpo/ablation.json || true

aws s3 sync /opt/assay/checkpoints "s3://$BUCKET/$NAME/checkpoints/"
aws s3 cp /var/log/assay-train.log "s3://$BUCKET/$NAME/assay-train.log"
echo "=== done $(date -Is) ==="

# Spot instances bill by the second and this one has nothing left to do.
shutdown -h now
