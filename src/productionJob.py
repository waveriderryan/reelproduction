#!/usr/bin/env python3
"""
productionJob.py (updated)

- Accepts NEW payload inputs with: {"clip": "<uuid>", "orientation": "...", "startTime": "..."}
- Finalizes each clip if needed by reading:
    gs://{bucket}/artifacts/{clipId}/manifest.json
  then stitching segments (ordered by segmentIndex) and muxing audio (if present),
  writing canonical:
    gs://{bucket}/clips/{clipId}_master.mp4
- Then proceeds with existing render + audio pipeline.

IMPORTANT:
- This file assumes your ffmpegAudioTools.py has the "timeline-safe" version:
  - mixAudioTracksTimeline(..., target_duration=base_duration) and it terminates.
- This file writes extracted/intermediate audio as .m4a (NOT raw .aac) to avoid duration ambiguity.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import storage

# Helper imports
from ffmpegVideoRender import renderFinalVideo
from ffmpegAudioTools import (
    extractAudioTrimmed,
    extractAudioUntrimmed,
    mixAudioTracksTrim,
    mixAudioTracksTimeline,
    muxVideoAudio,
    muxVideoWithTimelineAudio,
)

def get_segment_duration_seconds(path: Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            str(path),
        ]).decode().strip()

        return float(out) if out else 0.0

    except Exception as e:
        print(f"⚠️ ffprobe duration failed for {path.name}: {e}")
        return 0.0


def get_real_video_duration(path: Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            str(path),
        ]).decode().strip()

        dur = float(out) if out else 0.0
        return dur

    except Exception as e:
        print(f"⚠️ ffprobe duration failed for {path.name}: {e}")
        return 0.0



def normalize_container_timestamps(inp: Path, outp: Path):
    """
    Rewrites container timing (moov atoms / duration) so ffprobe duration matches actual PTS span.
    This does NOT re-encode.
    """
    subprocess.check_call([
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-i", str(inp),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c", "copy",
        "-movflags", "+faststart",
        str(outp),
    ])


def remux_reset_ts(inp: Path, outp: Path):
    subprocess.check_call([
        "ffmpeg", "-y",
        "-i", str(inp),
        "-map", "0",
        "-c", "copy",
        "-reset_timestamps", "1",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(outp),
    ])

def concat_streamcopy(concat_list: Path, outp: Path):
    subprocess.check_call([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(outp),
    ])

def validate_decode(path: Path):
    subprocess.check_call([
        "ffmpeg", "-v", "error",
        "-i", str(path),
        "-f", "null", "-"
    ])


def concat_and_normalize_av(concat_list: Path, outp: Path):
    subprocess.check_call([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),

        # 🔒 LOCK video timing
        "-vsync", "cfr",
        "-r", "30000/1001",

        # 🔒 LOCK audio timing
        "-af", "aresample=async=1:first_pts=0",
        "-ar", "48000",

        # Encode once (canonical)
        "-c:v", "hevc_nvenc",
        "-preset", "p5",
        "-pix_fmt", "yuv420p",
        "-g", "60",

        "-c:a", "aac",
        "-b:a", "192k",

        "-movflags", "+faststart",
        str(outp),
    ])



# -----------------------------
# GCS helpers
# -----------------------------
def gcs_exists(bucket_name: str, gcs_path: str, client) -> bool:
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)
    return blob.exists()


def downloadFromGCS(bucketName, gcsPath, localPath: Path, client):
    print(f"⬇️ Downloading gs://{bucketName}/{gcsPath}...")
    bucket = client.bucket(bucketName)
    blob = bucket.blob(gcsPath)
    localPath.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(localPath))


def uploadToGCS(bucketName, gcsPath, localPath: Path, client):
    print(f"⬆️ Uploading {localPath} -> gs://{bucketName}/{gcsPath}...")
    bucket = client.bucket(bucketName)
    blob = bucket.blob(gcsPath)
    blob.upload_from_filename(str(localPath))


# -----------------------------
# ffprobe helpers
# -----------------------------
def video_has_audio(path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "json",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(r.stdout or "{}")
    return len(data.get("streams", [])) > 0


def get_video_duration_seconds(video_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    out = subprocess.check_output(cmd).decode().strip()
    return float(out)


def merge_external_audio(video_path: Path, audio_path: Path, out_path: Path):
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),

        "-filter_complex",
        "[0:v]setpts=PTS-STARTPTS[v];[1:a]asetpts=PTS-STARTPTS[a]",

        "-map", "[v]",
        "-map", "[a]",

        # ⛔️ cannot use -c:v copy when filtering
        "-c:v", "hevc_nvenc",     # or libx265 if CPU
        "-preset", "p5",
        "-b:v", "5M",
        "-maxrate", "6M",
        "-bufsize", "12M",

        "-c:a", "aac",
        "-b:a", "192k",

        "-movflags", "+faststart",
        "-shortest",
        str(out_path),
    ]
    subprocess.check_call(cmd)




# -----------------------------
# Thumbnail + metadata helpers
# -----------------------------
def choose_thumbnail_time(duration: float) -> float:
    if duration < 1.0:
        return 0.0
    return max(0.1, duration * 0.5)


def extract_thumbnail(video_path: str, output_jpeg: str, timestamp: float):
    cmd = [
        "ffmpeg",
        "-y",
        "-skip_frame",
        "nokey",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        output_jpeg,
    ]
    subprocess.run(cmd, check=True)


def get_video_metadata(file_path: Path):
    print(f"🔍 Probing metadata for: {file_path}")

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-select_streams",
        "v:0",
        str(file_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout or "{}")

        duration = 0.0
        if "format" in data and "duration" in data["format"]:
            try:
                duration = float(data["format"]["duration"])
            except Exception:
                pass

        rotation = 0
        width = 0
        height = 0

        try:
            stream = data["streams"][0]
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))

            if "tags" in stream and "rotate" in stream["tags"]:
                rotation = int(float(stream["tags"]["rotate"]))
            elif "side_data_list" in stream:
                for side_data in stream["side_data_list"]:
                    if "rotation" in side_data:
                        rotation = int(float(side_data["rotation"]))
        except Exception:
            pass

        if abs(rotation) in [90, 270]:
            effective_width = height
            effective_height = width
        else:
            effective_width = width
            effective_height = height

        orientation_str = "portrait" if effective_height > effective_width else "landscape"
        print(f"✅ Metadata: {duration}s, {orientation_str} (Rot:{rotation}, {width}x{height})")

        return {"duration": duration, "orientation": orientation_str}
    except Exception as e:
        print(f"⚠️ FFprobe failed for metadata: {e}")
        return {"duration": 0.0, "orientation": "landscape"}


# -----------------------------
# NEW: Clip finalization via manifest
# -----------------------------
def parse_iso_utc(ts: str) -> float:
    # expects "2026-02-09T15:31:12.206Z"
    return (
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def ensure_clip_finalized(bucket_name: str, clip_id: str, client, workdir: Path) -> str:
    master_gcs = f"clips/{clip_id}_master.mp4"
    if gcs_exists(bucket_name, master_gcs, client):
        print(f"✅ Canonical clip exists: gs://{bucket_name}/{master_gcs}")
        return master_gcs

    print(f"🧵 Canonical clip missing. Finalizing clip {clip_id}...")

    artifact_root = f"artifacts/{clip_id}"
    manifest_gcs = f"{artifact_root}/manifest.json"
    local_manifest = workdir / f"{clip_id}_manifest.json"
    downloadFromGCS(bucket_name, manifest_gcs, local_manifest, client)

    manifest = json.loads(local_manifest.read_text())

    if not manifest.get("finalized", False):
        raise RuntimeError(f"Clip {clip_id} manifest not finalized yet")

    segments = sorted(manifest.get("segments", []), key=lambda s: int(s["segmentIndex"]))
    if not segments:
        raise RuntimeError(f"Clip {clip_id} manifest has no segments")

    concat_list = workdir / f"{clip_id}_concat.txt"

    with concat_list.open("w") as f:
        for i, seg in enumerate(segments):
            local_seg = workdir / f"{clip_id}_seg_{i:04d}.mp4"
            downloadFromGCS(bucket_name, seg["path"], local_seg, client)

            dur = get_real_video_duration(local_seg)
            print(f"🔍 Segment {local_seg.name} duration = {dur:.3f}s")

            if dur < 0.5:
                print(f"⚠️ Skipping tiny segment {local_seg.name}")
                continue

            f.write(f"file '{local_seg.as_posix()}'\n")

    stitched_video = workdir / f"{clip_id}_stitched.mp4"

    print("🎞️ Canonicalizing master clip (CFR + unified timebase)")

    subprocess.check_call([
        "ffmpeg", "-y",

        # Concat stitched segments
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),

        # Map streams explicitly
        "-map", "0:v:0",
        "-map", "0:a:0?",

        # 🔧 Encode once → canonical master (NO TIMELINE MODIFICATION)
        "-c:v", "hevc_nvenc",
        "-preset", "p5",
        "-pix_fmt", "yuv420p",
        "-profile:v", "main",
        "-tag:v", "hvc1",          # QuickTime requires this for HEVC
        "-g", "60",

        # 🔧 Audio encode (no resampling / no timeline forcing)
        "-c:a", "aac",
        "-b:a", "192k",

        # 🔧 Container flags for Apple
        "-movflags", "+faststart",

        str(stitched_video),
    ])



    # Final container normalization (safe but optional now)
    final_local = workdir / f"{clip_id}_master.mp4"
    normalize_container_timestamps(stitched_video, final_local)

    uploadToGCS(bucket_name, master_gcs, final_local, client)
    print(f"⬆️ Wrote canonical clip: gs://{bucket_name}/{master_gcs}")

    return master_gcs



# -----------------------------
# Main job
# -----------------------------
def run_job(
    bucket_name,
    input_specs,
    output_gcs_paths,
    workdir_str="/workspace",
    production_type="multi_view",
    is_left_hand=False,
):
    """
    input_specs: list[dict] with NEW shape:
      {"clip": "<uuid>", "orientation": "...", "startTime": "..."}
    Returns: (primary_output_local_path, metadata_dict)
    """
    workdir = Path(workdir_str).resolve()
    thumbnail_path = workdir / "thumbnail.jpg"
    workdir.mkdir(parents=True, exist_ok=True)

    client = storage.Client()

    print(f"🎬 Starting Job: {len(input_specs)} inputs -> {len(output_gcs_paths)} outputs")

    # ---------------------------------------------------------
    # 1. Ensure canonical clips exist + download inputs
    # ---------------------------------------------------------
    local_paths: list[Path] = []
    orientations: list[str] = []
    start_times_abs: list[float] = []
    clip_ids: list[str] = []

    try:
        for idx, inp in enumerate(input_specs, 1):
            clip_id = inp["clip"]
            orient = inp["orientation"].lower().strip()
            start_time_str = inp["startTime"]

            # Ensure canonical clip exists (stitch + audio mux if needed)
            ensure_clip_finalized(bucket_name, clip_id, client, workdir)

            master_gcs_path = f"clips/{clip_id}_master.mp4"
            local_video = workdir / f"clip{idx}_{clip_id}_master.mp4"
            downloadFromGCS(bucket_name, master_gcs_path, local_video, client)

            local_paths.append(local_video)
            orientations.append(orient)
            start_times_abs.append(parse_iso_utc(start_time_str))
            clip_ids.append(clip_id)

    except Exception as e:
        raise RuntimeError(f"Failed during input preparation/download: {e}")

    # ---------------------------------------------------------
    # 2. Derive timeline vs trim models from absolute start times
    # ---------------------------------------------------------
    earliest = min(start_times_abs)
    latest = max(start_times_abs)

    timeline_starts = [max(0.0, t - earliest) for t in start_times_abs]
    trim_offsets = [max(0.0, latest - t) for t in start_times_abs]

    # ---------------------------------------------------------
    # 3. Render Video Track (silent)
    # ---------------------------------------------------------
    final_video_track = workdir / "final_video_track.mp4"
    metadata = {}

    try:
        print("⏱️ Finding clip durations...")
        clip_durations = [get_video_duration_seconds(str(p)) for p in local_paths]

        base_duration = max(clip_durations) + 0.25

        print(f"🧮 clip_durations={clip_durations}")

        print(f"🎥 Rendering video track... base_duration={base_duration:.3f}s")

        render_mode = renderFinalVideo(
            local_paths,
            orientations,
            trim_offsets,          # offsets (trim)
            final_video_track,
            timeline_starts,       # startTimes
            base_duration,
            production_type=production_type,
            is_left_hand=is_left_hand,
        )

        if render_mode == "timeline":
            start_times = timeline_starts
            offsets = timeline_starts
        else:
            start_times = timeline_starts  # still useful later
            offsets = trim_offsets

        metadata = get_video_metadata(final_video_track)
        print(f"📏 Metadata extracted: {metadata}")

    except Exception as e:
        raise RuntimeError(f"Video render failed: {e}")

    assert final_video_track.exists(), f"Video missing: {final_video_track}"
    assert final_video_track.stat().st_size > 0, "Video file is empty"

    # ---------------------------------------------------------
    # 4. Process Audio & Mux
    # ---------------------------------------------------------
    primary_output_path: Path | None = None
    uploaded_outputs: list[str] = []

    try:
        print("🔊 Processing audio...")

        # Extract audio from source clips into .m4a (NOT .aac)
        audio_files: list[Path] = []
        for i, video_path in enumerate(local_paths):
            audio_out = workdir / f"audio_track_{i}.m4a"
            if render_mode == "trim":
                extractAudioTrimmed(video_path, audio_out, offsets[i])
            else:
                extractAudioUntrimmed(video_path, audio_out)
            audio_files.append(audio_out)

        n_outputs = len(output_gcs_paths)

        # Strategy A: Mixed Audio (1 Output)
        if n_outputs == 1:
            mixed_audio = workdir / "mixed_audio.m4a"

            if render_mode == "trim":
                mixAudioTracksTrim(audio_files, mixed_audio)
            else:
                # TIMELINE: must cap to base_duration to avoid infinite mix
                mixAudioTracksTimeline(audio_files, mixed_audio, offsets, target_duration=base_duration)

            final_output = workdir / "final_output.mp4"
            muxVideoAudio(final_video_track, mixed_audio, final_output)

            print(f"⬆️ Uploading to {output_gcs_paths[0]}...")
            uploadToGCS(bucket_name, output_gcs_paths[0], final_output, client)
            uploaded_outputs.append(output_gcs_paths[0])
            primary_output_path = final_output

        # Strategy B: Separate Outputs (N Outputs)
        else:
            for i, out_gcs_path in enumerate(output_gcs_paths):
                final_output = workdir / f"final_output_{i}.mp4"

                if render_mode == "trim":
                    muxVideoAudio(final_video_track, audio_files[i], final_output)
                else:
                    muxVideoWithTimelineAudio(final_video_track, audio_files[i], start_times[i], final_output)

                print(f"⬆️ Uploading variation {i} to {out_gcs_path}...")
                uploadToGCS(bucket_name, out_gcs_path, final_output, client)
                uploaded_outputs.append(out_gcs_path)

                if i == 0:
                    primary_output_path = final_output

    except Exception as e:
        raise RuntimeError(f"Audio/Mux processing failed: {e}")

    # ---------------------------------------------------------
    # 5. Generate Thumbnail(s)
    # ---------------------------------------------------------
    try:
        print("🖼️ Generating thumbnail...")
        duration = get_video_duration_seconds(str(final_video_track))
        thumb_time = choose_thumbnail_time(duration)

        extract_thumbnail(
            video_path=str(final_video_track),
            output_jpeg=str(thumbnail_path),
            timestamp=thumb_time,
        )

        for out_gcs_path in uploaded_outputs:
            base_name = Path(out_gcs_path).with_suffix("").name
            thumb_gcs_path = f"productions/{base_name}.jpg"
            uploadToGCS(bucket_name, thumb_gcs_path, thumbnail_path, client)

    except Exception as e:
        print(f"⚠️ Thumbnail generation failed: {e}")

    print("✅ Job Complete.")
    return primary_output_path, metadata


# ==========================================
# CLI Wrapper (Testing)
# ==========================================
def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--payload", required=True, help="Path to a JSON payload file (new format)")
    parser.add_argument("--workdir", default="/workspace")

    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.payload).read_text())
        bucket = payload["bucket"]
        inputs = payload["inputs"]
        outputs = payload["outputs"]
        production_type = payload.get("type", "multi_view")
        is_left = bool(payload.get("isLeftHand", False))

        out_path, meta = run_job(
            bucket_name=bucket,
            input_specs=inputs,
            output_gcs_paths=outputs,
            workdir_str=args.workdir,
            production_type=production_type,
            is_left_hand=is_left,
        )
        # print(json.dumps(meta))
        return 0
    except Exception as e:
        print(f"❌ Critical Failure: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
