#!/usr/bin/env python3
import argparse
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, deque

import cv2
import numpy as np
import dateutil.parser
import mediapipe as mp

from ultralytics import YOLO
from google.cloud import storage


# ==========================================
# 0. CONFIG
# ==========================================

SAMPLE_TIMES = [1, 5, 10, 30]  # seconds
YOLO_MODEL_PATH = "yolov8n.pt"
LOCAL_OUT = "analysis_local.json"


# ==========================================
# 1. HELPERS
# ==========================================

def sample_frames(video_path, times):
    cap = cv2.VideoCapture(str(video_path))
    frames = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


# ==========================================
# 2. WIDE CAMERA DETECTION (YOLO)
# ==========================================

yolo_model = YOLO(YOLO_MODEL_PATH)

def pick_best_wide_camera(local_paths, sample_times):
    scores = []

    for cam_idx, video_path in enumerate(local_paths):
        frames = sample_frames(video_path, sample_times)
        if not frames:
            scores.append((cam_idx, -1e9, {"avg_ratio": None, "avg_people": None}))
            continue

        ratios = []
        person_counts = []

        for f in frames:
            h, w, _ = f.shape
            frame_area = h * w

            results = yolo_model(f, verbose=False)[0]
            person_boxes = [b for b in results.boxes if int(b.cls[0]) == 0]  # person

            person_counts.append(len(person_boxes))

            if not person_boxes:
                continue

            max_ratio = 0.0
            for b in person_boxes:
                x1, y1, x2, y2 = b.xyxy[0].cpu().numpy()
                area = max(1.0, (x2 - x1) * (y2 - y1))
                ratio = area / frame_area
                max_ratio = max(max_ratio, ratio)

            ratios.append(max_ratio)

        avg_ratio = float(np.mean(ratios)) if ratios else 1.0
        avg_people = float(np.mean(person_counts)) if person_counts else 0.0

        # --- Wide score: more people + smaller players ---
        score = (avg_people * 2.0) - (avg_ratio * 10.0)

        print(
            f"📊 Cam {cam_idx}: avg_people={avg_people:.2f}, "
            f"avg_ratio={avg_ratio:.4f}, score={score:.3f}"
        )

        scores.append((cam_idx, score, {
            "avg_people": avg_people,
            "avg_ratio": avg_ratio
        }))

    best = max(scores, key=lambda x: x[1])
    best_cam_idx, best_score, debug = best

    return best_cam_idx, best_score, debug


def classify_camera_role_by_people(video_path):
    frames = sample_frames(video_path, SAMPLE_TIMES)
    if not frames:
        return "unknown", 0.0

    ratios = []
    person_counts = []

    for f in frames:
        h, w, _ = f.shape
        frame_area = h * w

        results = yolo_model(f, verbose=False)[0]
        person_boxes = [b for b in results.boxes if int(b.cls[0]) == 0]  # person

        person_counts.append(len(person_boxes))

        if not person_boxes:
            continue

        max_ratio = 0.0
        for b in person_boxes:
            x1, y1, x2, y2 = b.xyxy[0].cpu().numpy()
            area = max(1.0, (x2 - x1) * (y2 - y1))
            ratio = area / frame_area
            max_ratio = max(max_ratio, ratio)

        ratios.append(max_ratio)

    if not ratios:
        return "unknown", 0.0

    avg_ratio = float(np.mean(ratios))
    avg_people = float(np.mean(person_counts))

    # --- NEW stricter logic ---
    # Wide courts usually:
    #  - show BOTH players
    #  - players are VERY small in frame
    is_wide = (avg_people >= 2.0) and (avg_ratio < 0.03)

    confidence = 1.0 if is_wide else 1.0
    return ("wide" if is_wide else "closeup"), confidence


# ==========================================
# 3. SWING DETECTION (MEDIAPIPE)
# ==========================================

