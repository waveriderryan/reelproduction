#!/usr/bin/env python3
import argparse
import sys
import json
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from google.cloud import storage
import dateutil.parser 

# ==========================================
# CONFIGURATION
# ==========================================
# Indices based on your specific setup
CAM_WIDE = 1      # Master
CAM_CLOSE_A = 0   # Near
CAM_CLOSE_B = 2   # Far

# TUNING KNOBS (Adjust if it misses rallies)
# Lower threshold = Detects smaller movements (like just a serve toss)
MOTION_THRESHOLD = 6.0    # Was 5.0. Lowered to catch "lazy" movement.

# Lower duration = Keeps short points (Aces, 2-shot rallies)
MIN_RALLY_DURATION = 2.0  # Was 3.0. Lowered to catch the 19s-21s point.

# Merge Gap = How long they must stand still to trigger a "Cut"
MERGE_GAP = 2.0           # If action stops for 3s, we cut to close-up.


# ==========================================
# 1. MOTION DETECTOR
# ==========================================
def analyze_motion_energy(video_path):
    print(f"👁️  Scanning pixels in: {video_path}")
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        raise ValueError("Could not open video")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps
    
    print(f"   - Duration: {duration:.1f}s | FPS: {fps}")
    
    # We will sample every Nth frame to be fast
    sample_rate = 5 # Check every 5th frame
    prev_frame = None
    motion_timeline = [] # (timestamp, is_moving)
    
    # Resize for speed
    process_width = 640 
    process_height = 360

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        if frame_idx % sample_rate == 0:
            # 1. Grayscale & Blur
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (process_width, process_height))
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            
            if prev_frame is None:
                prev_frame = gray
                frame_idx += 1
                continue
                
            # 2. Frame Delta (Absolute difference)
            delta_frame = cv2.absdiff(prev_frame, gray)
            thresh = cv2.threshold(delta_frame, 25, 255, cv2.THRESH_BINARY)[1]
            
            # 3. Calculate "Motion Score" (Percentage of white pixels)
            motion_score = np.sum(thresh) / (process_width * process_height)
            
            # 4. Save Logic
            current_time = frame_idx / fps
            is_moving = motion_score > MOTION_THRESHOLD
            motion_timeline.append((current_time, is_moving))
            
            prev_frame = gray
            
        frame_idx += 1
        
    cap.release()
    return motion_timeline

def process_timeline(motion_data):
    """
    Converts raw (time, moving) tuples into clean (start, end) intervals.
    """
    intervals = []
    in_rally = False
    start_time = 0
    
    # 1. Raw Pass
    raw_blocks = []
    curr_start = None
    
    for t, moving in motion_data:
        if moving and not in_rally:
            in_rally = True
            curr_start = t
        elif not moving and in_rally:
            in_rally = False
            raw_blocks.append((curr_start, t))
            
    if in_rally: raw_blocks.append((curr_start, motion_data[-1][0]))

    if not raw_blocks: return []

    # 2. Merge Pass (Stitch together short gaps)
    merged = []
    if raw_blocks:
        curr_s, curr_e = raw_blocks[0]
        
        for next_s, next_e in raw_blocks[1:]:
            gap = next_s - curr_e
            if gap < MERGE_GAP:
                # Merge them
                curr_e = next_e
            else:
                # Save and start new
                merged.append((curr_s, curr_e))
                curr_s, curr_e = next_s, next_e
        merged.append((curr_s, curr_e))

    # 3. Filter Pass (Remove accidental bumps)
    final_intervals = [
        (s, e) for s, e in merged 
        if (e - s) > MIN_RALLY_DURATION
    ]
    
    return final_intervals

