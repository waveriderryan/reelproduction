#!/usr/bin/env python3
import argparse
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter

import cv2
import numpy as np
import dateutil.parser

from google.cloud import storage
from google import genai
from google.genai import types

# ==========================================
# 0. CONFIG
# ==========================================

SAMPLE_TIMES = [1, 5, 10, 30]  # seconds
DEFAULT_MODEL = "gemini-2.0-flash-001"

# Motion detection tuning
MOTION_FPS_SAMPLE = 5          # sample frames at ~5 fps
MOTION_DOWNSCALE_W = 320       # resize frames to reduce noise + cost
MOTION_THRESHOLD = 18.0        # mean absdiff threshold (after downscale)
MOTION_MIN_DURATION = 2.0      # seconds
MOTION_SMOOTH_WINDOW = 5       # moving average window (samples)


# ==========================================
# 1. MOTION DETECTION
# ==========================================
# ==========================================
# 1. MOTION DETECTION (WORKING VERSION)
# ==========================================
def detect_rallies_mog2(
    video_path,
    motion_threshold=4.5,
    min_rally_duration=1.5,
    merge_gap=2.0,
    target_w=640,
    target_h=360,
):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"❌ Failed to open {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    fgbg = cv2.createBackgroundSubtractorMOG2(
        history=200,
        varThreshold=50,
        detectShadows=False
    )

    motion_signal = []
    times = []

    t = 0.0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.resize(frame, (target_w, target_h))
        fgmask = fgbg.apply(frame)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        total_area = 0.0
        for c in contours:
            area = cv2.contourArea(c)
            if 150 < area < (target_w * target_h * 0.6):
                total_area += area

        motion_signal.append(total_area)
        times.append(t)
        t += 1.0 / fps

    cap.release()

    motion_signal = np.array(motion_signal)
    motion_norm = motion_signal / float(target_w * target_h)

    if len(motion_norm) == 0:
        print(f"⚠️ No motion samples for {video_path.name}")
        return []

    print(
        f"📊 Motion stats for {video_path.name}: "
        f"min={motion_norm.min():.4f}, "
        f"mean={motion_norm.mean():.4f}, "
        f"max={motion_norm.max():.4f}"
    )

    active = motion_norm > (motion_threshold / 1000.0)

    segments = []
    start = None
    for t, is_active in zip(times, active):
        if is_active and start is None:
            start = t
        elif not is_active and start is not None:
            if t - start >= min_rally_duration:
                segments.append((start, t))
            start = None

    if start is not None:
        end = times[-1]
        if end - start >= min_rally_duration:
            segments.append((start, end))

    merged = []
    for seg in segments:
        if not merged:
            merged.append(list(seg))
        else:
            prev = merged[-1]
            if seg[0] - prev[1] <= merge_gap:
                prev[1] = seg[1]
            else:
                merged.append(list(seg))

    return [(round(s, 2), round(e, 2)) for s, e in merged]



# ==========================================
# 2. PASS 1: CAMERA ROLE CLASSIFICATION
# ==========================================

def sample_frames(video_path, times):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    frames = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


def classify_frame_simple(frame):
    """
    Placeholder heuristic.
    This is intentionally dumb; you can swap this later for YOLO person-count etc.
    """
    h, w, _ = frame.shape
    aspect = w / float(h)
    return "wide" if aspect > 1.3 else "closeup"


def classify_camera_role(video_path):
    frames = sample_frames(video_path, SAMPLE_TIMES)
    votes = [classify_frame_simple(f) for f in frames if f is not None]
    if not votes:
        return "unknown", 0.0
    counts = Counter(votes)
    role, count = counts.most_common(1)[0]
    return role, (count / float(len(votes)))


# ==========================================
# 3. TIMELINE
# ==========================================

