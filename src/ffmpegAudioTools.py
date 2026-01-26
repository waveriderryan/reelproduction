#!/usr/bin/env python3
"""
Audio helpers: extract, mix, mux.
Now offset-aware and timestamp-safe.
"""

import subprocess
from pathlib import Path


def run(cmd: list):
    print("➡️", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}")


# --------------------------------------------------------------
#  FIXED: Offset-aware audio extraction + timestamp reset
# --------------------------------------------------------------
def extractAudioTrimmed(inVideo: Path, outAudio: Path, offset: float):
    """
    Extracts the audio track, honoring clip offset.
    Matches the sync behavior of your original bash script.

    offset == seconds to trim from this camera.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{offset}",     # apply same trim as VIDEO
        "-i", str(inVideo),
        "-vn",
        "-af", "asetpts=PTS-STARTPTS",  # reset timestamps
        "-acodec", "aac",
        "-b:a", "192k",
        str(outAudio),
    ]
    run(cmd)

# --------------------------------------------------------------
# TIMELINE MODE: Raw audio extraction (no trim, no PTS reset)
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
        "-acodec", "aac",
        "-b:a", "192k",
        str(outAudio),
    ]
    run(cmd)

# --------------------------------------------------------------
# Mixing multiple audio streams (unchanged)
# --------------------------------------------------------------
def mixAudioTracksTrim(audioList, outAudio: Path):
    # Build amix command
    inputs = []
    maps = []
    for a in audioList:
        inputs += ["-i", str(a)]
        maps.append(f"[{len(maps)}:a]")

    amix = f"{''.join(maps)}amix=inputs={len(audioList)}:duration=longest[aout]"

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
):
    """
    Mixes audio tracks by placing them on a global timeline.
    Offsets are in seconds.
    """

    assert len(audio_files) == len(offsets)

    inputs = []
    filter_parts = []

    for i, audio_file in enumerate(audio_files):
        inputs += ["-i", str(audio_file)]

        delay_ms = int(offsets[i] * 1000)

        # stereo-safe delay: left|right
        filter_parts.append(
            f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]"
        )

    mix_inputs = "".join(f"[a{i}]" for i in range(len(audio_files)))

    # filter_complex = (
    #     "; ".join(filter_parts)
    #     + f"; {mix_inputs}amix=inputs={len(audio_files)}:normalize=0"
    filter_complex = (
    "; ".join(filter_parts)
    + f"; {mix_inputs}amix=inputs={len(audio_files)}:normalize=0:duration=shortest"
)
    )

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-acodec", "aac",
        "-b:a", "192k",
        str(outAudio),
    ]
    run(cmd)

# --------------------------------------------------------------
# Video + Audio mux (unchanged)
# --------------------------------------------------------------
def muxVideoAudio(inVideo: Path, inAudio: Path, outFile: Path):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(inVideo),
        "-i", str(inAudio),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac",
        "-movflags", "+faststart",
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
        f"[1:a]adelay={delay_ms}|{delay_ms}[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        str(out_path),
    ]
    run(cmd)
