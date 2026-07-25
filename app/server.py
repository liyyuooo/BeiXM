#!/usr/bin/env python3
"""Local API server for the dessert tutorial MVP.

Serves both:
- Frontend static files (from /前端)
- Video files (from /甜品视频)
- JSON API endpoints under /api/
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "前端"
VIDEO_DIR = ROOT / "甜品视频"
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline  # noqa: E402

try:
    import ai_client  # noqa: E402
except ImportError:
    ai_client = None

mimetypes.init()
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")


def json_response(handler: BaseHTTPRequestHandler, status: int, data: Any) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length == 0:
        return {}
    body = handler.rfile.read(length).decode("utf-8")
    return json.loads(body or "{}")


def split_path(path: str) -> Tuple[str, ...]:
    return tuple(part for part in urlparse(path).path.split("/") if part)


def serve_static(handler: BaseHTTPRequestHandler, file_path: Path) -> bool:
    if not file_path.is_file():
        return False
    mime, _ = mimetypes.guess_type(str(file_path))
    mime = mime or "application/octet-stream"
    try:
        data = file_path.read_bytes()
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", mime)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Cache-Control", "public, max-age=3600")
        handler.end_headers()
        handler.wfile.write(data)
        return True
    except Exception:
        return False


class DessertHandler(BaseHTTPRequestHandler):
    server_version = "DessertMVP/0.2"

    def log_message(self, format, *args):
        path = args[0] if args else ""
        if "/videos/" in str(path) and ".mp4" in str(path):
            return
        super().log_message(format, *args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            raw_path = unquote(urlparse(self.path).path)
            parts = split_path(self.path)
            query = parse_qs(urlparse(self.path).query)

            # --- API routes ---
            if parts == ("api", "health"):
                json_response(self, HTTPStatus.OK, {"ok": True})
                return

            if parts == ("api", "videos"):
                videos = pipeline.load_videos()
                for video in videos:
                    video["video_url"] = f"/videos/{video['video_id']}.mp4"
                json_response(self, HTTPStatus.OK, {"videos": videos})
                return

            if len(parts) == 3 and parts[:2] == ("api", "videos"):
                video_id = parts[2]
                video = next(
                    (item for item in pipeline.load_videos() if item["video_id"] == video_id),
                    None,
                )
                if not video:
                    json_response(self, HTTPStatus.NOT_FOUND, {"error": "video_not_found"})
                    return
                video["video_url"] = f"/videos/{video['video_id']}.mp4"
                json_response(self, HTTPStatus.OK, video)
                return

            if parts == ("api", "current-video"):
                video_id = query.get("video_id", ["puff_01"])[0]
                video = next(
                    (item for item in pipeline.load_videos() if item["video_id"] == video_id),
                    None,
                )
                if video:
                    video["video_url"] = f"/videos/{video['video_id']}.mp4"
                json_response(self, HTTPStatus.OK, video or {})
                return

            # --- Video file serving ---
            if len(parts) >= 2 and parts[0] == "videos":
                video_id = unquote(parts[1]).replace(".mp4", "")
                video_file = self._find_video_file(video_id)
                if video_file and serve_static(self, video_file):
                    return
                json_response(self, HTTPStatus.NOT_FOUND, {"error": "video_file_not_found"})
                return

            # --- Frontend static files ---
            if not parts or raw_path == "/":
                serve_static(self, FRONTEND_DIR / "index.html")
                return

            rel_path = "/".join(parts)
            file_path = FRONTEND_DIR / rel_path
            if serve_static(self, file_path):
                return

            # Also try project root (for public/images etc.)
            root_path = ROOT / rel_path
            if serve_static(self, root_path):
                return

            json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parts = split_path(self.path)
            body = read_json_body(self)

            if parts == ("api", "identify"):
                image_base64 = body.get("image_base64", "")
                video_id = body.get("video_id", "")
                if image_base64 and ai_client and ai_client.is_configured():
                    aliases = pipeline.load_aliases()
                    categories = [v["name"] for v in aliases.values()]
                    try:
                        vision_result = ai_client.vision_identify(image_base64, categories)
                        dish_name = vision_result.get("dish_name", "")
                        category_key = None
                        for key, config in aliases.items():
                            if config["name"] == dish_name or dish_name in config.get("aliases", []):
                                category_key = key
                                break
                        if not category_key:
                            for key, config in aliases.items():
                                all_terms = [config["name"]] + config.get("aliases", [])
                                if any(term in dish_name for term in all_terms):
                                    category_key = key
                                    break
                        if category_key:
                            result = {
                                "dish_name": aliases[category_key]["name"],
                                "category_key": category_key,
                                "confidence": vision_result.get("confidence", 0.8),
                                "reason": vision_result.get("reason", ""),
                                "source": "vision_ai",
                            }
                            if video_id:
                                self._label_video(video_id, category_key, aliases[category_key]["name"])
                        else:
                            result = {
                                "dish_name": dish_name or "未知",
                                "category_key": "unknown",
                                "confidence": vision_result.get("confidence", 0.3),
                                "reason": vision_result.get("reason", ""),
                                "source": "vision_ai_unmatched",
                            }
                        json_response(self, HTTPStatus.OK, result)
                        return
                    except Exception as exc:
                        print(f"[vision] fallback due to: {exc}", file=sys.stderr)

                result = pipeline.identify_subject(
                    video_id=body.get("video_id"),
                    frame_caption=body.get("frame_caption", ""),
                    ocr_text=body.get("ocr_text", ""),
                    title=body.get("title", ""),
                )
                json_response(self, HTTPStatus.OK, result)
                return

            if parts == ("api", "analyze"):
                category_key = body.get("category_key", "")
                dish_name = body.get("dish_name", "")
                use_ai = bool(body.get("use_ai", False))
                if not category_key and body.get("video_id"):
                    identified = pipeline.identify_subject(video_id=body["video_id"])
                    category_key = identified.get("category_key", "")
                    dish_name = identified.get("dish_name", "")
                if not category_key:
                    json_response(self, HTTPStatus.BAD_REQUEST, {"error": "category_key_required"})
                    return
                tutorials = (
                    pipeline.retrieve_tutorials_with_ai(category_key, dish_name)
                    if use_ai
                    else pipeline.retrieve_tutorials(category_key)
                )
                video_ids = [item["video_id"] for item in tutorials]
                comments_data = pipeline.load_comments()
                if use_ai and tutorials:
                    extracted = pipeline.extract_tutorials_with_ai(tutorials, comments_data)
                else:
                    extracted = tutorials
                comment_summary = (
                    pipeline.analyze_comments_with_ai(video_ids)
                    if use_ai
                    else pipeline.summarize_comments(video_ids)
                )
                base_recipe = (
                    pipeline.synthesize_base_recipe_with_ai(category_key, comment_summary, extracted)
                    if use_ai
                    else pipeline.synthesize_base_recipe(category_key)
                )
                result = {
                    "retrieved_tutorials": tutorials,
                    "extracted_tutorials": extracted,
                    "comment_summary": comment_summary,
                    "base_recipe": base_recipe,
                    "baseRecipe": base_recipe,
                }
                json_response(self, HTTPStatus.OK, result)
                return

            if parts == ("api", "generate-recipe"):
                category_key = body.get("category_key", "")
                user_requirement = body.get("user_requirement", "")
                use_ai = bool(body.get("use_ai", False))
                comment_insights = body.get("comment_insights")
                base = body.get("base_recipe") or (
                    pipeline.synthesize_base_recipe_with_ai(category_key)
                    if use_ai
                    else pipeline.synthesize_base_recipe(category_key)
                )
                result = (
                    pipeline.personalize_recipe_with_ai(base, user_requirement, comment_insights)
                    if use_ai
                    else pipeline.personalize_recipe(base, user_requirement)
                )
                json_response(self, HTTPStatus.OK, result)
                return

            json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except json.JSONDecodeError:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _find_video_file(self, video_id: str) -> Path | None:
        """Find the actual video file for a video_id."""
        videos = pipeline.load_videos()
        video = next((v for v in videos if v["video_id"] == video_id), None)
        if video and video.get("source_video"):
            path = ROOT / video["source_video"]
            if path.is_file():
                return path
        for mp4 in VIDEO_DIR.glob("*.mp4"):
            if video_id in mp4.stem:
                return mp4
        mp4_list = sorted(VIDEO_DIR.glob("*.mp4"))
        if mp4_list:
            return mp4_list[0]
        return None

    def _label_video(self, video_id: str, category_key: str, category_name: str) -> None:
        """Update a video's category label in videos.json."""
        try:
            data_path = ROOT / "data" / "videos.json"
            videos = json.loads(data_path.read_text(encoding="utf-8"))
            updated = False
            for video in videos:
                if video["video_id"] == video_id:
                    video["category"] = category_name
                    video["category_key"] = category_key
                    updated = True
                    break
            if updated:
                data_path.write_text(
                    json.dumps(videos, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"[label] {video_id} -> {category_name} ({category_key})", file=sys.stderr)
        except Exception as exc:
            print(f"[label] failed: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local dessert MVP API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true", help="Validate imports and data, then exit.")
    args = parser.parse_args()

    if args.check:
        videos = pipeline.load_videos()
        comments = pipeline.load_comments()
        print(json.dumps({"ok": True, "videos": len(videos), "comment_groups": len(comments)}, ensure_ascii=False))
        return

    server = ThreadingHTTPServer((args.host, args.port), DessertHandler)
    print(f"Serving at http://{args.host}:{args.port}")
    print(f"  Frontend: {FRONTEND_DIR}")
    print(f"  Videos:   {VIDEO_DIR}")
    print(f"  API:      /api/health, /api/identify, /api/analyze, /api/generate-recipe")
    server.serve_forever()


if __name__ == "__main__":
    main()
