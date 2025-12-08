# layouts/twoLandscape.py
from pathlib import Path

def buildTwoLandscapeCmd(localPaths, offsets, outVideo: Path):
    """
    2-landscape vertical layout:
      - Portrait canvas (1080x1920)
      - Landscape clips stacked vertically
      - Aggressive horizontal crop (80% width)
      - Centered padding left/right
    """

    clip1, clip2 = localPaths
    voff1 = offsets[0]  # only clip1 is trimmed

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x5762FF"

    # Portrait canvas: 1080 wide, 1920 tall
    CANVAS_W = 1080
    TILE_H = 960        # each landscape tile gets half height

    filtergraph = f"""
        [0:v]setpts=PTS-STARTPTS,
             crop=in_w*0.8:in_h:(in_w-in_w*0.8)/2:0,
             scale={CANVAS_W}:-2:force_original_aspect_ratio=decrease,
             pad={CANVAS_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v0];

        [1:v]setpts=PTS-STARTPTS,
             crop=in_w*0.8:in_h:(in_w-in_w*0.8)/2:0,
             scale={CANVAS_W}:-2:force_original_aspect_ratio=decrease,
             pad={CANVAS_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v1];

        [v0][v1]vstack=inputs=2[layout];

        [2:v]scale=403.5:60:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.25'[logo_half];

        [layout][logo_half]overlay=(W-w)-10:(H-h)-10[outv]
    """

    return [
        "ffmpeg", "-y",

        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-init_hw_device", "cuda=cu:0",
        "-filter_hw_device", "cu",

        "-ss", f"{voff1}", "-i", str(clip1),
        "-ss", "0",        "-i", str(clip2),
        "-i", LOGO,

        "-filter_complex", filtergraph,

        "-map", "[outv]",

        "-c:v", "hevc_nvenc",
        "-tag:v", "hvc1",
        "-preset", "p5",
        "-rc", "vbr",
        "-b:v", "12M",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",

        str(outVideo),
    ]
