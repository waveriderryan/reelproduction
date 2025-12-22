from pathlib import Path
import subprocess


def get_input_resolution(path: Path):
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "default=nw=1:nk=1",
            str(path),
        ]
        out = subprocess.check_output(cmd).decode().strip().split()
        return tuple(map(int, out))
    except Exception:
        return (1920, 1080)


def compute_rotation_filter(orientation: str, width: int, height: int):
    is_portrait_sensor = (orientation == "portrait")
    is_portrait_pixels = height > width
    is_landscape_pixels = width >= height

    if is_portrait_sensor and is_landscape_pixels:
        return "transpose=clock,"
    if is_portrait_sensor and is_portrait_pixels:
        return ""
    if (orientation == "landscape") and is_portrait_pixels:
        return "transpose=cclock,"
    return ""


def buildMixedTwoCmd(localPaths, orientations, offsets, outVideo: Path):

    clip1, clip2 = localPaths
    off1, _ = offsets

    LOGO = "/app/assets/reelchains_logo.png"
    PAD_COLOR = "0x5762FF"

    TARGET_W = 1080
    TOP_H = 1280
    BOTTOM_H = 640

    if isinstance(off1, (list, tuple)):
        if not off1:
            raise ValueError("Offset list for first clip is empty.")
        off1 = off1[0]
    offset_str = f"{float(off1):.6f}"

    if orientations[0] == "portrait":
        portrait_idx = 0
        landscape_idx = 1
    else:
        portrait_idx = 1
        landscape_idx = 0

    pw, ph = get_input_resolution(localPaths[portrait_idx])
    lw, lh = get_input_resolution(localPaths[landscape_idx])

#    portrait_rot = compute_rotation_filter(orientations[portrait_idx], pw, ph)
#    landscape_rot = compute_rotation_filter(orientations[landscape_idx], lw, lh)

    portrait_v = f"[{portrait_idx}:v]"
    landscape_v = f"[{landscape_idx}:v]"

    filtergraph = (
        f"{portrait_v}"
        f"setpts=PTS-STARTPTS,"
#        f"{portrait_rot}"
        f"scale={TARGET_W}:{TOP_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[top];"

        f"{landscape_v}"
        f"setpts=PTS-STARTPTS,"
#        f"{landscape_rot}"
        f"scale={TARGET_W}:{BOTTOM_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[bottom];"

        f"[top][bottom]vstack=inputs=2[bg];"

        f"[2:v]scale=iw*0.30:-1,format=rgba[logo];"
        f"[logo]lut=a='val*0.50'[logo_half];"
        f"[bg][logo_half]overlay=(W-w)-40:(H-h)-40[outv]"
    )

    cmd = [
        "ffmpeg",
        "-y",

        "-ss", offset_str,
        "-i", str(clip1),

        "-ss", "0",
        "-i", str(clip2),

        "-i", LOGO,

        "-filter_complex", filtergraph,
        "-map", "[outv]",

        "-c:v", "hevc_nvenc",
        "-preset", "p5",
        "-rc", "vbr",
        "-b:v", "5M",
        "-maxrate", "6M",
        "-bufsize", "12M",
        "-g", "60",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-tag:v", "hvc1",
        "-movflags", "+faststart",

        str(outVideo),
    ]

    return cmd
