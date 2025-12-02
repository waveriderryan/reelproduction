# Start from linuxserver ffmpeg (Ubuntu 24.04 base, FFmpeg 8.x, CUDA/NVENC enabled)
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

# Copy your app
COPY assets/ ./assets/
COPY src/ ./src/
COPY src/requirements.txt ./src/requirements.txt

# Install Python dependencies
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r src/requirements.txt

# Work directory for temporary output
ENV WORK_DIR=/tmp/reelWork

# Run your main program
ENTRYPOINT ["python3", "/app/src/productionJob.py"]
