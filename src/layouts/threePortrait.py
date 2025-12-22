# layouts/threePortrait.py
from pathlib import Path

def buildThreePortraitCmd(localPaths, offsets, outVideo: Path):
    """
    3 portrait cameras → side-by-side on a landscape 1920x1080 canvas.
    Uses offsets EXACTLY as provided, no calculations.
    """

    clip1, clip2, clip3 = localPaths
    off1, off2, off3 = offsets

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x5762FF"

    CANVAS_W = 1920
    CANVAS_H = 1080

    TILE_W = CANVAS_W // 3   # 640 each
    TILE_H = CANVAS_H

    CROP = 0.90  # mild vertical crop to remove iPhone safe area

    filtergraph = f"""
        [0:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:-2:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v0];

        [1:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:-2:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v1];

        [2:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:-2:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v2];

        [v0][v1][v2]hstack=inputs=3[stacked];

        [3:v]scale=trunc({CANVAS_W}*0.20):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.25'[logo_half];

        [stacked][logo_half]overlay=(W-w)-48:(H-h)-48:format=auto[outv]
    """

    return [
        "ffmpeg", "-y",

        "-ss", f"{off1}", "-i", str(clip1),
        "-ss", f"{off2}", "-i", str(clip2),
        "-ss", f"{off3}", "-i", str(clip3),

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
