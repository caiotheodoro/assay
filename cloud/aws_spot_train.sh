#!/usr/bin/env bash
# Train the Challenger on one AWS spot g5.xlarge (A10G 24GB).
#
# Shape borrowed from plumb/cloud/aws_serve.sh: Deep Learning OSS AMI, an
# SSM-only instance with no inbound ports and no key pair, IAM role created on
# first use. Two things are different here and both matter.
#
#   1. It asks for a SPOT instance. Spot is reclaimed with two minutes' notice,
#      so the run checkpoints to S3 every `--save-steps` and the launcher tells
#      you how to resume rather than pretending reclamation will not happen.
#   2. The training reward RUNS THE ENVIRONMENT. The Harbor fixtures execute in
#      Docker, so the instance needs a working daemon before training starts and
#      the bootstrap fails loudly if it does not have one -- a run that silently
#      trained on the toy fixtures alone is a different experiment than the one
#      the write-up would claim.
#
# Usage:
#   ./cloud/aws_spot_train.sh                       # launch, print the tail command
#   DRY=1 ./cloud/aws_spot_train.sh                 # price and plan only, launch nothing
#   STEPS=600 GROUP_SIZE=8 ./cloud/aws_spot_train.sh
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
REGION=${AWS_REGION:-us-east-1}
export AWS_DEFAULT_REGION=$REGION

ITYPE=${AWS_INSTANCE:-g5.xlarge}                 # 1x A10G 24GB
NAME=${AWS_NAME:-assay-challenger-$(date +%m%d-%H%M)}
MODEL=${MODEL:-Qwen/Qwen3-1.7B}
STEPS=${STEPS:-300}
GROUP_SIZE=${GROUP_SIZE:-8}
LR=${LR:-1e-5}
ONLY=${ONLY:-"fixture harbor"}
HOLDOUT=${HOLDOUT:-harbor/self-graded}
REPO_URL=${REPO_URL:-}
BRANCH=${BRANCH:-worker/train}
BUCKET=${BUCKET:-assay-challenger-$(aws sts get-caller-identity --query Account --output text)}
ROLE_NAME=${ROLE_NAME:-assay-train-ec2}
SG_NAME=${SG_NAME:-assay-train-ssm}
DISK_GB=${DISK_GB:-200}
MAX_PRICE=${MAX_PRICE:-}                         # blank = on-demand price cap
DRY=${DRY:-0}
AMI_NAME_GLOB=${AMI_NAME_GLOB:-'Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.*Ubuntu 22.04*'}

if [ -z "$REPO_URL" ]; then
  REPO_URL=$(git -C "$ROOT" remote get-url origin 2>/dev/null || true)
fi
if [ -z "$REPO_URL" ]; then
  echo "REPO_URL is unset and this checkout has no origin remote." >&2
  echo "The instance clones the repo; it cannot read your laptop." >&2
  exit 2
fi

spot_price=$(aws ec2 describe-spot-price-history --instance-types "$ITYPE" \
  --product-descriptions "Linux/UNIX" --max-items 1 \
  --query 'SpotPriceHistory[0].SpotPrice' --output text 2>/dev/null || echo "unknown")
echo "instance:   $ITYPE (spot, current ${spot_price}/hr in ${REGION})"
echo "model:      $MODEL"
echo "steps:      $STEPS x group ${GROUP_SIZE}"
echo "corpus:     only='${ONLY}'  holdout='${HOLDOUT}'"
echo "artifacts:  s3://${BUCKET}/${NAME}/"

if [ "$DRY" = "1" ]; then
  echo "DRY RUN: nothing launched, nothing created."
  exit 0
fi

quota=$(aws service-quotas get-service-quota --service-code ec2 --quota-code L-3819A6DF \
  --query Quota.Value --output text 2>/dev/null || echo 0)
if [ "${quota%.*}" -lt 4 ]; then
  echo "All G/VT Spot quota is ${quota} vCPU in ${REGION}; ${ITYPE} needs 4." >&2
  echo "Raise it: Service Quotas > EC2 > 'All G and VT Spot Instance Requests'." >&2
  exit 2
fi

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || \
  aws s3api create-bucket --bucket "$BUCKET" \
    $([ "$REGION" = us-east-1 ] || echo "--create-bucket-configuration LocationConstraint=$REGION") \
    >/dev/null

