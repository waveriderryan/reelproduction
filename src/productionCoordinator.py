#!/usr/bin/env python3
import argparse
import json
import os
import sys
import traceback
from google.cloud import pubsub_v1

# Hardcoded for simplicity, or pass via args
RESULT_TOPIC_ID = "production-results"

# Import the main entry point from your existing script
# This assumes productionJob.py has a function: def main(argv=None):
import productionJob

def report_completion(project_id, status, payload, error_msg=None):
    """
    Publishes a JSON message back to Java via Pub/Sub
    """
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, RESULT_TOPIC_ID)
        
        # Helper to extract production ID from the inputs list we constructed earlier
        # (Java sent it as an attribute, but here we might need to dig it out 
        # or just rely on the output filename which usually contains the ID)
        # BETTER APPROACH: Pass production_id explicitly in the JSON payload from Java.
        
        # Let's assume payload['productionId'] exists (we will add it to Java DTO below)
        prod_id = payload.get('productionId', "UNKNOWN")
        
        # Construct result message
        result_data = {
            "productionId": prod_id,
            "status": status,
            # Assuming first output is the main one
            "outputKey": payload.get('outputs', [""])[0] if 'outputs' in payload else "", 
            "error": error_msg
        }
        
        json_str = json.dumps(result_data)
        future = publisher.publish(topic_path, json_str.encode("utf-8"))
        print(f"📢 Published result to {RESULT_TOPIC_ID}: {future.result()}")
        
    except Exception as e:
        print(f"🔥 Failed to report completion: {e}")


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
            # --- NEW: REPORT SUCCESS ---
            report_completion(args.project_id, "COMPLETED", payload)
            
            message.ack()
            os._exit(0)
        else:
            print(f"❌ Job failed with exit code {exit_code}")
            # --- NEW: REPORT FAILURE ---
            report_completion(args.project_id, "FAILED", payload, error_msg=f"Exit code {exit_code}")
            
            message.nack()
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