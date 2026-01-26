#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys
from google.cloud import storage

# Helper imports
from ffmpegVideoRender import renderFinalVideo
from ffmpegAudioTools import extractAudioTrimmed, extractAudioUntrimmed, mixAudioTracksTrim, mixAudioTracksTimeline, muxVideoAudio, muxVideoWithTimelineAudio

import subprocess
import json

def get_video_duration_seconds(video_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        video_path,
    ]
    out = subprocess.check_output(cmd).decode().strip()
    return float(out)

def choose_thumbnail_time(duration: float) -> float:
    # Avoid black frames at t=0 and EOF edge cases
    if duration < 1.0:
        return 0.0
    return max(0.1, duration * 0.5)

def extract_thumbnail(video_path: str, output_jpeg: str, timestamp: float):
    cmd = [
        "ffmpeg", "-y",
        "-skip_frame", "nokey",     # 🔑 decode ONLY keyframes
        "-ss", f"{timestamp:.3f}",  # seek to nearest keyframe at/after timestamp
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        output_jpeg,
    ]
    subprocess.run(cmd, check=True)


def get_video_metadata(file_path):
    print(f"🔍 Probing metadata for: {file_path}")
    
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-select_streams", "v:0",  # Only look at video stream
        file_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        
        # 1. Get Duration
        duration = 0.0
        if 'format' in data and 'duration' in data['format']:
            try:
                duration = float(data['format']['duration'])
            except ValueError:
                pass

        # 2. Get Raw Rotation & Dimensions
        rotation = 0
        width = 0
        height = 0
        
        try:
            stream = data['streams'][0]
            width = int(stream.get('width', 0))
            height = int(stream.get('height', 0))
            
            # Extract Rotation (Tags or Side Data)
            if 'tags' in stream and 'rotate' in stream['tags']:
                rotation = int(float(stream['tags']['rotate']))
            elif 'side_data_list' in stream:
                for side_data in stream['side_data_list']:
                    if 'rotation' in side_data:
                        rotation = int(float(side_data['rotation']))

        except Exception:
            pass

        # 3. Calculate "Portrait" vs "Landscape"
        # If rotation is 90 or 270, width and height are swapped visually
        if abs(rotation) in [90, 270]:
            effective_width = height
            effective_height = width
        else:
            effective_width = width
            effective_height = height
            
        # Determine string
        orientation_str = "portrait" if effective_height > effective_width else "landscape"

        print(f"✅ Metadata: {duration}s, {orientation_str} (Rot:{rotation}, {width}x{height})")
        
        return {
            "duration": duration,
            "orientation": orientation_str  # Now returns "landscape" or "portrait"
        }

    except Exception as e:
        print(f"❌ CRITICAL: FFprobe failed: {e}")
        return {"duration": 0.0, "orientation": "landscape"}
    
def parseInputSpec(spec: str):
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid --input format '{spec}'. Expected path:orientation:offset")
    gcsPath, orientation, offsetStr = parts
    return gcsPath, orientation.lower().strip(), float(offsetStr)

def downloadFromGCS(bucketName, gcsPath, localPath, client):
    print(f"⬇️ Downloading gs://{bucketName}/{gcsPath}...")
    bucket = client.bucket(bucketName)
    blob = bucket.blob(gcsPath)
    localPath.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(localPath))

def uploadToGCS(bucketName, gcsPath, localPath, client):
    print(f"⬆️ Uploading {localPath} -> gs://{bucketName}/{gcsPath}...")
    bucket = client.bucket(bucketName)
    blob = bucket.blob(gcsPath)
    blob.upload_from_filename(str(localPath))

