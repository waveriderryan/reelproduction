#!/usr/bin/env python3
import argparse
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from google.cloud import videointelligence
from google.cloud import storage
import dateutil.parser 

# ==========================================
# CONFIGURATION
# ==========================================
# We assume Clip 1 is the Wide Master based on previous chats.
MASTER_INDEX = 1 

CAM_WIDE = 1
CAM_CLOSE_A = 0
CAM_CLOSE_B = 2

def run_video_intel_job(payload_json_str, workdir_str="/workspace"):
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
    
    # 1. Select Master Clip
    master_input = inputs[MASTER_INDEX]
    gcs_uri = f"gs://{bucket_name}/{master_input['path']}"
    print(f"📡 Sending Master Clip to Video Intelligence API: {gcs_uri}")

    # 2. Call Video Intelligence API
    video_client = videointelligence.VideoIntelligenceServiceClient()
    
    features = [videointelligence.Feature.LABEL_DETECTION]
    
    operation = video_client.annotate_video(
        request={
            "features": features,
            "input_uri": gcs_uri,
            "video_context": {
                "label_detection_config": {
                    "label_detection_mode": videointelligence.LabelDetectionMode.SHOT_AND_FRAME_MODE,
                    "stationary_camera": True 
                }
            }
        }
    )

    print("⏳ Processing video (this takes about 30-60s)...")
    result = operation.result(timeout=300)
    print("✅ Analysis Complete.")

    # --- FIX STARTS HERE ---
    if not result.annotation_results:
        print("❌ API returned no results.")
        return

    # We must access the first result in the list (since we sent 1 video)
    video_analysis = result.annotation_results[0]
    
    # 3. Parse Segments
    # Now we can access segment_label_annotations on the specific video result
    relevant_labels = ["tennis", "racket", "sports", "athlete", "competition", "ball game", "play"]
    
    detected_segments = []

    for annotation in video_analysis.segment_label_annotations:
        label_name = annotation.entity.description.lower()
        
        # Check if this label is relevant
        if any(x in label_name for x in relevant_labels):
            for segment in annotation.segments:
                start_s = segment.segment.start_time_offset.total_seconds()
                end_s = segment.segment.end_time_offset.total_seconds()
                confidence = segment.confidence
                
                # Only trust high confidence
                if confidence > 0.60:
                    detected_segments.append((start_s, end_s))
                    print(f"   - Found '{label_name}': {start_s:.1f}s to {end_s:.1f}s ({confidence:.0%})")
    
    # --- FIX ENDS HERE ---

    # 4. Merge Overlapping Segments
    if not detected_segments:
        print("❌ No tennis action detected. Check video quality or labels.")
        # Fallback: Just return generic cut if nothing found? 
        # For now, let's exit so you see the error.
        return

    detected_segments.sort(key=lambda x: x[0])
    
    merged = []
    if detected_segments:
        curr_s, curr_e = detected_segments[0]
        for next_s, next_e in detected_segments[1:]:
            # Overlap or close gap (< 3s)
            if next_s < (curr_e + 3.0):
                curr_e = max(curr_e, next_e)
            else:
                merged.append((curr_s, curr_e))
                curr_s, curr_e = next_s, next_e
        merged.append((curr_s, curr_e))

    print(f"✅ Final Merged Rallies: {len(merged)}")
    for s, e in merged:
        print(f"   - {s:.1f}s to {e:.1f}s")

    # 5. Build EDL
    timeline_start = dateutil.parser.parse(master_input['startTime'])
    if timeline_start.tzinfo is None: timeline_start = timeline_start.replace(tzinfo=timezone.utc)
    global_zero = timeline_start 
    
    final_decisions = []
    last_end_time = 0.0
    uris = [f"gs://{bucket_name}/{inp['path']}" for inp in inputs]
    
    for i, (start_s, end_s) in enumerate(merged):
        # Dead Time (Close Up)
        if start_s > last_end_time:
            reaction_cam = CAM_CLOSE_B if i % 2 == 0 else CAM_CLOSE_A
            final_decisions.append({
                "timestamp_global": (global_zero + timedelta(seconds=last_end_time)).isoformat(),
                "event_phase": "REACTION",
                "camera_index": reaction_cam,
                "camera_uri": uris[reaction_cam],
                "reason": "No Action Label"
            })
            
        # Action (Wide)
        actual_start = max(0, start_s - 1.0)
        final_decisions.append({
            "timestamp_global": (global_zero + timedelta(seconds=actual_start)).isoformat(),
            "event_phase": "ACTION",
            "camera_index": CAM_WIDE,
            "camera_uri": uris[CAM_WIDE],
            "reason": "Action Detected (Video Intel)"
        })
        
        last_end_time = end_s

    # Final Tail
    final_decisions.append({
        "timestamp_global": (global_zero + timedelta(seconds=last_end_time)).isoformat(),
        "event_phase": "REACTION",
        "camera_index": CAM_CLOSE_A,
        "camera_uri": uris[CAM_CLOSE_A],
        "reason": "Match End"
    })

    # 6. Save
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
    print(f"✅ Video Intel Job Complete.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    parser.add_argument("--workdir", default="/workspace")
    args = parser.parse_args()
    run_video_intel_job(args.payload, args.workdir)

if __name__ == "__main__":
    sys.exit(main())