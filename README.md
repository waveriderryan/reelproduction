📘 README.md — Reel Pipeline (FFmpeg Production Engine)
🎥 Reel Video Production Pipeline

FFmpeg-based multi-camera video composer for ReelChains.

This repository contains the video production engine used to combine multiple VisionCamera recordings into a single synchronized composite video layout (portrait, landscape, or mixed), including logo overlays, audio mixing, and precise timestamp trimming.

It is designed to run both:

Locally (during development)

Inside Docker

Inside Google Cloud Batch (GPU-enabled spare capacity machines)

✨ Features
✔️ 2-Portrait

Two portrait videos side-by-side, height-normalized.

✔️ 2-Landscape

Two landscape videos stacked vertically.

✔️ Mixed Portrait + Landscape

Portrait above landscape, or landscape above portrait — auto-routed depending on input order.

✔️ Automatic Timestamp Offset Trim

If CAM1 started earlier (negative or positive offset), trimming is applied:

-ss OFFSET CAM1

✔️ Google Cloud Storage Integration

Downloads inputs from gs://BUCKET/artifacts/... using caching, and uploads the final production video back to GCS.

✔️ Debug Mode

Local runs copy output to the project root and skip cloud upload:

DEBUG=1 ./generateProductionJob.sh ...

✔️ GPU-accelerated HEVC encoding

Uses:

-c:v hevc_videotoolbox -tag:v hvc1


on macOS, or can be extended to NVENC when running in cloud.

📁 Repository Structure
reel-pipeline/
│
├── scripts/
│   ├── generate2Portrait.sh
│   ├── generate2Landscape.sh
│   ├── generateMixedPortraitLandscape.sh
│   ├── generateProductionJob.sh
│
├── Dockerfile
└── README.md

🚀 How to Run a Production Job (Locally)
01 — Ensure ffmpeg is installed

On macOS:

brew install ffmpeg

02 — Run the main job runner
./generateProductionJob.sh BUCKET OUTFILE \
    CLIP1_PATH MODE1 \
    CLIP2_PATH MODE2 \
    OFFSET_SEC

Example
./generateProductionJob.sh reel-artifacts production/out.mp4 \
    artifacts/abc/clip1.mp4 portrait \
    artifacts/xyz/clip2.mp4 landscape \
    0.116

What happens:

Clips are downloaded (with cache)

Orientation routing selects the correct layout script

FFmpeg generates the composite

If DEBUG=0, result is uploaded to:

gs://reel-artifacts/production/out.mp4

🧠 Orientation Logic

The job dispatcher decides which layout script to run:

MODE1	MODE2	Script
portrait	portrait	generate2Portrait.sh
landscape	landscape	generate2Landscape.sh
portrait	landscape	generateMixedPortraitLandscape.sh
landscape	portrait	generateMixedPortraitLandscape.sh

Only one mixed script is required — it handles both orders by reading MODE1 and MODE2.

⏱ Offset Logic (Very Important)

You supply:

OFFSET_SEC


Meaning:

CAM1 started OFFSET_SEC seconds earlier than CAM2.

Therefore:

CAM1 is trimmed at input time using -ss OFFSET_SEC


This guarantees synchronization so that the first real recorded frame aligns across both videos.

🧪 Debug Mode

Debug mode is ON by default (DEBUG=1):

Uses ./debug_workspace

Does not delete temp files

Does not upload to Google Cloud

Copies output to local directory

To run in production mode, supply:

DEBUG=0 ./generateProductionJob.sh ...

🐳 Running Inside Docker

You can package this entire pipeline into a Docker image.

Build:
docker build -t reel-pipeline .

Run:
docker run --rm \
  -e BUCKET=reel-artifacts \
  -e DEBUG=0 \
  -v $HOME/.config/gcloud:/root/.config/gcloud \
  reel-pipeline \
  ./generateProductionJob.sh reel-artifacts production/out.mp4 \
     artifacts/a.mp4 portrait \
     artifacts/b.mp4 portrait \
     0.033


Mounting your gcloud credentials allows the container to download from GCS.

☁️ Using Google Cloud Batch (GPU-Optimized)

This repo is designed to run perfectly inside Google Cloud Batch, especially on:

Spot (spare) GPU capacity

A2, L4, T4, or H100 machines

Cheap GPU preemptible nodes

Pipeline:

Cloud Function receives video upload event

Chooses appropriate machine type (GPU)

Submits a Batch job pointing to this repo’s container

Container runs FFmpeg and writes output to GCS

Status returned to application

If you want, I can generate:

batch-job.json

cloudbuild.yaml

main.py for Cloud Function

Dockerfile optimized for NVENC

Submission script (gcloud batch jobs submit ...)

📝 Future Enhancements

3-way and 4-way composite layouts

Real-time progress logging to Firestore

Horizontal / vertical adaptive cropping

Per-clip color correction (LUTs)

Server-side timestamp verification

❤️ Maintainers

Ryan Andrews
ReelChains Production Pipeline