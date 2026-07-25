#!/usr/bin/env python3
"""Validate local MVP data files."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def load(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main() -> None:
    videos = load(DATA_DIR / "videos.json")
    comments = load(DATA_DIR / "comments.json")
    aliases = load(DATA_DIR / "category_aliases.json")

    video_ids = {item["video_id"] for item in videos}
    comment_ids = {item["video_id"] for item in comments}
    missing_comment_groups = sorted(video_ids - comment_ids)
    missing_videos = [
        item["source_video"]
        for item in videos
        if not (ROOT / item["source_video"]).exists()
    ]
    missing_covers = [
        item["cover_image"]
        for item in videos
        if not (ROOT / item["cover_image"]).exists()
    ]
    missing_aliases = sorted({item["category_key"] for item in videos} - set(aliases))

    ok = not (missing_comment_groups or missing_videos or missing_covers or missing_aliases)
    result = {
        "ok": ok,
        "video_count": len(videos),
        "comment_group_count": len(comments),
        "missing_comment_groups": missing_comment_groups,
        "missing_videos": missing_videos,
        "missing_covers": missing_covers,
        "missing_aliases": missing_aliases,
        "needs_review": [
            {
                "video_id": item["video_id"],
                "source_video": item["source_video"],
                "mapping_note": item.get("mapping_note", ""),
            }
            for item in videos
            if "review" in item.get("category_source", "")
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
