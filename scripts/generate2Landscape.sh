#!/usr/bin/env bash
set -euo pipefail

# Arguments per new calling convention
# ------------------------------------
# $1 = CLIP1_LOCAL
# $2 = MODE1   (ignored here but must be consumed)
# $3 = CLIP2_LOCAL
# $4 = MODE2   (ignored here)
# $5 = VOFF1
# $6 = OUTNAME

CAM1="$1"
MODE1="$2"       # ignored but required
CAM2="$3"
MODE2="$4"       # ignored but required
VOFF1="$5"
OUTNAME="$6"

LOGO="reelchains_logo.png"
PAD_COLOR="0x5762FF"

echo "🎬 2-landscape vertical production using amerge with center-mix audio…"
echo "📹 CAM1: $CAM1 (trim $VOFF1 s)"
echo "📹 CAM2: $CAM2"
echo "🎞 OUT:  $OUTNAME"

ffmpeg -y \
  -ss "$VOFF1" -i "$CAM1" \
  -ss 0       -i "$CAM2" \
  -i "$LOGO" \
  -filter_complex "

    [0:v]setpts=PTS-STARTPTS,
         crop=iw*0.8:ih:(iw-iw*0.8)/2:0[v0_crop];
    [v0_crop]scale=1080:-2:force_original_aspect_ratio=decrease[v0_scaled];
    [v0_scaled]pad=1080:960:(ow-iw)/2:(oh-ih)/2:${PAD_COLOR}[v0_top];

    [1:v]setpts=PTS-STARTPTS,
         crop=iw*0.8:ih:(iw-iw*0.8)/2:0[v1_crop];
    [v1_crop]scale=1080:-2:force_original_aspect_ratio=decrease[v1_scaled];
    [v1_scaled]pad=1080:960:(ow-iw)/2:(oh-ih)/2:${PAD_COLOR}[v1_bottom];

    [v0_top][v1_bottom]vstack=inputs=2[layout];

    [2:v]scale=403.5:60,colorchannelmixer=aa=0.25[logo_scaled];
    [layout][logo_scaled]overlay=main_w-overlay_w-10:main_h-overlay_h-10[final_v];

    [0:a]asetpts=PTS-STARTPTS[a0];
    [1:a]asetpts=PTS-STARTPTS[a1];

    [a0][a1]amerge=inputs=2[stereo_raw];

    [stereo_raw]pan=mono|c0=0.5*c0+0.5*c1[mix_mono];
    [mix_mono]pan=stereo|c0=c0|c1=c0[aout];

  " \
  -map "[final_v]" -map "[aout]" \
  -ac 2 \
  -vsync cfr -r 30 \
  -c:v hevc_videotoolbox -tag:v hvc1 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$OUTNAME"

