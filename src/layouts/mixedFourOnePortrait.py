from pathlib import Path

def buildMixedFourOnePortraitCmd(localPaths, offsets, outVideo: Path):
    """
    3 landscape + 1 portrait on a LANDSCAPE canvas (1920x1080)

    Layout:
    -------------------------------------------------
    |  landscape A            |  landscape B       |
    -------------------------------------------------
    |  landscape C            |  portrait D        |
    -------------------------------------------------
    """

    clipA, clipB, clipC, clipD = localPaths
    offA, offB, offC, offD = offsets

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x5762FF"

    CANVAS_W = 1920
    CANVAS_H = 1080

    CELL_W = CANVAS_W // 2        # 960
    CELL_H = CANVAS_H // 2        # 540

    PORTRAIT_W = int(CELL_W * 0.75)
    PORTRAIT_H = CELL_H

    filtergraph = f"""
        [0:v]setpts=PTS-STARTPTS,
             scale={CELL_W}:{CELL_H}:force_original_aspect_ratio=decrease,
             pad={CELL_W}:{CELL_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[a];

        [1:v]setpts=PTS-STARTPTS,
             scale={CELL_W}:{CELL_H}:force_original_aspect_ratio=decrease,
             pad={CELL_W}:{CELL_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[b];

        [2:v]setpts=PTS-STARTPTS,
             scale={CELL_W}:{CELL_H}:force_original_aspect_ratio=decrease,
             pad={CELL_W}:{CELL_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[c];

        [3:v]setpts=PTS-STARTPTS,
            crop=in_w:in_h*0.50:0:(in_h-in_h*0.50)/2,
            scale={CELL_W}:{CELL_H}:force_original_aspect_ratio=decrease,
            pad={CELL_W}:{CELL_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[l0];
            
        [a][b]hstack=inputs=2[top];
        [c][d]hstack=inputs=2[bottom];

        [top][bottom]vstack=inputs=2[bg];

        [4:v]scale=trunc({CANVAS_W}*0.18):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.35'[logo_half];

        [bg][logo_half]overlay=(W-w)-48:(H-h)-48[outv]
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
