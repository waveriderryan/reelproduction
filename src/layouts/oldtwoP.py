from pathlib import Path

def buildTwoPortraitCmd(localPaths, offsets, outVideo: Path):
    clip1, clip2 = localPaths
    voff1 = offsets[0]

    TARGET_W = 1920
    TARGET_H = 1080
    PAD = "0x5762FF"
    LOGO = "/app/assets/reelchains_logo.png"
    CROP = 0.80

    filtergraph = f"""
        [0:v]setpts=PTS-STARTPTS,
             scale=-2:1080:force_original_aspect_ratio=decrease[v0s];
        [1:v]setpts=PTS-STARTPTS,
             scale=-2:1080:force_original_aspect_ratio=decrease[v1s];

        [v0s]crop=iw:ih*{CROP}:0:(ih-ih*{CROP})/2[v0c];
        [v1s]crop=iw:ih*{CROP}:0:(ih-ih*{CROP})/2[v1c];

        [v0c][v1c]hstack=inputs=2[stacked];

        [stacked]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,
                 pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:{PAD}[bg];

        [2:v]scale=trunc({TARGET_W}*0.18):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*0.7'[logo_half];
        [bg][logo_half]overlay=(W-w)-48:(H-h)-48:format=auto[outv]
    """

    return [
        "ffmpeg", "-y",
        "-ss", f"{voff1}", "-i", str(clip1),
        "-i", str(clip2),
        "-i", LOGO,
        "-filter_complex", filtergraph,
        "-map", "[outv]",
        "-c:v", "hevc_nvenc",
        "-rc", "vbr",
        "-b:v", "10M",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(outVideo),
    ]
