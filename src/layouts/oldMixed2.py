# layouts/mixedTwo.py
from pathlib import Path


def buildMixedTwoCmd(localPaths, orientations, offsets, outVideo: Path):
    clip1, clip2 = localPaths
    off1, off2 = offsets

    LOGO = "/app/assets/reelchains_logo.png"
    PAD_COLOR = "0x5762FF"

    TARGET_W = 1080
    TOP_H = 1200    # portrait zone
    BOTTOM_H = 800  # landscape zone
    CROP_H_FACTOR = 0.80
    CROP_W_FACTOR = 0.80

    # Determine which index is portrait vs landscape
    # orientations[i] is 'portrait' or 'landscape'
    if orientations[0] == "portrait":
        portrait_index = 0
        landscape_index = 1
    else:
        portrait_index = 1
        landscape_index = 0

    # ffmpeg input index to string
    p_idx = portrait_index
    l_idx = landscape_index

    # We still trim only clip1 (the "earlier" camera) by design
    # off2 is currently unused but kept in signature for future.
    filtergraph = (
        f"[{p_idx}:v]setpts=PTS-STARTPTS,"
        f"crop_cuda=in_w:in_h*{CROP_H_FACTOR}:0:(in_h-in_h*{CROP_H_FACTOR})/2,"
        f"scale_npp={TARGET_W}:{TOP_H},"
        f"pad_cuda={TARGET_W}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[top_gpu];"

        f"[{l_idx}:v]setpts=PTS-STARTPTS,"
        f"crop_cuda=in_w*{CROP_W_FACTOR}:in_h:(in_w-in_w*{CROP_W_FACTOR})/2:0,"
        f"scale_npp={TARGET_W}:{BOTTOM_H},"
        f"pad_cuda={TARGET_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[bottom_gpu];"

        f"color_cuda=c={PAD_COLOR}:s={TARGET_W}x{CANVAS_H}:r=30[bg_gpu];"

        f"[bg_gpu][top_gpu]overlay_cuda=0:0[bg2];"
        f"[bg2][bottom_gpu]overlay_cuda=0:{TOP_H}[bg_full];"

        f"[2:v]scale_npp=iw*0.30:-1,format=rgba[logo];"
        f"[logo]lut=a='val*0.50'[logo_half];"

        f"[bg_full][logo_half]overlay_cuda=(W-w)-40:(H-h)-40,fps=30[outv]"
    )



    return [
        "ffmpeg", "-y",
        "-ss", f"{off1}", "-i", str(clip1),
        "-ss", "0",        "-i", str(clip2),
        "-i", LOGO,
        "-filter_complex", filtergraph,
        "-map", "[outv]",
        "-c:v", "hevc_nvenc",
        "-preset", "p5",
        "-rc", "vbr",
        "-b:v", "10M",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(outVideo),
    ]
