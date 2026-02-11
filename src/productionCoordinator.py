#!/usr/bin/env python3
import argparse
import json
import os
import time
import sys
import traceback
import urllib.request
from google.cloud import pubsub_v1
from google.cloud import storage
from google.api_core.exceptions import PreconditionFailed


storage_client = storage.Client()


# Import your existing job logic
import productionJob

# CONFIGURATION
# Read from Docker Env Var, default to 'production-results' for safety
RESULT_TOPIC_ID = os.environ.get("RESULT_TOPIC", "production-results")

print(f"⚙️ Configured to reply to topic: {RESULT_TOPIC_ID}")

def acquire_gcs_lock(bucket_name: str, production_id: str):
    """
    Attempts to acquire a distributed lock for this productionId.
    Raises PreconditionFailed if lock already exists.
    """
    lock_path = f"locks/{production_id}.lock"
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(lock_path)

    # Atomic: only succeeds if object does NOT exist
    blob.upload_from_string(
        data="locked",
        if_generation_match=0
    )

    print(f"🔒 Acquired GCS lock: {lock_path}")
    return lock_path


def release_gcs_lock(bucket_name: str, lock_path: str):
    """Releases the distributed lock."""
    try:
        bucket = storage_client.bucket(bucket_name)
        bucket.blob(lock_path).delete()
        print(f"🔓 Released GCS lock: {lock_path}")
    except Exception as e:
        print(f"⚠️ Failed to release lock {lock_path}: {e}")


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
    """Translates Pub/Sub JSON -> productionJob.run_job() with full safety."""

    # ---------------------------------------------------------
    # Resolve worker identity
    # ---------------------------------------------------------
    my_worker_id = os.environ.get("WORKER_ID")
    if not my_worker_id or my_worker_id == "unknown":
        my_worker_id = get_gcp_instance_name()

    target_vm = message.attributes.get("target_vm")

    # ---------------------------------------------------------
    # Targeted delivery check
    # ---------------------------------------------------------
    if target_vm and target_vm != my_worker_id:
        print(f"🚫 Ignoring job intended for '{target_vm}' (I am '{my_worker_id}')")
        message.nack()
        return

    print(f"📨 Received job payload: {message.data}")
    worker_mode = os.environ.get("WORKER_MODE", "single_task")

    # ---------------------------------------------------------
    # Variables that must exist for finally{}
    # ---------------------------------------------------------
    lock_path = None
    bucket_name = None
    production_id = None
    payload = None

    try:
        # -----------------------------------------------------
        # Parse payload
        # -----------------------------------------------------
        payload = json.loads(message.data.decode("utf-8"))

        production_id = payload["productionId"]
        bucket_name = payload["bucket"]

        # -----------------------------------------------------
        # Acquire distributed GCS lock (atomic)
        # -----------------------------------------------------
        try:
            lock_path = acquire_gcs_lock(bucket_name, production_id)
        except PreconditionFailed:
            print(f"⏭️ Lock already exists for {production_id}. Skipping job.")
            message.ack()
            return  # IMPORTANT: do not continue

        # -----------------------------------------------------
        # Create per-job work directory
        # -----------------------------------------------------
        job_workdir = f"/workspace/jobs/{production_id}"
        os.makedirs(job_workdir, exist_ok=True)
        print(f"📁 Using job workdir: {job_workdir}")

        # -----------------------------------------------------
        # Execute job
        # -----------------------------------------------------
        print("🚀 Coordinator invoking productionJob (Direct Mode)...")

        type  = payload.get("type", "multi_view")
        is_left_hand  = payload.get("isLeftHand", False)

        raw_is_left_hand = payload.get("isLeftHand", False)

        if isinstance(raw_is_left_hand, str):
            is_left_hand = raw_is_left_hand.strip().lower() == "true"
        else:
            is_left_hand = bool(raw_is_left_hand)

        output_path, metadata = productionJob.run_job(
            bucket_name=bucket_name,
            input_specs=payload.get("inputs", []),
            output_gcs_paths=payload.get("outputs", []),
            workdir_str=job_workdir,
            production_type=type,
            is_left_hand=is_left_hand,
        )

        # -----------------------------------------------------
        # Success path
        # -----------------------------------------------------
        print(f"✅ Job completed successfully. Metadata captured: {metadata}")

        payload["duration"] = metadata.get("duration", 0.0)
        payload["orientation"] = metadata.get("orientation", "unknown")

        report_completion(args.project_id, "COMPLETED", payload)
        message.ack()

        cleanup_subscription(args.project_id, args.subscription_id)

        if worker_mode == "single_task":
            print("🏁 Single task complete. Exiting container.")
            os._exit(0)

    except Exception as e:
        # -----------------------------------------------------
        # Failure path
        # -----------------------------------------------------
        print(f"❌ Job failed with exception: {e}")
        traceback.print_exc()

        # Only report failure if we actually parsed a payload
        if payload:
            report_completion(
                args.project_id,
                "FAILED",
                payload,
                error_msg=str(e),
            )

        print("💀 Acknowledging failed message to prevent infinite retry loop.")
        message.ack()

        cleanup_subscription(args.project_id, args.subscription_id)

        if worker_mode == "single_task":
            os._exit(1)

    finally:
        # -----------------------------------------------------
        # Always release lock if we acquired it
        # -----------------------------------------------------
        if lock_path and bucket_name:
            release_gcs_lock(bucket_name, lock_path)


