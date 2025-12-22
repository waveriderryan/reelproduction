# ffmpegVideo.py


from ffmpegCommon import (
    IOS_SAFE_VIDEO_FLAGS,
    IOS_SAFE_INPUT_FLAGS,
    NVENC_HEVC_QUALITY,
)

def build_video_command(
    inputs,
    filtergraph,
    output_path,
    bitrate="3.8M",
):
    cmd = ["ffmpeg", "-y"]

    cmd += IOS_SAFE_INPUT_FLAGS

    for ss, path in inputs:
        cmd += ["-ss", str(ss), "-i", str(path)]

    cmd += [
        "-filter_complex", filtergraph,
        "-map", "[outv]",
    ]

    cmd += NVENC_HEVC_QUALITY
    cmd += ["-b:v", bitrate]
    cmd += IOS_SAFE_VIDEO_FLAGS

    cmd.append(str(output_path))
    return cmd
