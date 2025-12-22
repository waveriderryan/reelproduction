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
from layouts.mixedThreeTwoLandscape import buildMixedThreeTwoLandscapeCmd
from layouts.mixedThreeTwoPortrait import buildMixedThreeTwoPortraitCmd
from layouts.fourLandscape import buildFourLandscapeCmd
from layouts.fourPortrait import buildFourPortraitCmd
from layouts.mixedFourOneLandscape import buildMixedFourOneLandscapeCmd
from layouts.mixedFourOnePortrait import buildMixedFourOnePortraitCmd
from layouts.mixedFourTwoLandscape import buildMixedFourTwoLandscapeCmd


def run(cmd: list):
    print("➡️", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}")


def renderFinalVideo(localPaths, orientations, offsets, outVideo: Path):
    n = len(localPaths)

    if n == 2:
        mode1, mode2 = orientations
        if mode1 == "portrait" and mode2 == "portrait":
            cmd = buildTwoPortraitCmd(localPaths, offsets, outVideo)
        elif mode1 == "landscape" and mode2 == "landscape":
            cmd = buildTwoLandscapeCmd(localPaths, offsets, outVideo)
        else:
            cmd = buildMixedTwoCmd(localPaths, orientations, offsets, outVideo)

    elif n == 3:
        p = orientations.count("portrait")
        l = orientations.count("landscape")

        if p == 3:
            cmd = buildThreePortraitCmd(...)
        elif l == 3:
            cmd = buildThreeLandscapeCmd(...)
        elif p == 1 and l == 2:
            cmd = buildMixedThreeTwoLandscapeCmd(...)
        elif p == 2 and l == 1:
            cmd = buildMixedThreeTwoPortraitCmd(...)
        else:
            raise ValueError("Unsupported orientation mix")
        
        # 3 portrait or 3 landscape only (for now)
        # if all(m == "portrait" for m in orientations):
        #     cmd = buildThreePortraitCmd(localPaths, offsets, outVideo)
        # elif all(m == "landscape" for m in orientations):
        #     cmd = buildThreeLandscapeCmd(localPaths, offsets, outVideo)
        # else:
        #     raise NotImplementedError("Mixed 3-input layout not implemented.")
    elif n == 4:
            portraits, landscapes = count_orientations(orientations)

            if portraits == 4:
                cmd = buildFourPortraitCmd(localPaths, offsets, outVideo)

            elif landscapes == 4:
                cmd = buildFourLandscapeCmd(localPaths, offsets, outVideo)

            elif portraits == 1 and landscapes == 3:
                cmd = buildMixedFourOnePortraitCmd(localPaths, orientations, offsets, outVideo)

            elif portraits == 3 and landscapes == 1:
                cmd = buildMixedFourOneLandscapeCmd(localPaths, orientations, offsets, outVideo)

            elif portraits == 2 and landscapes == 2:
                cmd = buildMixedFourTwoLandscapeCmd(localPaths, orientations, offsets, outVideo)

            else:
                raise NotImplementedError("Unsupported 4-input orientation mix.")

    else:
        raise ValueError("Invalid number of inputs.")


    def count_orientations(orientations):
        portraits = sum(1 for o in orientations if o == "portrait")
        landscapes = sum(1 for o in orientations if o == "landscape")
        return portraits, landscapes

    run(cmd)
