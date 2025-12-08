#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------
# 0. Logging: persist logs for post-mortem + Cloud ops
# ---------------------------------------------------------
exec > /data/worker-execution.log 2>&1
echo "🟢 Worker script started at $(date)"

# ---------------------------------------------------------
# 1. Verify GPU availability (fast + sufficient now)
# ---------------------------------------------------------
if ! nvidia-smi; then
  echo "❌ GPU not available — aborting worker startup"
  exit 1
fi
echo "✅ GPU is ready"

# ---------------------------------------------------------
# 2. Fetch metadata injected by Java / gcloud
# ---------------------------------------------------------
PROJECT_ID=$(curl -fs -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/project_id")

SUBSCRIPTION_ID=$(curl -fs -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/subscription_id")

echo "📡 Project:        ${PROJECT_ID}"
echo "📡 Subscription:  ${SUBSCRIPTION_ID}"

# ---------------------------------------------------------
# 3. DEBUG MODE (VM stays up, container does not auto-run)
# ---------------------------------------------------------
if [[ "${SUBSCRIPTION_ID}" == "DEBUG" ]]; then
  echo "🛑 DEBUG MODE enabled"
  echo "• Docker container will not auto-start"
  echo "• VM will remain online"
  echo "• SSH in and run docker manually"
  echo "--------------------------------------------------"
  tail -f /dev/null
  exit 0
fi

# ---------------------------------------------------------
# 4. Pull latest image (important for spot workers)
# ---------------------------------------------------------
IMAGE="us-central1-docker.pkg.dev/reelchains-458715/reel-prod/reelchains:gpu"
echo "⬇️  Pulling latest image: ${IMAGE}"
docker pull "${IMAGE}"

# ---------------------------------------------------------
# 5. Launch container
# ---------------------------------------------------------
echo "🚀 Launching production worker container"

docker run --rm \
  --gpus all \
  --name production-worker \
  -e GCP_PROJECT="${PROJECT_ID}" \
  -e PUBSUB_SUBSCRIPTION="${SUBSCRIPTION_ID}" \
  -e WORKER_MODE="single_task" \
  -v /data:/data \
  "${IMAGE}"

# ---------------------------------------------------------
# 6. Exit handling
# ---------------------------------------------------------
EXIT_CODE=$?
echo "📦 Container exited with code ${EXIT_CODE} at $(date)"

if [[ ${EXIT_CODE} -eq 0 ]]; then
  echo "✅ Job finished cleanly"
  echo "⏱ Shutting down VM in 60s"
  sleep 60
  shutdown -h now
else
  echo "🔥 CRITICAL FAILURE"
  echo "🧪 VM will remain up for 30 minutes for debugging"
  sleep 1800
  shutdown -h now
fi
