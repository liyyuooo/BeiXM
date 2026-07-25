#!/usr/bin/env python3
"""Optional video preprocessing hooks for frame extraction and OCR.

This MVP keeps the interface stable even when real OCR/vision dependencies are
not installed. Later adapters can fill frame_caption and ocr_text fields.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
IMAGE_DIR = ROOT / "public" / "images"


def load_videos() -> List[Dict[str, Any]]:
    with (DATA_DIR / "videos.json").open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def generated_thumbnail_path(video_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{video_path.name}.png"


def generate_thumbnail(video_path: Path, output_dir: Path) -> Dict[str, Any]:
    qlmanage = shutil.which("qlmanage")
    if not qlmanage:
        return {"ok": False, "reason": "qlmanage not found"}

    output_dir.mkdir(parents=True, exist_ok=True)
    command = [qlmanage, "-t", "-s", "720", "-o", str(output_dir), str(video_path)]
    completed = subprocess.run(command, capture_output=True, text=True)
    generated_path = generated_thumbnail_path(video_path, output_dir)
    return {
        "ok": completed.returncode == 0,
        "command": command,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "generated_image": str(generated_path.relative_to(ROOT)) if generated_path.exists() else "",
    }


def build_preprocess_manifest(run_thumbnail: bool) -> Dict[str, Any]:
    records = []
    for video in load_videos():
        source_path = ROOT / video["source_video"]
        record = {
            "video_id": video["video_id"],
            "source_video": video["source_video"],
            "category_key": video["category_key"],
            "frame_samples": [],
            "ocr_text": "",
            "frame_caption": "",
            "status": "pending_real_vision_ocr",
            "notes": [
                "Use OCR on sampled frames to capture on-screen ingredient text.",
                "Use vision captioning on cover/middle/key frames to confirm dessert subject.",
                "Keep manual category mapping as fallback for demo stability.",
            ],
        }
        if run_thumbnail:
            thumbnail_result = generate_thumbnail(source_path, IMAGE_DIR)
            record["thumbnail_result"] = thumbnail_result
            if thumbnail_result.get("generated_image"):
                record["frame_samples"].append(
                    {
                        "kind": "quicklook_thumbnail",
                        "image": thumbnail_result["generated_image"],
                        "timestamp": "thumbnail",
                        "ocr_text": "",
                        "frame_caption": "",
                    }
                )
        records.append(record)

    return {
        "version": 1,
        "purpose": "Preprocess videos for frame recognition and OCR.",
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare optional vision/OCR manifest.")
    parser.add_argument("--thumbnail", action="store_true", help="Try generating macOS QuickLook thumbnails.")
    parser.add_argument("--out", default="data/generated/vision_manifest.json")
    args = parser.parse_args()

    manifest = build_preprocess_manifest(args.thumbnail)
    save_json(ROOT / args.out, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
