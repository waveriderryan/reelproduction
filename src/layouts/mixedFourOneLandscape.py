from pathlib import Path

def buildMixedFourOneLandscapeCmd(localPaths, offsets, outVideo: Path):
    """
    3 portrait + 1 landscape on a PORTRAIT canvas (1080x1920)

    Layout:
    -------------------------
    |      portrait A      |
    -------------------------
    |      portrait B      |
    -------------------------
    |      portrait C      |
    -------------------------
    | landscape (cropped)  |
    -------------------------
    """

    clipA, clipB, clipC, clipD = localPaths
    offA, offB, offC, offD = offsets

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x5762FF"

    CANVAS_W = 1080
    CANVAS_H = 1920

    TILE_W = CANVAS_W
    TILE_H = CANVAS_H // 4   # 480 each

    # Landscape crop factor (heavy crop, intentional)
    LAND_CROP = 0.50

    filtergraph = f"""
        [0:v]setpts=PTS-STARTPTS,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[p0];

        [1:v]setpts=PTS-STARTPTS,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[p1];

        [2:v]setpts=PTS-STARTPTS,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[p2];

        [3:v]setpts=PTS-STARTPTS,
             crop=in_w*{LAND_CROP}:in_h:(in_w-in_w*{LAND_CROP})/2:0,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[l0];

        [p0][p1][p2][l0]vstack=inputs=4[bg];

        [4:v]scale=trunc({CANVAS_W}*0.22):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.30'[logo_half];

        [bg][logo_half]overlay=(W-w)-40:(H-h)-40[outv]
    """

    return [
        "ffmpeg", "-y",

        "-ss", f"{offA}", "-i", str(clipA),
        "-ss", f"{offB}", "-i", str(clipB),
        "-ss", f"{offC}", "-i", str(clipC),
        "-ss", f"{offD}", "-i", str(clipD),

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
