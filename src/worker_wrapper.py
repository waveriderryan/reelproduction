#!/usr/bin/env python3
import argparse
import json
import os
import sys
import traceback
from google.cloud import pubsub_v1

# Import the main logic from productionJob
from productionJob import main as run_production_job

def process_message(message, args):
    """
    Translates Pub/Sub message -> CLI args -> productionJob.main()
    """
    print(f"📨 Received job payload: {message.data}")
    
    try:
        payload = json.loads(message.data.decode("utf-8"))
        
        # Construct arguments list for productionJob
        # We map the JSON keys to the expected CLI flags
        job_args = []
        
        job_args.extend(["--bucket", payload['bucket']])
        
        # Handle inputs list
        for inp in payload['inputs']:
            job_args.extend(["--input", inp])
            
        # Handle outputs list
        for out in payload['outputs']:
            job_args.extend(["--outputGCS", out])
            
        if 'workdir' in payload:
            job_args.extend(["--workdir", payload['workdir']])
            
        print(f"🚀 Invoking productionJob with args: {job_args}")

        # --- EXECUTE JOB ---
        exit_code = run_production_job(job_args)

        if exit_code == 0:
            print("✅ Job completed successfully.")
            message.ack()
            # Exit container to stop billing for this Spot VM
            print("💤 Shutting down container...")
            os._exit(0)
        else:
            print(f"❌ Job failed with exit code {exit_code}")
            # Nack to retry if you want, or Ack and report failure to separate topic
            message.nack() 
            os._exit(1)

    except Exception as e:
        print(f"🔥 Critical error processing message: {e}")
        traceback.print_exc()
        message.nack()
        os._exit(1)

def listen_for_work():
    parser = argparse.ArgumentParser(description="ReelChains Worker Wrapper")
    parser.add_argument("--project_id", required=True)
    parser.add_argument("--subscription_id", required=True)
    parser.add_argument("--timeout_seconds", type=int, default=600)
    args = parser.parse_args()

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(args.project_id, args.subscription_id)

    print(f"👂 Listening on {subscription_path} for up to {args.timeout_seconds}s...")

    def callback(message):
        process_message(message, args)

    # Open the subscription
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)

    try:
        # Block the main thread until timeout
        streaming_pull_future.result(timeout=args.timeout_seconds)
    except Exception as e:
        print(f"⏰ Timeout reached or error: {e}")
        streaming_pull_future.cancel()
        print("💤 Shutting down idle worker.")
        os._exit(0)

if __name__ == "__main__":
    listen_for_work()