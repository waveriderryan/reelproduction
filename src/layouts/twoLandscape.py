# layouts/twoLandscape.py
from pathlib import Path

def buildTwoLandscapeCmd(localPaths, startTimes, outVideo: Path, baseDuration):
    """
    2-landscape TIMELINE layout:
      - Portrait canvas (1080x1920)
      - Landscape clips stacked vertically
      - Clips appear at their startTimes
      - No input trimming (-ss)
      - Fixed base duration to prevent infinite render
    """

    clip1, clip2 = localPaths
    t0, t1 = startTimes

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x000000"

    CANVAS_W = 1080
    CANVAS_H = 1400
    TILE_H = CANVAS_H // 2  # 960 each

    CROP_FACTOR = 0.80

    filtergraph = f"""
        color=c=black:s={CANVAS_W}x{CANVAS_H}:d={baseDuration}[base];

        [0:v]setpts=PTS-STARTPTS+{t0}/TB,
             crop=in_w*{CROP_FACTOR}:in_h:(in_w-in_w*{CROP_FACTOR})/2:0,
             scale={CANVAS_W}:{TILE_H}:force_original_aspect_ratio=increase,
             crop={CANVAS_W}:{TILE_H},
             format=rgba[v0];

        [1:v]setpts=PTS-STARTPTS+{t1}/TB,
             crop=in_w*{CROP_FACTOR}:in_h:(in_w-in_w*{CROP_FACTOR})/2:0,
             scale={CANVAS_W}:{TILE_H}:force_original_aspect_ratio=increase,
             crop={CANVAS_W}:{TILE_H},
             format=rgba[v1];

        [base][v0]overlay=0:0:eof_action=pass[tmp];
        [tmp][v1]overlay=0:{TILE_H}:eof_action=pass[stacked];

        [2:v]scale=403.5:60:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.25'[logo_half];

        [stacked][logo_half]overlay=(W-w)-10:(H-h)-10[outv]
    """

    return [
        "ffmpeg", "-y",

        "-i", str(clip1),
        "-i", str(clip2),
        "-i", LOGO,

        "-filter_complex", filtergraph,
        "-map", "[outv]",
        "-shortest",

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
