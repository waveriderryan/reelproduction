from pathlib import Path


def buildMixedThreeTwoLandscapeCmd(
    localPaths,
    orientations,
    startTimes,
    baseDuration,
    outVideo: Path,
):
    """
    1 portrait + 2 landscape → portrait canvas (1080x1920)
    Timeline-based rendering.

    Portrait (aggressively cropped vertically) on top,
    two landscapes stacked below.

    Key invariants:
      - Every tile ends as exactly CANVAS_W x tile_h before stacking
      - No fixed-size crop after a scale that might produce smaller frames
    """

    LOGO = "/app/assets/reelchains_logo.png"
    PAD = "0x000000"

    # Canvas
    CANVAS_W = 1080
    CANVAS_H = 1920

    # Layout geometry
    TOP_H = 960
    BOT_H = (CANVAS_H - TOP_H) // 2  # 480 each

    # Cropping
    PORTRAIT_CROP = 0.75   # keep middle 75% of height (aggressive); 0.70–0.85 reasonable
    CROP_LAND = 0.80       # keep middle 80% of width

    # Logo
    LOGO_SCALE = 0.20
    LOGO_ALPHA = 0.25
    LOGO_PAD = 48

    # Identify indices
    portrait_idx = orientations.index("portrait")
    landscape_idxs = [i for i, o in enumerate(orientations) if o == "landscape"]
    if len(landscape_idxs) != 2:
        raise ValueError("mixedThreeTwoLandscape requires exactly 1 portrait and 2 landscape inputs")
    l0, l1 = landscape_idxs

    # Timeline start times (seconds)
    t_p = float(startTimes[portrait_idx])
    t_l0 = float(startTimes[l0])
    t_l1 = float(startTimes[l1])

    # Build filtergraph
    filtergraph = f"""
        color=c=black:s={CANVAS_W}x{CANVAS_H}:d={baseDuration}[base];

        [{portrait_idx}:v]setpts=PTS-STARTPTS+{t_p}/TB,
            crop=iw:ih*{PORTRAIT_CROP}:0:(ih-ih*{PORTRAIT_CROP})/2,
            scale={CANVAS_W}:{TOP_H}:force_original_aspect_ratio=increase,
            crop={CANVAS_W}:{TOP_H}
            [top];

        [{l0}:v]setpts=PTS-STARTPTS+{t_l0}/TB,
            crop=iw*{CROP_LAND}:ih:(iw-iw*{CROP_LAND})/2:0,
            scale={CANVAS_W}:{BOT_H}:force_original_aspect_ratio=increase,
            crop={CANVAS_W}:{BOT_H}
            [b0];

        [{l1}:v]setpts=PTS-STARTPTS+{t_l1}/TB,
            crop=iw*{CROP_LAND}:ih:(iw-iw*{CROP_LAND})/2:0,
            scale={CANVAS_W}:{BOT_H}:force_original_aspect_ratio=increase,
            crop={CANVAS_W}:{BOT_H}
            [b1];

        [b0][b1]vstack=inputs=2[bottom];
        [top][bottom]vstack=inputs=2[layout];
        [base][layout]overlay=0:0:eof_action=pass[bg];

        [3:v]scale=iw*{LOGO_SCALE}:-1:force_original_aspect_ratio=decrease,format=rgba[logo];
        [logo]lut=a='val*{LOGO_ALPHA}'[logo_half];
        [bg][logo_half]overlay=(W-w)-{LOGO_PAD}:(H-h)-{LOGO_PAD}:format=auto[outv]
    """

    return [
        "ffmpeg", "-y",

        "-i", str(localPaths[0]),
        "-i", str(localPaths[1]),
        "-i", str(localPaths[2]),
        "-i", LOGO,

        "-filter_complex", filtergraph,
        "-map", "[outv]",

        "-c:v", "hevc_nvenc",
        "-preset", "p5",
        "-rc", "vbr",
        "-b:v", "5M",
        "-maxrate", "6M",
        "-bufsize", "12M",
        "-g", "60",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-tag:v", "hvc1",
        "-movflags", "+faststart",

        str(outVideo),
    ]
