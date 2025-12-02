#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

"""
Python port of generateMixedPortraitLandscape.sh

Usage:
  python3 generate_mixed_portrait_landscape.py \
      CLIP1 MODE1 CLIP2 MODE2 OFFSET1 OUTNAME
"""

# Constants from your script
PAD_COLOR = "0x5762FF"

TARGET_W = 1080
TOP_H = 1200        # portrait zone
BOTTOM_H = 800      # landscape zone

SCRIPT_DIR = Path(__file__).resolve().parent
LOGO = SCRIPT_DIR.parent / "assets" / "reelchains_logo.png"

if not LOGO.exists():
    print(f"❌ Missing watermark logo file at {LOGO}")
    sys.exit(1)

def validate_mode(label: str, mode: str):
    m = mode.lower().strip()
    if m not in ("portrait", "landscape"):
        raise ValueError(f"{label} must be portrait or landscape (got '{mode}')")
    return m


def build_filter(mode1, mode2, voff1):
    """
    Builds the filter_complex string EXACTLY like your shell script.
    """
    # Portrait vs landscape mapping
    if mode1 == "portrait":
        PORTRAIT_V = "[0:v]"
        PORTRAIT_A = "[0:a]"
        LAND_V = "[1:v]"
        LAND_A = "[1:a]"
    else:
        PORTRAIT_V = "[1:v]"
        PORTRAIT_A = "[1:a]"
        LAND_V = "[0:v]"
        LAND_A = "[0:a]"

    # Build the same filter used in the Bash script
    filter_complex = f"""
    {PORTRAIT_V}setpts=PTS-STARTPTS,
         crop=in_w:in_h*0.80:0:(in_h - in_h*0.80)/2,
         scale={TARGET_W}:{TOP_H}:force_original_aspect_ratio=decrease,
         pad={TARGET_W}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[top];

    {LAND_V}setpts=PTS-STARTPTS,
         crop=in_w*0.80:in_h:(in_w - in_w*0.80)/2:0,
         scale={TARGET_W}:-1:force_original_aspect_ratio=decrease,
         pad={TARGET_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[bottom];

    [top][bottom]vstack=inputs=2[bg];

    [2:v]scale=iw*0.30:-1,format=rgba[logo];
    [logo]lut=a='val*0.50'[logo_half];
    [bg][logo_half]overlay=(W-w)-40:(H-h)-40[outv];

    {PORTRAIT_A}aresample=async=1:first_pts=0[a0];
    {LAND_A}aresample=async=1:first_pts=0[a1];
    [a0][a1]amix=inputs=2:normalize=0:duration=longest[aout]
    """
    return filter_complex


def run_ffmpeg(clip1, clip2, mode1, mode2, voff1, outname):
    """
    Executes ffmpeg using the same parameters you had in Bash.
    Uses hevc_videotoolbox for Apple Silicon macOS.
    """

    filter_complex = build_filter(mode1, mode2, voff1)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(offset1), "-i", str(clip1),
        "-ss", "0",           "-i", str(clip2),
        "-i", "/app/assets/reelchains_logo.png",

        "-filter_complex", filter_complex,

        # Apple silicon HEVC hardware encoder:
        # "-c:v", "hevc_videotoolbox",
        # "-tag:v", "hvc1",

        # --- NVENC video encoding ---
        "-map", "[outv]",
        "-map", "[aout]",

        "-c:v", "hevc_nvenc",
        "-preset", "p4",                  # Good speed/quality balance for T4
        "-rc:v", "vbr_hq",                # Quality-focused rate control
        "-b:v", "12M",                    # Reasonable high quality bitrate
        "-pix_fmt", "yuv420p",            # iPhone-compatible

        # Audio
        "-c:a", "aac",
        "-b:a", "192k",

        "-movflags", "+faststart",
        "-r", "30",
        "-fps_mode", "cfr",

        str(outname),
    ]


    print("🎬 Running ffmpeg...")
    print(" ".join(cmd))

    subprocess.run(cmd, check=True)
    print("✅ Mixed layout done!")


def main():
    parser = argparse.ArgumentParser(description="Python version of generateMixedPortraitLandscape.sh")
    parser.add_argument("clip1")
    parser.add_argument("mode1")
    parser.add_argument("clip2")
    parser.add_argument("mode2")
    parser.add_argument("offset1", type=float)
    parser.add_argument("outname")

    args = parser.parse_args()

    clip1 = Path(args.clip1)
    clip2 = Path(args.clip2)
    outname = Path(args.outname)

    if not clip1.exists():
        print(f"❌ CLIP1 not found: {clip1}")
        sys.exit(1)

    if not clip2.exists():
        print(f"❌ CLIP2 not found: {clip2}")
        sys.exit(1)

    # Validate modes
    mode1 = validate_mode("MODE1", args.mode1)
    mode2 = validate_mode("MODE2", args.mode2)

    if mode1 == mode2:
        print("❌ Mixed script called with non-mixed inputs!")
        sys.exit(1)

    # Validate logo
    if not Path(LOGO).exists():
        print(f"❌ Missing watermark logo file: {LOGO}")
        sys.exit(1)

    print("🎬 Mixed portrait+landscape layout (Python version)")
    print(f"➡️ CLIP1 = {clip1} ({mode1}), trim={args.offset1}")
    print(f"➡️ CLIP2 = {clip2} ({mode2})")
    print(f"🎞 Output = {outname}")

    run_ffmpeg(clip1, clip2, mode1, mode2, args.offset1, outname)


if __name__ == "__main__":
    main()
