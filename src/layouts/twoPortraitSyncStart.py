from pathlib import Path

def buildTwoPortraitCmd(localPaths, offsets, outVideo: Path):
    clip1, clip2 = localPaths
    voff1 = offsets[0]

    # Canvas is landscape
    CANVAS_W = 1920
    CANVAS_H = 1080
    #PAD_COLOR = "0x5762FF"
    PAD_COLOR = "0x000000"

    LOGO = "/app/assets/reelchains_logo.png"

    # We crop to 80% height (portrait videos have wasted top/bottom)
    CROP_FACTOR = 0.80

    filtergraph = (
        # --- Input 0 (portrait) ---
        "[0:v]setpts=PTS-STARTPTS,"
        "scale=-2:1080:force_original_aspect_ratio=decrease,"
        "crop=iw:ih*" + str(CROP_FACTOR) + ":0:(ih-ih*" + str(CROP_FACTOR) + ")/2[v0];"

        # --- Input 1 (portrait) ---
        "[1:v]setpts=PTS-STARTPTS,"
        "scale=-2:1080:force_original_aspect_ratio=decrease,"
        "crop=iw:ih*" + str(CROP_FACTOR) + ":0:(ih-ih*" + str(CROP_FACTOR) + ")/2[v1];"

        # --- Side-by-side ---
        "[v0][v1]hstack=inputs=2[stacked_raw];"

        # --- Center inside canvas ---
        "[stacked_raw]scale=" + str(CANVAS_W) + ":" + str(CANVAS_H) + ":force_original_aspect_ratio=decrease,"
        "pad=" + str(CANVAS_W) + ":" + str(CANVAS_H) + ":(ow-iw)/2:(oh-ih)/2:" + PAD_COLOR + "[bg];"

        # --- Logo ---
        "[2:v]scale=trunc(" + str(CANVAS_W) + "*0.18):-1:force_original_aspect_ratio=decrease,format=rgba[logo];"
        "[logo]lut=a='val*0.70'[logo_half];"
        "[bg][logo_half]overlay=(W-w)-48:(H-h)-48:format=auto[outv]"
    )

    return [
        "ffmpeg", "-y",
        "-ss", f"{voff1}",
        "-i", str(clip1),
        "-i", str(clip2),
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

        str(outVideo)
    ]