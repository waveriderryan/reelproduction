#!/usr/bin/env python3
"""
Tennis Rally Detector (SwingVision-lite)

Detect rally start/end from a SINGLE wide camera clip by:
  1) person detection (YOLOv8)
  2) tracking (ByteTrack via ultralytics)
  3) player motion energy (centroid velocity)
  4) hysteresis state machine -> rally segments

Outputs:
  - rallies as [(start_sec, end_sec)]
  - optionally converted to ISO timestamps given clip_start_iso

Usage:
  python tennis_rally_detector.py \
    --video /path/to/wide.mp4 \
    --clip_start_iso 2026-02-05T01:43:59.455Z \
    --out_json /tmp/rallies.json

Install:
  pip install ultralytics opencv-python numpy python-dateutil
"""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import dateutil.parser
from ultralytics import YOLO


@dataclass
class TrackPoint:
    t_sec: float
    cx: float
    cy: float


def parse_iso(s: str) -> datetime:
    dt = dateutil.parser.parse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def ema(prev: Optional[float], x: float, alpha: float) -> float:
    if prev is None:
        return x
    return alpha * x + (1.0 - alpha) * prev


def pick_two_player_tracks(track_hist: Dict[int, List[TrackPoint]]) -> List[int]:
    """
    Choose 1-2 most plausible 'players' tracks.
    Heuristic: longest track length first, then larger median box area proxy
    (we don't have area here, so we prioritize track length + stability).
    """
    items = sorted(track_hist.items(), key=lambda kv: len(kv[1]), reverse=True)
    # take top 2 by length
    ids = [tid for tid, pts in items[:2]]
    return ids


def compute_speed_series(points: List[TrackPoint]) -> List[Tuple[float, float]]:
    """
    Returns list of (t_sec, speed_px_per_sec) for consecutive points.
    """
    out = []
    for i in range(1, len(points)):
        p0 = points[i - 1]
        p1 = points[i]
        dt = p1.t_sec - p0.t_sec
        if dt <= 1e-6:
            continue
        dx = p1.cx - p0.cx
        dy = p1.cy - p0.cy
        speed = (dx * dx + dy * dy) ** 0.5 / dt
        out.append((p1.t_sec, speed))
    return out


def robust_thresholds(values: List[float]) -> Tuple[float, float]:
    """
    Build active/idle thresholds from noise floor.
    Uses median + MAD.
    """
    if not values:
        # fallback defaults
        return (25.0, 12.0)

    med = float(np.median(values))
    mad = float(np.median(np.abs(np.array(values) - med))) + 1e-6

    # active should be clearly above baseline; idle closer to baseline
    active_th = med + 6.0 * mad
    idle_th = med + 2.5 * mad

    # keep sane bounds
    active_th = clamp(active_th, 10.0, 250.0)
    idle_th = clamp(idle_th, 5.0, 150.0)
    # ensure active > idle
    if active_th <= idle_th:
        active_th = idle_th + 5.0

    return (active_th, idle_th)


def segment_from_energy(
    series: List[Tuple[float, float]],
    active_th: float,
    idle_th: float,
    min_active_sec: float = 1.0,
    min_idle_sec: float = 1.2,
) -> List[Tuple[float, float]]:
    """
    Hysteresis segmentation:
      - enter ACTIVE when energy > active_th for min_active_sec
      - exit ACTIVE when energy < idle_th for min_idle_sec
    """
    if not series:
        return []

    rallies: List[Tuple[float, float]] = []
    state = "IDLE"
    active_start: Optional[float] = None

    # timers
    above_start: Optional[float] = None
    below_start: Optional[float] = None

    for t, e in series:
        if state == "IDLE":
            if e > active_th:
                if above_start is None:
                    above_start = t
                if (t - above_start) >= min_active_sec:
                    state = "ACTIVE"
                    active_start = above_start
                    below_start = None
            else:
                above_start = None

        else:  # ACTIVE
            if e < idle_th:
                if below_start is None:
                    below_start = t
                if (t - below_start) >= min_idle_sec:
                    # end rally
                    end_t = below_start
                    if active_start is not None and end_t > active_start:
                        rallies.append((active_start, end_t))
                    state = "IDLE"
                    active_start = None
                    above_start = None
            else:
                below_start = None

    # if still active, close at last timestamp
    if state == "ACTIVE" and active_start is not None:
        rallies.append((active_start, series[-1][0]))

    # merge tiny gaps / clean up
    merged: List[Tuple[float, float]] = []
    for s, e in rallies:
        if not merged:
            merged.append((s, e))
            continue
        ps, pe = merged[-1]
        # merge if gap < 0.6s
        if s - pe < 0.6:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))

    # drop very short rallies
    merged = [(s, e) for (s, e) in merged if (e - s) >= 2.0]
    return merged


