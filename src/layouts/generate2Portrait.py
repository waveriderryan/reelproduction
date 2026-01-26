#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path

# Constants matching your Bash script
TARGET_W = 1920
TARGET_H = 1080
PAD_COLOR = "0x5762FF"

SCRIPT_DIR = Path(__file__).resolve().parent
LOGO = SCRIPT_DIR.parent / "assets" / "reelchains_logo.png"


def run_ffmpeg(cam1, cam2, voff1, outname):
    # CROP_H_FACTOR env var like in the bash script (default 0.8)
    crop_h_factor_str = os.environ.get("CROP_H_FACTOR", "0.8")
    try:
        crop_h_factor = float(crop_h_factor_str)
    except ValueError:
        print(f"⚠️ Invalid CROP_H_FACTOR='{crop_h_factor_str}', falling back to 0.8")
        crop_h_factor = 0.8

    if not LOGO.exists():
        print(f"❌ Missing logo file at {LOGO}")
        sys.exit(1)

    print("🎬 Building 2-portrait production (height-normalized)…")
    print(f"📹 CAM1: {cam1} (trim {voff1} s)")
    print(f"📹 CAM2: {cam2}")
    print(f"🎞 OUT : {outname}")
    print(f"DEBUG CAM1=<{cam1}>")
    print(f"DEBUG CAM2=<{cam2}>")

    filter_complex = f"""
    [0:v]setpts=PTS-STARTPTS,
         scale=-2:{TARGET_H}:force_original_aspect_ratio=decrease[v0s];
    [1:v]setpts=PTS-STARTPTS,
         scale=-2:{TARGET_H}:force_original_aspect_ratio=decrease[v1s];

    [v0s]crop=iw:ih*{crop_h_factor}:0:(ih-ih*{crop_h_factor})/2[v0c];
    [v1s]crop=iw:ih*{crop_h_factor}:0:(ih-ih*{crop_h_factor})/2[v1c];

    [v0c][v1c]hstack=inputs=2[stacked];

    [stacked]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,
             pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[bg];

    [2:v]scale=trunc({TARGET_W}*0.18):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
    [logo]lut=a='val*0.7'[logo_half];
    [bg][logo_half]overlay=(W-w)-48:(H-h)-48,format=yuv420p[outv];

    [0:a]aresample=async=1:first_pts=0[a0];
    [1:a]aresample=async=1:first_pts=0[a1];
    [a0][a1]amix=inputs=2:normalize=0:duration=longest[aout];
    """

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(voff1), "-i", str(cam1),
        "-i", str(cam2),
        "-i", str(LOGO),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[aout]",
        "-c:v", "hevc_videotoolbox",
        "-tag:v", "hvc1",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(outname),
    ]

    print("➡️ Running ffmpeg (2-portrait)…")
    # print(" ".join(cmd))  # uncomment for full command debug

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"❌ FFmpeg failed with status {result.returncode}")
        sys.exit(result.returncode)
    else:
        print(f"✅ Production video created: {outname}")


def main():
    parser = argparse.ArgumentParser(
        description="Python port of generateProductionFrom2PortraitInputs_logo_sync.sh"
    )
    parser.add_argument("cam1", help="CAM1 path")
    parser.add_argument("cam2", help="CAM2 path")
    parser.add_argument("offset1", type=float, help="Seconds to trim from CAM1")
    parser.add_argument("outname", help="Output filename")

    args = parser.parse_args()

    cam1 = Path(args.cam1).resolve()
    cam2 = Path(args.cam2).resolve()
    outname = Path(args.outname).resolve()

    if not cam1.exists():
        print(f"❌ CAM1 not found: {cam1}")
        sys.exit(1)
    if not cam2.exists():
        print(f"❌ CAM2 not found: {cam2}")
        sys.exit(1)

    outname.parent.mkdir(parents=True, exist_ok=True)

    run_ffmpeg(cam1, cam2, args.offset1, outname)


if __name__ == "__main__":
    main()
