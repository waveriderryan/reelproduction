#!/usr/bin/env python3
"""
Audio helpers: extract, mix, mux.
Offset-aware and timeline-safe.
"""

import subprocess
from pathlib import Path


def run(cmd: list):
    print("➡️", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}")


# --------------------------------------------------------------
# TRIM MODE: Offset-aware audio extraction + timestamp reset
# --------------------------------------------------------------
def extractAudioTrimmed(inVideo: Path, outAudio: Path, offset: float):
    """
    Extracts the audio track, honoring clip offset.
    offset == seconds to trim from this camera.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{offset}",
        "-i", str(inVideo),
        "-vn",
        "-af", "asetpts=PTS-STARTPTS",
        "-c:a", "aac",
        "-b:a", "192k",
        str(outAudio),
    ]
    run(cmd)


# --------------------------------------------------------------
# TIMELINE MODE: Raw audio extraction (no trim). We reset PTS so
# adelay/mix is deterministic even if the container has odd PTS.
# --------------------------------------------------------------
def extractAudioUntrimmed(inVideo: Path, outAudio: Path):
    """
    Extracts full audio track without trimming.
    Offsets will be applied later via adelay.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(inVideo),
        "-vn",
        "-af", "asetpts=PTS-STARTPTS",
        "-c:a", "aac",
        "-b:a", "192k",
        str(outAudio),
    ]
    run(cmd)


# --------------------------------------------------------------
# TRIM MODE: Mix multiple already-trimmed audio streams
# --------------------------------------------------------------
def mixAudioTracksTrim(audioList, outAudio: Path):
    inputs = []
    maps = []
    for a in audioList:
        inputs += ["-i", str(a)]
        maps.append(f"[{len(maps)}:a]")

    # Use longest so we don't accidentally truncate when one track is shorter
    amix = f"{''.join(maps)}amix=inputs={len(audioList)}:duration=longest:normalize=0[aout]"

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex", amix,
        "-map", "[aout]",
        "-c:a", "aac",
        "-b:a", "192k",
        str(outAudio),
    ]
    run(cmd)


# --------------------------------------------------------------
# TIMELINE MODE: Offset-based audio mixing using adelay
# --------------------------------------------------------------
def mixAudioTracksTimeline(
    audio_files: list[Path],
    outAudio: Path,
    offsets: list[float],
    target_duration: float | None = None,
):
    """
    Mixes audio tracks by placing them on a global timeline.
    Offsets are in seconds (>=0). Uses adelay + apad + amix=longest.

    If target_duration is provided, trims mixed audio to exactly that duration.
    """
    assert len(audio_files) == len(offsets)

    inputs: list[str] = []
    filter_parts: list[str] = []

    for i, audio_file in enumerate(audio_files):
        inputs += ["-i", str(audio_file)]

        delay_ms = max(0, int(offsets[i] * 1000))

        # stereo-safe delay: left|right
        # apad prevents amix from terminating early when streams start late
        filter_parts.append(
            f"[{i}:a]adelay={delay_ms}|{delay_ms},apad[a{i}]"
        )

    mix_inputs = "".join(f"[a{i}]" for i in range(len(audio_files)))

    # Mix to longest so late-starting streams don't get truncated
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(audio_files)}:normalize=0:duration=longest[aout]"
    )

    out_label = "[aout]"
    if target_duration is not None:
        # Trim to exact timeline duration and reset timestamps
        filter_parts.append(f"[aout]atrim=0:{target_duration},asetpts=PTS-STARTPTS[aout2]")
        out_label = "[aout2]"

    filter_complex = "; ".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", out_label,
        "-c:a", "aac",
        "-b:a", "192k",
        str(outAudio),
    ]
    run(cmd)


# --------------------------------------------------------------
# Video + Audio mux
# --------------------------------------------------------------
def muxVideoAudio(inVideo: Path, inAudio: Path, outFile: Path):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(inVideo),
        "-i", str(inAudio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(outFile),
    ]
    run(cmd)


def muxVideoWithTimelineAudio(
    video_path: Path,
    audio_path: Path,
    start_time: float,
    out_path: Path,
):
    """
    Muxes video with a single audio track placed correctly on the timeline.
    start_time is seconds from timeline start.
    """
    delay_ms = max(0, int(start_time * 1000))

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-filter_complex",
        f"[1:a]adelay={delay_ms}|{delay_ms},apad,asetpts=PTS-STARTPTS[a]",
        "-map", "0:v:0",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(out_path),
    ]
    run(cmd)
