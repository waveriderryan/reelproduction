#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys
from google.cloud import storage

# Helper imports
from ffmpegVideoRender import renderFinalVideo
from ffmpegAudioTools import extractAudioTrack, mixAudioTracks, muxVideoAudio

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

def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--input", required=True, action="append")
    parser.add_argument("--outputGCS", required=True, action="append")
    parser.add_argument("--workdir", default="/workspace")
    
    # If calling from wrapper, argv will be passed in. 
    # If calling from CLI, it uses sys.argv automatically.
    args = parser.parse_args(argv)

    bucketName = args.bucket
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    client = storage.Client()

    # 1. Download Inputs
    localPaths, orientations, offsets = [], [], []
    try:
        for idx, spec in enumerate(args.input, 1):
            gPath, orient, off = parseInputSpec(spec)
            localFile = workdir / f"clip{idx}_{Path(gPath).name}"
            downloadFromGCS(bucketName, gPath, localFile, client)
            
            localPaths.append(localFile)
            orientations.append(orient)
            offsets.append(off)
    except Exception as e:
        print(f"❌ Error preparing inputs: {e}")
        return 1

    # 2. Render Video (No Audio)
    finalVideo = workdir / "final_video_track.mp4"
    try:
        renderFinalVideo(localPaths, orientations, offsets, finalVideo)
    except Exception as e:
        print(f"❌ Video render failed: {e}")
        return 1

    # 3. Process Audio & Mux
    try:
        audioFiles = []
        # Extract audio from source clips
        for i, videoPath in enumerate(localPaths):
            audioOut = workdir / f"audio_track_{i}.aac"
            extractAudioTrack(videoPath, audioOut, offsets[i])
            audioFiles.append(audioOut)

        n_outputs = len(args.outputGCS)
        
        # Strategy A: Mixed Audio (1 Output)
        if n_outputs == 1:
            mixedAudio = workdir / "mixed_audio.aac"
            mixAudioTracks(audioFiles, mixedAudio)
            
            finalOutput = workdir / "final_output.mp4"
            muxVideoAudio(finalVideo, mixedAudio, finalOutput)
            uploadToGCS(bucketName, args.outputGCS[0], finalOutput, client)
            
        # Strategy B: Separate Outputs (N Outputs)
        else:
            for i, outPath in enumerate(args.outputGCS):
                finalOutput = workdir / f"final_output_{i}.mp4"
                # Mux the SAME video with DIFFERENT source audio
                muxVideoAudio(finalVideo, audioFiles[i], finalOutput)
                uploadToGCS(bucketName, outPath, finalOutput, client)
                
    except Exception as e:
        print(f"❌ Audio/Mux processing failed: {e}")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())