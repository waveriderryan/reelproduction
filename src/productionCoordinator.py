#!/usr/bin/env python3
import argparse
import json
import os
import sys
import traceback
import urllib.request
from google.cloud import pubsub_v1

# Import your existing job logic
import productionJob

# CONFIGURATION
RESULT_TOPIC_ID = "production-results"


def get_gcp_instance_name():
    """Fetches the VM name directly from Google Metadata Server"""
    try:
        req = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/name")
        req.add_header("Metadata-Flavor", "Google")
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.read().decode("utf-8").strip()
    except Exception as e:
        print(f"⚠️ Could not fetch instance name from metadata: {e}")
        return "unknown"

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

def cleanup_subscription(project_id, subscription_id):
    """
    Checks if the subscription is a temporary 'sub-collab-' one.
    If so, deletes it to prevent clutter.
    """
    # Only delete if it matches your temporary naming convention
    if "sub-collab-" in subscription_id:
        print(f"🧹 Detected temporary subscription '{subscription_id}'. Deleting...")
        try:
            subscriber = pubsub_v1.SubscriberClient()
            subscription_path = subscriber.subscription_path(project_id, subscription_id)
            subscriber.delete_subscription(request={"subscription": subscription_path})
            print(f"✅ Subscription deleted successfully.")
        except Exception as e:
            print(f"⚠️ Warning: Could not delete subscription: {e}")
    else:
        print(f"ℹ️ Subscription '{subscription_id}' is not temporary. Leaving it active.")

def process_message(message, args):
    """Translates Pub/Sub JSON -> CLI args list -> productionJob.main()"""
        
    # 1. RESOLVE WORKER ID (Fix for 'unknown')
    my_worker_id = os.environ.get("WORKER_ID")
    if not my_worker_id or my_worker_id == "unknown":
        my_worker_id = get_gcp_instance_name()

    target_vm = message.attributes.get("target_vm")

    # 2. TARGETED DELIVERY CHECK
    if target_vm and target_vm != my_worker_id:
        print(f"🚫 Ignoring job intended for '{target_vm}' (I am '{my_worker_id}')")
        message.nack()
        return 
   
    # ---------------------------------------------------------------
    # 2. STANDARD PROCESSING
    # ---------------------------------------------------------------
    print(f"📨 Received job payload: {message.data}")
    worker_mode = os.environ.get('WORKER_MODE', 'single_task')

    try:
        payload = json.loads(message.data.decode("utf-8"))
        
        # Construct Args
        job_args = []
        if 'bucket' in payload: job_args.extend(["--bucket", payload['bucket']])
        for inp in payload.get('inputs', []): job_args.extend(["--input", inp])
        for out in payload.get('outputs', []): job_args.extend(["--outputGCS", out])
        if 'workdir' in payload: job_args.extend(["--workdir", payload['workdir']])
            
        print(f"🚀 Coordinator invoking productionJob...")

        # Call the Job
        exit_code = productionJob.main(job_args)

        if exit_code == 0:
            print("✅ Job completed successfully.")
            report_completion(args.project_id, "COMPLETED", payload)
            
            # ACK matches success: Remove from queue
            message.ack() 
            
            # Clean up the dynamic subscription
            cleanup_subscription(args.project_id, args.subscription_id)
            
            if worker_mode == 'single_task':
                print("🏁 Single task complete. Exiting container.")
                os._exit(0)
                
        else:
            print(f"❌ Job failed with exit code {exit_code}")
            # Report failure so Java marks DB as FAILED (stopping the logic loop)
            report_completion(args.project_id, "FAILED", payload, error_msg=f"Exit code {exit_code}")
            
            # CRITICAL FIX: ACK the message anyway!
            # If we NACK, it just loops forever. We have reported the failure, so we are done with this message.
            print("💀 Acknowledging failed message to prevent infinite retry loop.")
            message.ack() 
            
            # Clean up the dynamic subscription even on failure
            cleanup_subscription(args.project_id, args.subscription_id)
            
            if worker_mode == 'single_task':
                # Exit 0 prevents cloud provider from retrying the VM itself as a "crash"
                # But you can use 1 if you want the orchestrator to know it 'failed'
                os._exit(1)

    except Exception as e:
        print(f"🔥 Critical error in coordinator: {e}")
        traceback.print_exc()
        
        try:
            # Attempt to report generic crash
            report_completion(args.project_id, "FAILED", payload if 'payload' in locals() else {}, error_msg=str(e))
            
            # CRITICAL FIX: ACK here too.
            message.ack() 
            cleanup_subscription(args.project_id, args.subscription_id)
        except Exception as inner_e:
            print(f"Could not report/ack crash: {inner_e}")
            # Only NACK if we literally cannot talk to the outside world
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

    # Pass args to the callback so we have access to project_id/subscription_id inside
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=lambda msg: process_message(msg, args))

    try:
        # Block until timeout
        streaming_pull_future.result(timeout=args.timeout_seconds)
    except Exception as e:
        print(f"⏰ Timeout reached ({args.timeout_seconds}s) or error: {e}")
        streaming_pull_future.cancel()
        
        # Check if we should delete the subscription on timeout (zombie vm case)
        # Usually unsafe to delete on timeout unless we are sure it was a one-off
        # But if you want aggressive cleanup for single_task mode:
        if os.environ.get('WORKER_MODE') == 'single_task':
             print("💤 Timeout. Cleaning up and shutting down.")
             cleanup_subscription(args.project_id, args.subscription_id)
             os._exit(0)
        else:
             print("💤 Loop mode timeout. Restarting loop...")

if __name__ == "__main__":
    listen_for_work()