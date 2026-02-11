from pathlib import Path

def buildTwoPortraitCmd(localPaths, startTimes, outVideo: Path, baseDuration):
    clip1, clip2 = localPaths

    CANVAS_W = 1400
    CANVAS_H = 1080
    PAD_COLOR = "0x000000"
    LOGO = "/app/assets/reelchains_logo.png"
    LOGO_SCALE = 0.18
    LOGO_ALPHA = 0.70
    LOGO_PAD = 48

    TILE_W = CANVAS_W // 2

    filtergraph = f"""
        color=c=black:s={CANVAS_W}x{CANVAS_H}:d={baseDuration}[base];

        [0:v]
            setpts=PTS-STARTPTS+{startTimes[0]}/TB,
            scale={TILE_W}:{CANVAS_H}:force_original_aspect_ratio=increase,
            crop={TILE_W}:{CANVAS_H},
            pad={TILE_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}
            [v0];

        [1:v]
            setpts=PTS-STARTPTS+{startTimes[1]}/TB,
            scale={TILE_W}:{CANVAS_H}:force_original_aspect_ratio=increase,
            crop={TILE_W}:{CANVAS_H},
            pad={TILE_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}
            [v1];

        [v0][v1]hstack=inputs=2[stacked];
        
        [base][stacked]overlay=0:0:eof_action=pass[bg];

        [2:v]scale=trunc({CANVAS_W}*{LOGO_SCALE}):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*{LOGO_ALPHA}'[logo_half];

        [bg][logo_half]overlay=(W-w)-{LOGO_PAD}:(H-h)-{LOGO_PAD}:format=auto[outv]
    """

    return [
        "ffmpeg", "-y",

        "-i", str(clip1),
        "-i", str(clip2),
        "-i", LOGO,

        "-filter_complex", filtergraph,
        "-map", "[outv]",

        "-video_track_timescale", "90000",

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
