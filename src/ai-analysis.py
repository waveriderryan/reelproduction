#!/usr/bin/env python3
import argparse
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from google.cloud import storage
import dateutil.parser 
from google import genai
from google.genai import types

# ==========================================
# 1. TIMELINE LOGIC
# ==========================================
class GlobalTimeline:
    def __init__(self, inputs, bucket_name):
        self.clips = []
        timestamps = []
        
        print("⏳ Synchronizing timeline...")
        for clip in inputs:
            dt = dateutil.parser.parse(clip['startTime'])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamps.append(dt)
            
            gs_uri = f"gs://{bucket_name}/{clip['path']}"
            
            self.clips.append({
                "gs_uri": gs_uri,
                "orientation": clip['orientation'],
                "start_dt": dt
            })
            
        self.global_zero = min(timestamps)
        print(f"🎬 Global Zero set to: {self.global_zero.isoformat()}")

    def get_context_for_ai(self):
        return {
            "match_start": self.global_zero.isoformat(),
            "camera_count": len(self.clips)
        }

# ==========================================
# 2. CORE JOB LOGIC
# ==========================================
def run_analysis_job(payload_json_str, workdir_str="/workspace"):
    
    # 1. Parse Payload
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

    print(f"🧠 Starting AI Analysis for Production: {production_id}")

    # 2. Initialize Timeline
    timeline = GlobalTimeline(inputs, bucket_name)
    ai_context = timeline.get_context_for_ai()
    
    # 3. SETUP GENAI CLIENT
    client = genai.Client(vertexai=True, location="us-central1")
    
    print(f"🤖 Invoking Gemini 2.0 Flash on {len(timeline.clips)} files...")
    
    # 4. Prepare Content
    contents = []
    
    # === UPDATED PROMPT: SPATIAL AWARENESS ===
    prompt_text = f"""
    You are a Motion Detection Analyst.
    I have provided {len(timeline.clips)} video inputs.
    
    TIMING CONTEXT:
    - T=0: {ai_context['match_start']}
    
    THE PROBLEM:
    Do NOT look for the ball. It is too small.
    
    YOUR MISSION:
    Identify the "Rally" timestamps by watching the PLAYERS.
    
    STATE 1: "ACTIVE RALLY"
    - Visual Cues: Players are running, strafing side-to-side, or swinging racquets.
    - Camera Rule: WIDE MASTER (Cam 0).
    - DURATION: Variable. A rally might be 3s or 30s. KEEP THE CLIP GOING as long as they are running.
    
    STATE 2: "DEAD BALL"
    - Visual Cues: Players are walking, standing still, towel off, or picking up balls.
    - Camera Rule: CLOSE-UP (Cam 1 or 2).
    - DURATION: Usually 15-20s between points.
    
    INSTRUCTIONS:
    1. Scan the video for bursts of "High Energy" (Running).
    2. Mark the START exactly when players transition from "Standing" to "Serve Motion".
    3. Mark the END exactly when players transition from "Running" to "Walking".
    
    CRITICAL:
    - If a player is running for 15 seconds, your "ACTIVE" duration MUST be 15 seconds.
    - Do not guess. Look at their legs.
    
    REQUIRED JSON OUTPUT FORMAT:
    {{
      "roles": {{
         "wide_index": 0,
         "close_up_primary_index": 1,
         "close_up_secondary_index": 2
      }},
      "decisions": [
        {{
          "timestamp_global": "ISO_STRING",
          "event_phase": "ACTION", 
          "camera_index": 0,
          "reason": "Players are running/playing",
          "visual_cue": "Both players moving rapidly"
        }},
        {{
          "timestamp_global": "ISO_STRING",
          "event_phase": "REACTION", 
          "camera_index": 2,
          "reason": "Players slowed down to walk",
          "visual_cue": "Player walking to baseline"
        }}
      ]
    }}
    """
    contents.append(prompt_text)
    
    # Attach Videos
    camera_map = {}
    for i, clip in enumerate(timeline.clips):
        print(f"   - Index {i}: {clip['gs_uri']}")
        video_part = types.Part.from_uri(
            file_uri=clip['gs_uri'],
            mime_type="video/mp4"
        )
        contents.append(video_part)
        camera_map[i] = clip['gs_uri']

    # 5. Call Gemini
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-001",
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        
        # 6. Process Response
        ai_data = json.loads(response.text)
        print("   - Received JSON. Mapping indexes to URIs...")
        
        # Map Roles
        if "roles" in ai_data:
            # FIX: Use list() to create a copy so we can modify the dict safely
            for role, idx in list(ai_data["roles"].items()): 
                if isinstance(idx, int) and idx in camera_map:
                    ai_data["roles"][f"{role}_uri"] = camera_map[idx]
        
        # Map Decisions
        if "decisions" in ai_data:
            for decision in ai_data["decisions"]:
                idx = decision.get("camera_index")
                if idx is not None and idx in camera_map:
                    decision["camera_uri"] = camera_map[idx]
        
        final_result = {
            "production_id": production_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ai_data": ai_data
        }

    except Exception as e:
        print(f"❌ AI Generation Failed: {e}")
        final_result = {"error": str(e)}

    # 7. Save & Upload
    output_filename = f"analysis_{production_id}.json"
    local_output_path = workdir / output_filename
    
    with open(local_output_path, 'w') as f:
        json.dump(final_result, f, indent=2)

    gcs_output_path = f"productions/{production_id}/analysis.json"
    
    print(f"⬆️ Uploading results to gs://{bucket_name}/{gcs_output_path}...")
    blob = storage_client.bucket(bucket_name).blob(gcs_output_path)
    blob.upload_from_filename(str(local_output_path))

    print(f"✅ Job Complete.")

# ==========================================
# 3. MAIN ENTRYPOINT
# ==========================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    parser.add_argument("--workdir", default="/workspace")

    args = parser.parse_args()

    try:
        run_analysis_job(args.payload, args.workdir)
        return 0
    except Exception as e:
        print(f"❌ Critical Failure: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())