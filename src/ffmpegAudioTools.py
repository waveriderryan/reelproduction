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
def extractAudioTrack(inVideo: Path, outAudio: Path, offset: float):
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
# Mixing multiple audio streams (unchanged)
# --------------------------------------------------------------
def mixAudioTracks(audioList, outAudio: Path):
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
