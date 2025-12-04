#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

PAD_COLOR = "0x5762FF"

SCRIPT_DIR = Path(__file__).resolve().parent
LOGO = SCRIPT_DIR.parent / "assets" / "reelchains_logo.png"


def run_ffmpeg(cam1, mode1, cam2, mode2, voff1, outname):
    """
    Python port of your original 2-landscape vertical production script.
    Preserves *all* filter logic exactly.
    """

    if not LOGO.exists():
        print(f"❌ Missing logo file at {LOGO}")
        sys.exit(1)

    print("🎬 2-landscape vertical production using amerge + center-mix audio…")
    print(f"📹 CAM1: {cam1} (trim {voff1} s)")
    print(f"📹 CAM2: {cam2}")
    print(f"🎞 OUT:  {outname}")

    filter_complex = f"""
    [0:v]setpts=PTS-STARTPTS,
         crop=iw*0.8:ih:(iw-iw*0.8)/2:0[v0_crop];
    [v0_crop]scale=1080:-2:force_original_aspect_ratio=decrease[v0_scaled];
    [v0_scaled]pad=1080:960:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[v0_top];

    [1:v]setpts=PTS-STARTPTS,
         crop=iw*0.8:ih:(iw-iw*0.8)/2:0[v1_crop];
    [v1_crop]scale=1080:-2:force_original_aspect_ratio=decrease[v1_scaled];
    [v1_scaled]pad=1080:960:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[v1_bottom];

    [v0_top][v1_bottom]vstack=inputs=2[layout];

    [2:v]scale=403.5:60,colorchannelmixer=aa=0.25[logo_scaled];
    [layout][logo_scaled]overlay=main_w-overlay_w-10:main_h-overlay_h-10[final_v];

    [0:a]asetpts=PTS-STARTPTS[a0];
    [1:a]asetpts=PTS-STARTPTS[a1];

    [a0][a1]amerge=inputs=2[stereo_raw];

    [stereo_raw]pan=mono|c0=0.5*c0+0.5*c1[mix_mono];
    [mix_mono]pan=stereo|c0=c0|c1=c0[aout];
    """

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(voff1), "-i", str(cam1),
        "-ss", "0", "-i", str(cam2),
        "-i", str(LOGO),
        "-filter_complex", filter_complex,
        "-map", "[final_v]",
        "-map", "[aout]",
        "-ac", "2",
        "-vsync", "cfr",
        "-r", "30",
            # --- NVENC video encoding ---
        "-map", "[outv]",
        "-map", "[aout]",

        "-c:v", "hevc_nvenc",
        "-preset", "p4",                  # Good speed/quality balance for T4
        "-rc:v", "vbr_hq",                # Quality-focused rate control
        "-b:v", "12M",                    # Reasonable high quality bitrate
        "-pix_fmt", "yuv420p",            # iPhone-compatible

        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(outname),
    ]

    print("➡️ Running ffmpeg (2-landscape)…")
    subprocess.run(cmd, check=True)

    print(f"✅ 2-landscape production created: {outname}")


def main():
    parser = argparse.ArgumentParser(
        description="Python port of 2-landscape vertical production script"
    )
    parser.add_argument("cam1")
    parser.add_argument("mode1")  # consumed but ignored
    parser.add_argument("cam2")
    parser.add_argument("mode2")  # consumed but ignored
    parser.add_argument("offset1", type=float)
    parser.add_argument("outname")

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

    run_ffmpeg(cam1, args.mode1, cam2, args.mode2, args.offset1, outname)


if __name__ == "__main__":
    main()
