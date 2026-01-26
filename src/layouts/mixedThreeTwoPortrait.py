from pathlib import Path


def buildMixedThreeTwoPortraitCmd(
    localPaths,
    orientations,
    startTimes,
    baseDuration,
    outVideo: Path,
):
    """
    2 portrait + 1 landscape → portrait canvas (1080x1920)
    Timeline-based (drop-in) rendering.
    """

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x000000"

    CANVAS_W = 1080
    CANVAS_H = 1920

    TOP_H = CANVAS_H // 2        # 960
    BOTTOM_H = CANVAS_H // 2     # 960
    TOP_W_EACH = CANVAS_W // 2   # 540

    LOGO_SCALE = 0.30
    LOGO_ALPHA = 0.40
    LOGO_PAD = 48

    # Identify indices
    portrait_idxs = [i for i, o in enumerate(orientations) if o == "portrait"]
    landscape_idx = orientations.index("landscape")

    if len(portrait_idxs) != 2:
        raise ValueError("mixedThreeTwoPortrait requires exactly 2 portrait inputs")

    p0, p1 = portrait_idxs
    l0 = landscape_idx

    t_p0 = float(startTimes[p0])
    t_p1 = float(startTimes[p1])
    t_l0 = float(startTimes[l0])
    
    filtergraph = f"""
        color=c=black:s={CANVAS_W}x{CANVAS_H}:d={baseDuration}[base];

        [{p0}:v]setpts=PTS-STARTPTS+{t_p0}/TB,
            scale={TOP_W_EACH}:{TOP_H}:force_original_aspect_ratio=decrease,
            pad={TOP_W_EACH}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD}
            [p0v];

        [{p1}:v]setpts=PTS-STARTPTS+{t_p1}/TB,
            scale={TOP_W_EACH}:{TOP_H}:force_original_aspect_ratio=decrease,
            pad={TOP_W_EACH}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD}
            [p1v];

        [p0v][p1v]hstack=inputs=2[top];

        [{l0}:v]setpts=PTS-STARTPTS+{t_l0}/TB,
            scale={CANVAS_W}:{BOTTOM_H}:force_original_aspect_ratio=decrease,
            pad={CANVAS_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD}
            [bottom];

        [top][bottom]vstack=inputs=2[layout];
        [base][layout]overlay=0:0:eof_action=pass[bg];

        [3:v]scale=trunc({CANVAS_W}*{LOGO_SCALE}):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*{LOGO_ALPHA}'[logo_half];

        [bg][logo_half]overlay=(W-w)-{LOGO_PAD}:(H-h)-{LOGO_PAD}:format=auto[outv]
    """

    return [
        "ffmpeg", "-y",

        "-i", str(localPaths[0]),
        "-i", str(localPaths[1]),
        "-i", str(localPaths[2]),
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
