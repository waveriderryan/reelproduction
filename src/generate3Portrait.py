#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

PAD_COLOR = "0x5762FF"
TILE_W = 1080
TILE_H = 1080
CANVAS_W = TILE_W * 3
CANVAS_H = TILE_H

SCRIPT_DIR = Path(__file__).resolve().parent
LOGO = SCRIPT_DIR.parent / "assets" / "reelchains_logo.png"


def run_ffmpeg(cam1, cam2, cam3, off1, off2, off3, outname: Path):
    if not LOGO.exists():
        print(f"❌ Missing logo file at {LOGO}")
        sys.exit(1)

    print("🎬 3-portrait side-by-side production…")
    print(f"📹 CAM1: {cam1} (trim {off1} s)")
    print(f"📹 CAM2: {cam2} (trim {off2} s)")
    print(f"📹 CAM3: {cam3} (trim {off3} s)")
    print(f"🎞 OUT : {outname}")

    filter_complex = f"""
    #######################################################
    # VIDEO: 3 portrait clips → 3 square tiles → hstack
    #######################################################
    [0:v]setpts=PTS-STARTPTS,
         scale={TILE_W}:-1:force_original_aspect_ratio=decrease,
         crop={TILE_W}:{TILE_H}:(iw-{TILE_W})/2:(ih-{TILE_H})/2[v0];

    [1:v]setpts=PTS-STARTPTS,
         scale={TILE_W}:-1:force_original_aspect_ratio=decrease,
         crop={TILE_W}:{TILE_H}:(iw-{TILE_W})/2:(ih-{TILE_H})/2[v1];

    [2:v]setpts=PTS-STARTPTS,
         scale={TILE_W}:-1:force_original_aspect_ratio=decrease,
         crop={TILE_W}:{TILE_H}:(iw-{TILE_W})/2:(ih-{TILE_H})/2[v2];

    [v0][v1][v2]hstack=inputs=3[stacked];

    # Ensure exact canvas + optional pad (should already be {CANVAS_W}x{CANVAS_H})
    [stacked]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=decrease,
             pad={CANVAS_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[bg];

    #######################################################
    # LOGO bottom-right
    #######################################################
    [3:v]scale=trunc({CANVAS_W}*0.10):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
    [logo]lut=a='val*0.7'[logo_half];
    [bg][logo_half]overlay=(W-w)-48:(H-h)-48,format=yuv420p[outv];

    #######################################################
    # AUDIO: 3-way amix (mono/stereo depending on source)
    #######################################################
    [0:a]aresample=async=1:first_pts=0[a0];
    [1:a]aresample=async=1:first_pts=0[a1];
    [2:a]aresample=async=1:first_pts=0[a2];
    [a0][a1][a2]amix=inputs=3:normalize=0:duration=longest[aout];
    """

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(off1), "-i", str(cam1),
        "-ss", str(off2), "-i", str(cam2),
        "-ss", str(off3), "-i", str(cam3),
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

    print("➡️ Running ffmpeg (3-portrait)…")
    subprocess.run(cmd, check=True)
    print(f"✅ 3-portrait production created: {outname}")


def main():
    parser = argparse.ArgumentParser(
        description="3 portrait inputs → side-by-side landscape canvas."
    )
    parser.add_argument("cam1")
    parser.add_argument("cam2")
    parser.add_argument("cam3")
    parser.add_argument("offset1", type=float, help="Trim seconds for CAM1")
    parser.add_argument("offset2", type=float, help="Trim seconds for CAM2")
    parser.add_argument("offset3", type=float, help="Trim seconds for CAM3")
    parser.add_argument("outname")

    args = parser.parse_args()

    cam1 = Path(args.cam1).resolve()
    cam2 = Path(args.cam2).resolve()
    cam3 = Path(args.cam3).resolve()
    outname = Path(args.outname).resolve()

    for label, p in [("CAM1", cam1), ("CAM2", cam2), ("CAM3", cam3)]:
        if not p.exists():
            print(f"❌ {label} not found: {p}")
            sys.exit(1)

    outname.parent.mkdir(parents=True, exist_ok=True)

    run_ffmpeg(cam1, cam2, cam3, args.offset1, args.offset2, args.offset3, outname)


if __name__ == "__main__":
    main()
