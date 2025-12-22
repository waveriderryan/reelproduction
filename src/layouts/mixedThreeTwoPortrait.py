# layouts/mixedThreeTwoPortrait.py
from pathlib import Path


def buildMixedThreeTwoPortraitCmd(localPaths, orientations, offsets, outVideo: Path):
    """
    2 portrait + 1 landscape → portrait canvas (1080x1920)
    Portraits side-by-side on top, landscape full-width on bottom.
    """

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x5762FF"

    CANVAS_W = 1080
    CANVAS_H = 1920

    TOP_H = CANVAS_H // 2        # 960
    BOTTOM_H = CANVAS_H // 2     # 960
    TOP_W_EACH = CANVAS_W // 2   # 540

    # Identify indices
    portrait_idxs = [i for i, o in enumerate(orientations) if o == "portrait"]
    landscape_idx = orientations.index("landscape")

    if len(portrait_idxs) != 2:
        raise ValueError("mixedThreeTwoPortrait requires exactly 2 portrait inputs")

    p0, p1 = portrait_idxs
    l0 = landscape_idx

    off_p0, off_p1, off_l0 = offsets

    filtergraph = f"""
        [{p0}:v]setpts=PTS-STARTPTS,
            scale={TOP_W_EACH}:{TOP_H}:force_original_aspect_ratio=decrease,
            pad={TOP_W_EACH}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[p0];

        [{p1}:v]setpts=PTS-STARTPTS,
            scale={TOP_W_EACH}:{TOP_H}:force_original_aspect_ratio=decrease,
            pad={TOP_W_EACH}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[p1];

        [p0][p1]hstack=inputs=2[top];

        [{l0}:v]setpts=PTS-STARTPTS,
            scale={CANVAS_W}:{BOTTOM_H}:force_original_aspect_ratio=decrease,
            pad={CANVAS_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[bottom];

        [top][bottom]vstack=inputs=2[stacked];

        [3:v]scale=iw*0.20:-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.25'[logo_half];

        [stacked][logo_half]overlay=(W-w)-48:(H-h)-48:format=auto[outv]
    """

    return [
        "ffmpeg", "-y",

        "-ss", f"{off_p0}", "-i", str(localPaths[p0]),
        "-ss", f"{off_p1}", "-i", str(localPaths[p1]),
        "-ss", f"{off_l0}", "-i", str(localPaths[l0]),

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
