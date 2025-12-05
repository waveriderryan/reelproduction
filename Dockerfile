# Start from linuxserver ffmpeg (Ubuntu 24.04 base, FFmpeg 6.x+, CUDA/NVENC enabled)
FROM linuxserver/ffmpeg:latest

# Make sure runtime still sees GPUs
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
ENV DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# NEW: Ensure logs appear in Cloud Logging immediately (Critical for debugging)
# ---------------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------------
# NEW: Tell your script to run in "One-Shot" mode
# Your Python script should check os.environ.get('WORKER_MODE')
# ---------------------------------------------------------------------------
ENV WORKER_MODE=single_task

# Install Python + tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Create venv
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy your source code
COPY src/ /app/src/

# Install Python dependencies
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/src/requirements.txt

# Work directory for temporary output
ENV WORK_DIR=/workspace
RUN mkdir -p /workspace

# Make scripts executable
RUN chmod +x /app/src/*.py

# Define these in your Java 'startVm' call or Golden Image env, 
# or hardcode them here if they never change.
ENV GCP_PROJECT=your-project-id
ENV PUBSUB_SUBSCRIPTION=your-subscription-id
ENV WORKER_MODE=single_task

# Set the ENTRYPOINT
ENTRYPOINT ["python3", "/app/src/productionCoordinator.py"]
