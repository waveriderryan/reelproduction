# layouts/mixedThree.py
from pathlib import Path

def buildMixedThreeTwoLandscapeCmd(localPaths, orientations, offsets, outVideo: Path):
    """
    1 portrait + 2 landscape → portrait canvas (1080x1920)
    Portrait on top, two landscapes stacked below.
    """

    # Identify indices
    portrait_idx = orientations.index("portrait")
    landscape_idxs = [i for i, o in enumerate(orientations) if o == "landscape"]

    if len(landscape_idxs) != 2:
        raise ValueError("buildMixedThreeCmd requires exactly 1 portrait and 2 landscape inputs")

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x5762FF"

    CANVAS_W = 1080
    CANVAS_H = 1920

    TOP_H = 960
    BOT_H = (CANVAS_H - TOP_H) // 2  # 480 each

    CROP_LAND = 0.80  # same as threeLandscape

    filtergraph = (
        # --- Portrait hero ---
        f"[{portrait_idx}:v]setpts=PTS-STARTPTS,"
        f"scale={CANVAS_W}:{TOP_H}:force_original_aspect_ratio=decrease,"
        f"pad={CANVAS_W}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[top];"

        # --- Landscape 1 ---
        f"[{landscape_idxs[0]}:v]setpts=PTS-STARTPTS,"
        f"crop=in_w*{CROP_LAND}:in_h:(in_w-in_w*{CROP_LAND})/2:0,"
        f"scale={CANVAS_W}:-2:force_original_aspect_ratio=decrease,"
        f"pad={CANVAS_W}:{BOT_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[b0];"

        # --- Landscape 2 ---
        f"[{landscape_idxs[1]}:v]setpts=PTS-STARTPTS,"
        f"crop=in_w*{CROP_LAND}:in_h:(in_w-in_w*{CROP_LAND})/2:0,"
        f"scale={CANVAS_W}:-2:force_original_aspect_ratio=decrease,"
        f"pad={CANVAS_W}:{BOT_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[b1];"

        # --- Stack ---
        "[b0][b1]vstack=inputs=2[bottom];"
        "[top][bottom]vstack=inputs=2[stacked];"

        # --- Logo ---
        f"[3:v]scale=iw*0.20:-1:force_original_aspect_ratio=decrease,format=rgba[logo];"
        "[logo]lut=a='val*0.25'[logo_half];"
        "[stacked][logo_half]overlay=(W-w)-48:(H-h)-48[outv]"
    )

    return [
        "ffmpeg", "-y",

        # Inputs (offsets respected exactly)
        "-ss", f"{offsets[0]}", "-i", str(localPaths[0]),
        "-ss", f"{offsets[1]}", "-i", str(localPaths[1]),
        "-ss", f"{offsets[2]}", "-i", str(localPaths[2]),

        "-i", LOGO,

        "-filter_complex", filtergraph,
        "-map", "[outv]",

        # Encoding — same family as your others
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
