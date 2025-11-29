# ------------------------------------------------------------
# Base Image with CUDA + Ubuntu (required for GPU use in Batch)
# ------------------------------------------------------------
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# ------------------------------------------------------------
# Install FFmpeg + gsutil + dependencies
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    python3 \
    python3-pip \
    bash \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install gsutil (needed for fetching & uploading clips)
RUN pip3 install gsutil

# ------------------------------------------------------------
# Create working directory
# ------------------------------------------------------------
WORKDIR /app

# ------------------------------------------------------------
# Copy scripts and make them executable
# ------------------------------------------------------------
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/*.sh

# Copy logo if stored in repo
COPY reelchains_logo.png ./

# ------------------------------------------------------------
# Default command (user can override in Batch job)
# ------------------------------------------------------------
CMD ["/bin/bash"]
