#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------
# 0. Logging: persist logs for post-mortem + Cloud ops
# ---------------------------------------------------------
LOG_DIR="/data/logs"
mkdir -p "$LOG_DIR"

# Create a timestamped log file INSIDE the logs directory
LOG_FILE="${LOG_DIR}/worker-$(date +%Y%m%d-%H%M%S).log"

# Redirect all future output to this file AND the console
exec > >(tee -a "$LOG_FILE") 2>&1

echo "🟢 Worker script started at $(date)"
set -e

# Setup variables for the upload function later
INSTANCE_NAME="$(hostname)"
DATE_UTC="$(date -u +%Y-%m-%d)"
GCS_LOG_DIR="gs://reel-artifacts/worker-logs/${INSTANCE_NAME}/${DATE_UTC}"

upload_logs() {
  echo "📤 Uploading logs to ${GCS_LOG_DIR} ..."
  gsutil cp "$LOG_FILE" "${GCS_LOG_DIR}/" || true
}

trap upload_logs EXIT
trap upload_logs ERR
# ---------------------------------------------------------
# 1. Verify GPU availability (fast + sufficient now)
# ---------------------------------------------------------
if ! nvidia-smi; then
  echo "❌ GPU not available — aborting worker startup"
  exit 1
fi
echo "✅ GPU is ready"

echo "Restarting Docker after GPU init..."
systemctl restart docker
sleep 3

# ---------------------------------------------------------
# 2. Fetch metadata injected by Java / gcloud
# ---------------------------------------------------------
PROJECT_ID=$(curl -fs -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/project_id")

SUBSCRIPTION_ID=$(curl -fs -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/subscription_id")

# [NEW] Fetch the Topic. Defaults to "production-results" if missing.
RESULT_TOPIC=$(curl -fs -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/result_topic" || echo "production-results")

echo "📡 Project:        ${PROJECT_ID}"
echo "📡 Subscription:  ${SUBSCRIPTION_ID}"
echo "📡 Result Topic:  ${RESULT_TOPIC}"

# ---------------------------------------------------------
# 3. DEBUG MODE (VM stays up, container does not auto-run)
# ---------------------------------------------------------
if [ "$SUBSCRIPTION_ID" == "DEBUG" ]; then
    echo "🛑 DEBUG MODE enabled"
    echo "• Docker container will not auto-start"
    
    # 1. Schedule the Time Bomb (60 minutes)
    echo "⏳ AUTO-SHUTDOWN SCHEDULED: VM will kill itself in 60 minutes."
    shutdown -h +60 "Debug session time limit reached. Shutting down to save money." &

    # 2. Create the 'Extend' shortcut command
    # This creates a global command 'extend-session' that cancels the shutdown and adds another hour
    cat << 'EOF' > /usr/local/bin/extend-session
#!/bin/bash
sudo shutdown -c
echo "✅ Auto-shutdown CANCELLED."
sudo shutdown -h +60 "Debug session extended. Shutting down in 60 minutes."
echo "⏳ New shutdown scheduled for +60 minutes."
EOF
    chmod +x /usr/local/bin/extend-session

    echo "• VM will remain online for 1 HOUR."
    echo "• To stay longer, run:  sudo extend-session"
    echo "• SSH in and run docker manually"
    
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
echo "Cleaning up old docker runs"
docker rm -f production-worker 2>/dev/null || true

echo "🚀 Launching production worker container"

set +e

docker run \
  --gpus all \
  --name production-worker \
  -e GCP_PROJECT="${PROJECT_ID}" \
  -e PUBSUB_SUBSCRIPTION="${SUBSCRIPTION_ID}" \
  -e RESULT_TOPIC="${RESULT_TOPIC}" \
  -e WORKER_MODE="single_task" \
  -v /data:/data \
  "${IMAGE}"

# ---------------------------------------------------------
# 6. Exit handling
# ---------------------------------------------------------
EXIT_CODE=$?
echo "📦 Container exited with code ${EXIT_CODE} at $(date)"

set -e

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
