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

# ==========================================
# 2. AUDIT LOGIC
# ==========================================
def run_audit_job(payload_json_str):
    try:
        payload = json.loads(payload_json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON Payload: {e}")

    bucket_name = payload.get("bucket")
    inputs = payload.get("inputs", [])
    production_id = payload.get("productionId")
    
    storage_client = storage.Client()
    timeline = GlobalTimeline(inputs, bucket_name)
    client = genai.Client(vertexai=True, location="us-central1")
    
    print(f"🕵️ STARTING INDIVIDUAL AUDIT for {production_id}")
    print("------------------------------------------------")

    # === LOOP THROUGH EACH CLIP INDIVIDUALLY ===
    for i, clip in enumerate(timeline.clips):
        print(f"\n🎥 ANALYZING CLIP {i}: {clip['gs_uri']}")
        
        # 1. Prepare Single Video Content
        contents = []
        video_part = types.Part.from_uri(
            file_uri=clip['gs_uri'],
            mime_type="video/mp4"
        )
        
        prompt_text = """
        You are auditing a single video file from a tennis match.
        
        TASK 1: IDENTIFY VIEW
        - Is this a "WIDE" shot (full court visible)?
        - Is this a "CLOSE-UP" (only one player visible)?
        
        TASK 2: PHYSICS LOG (Seconds)
        - List the timestamp (in seconds from 00:00) of EVERY racquet contact you see.
        - If you see a rally, list the Start (Serve) and End (last shot).
        
        CRITICAL:
        - Be precise. If the rally lasts 15 seconds, your Start and End must be 15 seconds apart.
        
        JSON OUTPUT FORMAT:
        {
          "camera_type": "WIDE",
          "visible_events": [
             {"time_sec": 12.5, "action": "Serve"},
             {"time_sec": 27.0, "action": "Point End (Net)"}
          ]
        }
        """
        
        contents.append(prompt_text)
        contents.append(video_part)

        # 2. Call Gemini
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            
            # 3. Print Result Immediately
            data = json.loads(response.text)
            print(f"   ✅ View Type: {data.get('camera_type')}")
            
            events = data.get("visible_events", [])
            if not events:
                print("   ⚠️ No events detected.")
            else:
                for event in events:
                    print(f"      - {event.get('time_sec')}s: {event.get('action')}")
                    
        except Exception as e:
            print(f"   ❌ Error analyzing clip {i}: {e}")

    print("\n------------------------------------------------")
    print("✅ Audit Complete.")

# ==========================================
# 3. ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    parser.add_argument("--workdir", default="/workspace")
    args = parser.parse_args()

    run_audit_job(args.payload)