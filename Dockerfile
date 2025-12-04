# Start from linuxserver ffmpeg (Ubuntu 24.04 base, FFmpeg 6.x+, CUDA/NVENC enabled)
FROM linuxserver/ffmpeg:latest

# Make sure runtime still sees GPUs
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
ENV DEBIAN_FRONTEND=noninteractive

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
# Assumes your folder structure is:
#   src/
#     ├── productionCoordinator.py
#     ├── productionJob.py
#     ├── ffmpegVideoRender.py
#     ├── ffmpegAudioTools.py
#     └── requirements.txt
COPY src/ /app/src/

# Install Python dependencies
# IMPORTANT: Ensure src/requirements.txt contains:
#   google-cloud-storage
#   google-cloud-pubsub
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/src/requirements.txt

# Work directory for temporary output
ENV WORK_DIR=/workspace
RUN mkdir -p /workspace

# Make scripts executable
RUN chmod +x /app/src/*.py

# Set the ENTRYPOINT to the new Coordinator script
# This wrapper will listen for the Pub/Sub message and trigger the job
ENTRYPOINT ["python3", "/app/src/productionCoordinator.py"]