#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./generateMixedPortraitLandscape.sh <CLIP1> <MODE1> <CLIP2> <MODE2> <OFFSET1> <OUTNAME>
# OFFSET1 (VOFF1) always trims CLIP1 because CLIP1 started earlier.

CLIP1="$1"
MODE1="$2"      # portrait | landscape
CLIP2="$3"
MODE2="$4"      # portrait | landscape
VOFF1="$5"      # seconds to trim from CLIP1
OUTNAME="$6"

LOGO="reelchains_logo.png"
PAD_COLOR="0x5762FF"

TARGET_W=1080
TOP_H=1280       # portrait zone (2/3)
BOTTOM_H=640     # landscape zone (1/3)

echo "🎬 Mixed portrait + landscape layout (portrait TOP)"
echo "➡️  CLIP1: $CLIP1 ($MODE1)  trim=$VOFF1"
echo "➡️  CLIP2: $CLIP2 ($MODE2)"
echo "🎞 Output: $OUTNAME"

# Validate modes are mixed
if [[ "$MODE1" == "$MODE2" ]]; then
  echo "❌ Mixed script called with non-mixed inputs!"
  exit 1
fi

# Decide which input index is portrait vs landscape
if [[ "$MODE1" == "portrait" ]]; then
  PORTRAIT_V="[0:v]"
  PORTRAIT_A="[0:a]"
  LAND_V="[1:v]"
  LAND_A="[1:a]"
else
  PORTRAIT_V="[1:v]"
  PORTRAIT_A="[1:a]"
  LAND_V="[0:v]"
  LAND_A="[0:a]"
fi

ffmpeg -y \
  -ss "$VOFF1" -i "$CLIP1" \
  -ss 0       -i "$CLIP2" \
  -i "$LOGO" \
  -filter_complex "
    ${PORTRAIT_V}setpts=PTS-STARTPTS,
         scale=${TARGET_W}:${TOP_H}:force_original_aspect_ratio=decrease,
         pad=${TARGET_W}:${TOP_H}:(ow-iw)/2:(oh-ih)/2:${PAD_COLOR}[top];

    ${LAND_V}setpts=PTS-STARTPTS,
         scale=${TARGET_W}:${BOTTOM_H}:force_original_aspect_ratio=decrease,
         pad=${TARGET_W}:${BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:${PAD_COLOR}[bottom];

    [top][bottom]vstack=inputs=2[bg];

    [2:v]scale=iw*0.30:-1,format=rgba[logo];
    [logo]lut=a='val*0.50'[logo_half];
    [bg][logo_half]overlay=(W-w)-40:(H-h)-40[outv];

    ${PORTRAIT_A}aresample=async=1:first_pts=0[a0];
    ${LAND_A}aresample=async=1:first_pts=0[a1];
    [a0][a1]amix=inputs=2:normalize=0:duration=longest[aout]
  " \
  -map "[outv]" -map "[aout]" \
  -c:v hevc_videotoolbox -tag:v hvc1 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  -r 30 -fps_mode cfr \
  "$OUTNAME"

echo "✅ Mixed layout done!"