class GlobalTimeline:
    def __init__(self, inputs, bucket_name, local_paths):
        self.clips = []
        timestamps = []

        for i, clip in enumerate(inputs):
            dt = dateutil.parser.parse(clip["startTime"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamps.append(dt)

            self.clips.append({
                "gs_uri": f"gs://{bucket_name}/{clip['path']}",
                "orientation": clip.get("orientation", "unknown"),
                "start_dt": dt,
                "local_path": local_paths[i],
            })

        self.global_zero = min(timestamps) if timestamps else datetime.now(timezone.utc)


def local_sec_to_global_iso(clip_start_dt, seconds):
    return (clip_start_dt + timedelta(seconds=float(seconds))).isoformat()


# ==========================================
# 4. GEMINI: LABEL SEGMENTS (NOT DETECT FROM SCRATCH)
# ==========================================

def gemini_label_segments(client, wide_video_uri, segments_payload, model=DEFAULT_MODEL):
    """
    segments_payload: list of dicts, each with:
      - segment_index
      - start_global
      - end_global
      - start_local_sec
      - end_local_sec
      - wide_camera_index
    """
    prompt_text = f"""
You are analyzing tennis footage.

I have already detected candidate "activity segments" from a WIDE camera using motion detection.
Each segment MAY be a real rally, or it may be camera adjustment, between-point walking, warm-up, etc.

Your job:
For each provided segment, decide whether it is a REAL RALLY.

Rules:
- Do NOT invent new timestamps.
- Do NOT add segments.
- Only label the provided segments.
- A real rally starts with a serve motion or a ball feed motion where the player drops the ball into a forehand or backhand hititng motion.
- A real rally lasts until the players stop moving for and swinging at the ball.  
- Exclude: people walking, towel breaks, ball pickup, long idle time, camera pans without play.

Return JSON ONLY, in this format:

{{
  "labels": [
    {{
      "segment_index": 0,
      "is_rally": true,
      "confidence": 0.0,
      "reason": "Short explanation"
    }}
  ]
}}

Here are the segments:
{json.dumps(segments_payload, indent=2)}
""".strip()

    contents = [
        prompt_text,
        types.Part.from_uri(file_uri=wide_video_uri, mime_type="video/mp4"),
    ]

    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    return json.loads(resp.text)


# ==========================================
# 5. CORE JOB
# ==========================================

def run_analysis_job(payload_json_str, workdir_str="/workspace"):
    payload = json.loads(payload_json_str)

    bucket_name = payload["bucket"]
    inputs = payload["inputs"]
    production_id = payload["productionId"]

    workdir = Path(workdir_str).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    storage_client = storage.Client()

    print(f"🧠 Starting AI Analysis v2 for Production: {production_id}")

    # --------------------------------------
    # Download clips locally (for PASS1 + motion)
    # --------------------------------------
    local_paths = []
    for i, clip in enumerate(inputs):
        local_path = workdir / f"clip_{i}.mp4"
        blob = storage_client.bucket(bucket_name).blob(clip["path"])

        if local_path.exists() and local_path.stat().st_size > 1024 * 1024:  # >1MB sanity check
            print(f"♻️ Reusing cached file: {local_path}")
        else:
            print(f"⬇️ Downloading gs://{bucket_name}/{clip['path']} -> {local_path}")
            local_path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(local_path))

        local_paths.append(local_path)


    # --------------------------------------
    # Timeline
    # --------------------------------------
    timeline = GlobalTimeline(inputs, bucket_name, local_paths)

    # --------------------------------------
    # PASS 1: Camera Role Classification
    # --------------------------------------
    print("📸 PASS 1: Classifying camera roles...")
    camera_roles = {}
    for i, clip in enumerate(timeline.clips):
        role, conf = classify_camera_role(clip["local_path"])
        camera_roles[str(i)] = {
            "role": role,
            "confidence": round(conf, 2),
            "uri": clip["gs_uri"],
        }
        print(f"   Cam {i}: {role} (conf={conf:.2f})")

    wide_cams = [int(i) for i, r in camera_roles.items() if r["role"] == "wide"]
    if not wide_cams:
        # fallback: pick highest confidence unknown-> treat as wide (or cam0)
        print("⚠️ No wide cameras detected. Falling back to cam0.")
        wide_cams = [0]

    # --------------------------------------
    # MOTION: candidate segments per wide camera
    # --------------------------------------
    print("🏃 Detecting motion segments on wide cameras...")
    all_candidates = []  # flattened across wide cams
    for cam_idx in wide_cams:
        clip = timeline.clips[cam_idx]
        
        segments = detect_rallies_mog2(
            clip["local_path"],
            motion_threshold=4.5,      # your known-good values
            min_rally_duration=1.5,
            merge_gap=2.0,
        )

        print(f"   Cam {cam_idx}: {len(segments)} motion segments")

        for (s, e) in segments:
            all_candidates.append({
                "wide_camera_index": cam_idx,
                "start_local_sec": s,
                "end_local_sec": e,
                "start_global": local_sec_to_global_iso(clip["start_dt"], s),
                "end_global": local_sec_to_global_iso(clip["start_dt"], e),
            })

    print("🧪 Motion candidates:")
    for seg in all_candidates:
        print(
            f"Cam {seg['wide_camera_index']} "
            f"{seg['start_local_sec']:.2f}s → {seg['end_local_sec']:.2f}s "
            f"({seg['end_local_sec'] - seg['start_local_sec']:.2f}s)"
        )

    # If motion detection found nothing, still output roles (don’t crash)
    if not all_candidates:
        print("⚠️ No motion segments found. Outputting roles only.")
        ai_data = {"rallies": []}
        final_result = {
            "production_id": production_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "camera_roles": camera_roles,
            "ai_data": ai_data,
            "motion_candidates": [],
        }
        return _save_and_upload(storage_client, bucket_name, production_id, workdir, final_result)

    # --------------------------------------
    # PASS 2: Gemini segment labeling
    # --------------------------------------
    print("🤖 PASS 2: Calling Gemini to label segments...")
    client = genai.Client(vertexai=True, location="us-central1")

    # Group by wide camera and label each wide cam separately (keeps context cleaner)
    labeled_rallies = []
    for cam_idx in wide_cams:
        clip = timeline.clips[cam_idx]
        cam_candidates = [c for c in all_candidates if c["wide_camera_index"] == cam_idx]

        # Add segment_index per camera batch
        segments_payload = []
        for si, c in enumerate(cam_candidates):
            segments_payload.append({
                "segment_index": si,
                **c
            })

        labels = gemini_label_segments(
            client=client,
            wide_video_uri=clip["gs_uri"],
            segments_payload=segments_payload,
        )

        # Merge labels -> rallies
        for item in labels.get("labels", []):
            si = item.get("segment_index")
            if si is None or si < 0 or si >= len(cam_candidates):
                continue
            if item.get("is_rally") is True:
                seg = cam_candidates[si]
                labeled_rallies.append({
                    "start_global": seg["start_global"],
                    "end_global": seg["end_global"],
                    "wide_camera_index": cam_idx,
                    "confidence": float(item.get("confidence", 0.0)),
                    "reason": item.get("reason", ""),
                })

    # Sort rallies by start time for downstream EDL
    labeled_rallies.sort(key=lambda r: r["start_global"])

    ai_data = {"rallies": labeled_rallies}

    final_result = {
        "production_id": production_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "camera_roles": camera_roles,
        "motion_candidates": all_candidates,
        "ai_data": ai_data,
    }

    return _save_and_upload(storage_client, bucket_name, production_id, workdir, final_result)


def _save_and_upload(storage_client, bucket_name, production_id, workdir, final_result):
    out_path = workdir / f"analysis_{production_id}.json"
    with open(out_path, "w") as f:
        json.dump(final_result, f, indent=2)

    gcs_out = f"productions/{production_id}/analysis.json"
    print(f"⬆️ Uploading {out_path} -> gs://{bucket_name}/{gcs_out}")
    storage_client.bucket(bucket_name).blob(gcs_out).upload_from_filename(str(out_path))

    print(f"✅ Analysis complete: gs://{bucket_name}/{gcs_out}")
    return final_result


# ==========================================
# 6. MAIN
# ==========================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    parser.add_argument("--workdir", default="./workspace")
    args = parser.parse_args()

    try:
        run_analysis_job(args.payload, args.workdir)
        return 0
    except Exception as e:
        print(f"❌ Critical Failure: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