# ---------------------------------------------------------
# Helper: The Safety Wrapper
# ---------------------------------------------------------
def safe_process_callback(message, args):
    """
    Wraps the real processing logic to add:
    1. STALE CHECK: Discards messages older than 20 minutes (Zombies)
    2. LOGGING: clear visibility of what we are picking up
    """
    try:
        # Parse the JSON to check the timestamp
        # (Assuming your Java Payload now includes "timestamp": <long_millis>)
        data = json.loads(message.data.decode("utf-8"))
        
        # Calculate Age
        # Java uses Milliseconds. Python time.time() is Seconds.
        current_time_ms = time.time() * 1000
        msg_timestamp = data.get("timestamp", current_time_ms) # Default to now if missing
        msg_age_ms = current_time_ms - msg_timestamp
        
        # 🛑 STALE CHECK: 20 Minutes (1,200,000 ms)
        # If the message has been sitting in the queue for > 20 mins, it's from a dead run.
        if msg_age_ms > 1200000:
            print(f"🧟‍♂️ ZOMBIE DETECTED: Discarding stale message (Age: {msg_age_ms/1000:.1f}s).")
            message.ack() # Remove from queue so it doesn't come back
            return

        # ✅ If fresh, run the REAL logic
        # (Assuming process_message is defined elsewhere in your file)
        print(f"✅ Processing fresh message (Age: {msg_age_ms/1000:.1f}s)...")
        process_message(message, args)
        
    except Exception as e:
        print(f"⚠️ Error in safety wrapper: {e}")
        # If parsing fails, we usually Ack or Nack depending on policy.
        # Nacking here to be safe so we don't lose data, but be careful of poison loops.
        message.nack() 


# ---------------------------------------------------------
# Main Listener
# ---------------------------------------------------------
def listen_for_work():
    print("Begin of listen_for_work()")
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", default=os.environ.get("GCP_PROJECT"))
    parser.add_argument("--subscription_id", default=os.environ.get("PUBSUB_SUBSCRIPTION"))
    parser.add_argument("--timeout_seconds", type=int, default=1200) # default to 20 minutes
    args = parser.parse_args()

    if not args.project_id or not args.subscription_id:
        print("❌ Error: Must provide project_id and subscription_id via Args or Env Vars")
        sys.exit(1)

    # 1. CONCURRENCY CONTROL
    # This prevents the "Double-Tap" crash. 
    # We tell Google: "Do not give me more than 1 message at a time."
    flow_control = pubsub_v1.types.FlowControl(max_messages=1)

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(args.project_id, args.subscription_id)

    print(f"👂 Coordinator listening on {subscription_path} (Mode: {os.environ.get('WORKER_MODE', 'single_task')})...")

    # 2. SUBSCRIBE with Flow Control & Wrapper
    streaming_pull_future = subscriber.subscribe(
        subscription_path, 
        callback=lambda msg: safe_process_callback(msg, args), # Use the wrapper!
        flow_control=flow_control # Apply the limit!
    )

    try:
        # Block until timeout
        streaming_pull_future.result(timeout=args.timeout_seconds)
    except Exception as e:
        print(f"⏰ Timeout reached ({args.timeout_seconds}s) or error: {e}")
        streaming_pull_future.cancel()
        
        if os.environ.get('WORKER_MODE') == 'single_task':
             print("💤 Timeout. Cleaning up and shutting down.")
             cleanup_subscription(args.project_id, args.subscription_id)
             os._exit(0)
        else:
             print("💤 Loop mode timeout. Restarting loop...")

if __name__ == "__main__":
    listen_for_work()