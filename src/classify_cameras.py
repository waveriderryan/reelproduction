import argparse
import sys
import json
import vertexai
from vertexai.generative_models import GenerativeModel, Part, SafetySetting

def classify_camera_angles(project_id, location, uris):
    """
    Sends video URIs to Gemini to identify their roles (Wide vs Close).
    """
    # 1. Initialize Vertex AI
    vertexai.init(project=project_id, location=location)
    model = GenerativeModel("gemini-1.5-pro-002")

    # 2. Load Videos (Cloud References)
    # Gemini 1.5 Pro can handle multiple video streams simultaneously.
    video_parts = []
    video_map = {} # Map index to filename for safety
    
    print(f"👀 analyzing {len(uris)} videos...")

    for idx, uri in enumerate(uris):
        filename = uri.split('/')[-1]
        video_map[f"video_{idx}"] = filename
        
        # Create the Part object
        part = Part.from_uri(uri=uri, mime_type="video/mp4")
        video_parts.append(part)

    # 3. The Classification Prompt
    # We map the videos by index (0, 1, 2) to avoid confusion.
    prompt_text = f"""
    You are a professional Video Engineer. I have provided {len(uris)} synchronized video angles of a tennis match.

    Your Task: Classify the "Camera Role" for each video stream.
    
    Roles to assign:
    - "MASTER_WIDE": The main broadcast angle showing the full court, net, and baselines.
    - "PLAYER_CLOSE": A zoomed-in angle focused on a specific player.
    - "SIDELINE/CROWD": A generic side angle, bench view, or audience view.
    - "UNKNOWN": If the video is black, blurry, or unrecognizable.

    Instructions:
    1. Analyze the visual content of each video.
    2. Return a strict JSON object mapping the index (0, 1, 2...) to the Role.
    3. Do NOT explain your reasoning. JSON ONLY.

    Expected Output Format:
    {{
        "0": "MASTER_WIDE",
        "1": "PLAYER_CLOSE",
        "2": "PLAYER_CLOSE"
    }}
    """

    # 4. Generate Content
    generation_config = {
        "response_mime_type": "application/json",
        "temperature": 0.0, # Deterministic output
    }

    response = model.generate_content(
        video_parts + [prompt_text],
        generation_config=generation_config
    )

    # 5. Parse and Map back to Filenames
    try:
        result_json = json.loads(response.text)
        
        # Convert "0" -> "gs://..." for the final output
        final_mapping = {}
        for idx_str, role in result_json.items():
            idx = int(idx_str)
            original_uri = uris[idx]
            final_mapping[original_uri] = role
            
        return final_mapping

    except json.JSONDecodeError:
        print("❌ Error: AI did not return valid JSON.")
        print("Raw Response:", response.text)
        return {}

# ==========================================
# CLI WRAPPER
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Camera Classifier")
    parser.add_argument("--project", required=True, help="GCP Project ID")
    parser.add_argument("--location", default="us-central1", help="GCP Region")
    parser.add_argument("--inputs", nargs='+', required=True, help="List of gs:// paths")
    
    args = parser.parse_args()

    try:
        mapping = classify_camera_angles(args.project, args.location, args.inputs)
        
        print("\n✅ Classification Results:")
        print(json.dumps(mapping, indent=2))
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)