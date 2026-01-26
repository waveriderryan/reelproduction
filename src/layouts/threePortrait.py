# layouts/threePortrait.py
from pathlib import Path

def buildThreePortraitCmd(
    localPaths,
    startTimes,
    baseDuration,
    outVideo: Path,
):
    clip1, clip2, clip3 = localPaths

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x000000"

    CANVAS_W = 1920
    CANVAS_H = 1080

    TILE_W = CANVAS_W // 3   # 640
    TILE_H = CANVAS_H

    CROP = 0.90  # mild vertical crop (same as before)

    t0, t1, t2 = map(float, startTimes)

    filtergraph = f"""
        color=c=black:s={CANVAS_W}x{CANVAS_H}:d={baseDuration}[base];

        [0:v]setpts=PTS-STARTPTS+{t0}/TB,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}
             [v0];

        [1:v]setpts=PTS-STARTPTS+{t1}/TB,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}
             [v1];

        [2:v]setpts=PTS-STARTPTS+{t2}/TB,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}
             [v2];

        [v0][v1][v2]hstack=inputs=3[layout];

        [base][layout]overlay=0:0:eof_action=pass[bg];

        [3:v]scale=trunc({CANVAS_W}*0.20):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.25'[logo_half];

        [bg][logo_half]overlay=(W-w)-48:(H-h)-48:format=auto[outv]
    """

    return [
        "ffmpeg", "-y",

        "-i", str(clip1),
        "-i", str(clip2),
        "-i", str(clip3),
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

