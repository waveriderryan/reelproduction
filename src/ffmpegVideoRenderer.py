#!/usr/bin/env python3
"""
ffmpegVideoRender.py

Renders the CANONICAL final video layout (video-only).
Uses NVENC for CUDA performance.

This file delegates layout logic to:
  layouts/twoPortrait.py
  layouts/twoLandscape.py
  layouts/mixedTwo.py
  layouts/threePortrait.py
  layouts/threeLandscape.py
"""

from pathlib import Path
import subprocess
import sys

from layouts.twoPortrait import buildTwoPortraitCmd
from layouts.twoLandscape import buildTwoLandscapeCmd
from layouts.mixedTwo import buildMixedTwoCmd
from layouts.threePortrait import buildThreePortraitCmd
from layouts.threeLandscape import buildThreeLandscapeCmd


def run(cmd: list):
    print("➡️", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}")


def renderFinalVideoOLD(localPaths, orientations, offsets, outVideo: Path, startTimes, baseDuration):
    n = len(localPaths)

    if n == 2:
        mode1, mode2 = orientations
        if mode1 == "portrait" and mode2 == "portrait":
            cmd = buildTwoPortraitCmd(localPaths, startTimes, baseDuration, outVideo)
        elif mode1 == "landscape" and mode2 == "landscape":
            cmd = buildTwoLandscapeCmd(localPaths, offsets, outVideo)
        else:
            cmd = buildMixedTwoCmd(localPaths, orientations, offsets, outVideo)

    elif n == 3:
        # 3 portrait or 3 landscape only (for now)
        if all(m == "portrait" for m in orientations):
            cmd = buildThreePortraitCmd(localPaths, offsets, outVideo)
        elif all(m == "landscape" for m in orientations):
            cmd = buildThreeLandscapeCmd(localPaths, offsets, outVideo)
        else:
            raise NotImplementedError("Mixed 3-input layout not implemented.")

    else:
        raise ValueError("Invalid number of inputs.")

    run(cmd)
