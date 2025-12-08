#!/bin/bash

# 0. Logging: Save all output to a file on the data drive so you can read it later
exec > /data/worker-execution.log 2>&1

echo "Script started at $(date)"

# 1. SMART GPU WAIT
# Try to run nvidia-smi. If it fails, wait 1 second and try again.
# We give it up to 60 seconds to wake up.
echo "Waiting for GPU to initialize..."
timeout=0
while ! nvidia-smi > /dev/null 2>&1; do
    sleep 1
    ((timeout++))
    if [ $timeout -ge 60 ]; then
        echo "Error: GPU failed to initialize after 60 seconds."
        # Don't shutdown immediately; keep it up for debugging
        sleep 1800 
        exit 1
    fi
done
echo "GPU is ready!"

# 2. Run the Docker Container
# --gpus all : Gives the container access to the Nvidia card
# --rm       : Deletes the container when it stops (keeps disk clean)
# --name     : Names it so we can find it easily
# -v         : Maps your big data drive
echo "Launching Docker container..."

# --- FETCH METADATA ---
# This allows the Java code to tell us which specific job to listen to
PROJECT_ID=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/project_id")
SUBSCRIPTION_ID=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/subscription_id")

echo "Starting Worker for Project: $PROJECT_ID on Sub: $SUBSCRIPTION_ID"

docker run --rm --gpus all --name production-worker \
-e PROJECT_ID="$PROJECT_ID" \
-e SUBSCRIPTION_ID="$SUBSCRIPTION_ID" \
-v /data:/data us-central1-docker.pkg.dev/reelchains-458715/reel-prod/reelchains:gpu

# 3. Capture the Exit Code
EXIT_CODE=$?
echo "Container exited with code: $EXIT_CODE at $(date)"

# 4. Decision Logic
if [ $EXIT_CODE -eq 0 ]; then
    echo "Job finished successfully (or timed out cleanly)."
    echo "Shutting down in 60 seconds..."
    sleep 60
    shutdown -h now
else
    echo "CRITICAL FAILURE: Container crashed or failed."
    echo "Staying awake for 30 MINUTES to allow for debugging (SSH in now!)."
    sleep 1800
    echo "Debugging time over. Shutting down."
    shutdown -h now
fi