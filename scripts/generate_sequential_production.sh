#!/usr/bin/env bash
set -euo pipefail
#
# Usage:
#   ./generate_sequential_production.sh <segment_time> <voff1> <voff2> <cam1> <cam2> <cam3> <logo_path> <output_name>
#
# Example:
#   ./generate_sequential_production.sh 10 5.2 3.5 clip1.mp4 clip2.mp4 clip3.mp4 logo.png final.mp4
#
# Where:
#   <voff1> = Start time of clip 2 MINUS start time of clip 1 (e.g., 5.2)
#   <voff2> = Start time of clip 3 MINUS start time of clip 2 (e.g., 3.5)
#

# --- 1. Input Arguments ---
CAM1="$1"
CAM2="$2"
CAM3="$3"
VOFF1="${4:-0}"
VOFF2="${5:-0}"
OUTNAME="${6:-output.mp4}"
SEGMENT_TIME=10

# portrait canvas
TARGET_W=1080
TARGET_H=1920
PAD_COLOR="0x000000" # Black
LOGO_PATH="${WORKDIR:-.}/reelchains_logo.png"

echo "🎬 Building 3-clip sequential production..."

# --- 2. Calculate Seek Times (using bc for float math) ---
SEEK1="0"
SEEK2_CALC=$(echo "$SEGMENT_TIME - $VOFF1" | bc)
SEEK2=$(echo "if ($SEEK2_CALC > 0) $SEEK2_CALC else 0" | bc)
VOFF_TOTAL=$(echo "$VOFF1 + $VOFF2" | bc)
SEGMENT_TIME_X_2=$(echo "$SEGMENT_TIME * 2" | bc)
SEEK3_CALC=$(echo "$SEGMENT_TIME_X_2 - $VOFF_TOTAL" | bc)
SEEK3=$(echo "if ($SEEK3_CALC > 0) $SEEK3_CALC else 0" | bc)

echo "--- Calculated Seek Times ---"
echo "Clip 1 Seek (SEEK1): $SEEK1 s"
echo "Clip 2 Seek (SEEK2): $SEEK2 s"
echo "Clip 3 Seek (SEEK3): $SEEK3 s"
echo "----------------------------"

# --- 3. Calculate FFMPEG Filter Parameters ---
FADE_DURATION=1
OFFSET1=$(echo "$SEGMENT_TIME - $FADE_DURATION" | bc)
OFFSET2=$(echo "($SEGMENT_TIME * 2) - $FADE_DURATION" | bc)
TOTAL_DURATION=$(echo "($SEGMENT_TIME * 3) - ($FADE_DURATION * 2)" | bc)

echo "--- Filter Parameters ---"
echo "Fade 1 (Clip 1 -> 2) starts at: $OFFSET1 s"
echo "Fade 2 (Clip 2 -> 3) starts at: $OFFSET2 s"
echo "Total Duration: $TOTAL_DURATION s"
echo "-------------------------"

# --- 4. PASS 1: Create 3 "clean" video-only segments ---
# We create 3 separate, 10-second clips that are already trimmed,
# rotated, and have a constant frame rate.
echo "--- Pass 1: Creating 3 clean 10-second video segments ---"
# We use -ss as an *input* option for fast (but-less-accurate) seeking
# and then use the `fps=30` filter to force a CFR.
ffmpeg -y -ss "$SEEK1" -i "$CAM1" -t "$SEGMENT_TIME" -filter_complex "[0:v]fps=30,scale=$TARGET_W:$TARGET_H:force_original_aspect_ratio=decrease,pad=$TARGET_W:$TARGET_H:(ow-iw)/2:(oh-ih)/2:color=$PAD_COLOR[v]" \
-map "[v]" -an -c:v hevc_videotoolbox -tag:v hvc1 temp_seg1.mp4

ffmpeg -y -ss "$SEEK2" -i "$CAM2" -t "$SEGMENT_TIME" -filter_complex "[0:v]fps=30,scale=$TARGET_W:$TARGET_H:force_original_aspect_ratio=decrease,pad=$TARGET_W:$TARGET_H:(ow-iw)/2:(oh-ih)/2:color=$PAD_COLOR[v]" \
-map "[v]" -an -c:v hevc_videotoolbox -tag:v hvc1 temp_seg2.mp4

