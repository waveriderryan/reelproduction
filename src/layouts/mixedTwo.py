from pathlib import Path
import subprocess


def buildMixedTwoCmd(
    localPaths,
    orientations,
    startTimes,      # <-- NEW: timeline start times (seconds)
    baseDuration,    # <-- NEW: total timeline duration (seconds)
    outVideo: Path,
):
    clip1, clip2 = localPaths

    LOGO = "/app/assets/reelchains_logo.png"
    PAD_COLOR = "0x000000"

    TARGET_W = 1080
    TOP_H = 1280
    BOTTOM_H = 640

    # Identify which clip is portrait vs landscape
    if orientations[0] == "portrait":
        portrait_idx = 0
        landscape_idx = 1
    else:
        portrait_idx = 1
        landscape_idx = 0

    portrait_start = float(startTimes[portrait_idx])
    landscape_start = float(startTimes[landscape_idx])

    portrait_v = f"[{portrait_idx}:v]"
    landscape_v = f"[{landscape_idx}:v]"

    filtergraph = f"""
        color=c=black:s={TARGET_W}x{TOP_H + BOTTOM_H}:d={baseDuration}:rate=30000/1001[base];

        {portrait_v}
            setpts=PTS-STARTPTS+{portrait_start}/TB,
            scale={TARGET_W}:{TOP_H}:force_original_aspect_ratio=decrease,
            pad={TARGET_W}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}
            [top];

        {landscape_v}
            setpts=PTS-STARTPTS+{landscape_start}/TB,
            scale={TARGET_W}:{BOTTOM_H}:force_original_aspect_ratio=decrease,
            pad={TARGET_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}
            [bottom];

        [top][bottom]vstack=inputs=2, setpts=PTS-STARTPTS[layout];

        [base][layout]overlay=0:0:eof_action=pass:shortest=1[bg];

        [2:v]scale=iw*0.30:-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.50'[logo_half];

        [bg][logo_half]overlay=(W-w)-40:(H-h)-40[outv]
    """


    return [
        "ffmpeg", "-y",

        "-i", str(clip1),
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
