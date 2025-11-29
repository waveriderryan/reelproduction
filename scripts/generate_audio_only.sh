
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
#TOTAL_DURATION=$(echo "($SEGMENT_TIME * 3) - ($FADE_DURATION * 2)" | bc)
TOTAL_DURATION=$(echo "($SEGMENT_TIME * 3)" | bc)

MS_VOFF1=$(awk -v val="$VOFF1" 'BEGIN { print val * 1000 }')
MS_VOFF_TOTAL=$(awk -v val="$VOFF_TOTAL" 'BEGIN { print val * 1000 }')

echo "VOFF total is $VOFF_TOTAL"
echo "MS_VOFF1 is $MS_VOFF1"
echo "MS_VOFF_TOTAL is $MS_VOFF_TOTAL"


echo "--- Filter Parameters ---"
echo "Fade 1 (Clip 1 -> 2) starts at: $OFFSET1 s"
echo "Fade 2 (Clip 2 -> 3) starts at: $OFFSET2 s"
echo "Total Duration: $TOTAL_DURATION s"
echo "-------------------------"

echo "--- Pass 2: Creating merged audio track ---"

FILTER_COMPLEX="[0:a]asetpts=PTS-STARTPTS[a0]; \
[1:a]asetpts=PTS-STARTPTS[a1]; \
[2:a]asetpts=PTS-STARTPTS[a2]; \
[a1]adelay=${MS_VOFF1}:all=1[a1_delayed]; \
[a2]adelay=${MS_VOFF_TOTAL}:all=1[a2_delayed]; \
[a0][a1_delayed][a2_delayed]amix=inputs=3[a_sequence]"

echo "Filter complex is $FILTER_COMPLEX"

FFMPEG_CMD="ffmpeg -y \
-i \"$CAM1\" \
-i \"$CAM2\" \
-i \"$CAM3\" \
-filter_complex \"$FILTER_COMPLEX\" \
-map \"[a_sequence]\" -c:a aac -b:a 192k -t \"$TOTAL_DURATION\" temp_audio.m4a"

# --- 4. Echo the Command (for debugging) ---
echo "--- Generated Command ---"
echo "$FFMPEG_CMD"
echo "---------------------------"

# --- 5. Execute the Command ---
# 'eval' forces the shell to re-read the string as a command,
# correctly interpreting all the quotes and spaces.
eval "$FFMPEG_CMD"