def detect_rallies_yolo_track(
    video_path: str,
    model_name: str = "yolov8n.pt",
    device: Optional[str] = None,
    sample_fps: float = 10.0,
    warmup_sec: float = 8.0,
    ema_alpha: float = 0.35,
) -> Tuple[List[Tuple[float, float]], Dict]:
    """
    Returns (rallies_seconds, debug_info)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = float(frame_count / native_fps) if frame_count > 0 else None

    # sample step
    step = max(1, int(round(native_fps / sample_fps)))
    effective_fps = native_fps / step

    model = YOLO(model_name)

    # Track history: track_id -> list of TrackPoint
    track_hist: Dict[int, List[TrackPoint]] = {}

    # Motion energy series
    energy_series: List[Tuple[float, float]] = []
    smooth_energy: Optional[float] = None

    frame_idx = 0
    sampled_idx = 0

    # We'll use ultralytics tracker by calling model.track(frame, persist=True)
    # This keeps track IDs stable across frames.
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step != 0:
            frame_idx += 1
            continue

        t_sec = frame_idx / native_fps

        results = model.track(
            frame,
            persist=True,
            verbose=False,
            device=device,
            conf=0.25,
            iou=0.45,
            classes=[0],  # person only
        )

        r0 = results[0]
        boxes = r0.boxes
        if boxes is not None and boxes.id is not None:
            ids = boxes.id.cpu().numpy().astype(int)
            xyxy = boxes.xyxy.cpu().numpy()

            for tid, (x1, y1, x2, y2) in zip(ids, xyxy):
                cx = float((x1 + x2) / 2.0)
                cy = float((y1 + y2) / 2.0)
                track_hist.setdefault(tid, []).append(TrackPoint(t_sec=t_sec, cx=cx, cy=cy))

        frame_idx += 1
        sampled_idx += 1

    cap.release()

    # Pick two most stable tracks (usually the two players)
    player_ids = pick_two_player_tracks(track_hist)

    # Build per-player speed series; align on timestamps by interpolation-ish (simple nearest)
    # We'll compute energy at the timestamps of the denser series among chosen tracks.
    player_speed_series = []
    for pid in player_ids:
        pts = track_hist.get(pid, [])
        player_speed_series.append((pid, compute_speed_series(pts)))

    # If we got nothing, return empty
    if not player_speed_series or all(len(s) == 0 for _, s in player_speed_series):
        return [], {
            "native_fps": native_fps,
            "effective_fps": effective_fps,
            "picked_track_ids": player_ids,
            "reason": "no tracks / no speed series",
        }

    # Choose a base timeline: the series with most samples
    base_pid, base_series = max(player_speed_series, key=lambda kv: len(kv[1]))

    # Build quick lookup for other players (nearest time)
    def nearest_speed(series: List[Tuple[float, float]], t: float) -> float:
        if not series:
            return 0.0
        # binary-ish would be better; linear OK for small sizes
        best = series[0][1]
        best_dt = abs(series[0][0] - t)
        for ts, sp in series:
            dt = abs(ts - t)
            if dt < best_dt:
                best_dt = dt
                best = sp
        return best

    for t, sp_base in base_series:
        total = sp_base
        for pid, ser in player_speed_series:
            if pid == base_pid:
                continue
            total += nearest_speed(ser, t)
        smooth_energy = ema(smooth_energy, float(total), ema_alpha)
        energy_series.append((t, smooth_energy))

    # Warmup window to estimate noise floor (camera settle / pre-point walking)
    warm_vals = [e for (t, e) in energy_series if t <= warmup_sec]
    if not warm_vals:
        warm_vals = [e for (_, e) in energy_series[:max(10, int(effective_fps * 3))]]

    active_th, idle_th = robust_thresholds(warm_vals)

    rallies = segment_from_energy(
        energy_series,
        active_th=active_th,
        idle_th=idle_th,
        min_active_sec=1.0,
        min_idle_sec=1.2,
    )

    debug = {
        "native_fps": native_fps,
        "effective_fps": effective_fps,
        "duration_sec": duration,
        "picked_track_ids": player_ids,
        "active_threshold": active_th,
        "idle_threshold": idle_th,
        "energy_samples": len(energy_series),
    }

    return rallies, debug


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--clip_start_iso", default=None, help="ISO timestamp of clip start (UTC preferred)")
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--device", default=None, help="e.g. '0' for GPU0 or 'cpu'")
    ap.add_argument("--sample_fps", type=float, default=10.0)
    ap.add_argument("--out_json", default=None)
    args = ap.parse_args()

    rallies, debug = detect_rallies_yolo_track(
        video_path=args.video,
        model_name=args.model,
        device=args.device,
        sample_fps=args.sample_fps,
    )

    out = {
        "video": args.video,
        "debug": debug,
        "rallies": [{"start_sec": s, "end_sec": e, "duration_sec": (e - s)} for (s, e) in rallies],
    }

    if args.clip_start_iso:
        clip_start = parse_iso(args.clip_start_iso)
        for r in out["rallies"]:
            r["start_global"] = iso_from(clip_start + timedelta(seconds=float(r["start_sec"])))
            r["end_global"] = iso_from(clip_start + timedelta(seconds=float(r["end_sec"])))

    text = json.dumps(out, indent=2)
    if args.out_json:
        with open(args.out_json, "w") as f:
            f.write(text)
        print(f"✅ Wrote: {args.out_json}")
    else:
        print(text)


if __name__ == "__main__":
    main()