ffmpeg -y -ss "$SEEK3" -i "$CAM3" -t "$SEGMENT_TIME" -filter_complex "[0:v]fps=30,scale=$TARGET_W:$TARGET_H:force_original_aspect_ratio=decrease,pad=$TARGET_W:$TARGET_H:(ow-iw)/2:(oh-ih)/2:color=$PAD_COLOR[v]" \
-map "[v]" -an -c:v hevc_videotoolbox -tag:v hvc1 temp_seg3.mp4
echo "--- Pass 1 Complete ---"

# --- 5. PASS 2: Create one merged audio track ---
echo "--- Pass 2a: Creating merged audio track ---"
ffmpeg -y \
-ss "$SEEK1" -i "$CAM1" \
-ss "$SEEK2" -i "$CAM2" \
-ss "$SEEK3" -i "$CAM3" \
-filter_complex \
"[0:a]asetpts=PTS-STARTPTS[a0]; \
 [1:a]asetpts=PTS-STARTPTS[a1]; \
 [2:a]asetpts=PTS-STARTPTS[a2]; \
 [a0]afade=type=out:start_time=$OFFSET1:duration=$FADE_DURATION[a0_faded]; \
 [a1]afade=type=in:start_time=0:duration=$FADE_DURATION,afade=type=out:start_time=$OFFSET1:duration=$FADE_DURATION[a1_faded]; \
 [a2]afade=type=in:start_time=0:duration=$FADE_DURATION,afade=type=out:start_time=$OFFSET1:duration=$FADE_DURATION[a2_faded]; \
 [a1_faded]adelay=${OFFSET1}s:all=1[a1_delayed]; \
 [a2_faded]adelay=${OFFSET2}s:all=1[a2_delayed]; \
 [a0_faded][a1_delayed][a2_delayed]amix=inputs=3[a_sequence]" \
-map "[a_sequence]" -c:a aac -b:a 192k -t "$TOTAL_DURATION" temp_audio_faded.m4a
echo "--- Pass 2a Complete ---"

echo "--- Pass 2: Creating merged audio track ---"
ffmpeg -y \
-i "$CAM1" \
-i "$CAM2" \
-i "$CAM3" \
-filter_complex \
"[0:a]asetpts=PTS-STARTPTS[a0]; \
 [1:a]asetpts=PTS-STARTPTS[a1]; \
 [2:a]asetpts=PTS-STARTPTS[a2]; \
 \
 [a1]adelay=${VOFF1}s:all=1[a1_delayed]; \
 [a2]adelay=${VOFF_TOTAL}s:all=1[a2_delayed]; \
 \
 [a0][a1_delayed][a2_delayed]amix=inputs=3[a_sequence]" \
-map "[a_sequence]" -c:a aac -b:a 192k -t "$TOTAL_DURATION" temp_audio.m4a
echo "--- Pass 2b Complete ---"


# --- 6. PASS 3: Fade videos, add audio & logo ---
echo "--- Pass 3: Building final production ---"
ffmpeg -y \
-i temp_seg1.mp4 \
-i temp_seg2.mp4 \
-i temp_seg3.mp4 \
-i temp_audio.m4a \
-i "$LOGO_PATH" \
-filter_complex \
"[0:v][1:v]xfade=transition=fade:duration=$FADE_DURATION:offset=$OFFSET1[f1]; \
 [f1][2:v]xfade=transition=fade:duration=$FADE_DURATION:offset=$OFFSET2[v_sequence]; \
 [4:v]scale=403.5:60,colorchannelmixer=aa=0.25[logo_scaled]; \
 [v_sequence][logo_scaled]overlay=main_w-overlay_w-10:main_h-overlay_h-10[final_v]" \
-map "[final_v]" -map 3:a \
-t "$TOTAL_DURATION" \
-c:v hevc_videotoolbox -tag:v hvc1 \
-c:a copy \
-movflags +faststart \
"$OUTNAME"

# --- 7. Clean up all temporary files ---
if [ "$DEBUG" != "1" ]; then
    echo "--- Cleaning up temporary files ---"
    rm temp_seg1.mp4 temp_seg2.mp4 temp_seg3.mp4 temp_audio.m4a
else
    echo "--- DEBUG=1: Preserving temporary files ---"
fi

echo "✅ Generated: $OUTNAME"
