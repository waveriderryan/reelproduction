#!/usr/bin/env python3
"""
productionJob.py

GPU-optimized ReelChains production pipeline.

- Downloads input clips from GCS.
- Renders final VIDEO-ONLY layout via ffmpegVideoRender.renderFinalVideo().
- Extracts per-camera audio, either:
    * mixes all audio for a single output, OR
    * produces one output per camera (same video, different audio source).
- Uploads final outputs back to GCS.

CLI:

  --bucket BUCKET_NAME
  --input gcs/path.mp4:orientation:offset   (repeatable)
  --outputGCS productions/out1.mp4          (repeatable)
  --workdir /workspace                      (optional)

Examples:

  # Single merged-audio output
  python3 productionJob.py \
    --bucket reel-artifacts \
    --input artifacts/cam1.mp4:portrait:0.033 \
    --input artifacts/cam2.mp4:landscape:0.0 \
    --outputGCS productions/johnson_merged.mp4 \
    --workdir /workspace

  # Per-camera outputs (same video, different audio per output)
  python3 productionJob.py \
    --bucket reel-artifacts \
    --input artifacts/cam1.mp4:portrait:0.033 \
    --input artifacts/cam2.mp4:landscape:0.0 \
    --outputGCS productions/johnson_cam1.mp4 \
    --outputGCS productions/johnson_cam2.mp4 \
    --workdir /workspace
"""

import argparse
from pathlib import Path
import sys

from google.cloud import storage

from ffmpegVideoRender import renderFinalVideo
from ffmpegAudioTools import (
    extractAudioTrack,
    mixAudioTracks,
    muxVideoAudio,
)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def parseInputSpec(spec: str):
    """
    Format:
      gcs/path.mp4:orientation:offset

    Example:
      artifacts/clip1.mp4:portrait:0.033
    """
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"Invalid --input format '{spec}'. Expected gcsPath:orientation:offset"
        )

    gcsPath, orientation, offsetStr = parts
    orientation = orientation.lower().strip()
    if orientation not in ("portrait", "landscape"):
        raise ValueError(f"Invalid orientation '{orientation}' in '{spec}'.")

    try:
        offset = float(offsetStr)
    except ValueError:
        raise ValueError(f"Invalid offset '{offsetStr}' in '{spec}' (must be float).")

    return gcsPath, orientation, offset


def downloadFromGCS(bucketName: str, gcsPath: str, localPath: Path, client: storage.Client):
    print(f"⬇️  Downloading gs://{bucketName}/{gcsPath} → {localPath}")
    bucket = client.bucket(bucketName)
    blob = bucket.blob(gcsPath)
    localPath.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(localPath))


def uploadToGCS(bucketName: str, gcsPath: str, localPath: Path, client: storage.Client):
    print(f"⬆️  Uploading {localPath} → gs://{bucketName}/{gcsPath}")
    bucket = client.bucket(bucketName)
    blob = bucket.blob(gcsPath)
    blob.upload_from_filename(str(localPath))


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ReelChains GPU Production Job (GCS + NVENC)")

    parser.add_argument(
        "--bucket",
        required=True,
        help="GCS bucket name (no gs:// prefix)",
    )

    parser.add_argument(
        "--input",
        required=True,
        action="append",
        help="Format: gcsPath.mp4:orientation:offset (orientation ∈ {portrait,landscape})",
    )

    parser.add_argument(
        "--outputGCS",
        required=True,
        action="append",
        help="One or more GCS output paths (no gs://bucket/ prefix). "
             "1 output → mixed audio; N outputs → one per input audio.",
    )

    parser.add_argument(
        "--workdir",
        default="/workspace",
        help="Scratch directory for temp files and intermediates (default: /workspace)",
    )

    args = parser.parse_args(argv)

    bucketName = args.bucket
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    # ---------------------------- Parse inputs -----------------------------
    try:
        parsedInputs = [parseInputSpec(s) for s in args.input]
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    n_inputs = len(parsedInputs)
    n_outputs = len(args.outputGCS)

    if n_inputs not in (2, 3):
        print("❌ Only 2 or 3 input sources supported for now.")
        return 1

    if n_outputs != 1 and n_outputs != n_inputs:
        print(
            "❌ For multiple outputs, number of --outputGCS values must equal number of inputs. "
            "Otherwise, provide exactly 1 outputGCS for merged-audio output."
        )
        return 1

    client = storage.Client()

    # ----------------------- Download input clips --------------------------
    localPaths = []
    orientations = []
    offsets = []

    for idx, (gcsPath, orientation, offset) in enumerate(parsedInputs, start=1):
        localClip = workdir / f"clip{idx}_{Path(gcsPath).name}"
        downloadFromGCS(bucketName, gcsPath, localClip, client)

        localPaths.append(localClip)
        orientations.append(orientation)
        offsets.append(offset)

    # -------------------- Step 1: Render VIDEO-ONLY -----------------------
    finalVideo = workdir / "final_video.mp4"
    print("🎬 Rendering final video layout (video-only)…")

    renderFinalVideo(
        localPaths=localPaths,
        orientations=orientations,
        offsets=offsets,
        outVideo=finalVideo,
    )

    if not finalVideo.exists():
        print("❌ Final video not produced!")
        return 1

    # --------------------- Step 2: Extract per-camera audio ----------------
    audioFiles = []
    for i, cam in enumerate(localPaths, start=1):
        outA = workdir / f"audio_cam{i}.aac"
        print(f"🎧 Extracting audio for CAM{i} (offset={offsets[i-1]})…")
        extractAudioTrack(cam, outA, offsets[i-1])
        if not outA.exists():
            print(f"❌ Failed to extract audio for {cam}")
            return 1
        audioFiles.append(outA)

    # ---------------------- Step 3: Output strategy ------------------------
    outGcsPaths = args.outputGCS

    if n_outputs == 1:
        # Single merged-audio output
        print("🎶 Single-output mode: mixing all audio tracks…")
        mergedAudio = workdir / "merged_audio.aac"
        mixAudioTracks(audioFiles, mergedAudio)

        if not mergedAudio.exists():
            print("❌ Failed to produce merged audio file.")
            return 1

        finalLocal = workdir / "final_merged.mp4"
        print(f"📦 Muxing final video + merged audio → {finalLocal}")
        muxVideoAudio(finalVideo, mergedAudio, finalLocal)

        if not finalLocal.exists():
            print("❌ Final merged output not created.")
            return 1

        uploadToGCS(bucketName, outGcsPaths[0], finalLocal, client)

    else:
        # Multi-output: one output per input audio
        print("🎧 Multi-output mode: one output per camera audio source")
        if len(outGcsPaths) != len(audioFiles):
            print("❌ Internal mismatch: outputs vs audio tracks.")
            return 1

        for i, (audio, gcsOut) in enumerate(zip(audioFiles, outGcsPaths), start=1):
            finalLocal = workdir / f"final_cam{i}.mp4"
            print(f"📦 Muxing CAM{i} audio with final video → {finalLocal}")
            muxVideoAudio(finalVideo, audio, finalLocal)

            if not finalLocal.exists():
                print(f"❌ Failed to create output for CAM{i}")
                return 1

            uploadToGCS(bucketName, gcsOut, finalLocal, client)

    print("✅ All outputs complete.")
    print(f"   Bucket: {bucketName}")
    print(f"   Outputs: {', '.join(outGcsPaths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