if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
fi
# Scoped to this one bucket: the instance runs third-party environment code,
# and handing that a wildcard S3 policy would be careless.
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name assay-artifacts \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{\"Effect\":\"Allow\",
      \"Action\":[\"s3:PutObject\",\"s3:GetObject\",\"s3:ListBucket\"],
      \"Resource\":[\"arn:aws:s3:::${BUCKET}\",\"arn:aws:s3:::${BUCKET}/*\"]}]
  }" >/dev/null

PROFILE_ARN=$(aws iam get-instance-profile --instance-profile-name "$ROLE_NAME" \
  --query 'InstanceProfile.Arn' --output text 2>/dev/null || true)
if [ -z "$PROFILE_ARN" ] || [ "$PROFILE_ARN" = "None" ]; then
  aws iam create-instance-profile --instance-profile-name "$ROLE_NAME" >/dev/null
  for _ in $(seq 1 20); do
    aws iam add-role-to-instance-profile --instance-profile-name "$ROLE_NAME" \
      --role-name "$ROLE_NAME" 2>/dev/null && break || sleep 3
  done
fi

SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
  SG_ID=$(aws ec2 create-security-group --group-name "$SG_NAME" \
    --description "assay training: SSM only, no inbound" --query 'GroupId' --output text)
fi

AMI=$(aws ec2 describe-images --owners amazon \
  --filters "Name=name,Values=$AMI_NAME_GLOB" \
  --query 'reverse(sort_by(Images[].{Name:Name,Id:ImageId,Date:CreationDate}, &Date))[0].Id' \
  --output text)
[ "$AMI" = "None" ] && { echo "no Deep Learning AMI matched in $REGION" >&2; exit 2; }

USERDATA=$(REPO_URL="$REPO_URL" BRANCH="$BRANCH" BUCKET="$BUCKET" NAME="$NAME" \
  MODEL="$MODEL" STEPS="$STEPS" GROUP_SIZE="$GROUP_SIZE" LR="$LR" \
  ONLY="$ONLY" HOLDOUT="$HOLDOUT" envsubst < "$ROOT/cloud/bootstrap.sh" | base64)

MARKET='{"MarketType":"spot","SpotOptions":{"SpotInstanceType":"one-time","InstanceInterruptionBehavior":"terminate"}}'
if [ -n "$MAX_PRICE" ]; then
  MARKET="{\"MarketType\":\"spot\",\"SpotOptions\":{\"SpotInstanceType\":\"one-time\",\"MaxPrice\":\"${MAX_PRICE}\",\"InstanceInterruptionBehavior\":\"terminate\"}}"
fi

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI" --instance-type "$ITYPE" \
  --iam-instance-profile "Name=$ROLE_NAME" \
  --security-group-ids "$SG_ID" \
  --instance-market-options "$MARKET" \
  --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":${DISK_GB},\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]" \
  --tag-specifications "[{\"ResourceType\":\"instance\",\"Tags\":[
     {\"Key\":\"Name\",\"Value\":\"${NAME}\"},
     {\"Key\":\"project\",\"Value\":\"assay\"},
     {\"Key\":\"role\",\"Value\":\"challenger-grpo\"}]}]" \
  --user-data "$USERDATA" \
  --query 'Instances[0].InstanceId' --output text)

echo "launched $INSTANCE_ID"
echo "waiting for SSM..."
state=""
for _ in $(seq 1 90); do
  state=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)
  [ "$state" = "Online" ] && break
  sleep 10
done
echo "SSM: ${state:-offline}"
cat <<EOS

  tail:      aws ssm start-session --target $INSTANCE_ID \\
               --document-name AWS-StartInteractiveCommand \\
               --parameters '{"command":["tail -f /var/log/assay-train.log"]}'
  artifacts: aws s3 sync s3://${BUCKET}/${NAME}/ ./results/${NAME}/
  stop:      aws ec2 terminate-instances --instance-ids $INSTANCE_ID

  Spot is reclaimed without warning. Everything under checkpoints/ is synced to
  S3 as it is written, so a reclaimed run keeps whatever it had reached; the
  run.json summary is only written on a clean finish, which is how you tell a
  short run from a killed one.
EOS
