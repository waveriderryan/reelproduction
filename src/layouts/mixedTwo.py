from pathlib import Path


def buildMixedTwoCmd(localPaths, orientations, offsets, outVideo: Path):
    """
    Mixed portrait + landscape layout on a portrait canvas.

    - Canvas: 1080x1920
      * Top zone (portrait):   1080 x 1280
      * Bottom zone (landscape): 1080 x 640
      => total height = 1920

    - Clip1 is always the one that gets trimmed by offsets[0]
    - Clip2 is always untrimmed
    - orientations[i] is 'portrait' or 'landscape'
      We detect which input is portrait vs landscape only
      for the FILTER graph (visual placement).

    NOTE: This function is *video-only*. Your existing pipeline
    already:
      1) extracts audio from each camera,
      2) either mixes or picks one track,
      3) muxes it with this video.
    That is where your "auto audio mode" lives.
    """

    clip1, clip2 = localPaths
    off1, off2 = offsets  # off2 currently unused, kept for future

    LOGO = "/app/assets/reelchains_logo.png"
    PAD_COLOR = "0x5762FF"

    TARGET_W = 1080
    TOP_H = 1280       # portrait zone (2/3)
    BOTTOM_H = 640     # landscape zone (1/3)

    # ---- Normalize offset for clip1 (it is always the trimmed input) ----
    if isinstance(off1, (list, tuple)):
        if not off1:
            raise ValueError("Offset list for first clip is empty.")
        off1 = off1[0]

    offset_str = f"{float(off1):.6f}"

    # ---- Decide which *video input index* is portrait vs landscape ----
    # orientations[i] is 'portrait' or 'landscape'
    if orientations[0] == "portrait":
        portrait_idx = 0
        landscape_idx = 1
    else:
        portrait_idx = 1
        landscape_idx = 0

    portrait_v = f"[{portrait_idx}:v]"
    landscape_v = f"[{landscape_idx}:v]"

    # ---- Filter graph: logically identical to your shell script ----
    #
    # ${PORTRAIT_V}setpts=PTS-STARTPTS,
    #      scale=TARGET_W:TOP_H:force_original_aspect_ratio=decrease,
    #      pad=TARGET_W:TOP_H:(ow-iw)/2:(oh-ih)/2:PAD_COLOR[top];
    #
    # ${LAND_V}setpts=PTS-STARTPTS,
    #      scale=TARGET_W:BOTTOM_H:force_original_aspect_ratio=decrease,
    #      pad=TARGET_W:BOTTOM_H:(ow-iw)/2:(oh-ih)/2:PAD_COLOR[bottom];
    #
    # [top][bottom]vstack=inputs=2[bg];
    #
    # [2:v]scale=iw*0.30:-1,format=rgba[logo];
    # [logo]lut=a='val*0.50'[logo_half];
    # [bg][logo_half]overlay=(W-w)-40:(H-h)-40[outv];
    #
    filtergraph = (
        f"{portrait_v}setpts=PTS-STARTPTS,"
        f"scale={TARGET_W}:{TOP_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TOP_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[top];"
        f"{landscape_v}setpts=PTS-STARTPTS,"
        f"scale={TARGET_W}:{BOTTOM_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{BOTTOM_H}:(ow-iw)/2:(oh-ih)/2:{PAD_COLOR}[bottom];"
        f"[top][bottom]vstack=inputs=2[bg];"
        f"[2:v]scale=iw*0.30:-1,format=rgba[logo];"
        f"[logo]lut=a='val*0.50'[logo_half];"
        f"[bg][logo_half]overlay=(W-w)-40:(H-h)-40[outv]"
    )

    cmd = [
        "ffmpeg",
        "-y",

        # Clip1 is always the trimmed one (started earlier).
        "-ss", offset_str, "-i", str(clip1),

        # Clip2 is always untrimmed.
        "-ss", "0", "-i", str(clip2),

        # Logo input
        "-i", LOGO,

        "-filter_complex", filtergraph,
        "-map", "[outv]",

        # --- HEVC via NVENC, Apple-friendly tag ---
        "-c:v", "hevc_nvenc",
        "-preset", "p5",
        "-rc", "vbr",
        "-b:v", "10M",
        "-pix_fmt", "yuv420p",
        "-tag:v", "hvc1",
        "-movflags", "+faststart",
        "-r", "30",  # CFR 30 like your shell script

        str(outVideo),
    ]

    return cmd
