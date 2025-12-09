#!/usr/bin/env python3
import argparse
import json
import os
import sys
import traceback
from google.cloud import pubsub_v1

# Import your existing job logic
import productionJob

# CONFIGURATION
RESULT_TOPIC_ID = "production-results"

def report_completion(project_id, status, payload, error_msg=None):
    """Publishes a JSON message back to Java via Pub/Sub"""
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, RESULT_TOPIC_ID)
        
        prod_id = payload.get('productionId', "UNKNOWN")
        
        result_data = {
            "productionId": prod_id,
            "status": status,
            "outputKey": payload.get('outputs', [""])[0] if 'outputs' in payload else "", 
            "error": error_msg
        }
        
        json_str = json.dumps(result_data)
        future = publisher.publish(topic_path, json_str.encode("utf-8"))
        print(f"📢 Published result to {RESULT_TOPIC_ID}: {future.result()}")
        
    except Exception as e:
        print(f"🔥 Failed to report completion: {e}")

def process_message(message, args):
    """Translates Pub/Sub JSON -> CLI args list -> productionJob.main()"""
    print(f"📨 Received job payload: {message.data}")
    
    # 1. Check Worker Mode
    worker_mode = os.environ.get('WORKER_MODE', 'single_task') # Default to single_task for safety

    try:
        payload = json.loads(message.data.decode("utf-8"))
        
        # 2. Construct Args
        job_args = []
        if 'bucket' in payload: job_args.extend(["--bucket", payload['bucket']])
        for inp in payload.get('inputs', []): job_args.extend(["--input", inp])
        for out in payload.get('outputs', []): job_args.extend(["--outputGCS", out])
        if 'workdir' in payload: job_args.extend(["--workdir", payload['workdir']])
            
        print(f"🚀 Coordinator invoking productionJob...")

        # 3. Call the Job
        exit_code = productionJob.main(job_args)

        if exit_code == 0:
            print("✅ Job completed successfully.")
            report_completion(args.project_id, "COMPLETED", payload)
            message.ack()
            
            # --- EXIT LOGIC ---
            if worker_mode == 'single_task':
                print("🏁 Single task complete. Exiting container.")
                os._exit(0) # Hard exit to ensure container stops
            else:
                print("🔄 Mode is 'loop'. Waiting for next job...")
                
        else:
            print(f"❌ Job failed with exit code {exit_code}")
            report_completion(args.project_id, "FAILED", payload, error_msg=f"Exit code {exit_code}")
            message.nack() # Retry?
            
            # If failed, we usually want to exit in single task mode too
            if worker_mode == 'single_task':
                os._exit(1)

    except Exception as e:
        print(f"🔥 Critical error in coordinator: {e}")
        traceback.print_exc()
        message.nack()
        if worker_mode == 'single_task':
            os._exit(1)

def listen_for_work():
    print("Begin of listen_for_work()")
    parser = argparse.ArgumentParser()
    # Updated to use Environment Variables as defaults (Cleaner for Docker)
    parser.add_argument("--project_id", default=os.environ.get("GCP_PROJECT"))
    parser.add_argument("--subscription_id", default=os.environ.get("PUBSUB_SUBSCRIPTION"))
    parser.add_argument("--timeout_seconds", type=int, default=600)
    args = parser.parse_args()

    if not args.project_id or not args.subscription_id:
        print("❌ Error: Must provide project_id and subscription_id via Args or Env Vars")
        sys.exit(1)

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(args.project_id, args.subscription_id)

    print(f"👂 Coordinator listening on {subscription_path} (Mode: {os.environ.get('WORKER_MODE', 'single_task')})...")

    streaming_pull_future = subscriber.subscribe(subscription_path, callback=lambda msg: process_message(msg, args))

    try:
        # Block until timeout
        streaming_pull_future.result(timeout=args.timeout_seconds)
    except Exception as e:
        print(f"⏰ Timeout reached ({args.timeout_seconds}s) or error: {e}")
        streaming_pull_future.cancel()
        
        # If we timed out and found no work, we should exit so the VM shuts down
        print("💤 No work received. Shutting down container.")
        os._exit(0)

if __name__ == "__main__":
    listen_for_work()