from pathlib import Path


def buildFourPortraitCmd(localPaths, offsets, outVideo: Path):
    """
    4 portrait videos → 2x2 grid on a 1080x1920 canvas
    """

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x5762FF"

    CANVAS_W = 1080
    CANVAS_H = 1920

    TILE_W = CANVAS_W // 2    # 540
    TILE_H = CANVAS_H // 2    # 960

    CROP = 0.85  # vertical crop

    filtergraph = f"""
        [0:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v0];

        [1:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v1];

        [2:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v2];

        [3:v]setpts=PTS-STARTPTS,
             crop=in_w:in_h*{CROP}:0:(in_h-in_h*{CROP})/2,
             scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,
             pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[v3];

        [v0][v1]hstack=inputs=2[top];
        [v2][v3]hstack=inputs=2[bottom];
        [top][bottom]vstack=inputs=2[grid];

        [4:v]scale=trunc({CANVAS_W}*0.18):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.25'[logo_half];

        [grid][logo_half]overlay=(W-w)-48:(H-h)-48:format=auto[outv]
    """

    return [
        "ffmpeg", "-y",

        "-ss", f"{offsets[0]}", "-i", str(localPaths[0]),
        "-ss", f"{offsets[1]}", "-i", str(localPaths[1]),
        "-ss", f"{offsets[2]}", "-i", str(localPaths[2]),
        "-ss", f"{offsets[3]}", "-i", str(localPaths[3]),

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