def detect_swings_mediapipe(video_path, player="near", min_peak_gap_sec=0.6):
    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        smooth_landmarks=True,
        enable_segmentation=False,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    wrist_history = deque(maxlen=5)
    swing_times = []
    prev_peak_t = -999

    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = pose.process(rgb)

        t = frame_idx / fps

        if res.pose_landmarks:
            lm = res.pose_landmarks.landmark

            if player == "near":
                wrist = lm[mp_pose.PoseLandmark.RIGHT_WRIST]
            else:
                wrist = lm[mp_pose.PoseLandmark.LEFT_WRIST]

            wrist_xy = np.array([wrist.x, wrist.y])
            wrist_history.append(wrist_xy)

            if len(wrist_history) >= 3:
                v1 = np.linalg.norm(wrist_history[-1] - wrist_history[-2]) * fps
                v0 = np.linalg.norm(wrist_history[-2] - wrist_history[-3]) * fps
                a = abs(v1 - v0)

                if v1 > 1.2 and a > 0.6:
                    if (t - prev_peak_t) > min_peak_gap_sec:
                        swing_times.append(round(t, 2))
                        prev_peak_t = t

        frame_idx += 1

    cap.release()
    pose.close()
    return swing_times


# ==========================================
# 4. TIMELINE
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
                "start_dt": dt,
                "local_path": local_paths[i],
            })

        self.global_zero = min(timestamps)


def local_sec_to_global_iso(clip_start_dt, seconds):
    return (clip_start_dt + timedelta(seconds=float(seconds))).isoformat()


# ==========================================
# 5. CORE JOB
# ==========================================

def run_analysis_job(payload_json_str, workdir_str="./workspace"):
    payload = json.loads(payload_json_str)
    bucket_name = payload["bucket"]
    inputs = payload["inputs"]
    production_id = payload["productionId"]

    workdir = Path(workdir_str).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    storage_client = storage.Client()

    print(f"\n🧠 Starting Local CV Analysis for Production: {production_id}")

    # --------------------------------------
    # Download clips locally (cached)
    # --------------------------------------
    local_paths = []
    for i, clip in enumerate(inputs):
        local_path = workdir / f"clip_{i}.mp4"
        blob = storage_client.bucket(bucket_name).blob(clip["path"])

        if local_path.exists() and local_path.stat().st_size > 1_000_000:
            print(f"♻️ Reusing cached file: {local_path}")
        else:
            print(f"⬇️ Downloading gs://{bucket_name}/{clip['path']} -> {local_path}")
            blob.download_to_filename(str(local_path))

        local_paths.append(local_path)

    # --------------------------------------
    # Timeline
    # --------------------------------------
    timeline = GlobalTimeline(inputs, bucket_name, local_paths)

    # --------------------------------------
    # PASS 1: Pick WIDE camera
    # --------------------------------------
    print("📸 Detecting WIDE camera using YOLO person scale (ranking)...")

    wide_cam, best_score, debug = pick_best_wide_camera(local_paths, SAMPLE_TIMES)

    print(
        f"🎾 Selected WIDE camera: Cam {wide_cam} "
        f"(score={best_score:.3f}, "
        f"avg_people={debug['avg_people']:.2f}, "
        f"avg_ratio={debug['avg_ratio']:.4f})"
    )

    print(f"\n🎾 Using WIDE camera: Cam {wide_cam}")

    clip = timeline.clips[wide_cam]

    # --------------------------------------
    # PASS 2: Swing detection
    # --------------------------------------
    print("\n🏓 Detecting swings with MediaPipe Pose...")
    near_swings = detect_swings_mediapipe(clip["local_path"], player="near")
    far_swings  = detect_swings_mediapipe(clip["local_path"], player="far")

    all_swings = []
    for t in near_swings:
        all_swings.append({
            "time_sec": t,
            "player": "near",
            "time_global": local_sec_to_global_iso(clip["start_dt"], t),
        })

    for t in far_swings:
        all_swings.append({
            "time_sec": t,
            "player": "far",
            "time_global": local_sec_to_global_iso(clip["start_dt"], t),
        })

    all_swings.sort(key=lambda s: s["time_sec"])

    print("\n🧪 Swings detected:")
    for s in all_swings:
        print(f"  {s['time_sec']:6.2f}s | {s['player']}")

    # --------------------------------------
    # Save local file
    # --------------------------------------
    out = {
        "production_id": production_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wide_camera_index": wide_cam,
        "swings": all_swings,
    }

    out_path = workdir / LOCAL_OUT
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\n💾 Wrote local results to: {out_path}")
    print("\n✅ Done.")


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
        print(f"\n❌ Critical Failure: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
