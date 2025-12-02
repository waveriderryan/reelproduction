#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

# Resolve layout scripts
BASE = Path(__file__).resolve().parent
PORTRAIT_SCRIPT = BASE / "generate2Portrait.py"
LANDSCAPE_SCRIPT = BASE / "generate2Landscape.py"
MIXED_SCRIPT = BASE / "generateMixedPortraitLandscape.py"


def run_layout(layout_type, clip1, clip2, mode1, mode2, offset1, combined_path):
    """
    Calls the correct layout script based on orientation.
    """

    if layout_type == "portrait":
        print("🎬 Using 2-portrait layout…")
        cmd = [
            sys.executable,
            str(PORTRAIT_SCRIPT),
            str(clip1),
            str(clip2),
            str(offset1),
            str(combined_path),
        ]

    elif layout_type == "landscape":
        print("🎬 Using 2-landscape layout…")
        # Must pass MODE1/MODE2 because the script signature expects them, even though it ignores them.
        cmd = [
            sys.executable,
            str(LANDSCAPE_SCRIPT),
            str(clip1),
            "landscape",
            str(clip2),
            "landscape",
            str(offset1),
            str(combined_path),
        ]

    else:  # mixed
        print("🎬 Using mixed portrait/landscape layout…")
        cmd = [
            sys.executable,
            str(MIXED_SCRIPT),
            str(clip1),
            mode1,
            str(clip2),
            mode2,
            str(offset1),
            str(combined_path),
        ]

    print("➡️ Running layout command:")
    print("   " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def make_output_with_audio(combined_video, audio_source, out_path):
    """
    Takes the combined stacked video and swaps in audio from one source.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(combined_video),
        "-i", str(audio_source),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path),
    ]

    print(f"🎧 Building output with audio from {audio_source}")
    print("   →", out_path)

    subprocess.run(cmd, check=True)


def determine_layout(mode1, mode2):
    """
    Returns 'portrait', 'landscape', or 'mixed'
    """
    mode1 = mode1.lower().strip()
    mode2 = mode2.lower().strip()

    if mode1 == "portrait" and mode2 == "portrait":
        return "portrait"
    if mode1 == "landscape" and mode2 == "landscape":
        return "landscape"
    return "mixed"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Unified 2-input production job (portrait, landscape, or mixed)."
    )

    parser.add_argument(
        "--mode",
        choices=["single", "multi"],
        default="single",
        help="single = one merged output, multi = one output per input with separate audio",
    )

    parser.add_argument(
        "--inputs",
        nargs=2,
        required=True,
        help="Two input video paths (CLIP1 CLIP2) in the order they started.",
    )

    parser.add_argument(
        "--orientations",
        nargs=2,
        required=True,
        help="Two orientations: portrait|landscape portrait|landscape",
    )

    parser.add_argument(
        "--offset1",
        type=float,
        default=0.0,
        help="Seconds to trim from the first clip (CLIP1 started earlier).",
    )

    parser.add_argument(
        "--output",
        help="Output file for --mode single.",
    )

    parser.add_argument(
        "--outputs",
        nargs=2,
        help="Two output files for --mode multi.",
    )

    args = parser.parse_args(argv)

    clip1 = Path(args.inputs[0]).resolve()
    clip2 = Path(args.inputs[1]).resolve()
    mode1 = args.orientations[0]
    mode2 = args.orientations[1]

    if not clip1.exists():
        print(f"❌ CLIP1 not found: {clip1}")
        sys.exit(1)
    if not clip2.exists():
        print(f"❌ CLIP2 not found: {clip2}")
        sys.exit(1)

    layout_type = determine_layout(mode1, mode2)
    print(f"📐 Layout detected: {layout_type}")

    combined = clip1.parent / "combined_temp.mp4"

    # Generate combined stacked/watermarked video
    run_layout(layout_type, clip1, clip2, mode1, mode2, args.offset1, combined)

    # ----------------------------------------------------------------------
    # SINGLE OUTPUT MODE
    # ----------------------------------------------------------------------
    if args.mode == "single":
        if not args.output:
            print("❌ --output is required for single mode")
            sys.exit(1)

        final_out = Path(args.output).resolve()
        final_out.parent.mkdir(parents=True, exist_ok=True)

        print(f"📦 Single-output mode: copying combined → {final_out}")
        final_out.write_bytes(combined.read_bytes())
        print(f"✅ Single-output job complete: {final_out}")
        return 0

    # ----------------------------------------------------------------------
    # MULTI-OUTPUT MODE
    # ----------------------------------------------------------------------
    if args.mode == "multi":
        if not args.outputs or len(args.outputs) != 2:
            print("❌ --outputs must provide exactly two paths in multi mode.")
            sys.exit(1)

        out1 = Path(args.outputs[0]).resolve()
        out2 = Path(args.outputs[1]).resolve()

        out1.parent.mkdir(parents=True, exist_ok=True)
        out2.parent.mkdir(parents=True, exist_ok=True)

        # Output 1 uses audio from CLIP1
        make_output_with_audio(combined, clip1, out1)

        # Output 2 uses audio from CLIP2
        make_output_with_audio(combined, clip2, out2)

        print("✅ Multi-output job complete:")
        print("   →", out1)
        print("   →", out2)

        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
