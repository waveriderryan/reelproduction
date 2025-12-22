from pathlib import Path

def buildMixedFourTwoLandscapeCmd(localPaths, offsets, outVideo: Path):
    """
    2 landscape (top stacked) + 2 portrait (bottom side-by-side)
    Portrait canvas: 1080x1920
    """

    l1, l2, p1, p2 = localPaths
    o1, o2, o3, o4 = offsets

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x5762FF"

    CANVAS_W = 1080
    CANVAS_H = 1920

    TOP_H = 520
    BOTTOM_H = CANVAS_H - (TOP_H * 2)
    PORT_W = CANVAS_W // 2

    LAND_CROP = 0.50  # aggressive vertical crop

    filtergraph = f"""
        [0:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{LAND_CROP}:0:(in_h-in_h*{LAND_CROP})/2,
             scale={CANVAS_W}:{TOP_H}:force_original_aspect_ratio=decrease,
             pad={CANVAS_W}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[l0];

        [1:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{LAND_CROP}:0:(in_h-in_h*{LAND_CROP})/2,
             scale={CANVAS_W}:{TOP_H}:force_original_aspect_ratio=decrease,
             pad={CANVAS_W}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[l1];

        [2:v]setpts=PTS-STARTPTS,
             scale={PORT_W}:{BOTTOM_H}:force_original_aspect_ratio=decrease,
             pad={PORT_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[p0];

        [3:v]setpts=PTS-STARTPTS,
             scale={PORT_W}:{BOTTOM_H}:force_original_aspect_ratio=decrease,
             pad={PORT_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[p1];

        [l0][l1]vstack=inputs=2[top];
        [p0][p1]hstack=inputs=2[bottom];

        [top][bottom]vstack=inputs=2[stacked];

        [4:v]scale=trunc({CANVAS_W}*0.20):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.25'[logo_half];

        [stacked][logo_half]overlay=(W-w)-40:(H-h)-40[outv]
    """

    return [
        "ffmpeg", "-y",

        "-ss", f"{o1}", "-i", str(l1),
        "-ss", f"{o2}", "-i", str(l2),
        "-ss", f"{o3}", "-i", str(p1),
        "-ss", f"{o4}", "-i", str(p2),
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
