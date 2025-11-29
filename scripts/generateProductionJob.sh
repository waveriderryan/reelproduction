#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# generateProductionJob.sh
#
# Usage:
#   ./generateProductionJob.sh BUCKET OUTFILE \
#     CAM1_PATH MODE1 \
#     CAM2_PATH MODE2 \
#     OFFSET_SEC
###############################################################################

BUCKET="$1"
OUT_REL="$2"
CLIP1_REL="$3"

# Normalize modes to lowercase + trim
MODE1="$(echo "$4" | tr '[:upper:]' '[:lower:]' | xargs)"
CLIP2_REL="$5"
MODE2="$(echo "$6" | tr '[:upper:]' '[:lower:]' | xargs)"

VOFF1="$7"   # offset seconds (CAM1 started earlier → trim CAM1)

if [[ "$MODE1" != "portrait" && "$MODE1" != "landscape" ]]; then
  echo "❌ MODE1 must be portrait or landscape (got '$MODE1')"
  exit 1
fi

if [[ "$MODE2" != "portrait" && "$MODE2" != "landscape" ]]; then
  echo "❌ MODE2 must be portrait or landscape (got '$MODE2')"
  exit 1
fi

###############################################################################
# DEBUG MODE / WORKDIR
###############################################################################
DEBUG="${DEBUG:-1}"

if [[ "$DEBUG" == "1" ]]; then
  WORKDIR="./debug_workspace"
  mkdir -p "$WORKDIR"
  echo "📂 Using persistent debug workspace: $WORKDIR"
else
  WORKDIR="$(mktemp -d)"
  echo "📂 Using temp workspace: $WORKDIR"
fi

CACHE_DIR="$HOME/reelcache/videos"
mkdir -p "$CACHE_DIR"

###############################################################################
# HELPERS
###############################################################################
cache_key_for() {
  local s="gs://${BUCKET}/$1"
  echo "$(echo -n "$s" | shasum -a 1 | awk '{print $1}')"
}

fetch_clip() {
  local rel="$1"
  local base="$(basename "$rel")"
  local key="$(cache_key_for "$rel")"
  local cached="${CACHE_DIR}/${key}__${base}"
  local dest="${WORKDIR}/${base}"

  if [[ -f "$cached" ]]; then
    echo "💾 CACHE HIT $base" >&2
    cp "$cached" "$dest"
  else
    echo "⬇️ Downloading gs://${BUCKET}/${rel}" >&2
    gsutil -q cp "gs://${BUCKET}/${rel}" "$cached"
    cp "$cached" "$dest"
  fi

  # THE ONLY OUTPUT TO STDOUT:
  echo "$dest"
}


###############################################################################
# FETCH INPUT FILES
###############################################################################
CLIP1_LOCAL=$(fetch_clip "$CLIP1_REL")
CLIP2_LOCAL=$(fetch_clip "$CLIP2_REL")

###############################################################################
# DETERMINE WHICH LAYOUT SCRIPT TO USE
###############################################################################
if [[ "$MODE1" == "portrait" && "$MODE2" == "portrait" ]]; then
  SCRIPT="generate2Portrait.sh"

elif [[ "$MODE1" == "landscape" && "$MODE2" == "landscape" ]]; then
  SCRIPT="generate2Landscape.sh"

else
  # any portrait/landscape combination
  SCRIPT="generateMixedPortraitLandscape.sh"
fi

echo "🎬 Layout chosen: $SCRIPT"

OUT_LOCAL="$WORKDIR/$(basename "$OUT_REL")"

###############################################################################
# EXECUTE LAYOUT SCRIPT WITH CORRECT ARG PATTERN
###############################################################################

if [[ "$MODE1" == "$MODE2" ]]; then
  # SAME ORIENTATION
  echo "➡️ Calling: $SCRIPT CAM1 CAM2 OFFSET OUT"
  bash "$SCRIPT" \
    "$CLIP1_LOCAL" \
    "$CLIP2_LOCAL" \
    "$VOFF1" \
    "$OUT_LOCAL"

else
  # MIXED ORIENTATION
  echo "➡️ Calling: $SCRIPT CAM1 MODE1 CAM2 MODE2 OFFSET OUT"
  bash "$SCRIPT" \
    "$CLIP1_LOCAL" "$MODE1" \
    "$CLIP2_LOCAL" "$MODE2" \
    "$VOFF1" \
    "$OUT_LOCAL"
fi

###############################################################################
# VERIFY OUTPUT
###############################################################################
if [[ ! -f "$OUT_LOCAL" ]]; then
  echo "❌ ERROR: Layout script did not produce output!"
  exit 1
fi

###############################################################################
# UPLOAD OR SAVE LOCALLY
###############################################################################
if [[ "$DEBUG" == "1" ]]; then
  echo "🧩 DEBUG MODE: copying result locally instead of uploading"
  cp "$OUT_LOCAL" "./$(basename "$OUT_REL")"
else
  echo "⬆️ Uploading to gs://${BUCKET}/${OUT_REL}"
  gsutil -q cp "$OUT_LOCAL" "gs://${BUCKET}/${OUT_REL}"
fi

echo "✅ Done!"
echo "📍 Output: $OUT_LOCAL"
