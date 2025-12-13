#!/bin/bash

# The file containing your fixed code
SCRIPT_FILE="run-worker.sh"

# Check if file exists
if [ ! -f "$SCRIPT_FILE" ]; then
    echo "❌ Error: Could not find '$SCRIPT_FILE' in current directory."
    exit 1
fi

echo "🚀 Updating workers with $SCRIPT_FILE..."
echo "----------------------------------------"

# 1. Update Central
echo "1️⃣  Updating gpu-worker-central-1 (us-central1-b)..."
gcloud compute instances add-metadata gpu-worker-central-1 \
    --metadata-from-file startup-script="$SCRIPT_FILE" \
    --zone us-central1-b

# 2. Update Toronto
echo "2️⃣  Updating gpu-worker-toronto1 (northamerica-northeast2-b)..."
gcloud compute instances add-metadata gpu-worker-toronto1 \
    --metadata-from-file startup-script="$SCRIPT_FILE" \
    --zone northamerica-northeast2-b

# 3. Update West
echo "3️⃣  Updating gpu-worker-west1-1 (us-west1-b)..."
gcloud compute instances add-metadata gpu-worker-west1-1 \
    --metadata-from-file startup-script="$SCRIPT_FILE" \
    --zone us-west1-b

echo "----------------------------------------"
echo "✅ All workers updated."
echo "⚠️  REMINDER: Changes only take effect when the VM reboots."