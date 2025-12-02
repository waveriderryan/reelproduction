#!/usr/bin/env python3
import argparse
import json
import os
import sys
import traceback
from google.cloud import pubsub_v1

# Import the main entry point from your existing script
# This assumes productionJob.py has a function: def main(argv=None):
import productionJob

def process_message(message, args):
    """
    Translates Pub/Sub JSON -> CLI args list -> productionJob.main()
    """
    print(f"📨 Received job payload: {message.data}")
    
    try:
        # 1. Parse the JSON payload sent by Java
        payload = json.loads(message.data.decode("utf-8"))
        
        # 2. Construct the argument list that productionJob expects
        # We manually build the list that sys.argv would usually contain
        job_args = []
        
        # --bucket
        if 'bucket' in payload:
            job_args.extend(["--bucket", payload['bucket']])
        
        # --input (Repeatable)
        # Java sends: "inputs": ["path:orient:off", "path:orient:off"]
        for inp in payload.get('inputs', []):
            job_args.extend(["--input", inp])
            
        # --outputGCS (Repeatable)
        # Java sends: "outputs": ["out1.mp4", "out2.mp4"]
        for out in payload.get('outputs', []):
            job_args.extend(["--outputGCS", out])
            
        # --workdir
        if 'workdir' in payload:
            job_args.extend(["--workdir", payload['workdir']])
            
        print(f"🚀 Coordinator invoking productionJob with args: {job_args}")

        # 3. Call the production job directly
        # We pass the args list directly to main(), avoiding subprocess overhead
        exit_code = productionJob.main(job_args)

        if exit_code == 0:
            print("✅ Job completed successfully.")
            message.ack() # Acknowledge receipt so it's removed from queue
            
            print("💤 Coordinator shutting down container to stop billing...")
            os._exit(0) # Force exit to terminate the Spot VM
        else:
            print(f"❌ Job failed with exit code {exit_code}")
            message.nack() # Negative Ack: Pub/Sub will redeliver (optional logic here)
            os._exit(1)

    except Exception as e:
        print(f"🔥 Critical error in coordinator: {e}")
        traceback.print_exc()
        message.nack()
        os._exit(1)

def listen_for_work():
    parser = argparse.ArgumentParser(description="ReelChains Production Coordinator")
    parser.add_argument("--project_id", required=True)
    parser.add_argument("--subscription_id", required=True)
    parser.add_argument("--timeout_seconds", type=int, default=600) # Default 10m wait
    args = parser.parse_args()

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(args.project_id, args.subscription_id)

    print(f"👂 Coordinator listening on {subscription_path} for up to {args.timeout_seconds}s...")

    def callback(message):
        process_message(message, args)

    # Start the pull loop
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)

    try:
        # Block main thread until the timeout is reached or a job exits the process
        streaming_pull_future.result(timeout=args.timeout_seconds)
    except Exception as e:
        print(f"⏰ Timeout reached ({args.timeout_seconds}s) or error: {e}")
        streaming_pull_future.cancel()
        print("💤 No work received. Shutting down.")
        os._exit(0)

if __name__ == "__main__":
    listen_for_work()