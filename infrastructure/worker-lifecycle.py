import os
import subprocess
import time

# CONFIGURATION
DOCKER_IMAGE = "gcr.io/your-project/transcoder:latest"

def run_worker():
    print("Starting Worker Container...")
    
    try:
        # Run Docker in the foreground. Script BLOCKS here until Docker exits.
        # We pass the GPU flag and mapped volumes.
        subprocess.run([
            "docker", "run", "--rm",
            "--gpus", "all",
            "-v", "/tmp:/tmp",
            # We don't pass input/output args here because 
            # the container will pull them from Pub/Sub itself.
            DOCKER_IMAGE
        ], check=True)
        
        print("Container finished successfully.")
        
    except subprocess.CalledProcessError:
        print("Container crashed or failed!")
        # Optional: Send an alert to logging here
        
    finally:
        # Whether success or failure, we SHUT DOWN.
        print("Shutting down VM...")
        # Give logs a moment to flush
        time.sleep(5) 
        os.system("sudo shutdown -h now")

if __name__ == "__main__":
    # Optional: Wait 10s for networking/drivers to settle before starting
    time.sleep(10)
    run_worker()