def run_job(bucket_name, input_specs, output_gcs_paths, workdir_str="/workspace"):
    """
    The main logic function called by productionCoordinator.
    Returns: (final_output_path, metadata_dict)
    """
    workdir = Path(workdir_str).resolve()
    thumbnail_path = workdir / "thumbnail.jpg"

    workdir.mkdir(parents=True, exist_ok=True)
    client = storage.Client()

    print(f"🎬 Starting Job: {len(input_specs)} inputs -> {len(output_gcs_paths)} outputs")

    # ---------------------------------------------------------
    # 1. Download Inputs
    # ---------------------------------------------------------
    local_paths = []
    orientations = []
    offsets = []
    
    try:
        for idx, spec in enumerate(input_specs, 1):
            g_path, orient, off = parseInputSpec(spec) # Ensure this helper is defined
            local_file = workdir / f"clip{idx}_{Path(g_path).name}"
            
            print(f"⬇️ Downloading {g_path}...")
            downloadFromGCS(bucket_name, g_path, local_file, client)
            
            local_paths.append(local_file)
            orientations.append(orient)
            offsets.append(off)
    except Exception as e:
        raise RuntimeError(f"Failed during input download: {e}")

    # ---------------------------------------------------------
    # 2. Render Video Track (Silent)
    # ---------------------------------------------------------
    final_video_track = workdir / "final_video_track.mp4"
    metadata = {}

    try:
        print(" Finding clip durations...")
        clip_durations = [
            get_video_duration_seconds(str(p))
            for p in local_paths
        ]

        latest_start = max(offsets)

        start_times = [
            latest_start - off
            for off in offsets
        ]

        base_duration = max(
            start_times[i] + clip_durations[i]
            for i in range(len(local_paths))
        ) + 0.25   # small safety pad

        print(f"🎥 !Rendering video track...base duration is {base_duration}")
        render_mode = renderFinalVideo(local_paths, orientations, offsets, final_video_track, start_times, base_duration)
        
        # ✅ Extract Metadata HERE (while we have the clean video track)
        # This is safe because orientation/duration won't change after audio muxing
        metadata = get_video_metadata(final_video_track)
        print(f"📏 Metadata extracted: {metadata}")

    except Exception as e:
        raise RuntimeError(f"Video render failed: {e}")

    assert final_video_track.exists(), f"Video missing: {final_video_track}"
    assert final_video_track.stat().st_size > 0, "Video file is empty"

    # ---------------------------------------------------------
    # 3. Process Audio & Mux
    # ---------------------------------------------------------
    primary_output_path = None
    uploaded_outputs = []

    try:
        print("🔊 Processing audio...")
        audio_files = []
        
        # Extract audio from source clips
        for i, video_path in enumerate(local_paths):
            audio_out = workdir / f"audio_track_{i}.aac"
            if render_mode == "trim":
                extractAudioTrimmed(video_path, audio_out, offsets[i])
            else:
                extractAudioUntrimmed(video_path, audio_out)

            audio_files.append(audio_out)

        n_outputs = len(output_gcs_paths)
        
        # Strategy A: Mixed Audio (1 Output)
        if n_outputs == 1:
            mixed_audio = workdir / "mixed_audio.aac"
            if (render_mode == "trim"):
                mixAudioTracksTrim(audio_files, mixed_audio)
            else:
                mixAudioTracksTimeline(audio_files, mixed_audio, start_times)
            final_output = workdir / "final_output.mp4"
            muxVideoAudio(final_video_track, mixed_audio, final_output)
            
            print(f"⬆️ Uploading to {output_gcs_paths[0]}...")
            uploadToGCS(bucket_name, output_gcs_paths[0], final_output, client)
            uploaded_outputs.append(output_gcs_paths[0])
            
            primary_output_path = final_output

        # Strategy B: Separate Outputs (N Outputs)
        else:
            for i, out_gcs_path in enumerate(output_gcs_paths):
                # Unique output for each audio track
                final_output = workdir / f"final_output_{i}.mp4"
                
                if (render_mode == "trim"): 
                    # Mux the SAME video with DIFFERENT source audio
                    muxVideoAudio(final_video_track, audio_files[i], final_output)
                else:
                    muxVideoWithTimelineAudio(final_video_track, audio_files[i], start_times[i], final_output)
                

                print(f"⬆️ Uploading variation {i} to {out_gcs_path}...")
                uploadToGCS(bucket_name, out_gcs_path, final_output, client)
                uploaded_outputs.append(out_gcs_path)

                # We just return the first one as the "primary" for logging purposes
                if i == 0:
                    primary_output_path = final_output

    except Exception as e:
        raise RuntimeError(f"Audio/Mux processing failed: {e}")
    
    # ---------------------------------------------------------
    # 3.5 Generate Thumbnail(s)
    # ---------------------------------------------------------
    try:
        print("🖼️ Generating thumbnail...")

        duration = get_video_duration_seconds(str(final_video_track))
        thumb_time = choose_thumbnail_time(duration)

        extract_thumbnail(
            video_path=str(final_video_track),
            output_jpeg=str(thumbnail_path),
            timestamp=thumb_time,
        )

        # Option A: upload a JPEG per output (same bytes, different name)
        for out_gcs_path in uploaded_outputs:
            base_name = Path(out_gcs_path).with_suffix("").name
            thumb_gcs_path = f"productions/{base_name}.jpg"

            uploadToGCS(
                bucket_name,
                thumb_gcs_path,
                thumbnail_path,
                client,
            )

    except Exception as e:
        # Thumbnail failure must NEVER fail the job
        print(f"⚠️ Thumbnail generation failed: {e}")

    print("✅ Job Complete.")
    
    # ---------------------------------------------------------
    # 4. Return Data to Coordinator
    # ---------------------------------------------------------
    # We return the file path (in case Coordinator wants it) and the metadata
    return primary_output_path, metadata


# ==========================================
# CLI Wrapper (For testing or standalone use)
# ==========================================
def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--input", required=True, action="append")
    parser.add_argument("--outputGCS", required=True, action="append")
    parser.add_argument("--workdir", default="/workspace")
    
    args = parser.parse_args(argv)

    try:
        # Call the logic function
        out_path, meta = run_job(args.bucket, args.input, args.outputGCS, args.workdir)
        
        # If running from CLI, maybe print the metadata as JSON to stdout so it can be piped?
        # print(json.dumps(meta))
        return 0
    except Exception as e:
        print(f"❌ Critical Failure: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())