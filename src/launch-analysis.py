import argparse
import sys
import mysql.connector
import subprocess
import json

# DB CONFIG
config = {
  'user': 'reel_app',
  'password': 'morethancorn',
  'host': '127.0.0.1', # TCP mode
  'database': 'reel_chains_prod',
  'raise_on_warnings': True
}

def get_payload_from_db(production_id):
    # 1. Define the format string as a variable (Standard MySQL syntax, no double % needed)
    iso_format = '%Y-%m-%dT%H:%i:%s.%fZ'

    # 2. Use %s placeholders for BOTH the date format and the ID
    query = """
    SELECT JSON_OBJECT(
        'productionId', p.id,
        'bucket', 'reel-prod', 
        'type', LOWER(c.type),
        'isLeftHand', IF(c.hi5_use_left_hand = b'1', true, false),
        'inputs', (
            SELECT JSON_ARRAYAGG(
                JSON_OBJECT(
                    'path', uc.s3_key,
                    'orientation', LOWER(uc.orientation),
                    'startTime', DATE_FORMAT(uc.recording_start_time, %s)
                )
            )
            FROM user_clips uc
            WHERE uc.production_master_id = pm.id
              AND uc.clip_status = 'COMPLETE'
              AND uc.s3_key IS NOT NULL
        )
    )
    FROM productions p
    JOIN production_masters pm ON p.master_id = pm.id
    JOIN collaborations c ON pm.collaboration_id = c.id
    WHERE p.id = %s
    """
    
    try:
        cnx = mysql.connector.connect(**config)
        cursor = cnx.cursor()
        
        # 3. Pass parameters in the order they appear in the query:
        #    First %s is the format string, Second %s is the production ID
        cursor.execute(query, (iso_format, production_id))
        
        row = cursor.fetchone()
        
        if row and row[0]:
            return row[0]
        else:
            print("❌ Production not found or no clips attached.")
            return None
            
    except Exception as err:
        print(f"DB Error: {err}")
        return None
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'cnx' in locals(): cnx.close()


# --- MAIN EXECUTION ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launch AI Analysis from DB")
    parser.add_argument("production_id", help="UUID of the production to analyze")
    parser.add_argument("--audit", action="store_true", help="Run in Audit Mode (Single clip analysis)")
    parser.add_argument("--vision", action="store_true", help="Run in Vision Mode (Single clip analysis)")
    parser.add_argument("--print", action="store_true", help="Print the command")

    args = parser.parse_args()
    
    # 1. Get JSON from DB
    print(f"🔎 Fetching data for production: {args.production_id}")
    json_payload = get_payload_from_db(args.production_id)

    if args.audit:
        print("🕵️  AUDIT MODE SELECTED")
        ai_script = "ai-analysis_worker_v2.py"
    elif args.vision:
        print("vision")
        ai_script = "ai-vision.py"
    else:
        print("🎬  FULL PRODUCTION MODE")
        ai_script = "ai-analysis.py"

    

    if json_payload:
        print(f"🚀 Launching AI Analysis...")
        
        if args.print:
            print(f"{json_payload}")
            sys.exit(0)

        try:
            # Use sys.executable to guarantee we use the venv python
            subprocess.run([
                sys.executable,        # <--- Change 1: Uses the current venv python
                ai_script, 
                "--payload", json_payload,
                "--workdir", "./workspace" # <--- Change 2: Use a local folder
            ], check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ Job failed with exit code {e.returncode}")
            sys.exit(e.returncode)