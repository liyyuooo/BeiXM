#!/usr/bin/env python3
"""Pre-label video categories using AI vision.

Extracts a frame from each video and uses the vision model to identify the dessert category.
Updates data/videos.json with the identified categories.
"""

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ai_client

DATA_PATH = ROOT / "data" / "videos.json"
CATEGORIES = ["泡芙", "雪媚娘", "巴斯克芝士蛋糕"]
CATEGORY_KEY_MAP = {
    "泡芙": "puff",
    "雪媚娘": "snow_skin_mochi",
    "巴斯克芝士蛋糕": "basque",
    "巴斯克": "basque",
}


def extract_frame(video_path: Path, time_sec: float = 3.0) -> str:
    """Extract a frame from video and return base64 JPEG."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-ss", str(time_sec), "-frames:v", "1",
        "-q:v", "3", tmp_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=15)
    if result.returncode != 0:
        cmd_fallback = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-frames:v", "1", "-q:v", "3", tmp_path,
        ]
        subprocess.run(cmd_fallback, capture_output=True, timeout=15)

    tmp_file = Path(tmp_path)
    if not tmp_file.exists() or tmp_file.stat().st_size == 0:
        return ""
    data = tmp_file.read_bytes()
    tmp_file.unlink()
    return base64.b64encode(data).decode()


def main():
    if not ai_client.is_configured():
        print("ERROR: OPENROUTER_API_KEY not set. Cannot label videos.")
        sys.exit(1)

    videos = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    print(f"Labeling {len(videos)} videos...")

    for video in videos:
        source = ROOT / video["source_video"]
        if not source.exists():
            print(f"  SKIP {video['video_id']}: file not found ({video['source_video']})")
            continue

        print(f"  Processing {video['video_id']} ({source.name})...")
        frame_b64 = extract_frame(source)
        if not frame_b64:
            print(f"    WARN: could not extract frame, trying with direct read")
            continue

        try:
            result = ai_client.vision_identify(frame_b64, CATEGORIES)
            dish_name = result.get("dish_name", "")
            category_key = CATEGORY_KEY_MAP.get(dish_name, "")
            confidence = result.get("confidence", 0)
            reason = result.get("reason", "")

            video["category"] = dish_name
            video["category_key"] = category_key
            video["ai_label_confidence"] = confidence
            video["ai_label_reason"] = reason
            print(f"    -> {dish_name} (key={category_key}, conf={confidence}) {reason}")
        except Exception as exc:
            print(f"    ERROR: {exc}")

    DATA_PATH.write_text(json.dumps(videos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nDone. Updated {DATA_PATH}")

    labeled = [v for v in videos if v.get("category_key")]
    print(f"Labeled: {len(labeled)}/{len(videos)}")
    for v in labeled:
        print(f"  {v['video_id']}: {v['category']} ({v['category_key']})")


if __name__ == "__main__":
    main()
