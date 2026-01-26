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
# Read from Docker Env Var, default to 'production-results' for safety
RESULT_TOPIC_ID = os.environ.get("RESULT_TOPIC", "production-results")

print(f"⚙️ Configured to reply to topic: {RESULT_TOPIC_ID}")


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
        
        # FIX: Look directly in 'payload', not 'payload.metadata'
        result_data = {
            "productionId": prod_id,
            "status": status,
            "outputKey": payload.get('outputs', [""])[0], 
            "error": error_msg,
            
            # ✅ CORRECT PATH:
            "duration": payload.get('duration', 0.0),
            "orientation": payload.get('orientation', "UNKNOWN")
        }
        
        print(f"📢 Publishing result payload: {result_data}")
        
        msg_bytes = json.dumps(result_data).encode("utf-8")
        future = publisher.publish(topic_path, msg_bytes)
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
        
        print(f"🚀 Coordinator invoking productionJob (Direct Mode)...")

        # 1. Call run_job DIRECTLY
        # instead of building CLI strings, we pass the data straight in.
        # This allows us to capture the 'metadata' return value.
        output_path, metadata = productionJob.run_job(
            bucket_name=payload['bucket'],
            input_specs=payload.get('inputs', []),
            output_gcs_paths=payload.get('outputs', []), # Note: JSON key is usually 'outputs'
            workdir_str=payload.get('workdir', '/workspace')
        )

        # ---------------------------------------------------------
        # SUCCESS PATH (No exception raised)
        # ---------------------------------------------------------
        print(f"✅ Job completed successfully. Metadata captured: {metadata}")

        # 2. Inject Metadata into Payload
        # This is the vital step that was missing.
        payload['duration'] = metadata.get('duration', 0.0)
        payload['orientation'] = metadata.get('orientation', 'unknown')

        # 3. Report Success with DATA
        report_completion(args.project_id, "COMPLETED", payload)
        
        # ACK matches success: Remove from queue
        message.ack() 
        
        # Clean up the dynamic subscription
        cleanup_subscription(args.project_id, args.subscription_id)
        
        if worker_mode == 'single_task':
            print("🏁 Single task complete. Exiting container.")
            os._exit(0)

    except Exception as e:
        # ---------------------------------------------------------
        # FAILURE PATH (Exception raised by run_job)
        # ---------------------------------------------------------
        print(f"❌ Job failed with exception: {e}")
        
        # Report failure so Java marks DB as FAILED
        report_completion(args.project_id, "FAILED", payload, error_msg=str(e))
        
        print("💀 Acknowledging failed message to prevent infinite retry loop.")
        message.ack() 
        
        # Clean up the dynamic subscription
        cleanup_subscription(args.project_id, args.subscription_id)
        
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