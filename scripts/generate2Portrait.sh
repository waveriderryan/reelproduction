#!/usr/bin/env bash
set -euo pipefail
#
# Usage:
#   ./generateProductionFrom2PortraitInputs_logo_sync.sh <cam1.mp4> <cam2.mp4> <offset1> <output_name>
#
# Example:
#   ./generateProductionFrom2PortraitInputs_logo_sync.sh cam1.mp4 cam2.mp4 0.116 output.mp4
#
# cam1 started 0.116s before cam2 (reference),
# so we trim 0.116s from cam1 at input time (-ss).

CAM1="$1"
CAM2="$2"
VOFF1="${3:-0}"             # seconds to trim from CAM1 (cam1 started earlier)
OUTNAME="${4:-output.mp4}"  # output filename

TARGET_W=1920
TARGET_H=1080
PAD_COLOR="0x5762FF"
LOGO="reelchains_logo.png"

# vertical crop factor: 1.0 = none, 0.8 = remove 10% top & bottom
CROP_H_FACTOR="${CROP_H_FACTOR:-0.8}"

echo "🎬 Building 2-portrait production (height-normalized)…"
echo "📹 CAM1: $CAM1 (trim $VOFF1 s)"
echo "📹 CAM2: $CAM2"
echo "🎞 OUT : $OUTNAME"

echo "DEBUG CAM1=<${CAM1}>"
echo "DEBUG CAM2=<${CAM2}>"

ffmpeg \
  -y \
  -ss "$VOFF1" -i "$CAM1" \
  -i "$CAM2" \
  -i "$LOGO" \
  -filter_complex "
    [0:v]setpts=PTS-STARTPTS,scale=-2:1080:force_original_aspect_ratio=decrease[v0s];
    [1:v]setpts=PTS-STARTPTS,scale=-2:1080:force_original_aspect_ratio=decrease[v1s];

    [v0s]crop=iw:ih*${CROP_H_FACTOR}:0:(ih-ih*${CROP_H_FACTOR})/2[v0c];
    [v1s]crop=iw:ih*${CROP_H_FACTOR}:0:(ih-ih*${CROP_H_FACTOR})/2[v1c];

    [v0c][v1c]hstack=inputs=2[stacked];

    [stacked]scale=${TARGET_W}:${TARGET_H}:force_original_aspect_ratio=decrease,
             pad=${TARGET_W}:${TARGET_H}:(ow-iw)/2:(oh-ih)/2:${PAD_COLOR}[bg];

    [2:v]scale=trunc(${TARGET_W}*0.18):-1:force_original_aspect_ratio=decrease,format=rgba[logo];
    [logo]lut=a='val*0.7'[logo_half];
    [bg][logo_half]overlay=(W-w)-48:(H-h)-48,format=yuv420p[outv];

    [0:a]aresample=async=1:first_pts=0[a0];
    [1:a]aresample=async=1:first_pts=0[a1];
    [a0][a1]amix=inputs=2:normalize=0:duration=longest[aout];
  " \
  -map "[outv]" -map "[aout]" \
  -c:v hevc_videotoolbox -tag:v hvc1 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$OUTNAME"

ffmpeg_status=$?
if [ $ffmpeg_status -ne 0 ]; then
  echo "❌ FFmpeg failed with status $ffmpeg_status"
  exit $ffmpeg_status
else
  echo "✅ Production video created: $OUTNAME"
fi
