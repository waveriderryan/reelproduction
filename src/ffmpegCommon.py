# ffmpegCommon.py

IOS_SAFE_VIDEO_FLAGS = [
    "-pix_fmt", "yuv420p",
    "-tag:v", "hvc1",
    "-r", "30",
    "-movflags", "+faststart",
]

IOS_SAFE_INPUT_FLAGS = [
    "-noautorotate",
]

NVENC_HEVC_QUALITY = [
    "-c:v", "hevc_nvenc",
    "-preset", "p6",
    "-rc", "vbr_hq",
    "-spatial_aq", "1",
    "-temporal_aq", "1",
    "-aq-strength", "8",
    "-rc-lookahead", "32",
]