# ==========================================
# 2. MAIN JOB LOGIC
# ==========================================
def run_vision_job(payload_json_str, workdir_str="/workspace"):
    try:
        payload = json.loads(payload_json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON Payload: {e}")

    bucket_name = payload.get("bucket")
    inputs = payload.get("inputs", [])
    production_id = payload.get("productionId")
    
    workdir = Path(workdir_str).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    storage_client = storage.Client()
    
    # 1. Download Wide Master (Clip 1)
    # We assume inputs are synced. We only need to download ONE file to analyze timing.
    # Note: This requires the file to be present locally.
    # If using GCS URIs, we must download first.
    
    print(f"📥 Downloading Master Clip for Vision Analysis...")
    master_input = inputs[CAM_WIDE] # Index 1
    blob_path = master_input['path']
    local_video_path = workdir / "master_temp.mp4"
    
    blob = storage_client.bucket(bucket_name).blob(blob_path)
    blob.download_to_filename(str(local_video_path))
    print("   - Download complete.")
    
    # 2. Run Vision Analysis
    raw_motion = analyze_motion_energy(str(local_video_path))
    rally_intervals = process_timeline(raw_motion)
    
    print(f"✅ DETECTED {len(rally_intervals)} RALLIES:")
    for s, e in rally_intervals:
        print(f"   - {s:.1f}s to {e:.1f}s (Duration: {e-s:.1f}s)")

    # 3. Build EDL (Global Timeline)
    # We need Global Zero to map the relative seconds back to ISO time
    timeline_start = dateutil.parser.parse(master_input['startTime'])
    if timeline_start.tzinfo is None: timeline_start = timeline_start.replace(tzinfo=timezone.utc)
    
    # Find Global Zero across all clips just in case (assuming sync)
    global_zero = timeline_start 

    final_decisions = []
    last_end_time = 0.0
    
    # URIs for the JSON
    uris = [f"gs://{bucket_name}/{inp['path']}" for inp in inputs]

    for i, (start_s, end_s) in enumerate(rally_intervals):
        
        # Dead Time (Walking)
        if start_s > last_end_time:
            # Reaction Shot (Close)
            reaction_cam = CAM_CLOSE_B if i % 2 == 0 else CAM_CLOSE_A
            final_decisions.append({
                "timestamp_global": (global_zero + timedelta(seconds=last_end_time)).isoformat(),
                "event_phase": "REACTION",
                "camera_index": reaction_cam,
                "camera_uri": uris[reaction_cam],
                "reason": "Low Motion (Walking)"
            })
            
        # Action (Rally)
        # Pad the start slightly (-1s) to catch the toss
        actual_start = max(0, start_s - 1.0)
        final_decisions.append({
            "timestamp_global": (global_zero + timedelta(seconds=actual_start)).isoformat(),
            "event_phase": "ACTION",
            "camera_index": CAM_WIDE,
            "camera_uri": uris[CAM_WIDE],
            "reason": "High Motion (Rally Detected)"
        })
        
        last_end_time = end_s

    # Final tail
    final_decisions.append({
        "timestamp_global": (global_zero + timedelta(seconds=last_end_time)).isoformat(),
        "event_phase": "REACTION",
        "camera_index": CAM_CLOSE_A,
        "camera_uri": uris[CAM_CLOSE_A],
        "reason": "Match End"
    })

    # 4. Save Output
    final_output = {
        "production_id": production_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ai_data": {
            "decisions": final_decisions,
            "roles": { "wide_index": CAM_WIDE }
        }
    }
    
    output_filename = f"analysis_{production_id}.json"
    local_output_path = workdir / output_filename
    with open(local_output_path, 'w') as f:
        json.dump(final_output, f, indent=2)

    gcs_output_path = f"productions/{production_id}/analysis.json"
    print(f"⬆️ Uploading results...")
    storage_client.bucket(bucket_name).blob(gcs_output_path).upload_from_filename(str(local_output_path))
    print(f"✅ Vision Job Complete.")
    
    # Cleanup
    local_video_path.unlink(missing_ok=True)

def main():
    print(f"Vision is starting")
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    parser.add_argument("--workdir", default="/workspace")
    args = parser.parse_args()
    run_vision_job(args.payload, args.workdir)

if __name__ == "__main__":
    sys.exit(main())