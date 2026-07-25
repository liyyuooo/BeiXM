#!/usr/bin/env python3
"""AI client using OpenRouter API for the dessert tutorial MVP.

Supports:
- Vision (image recognition) via multimodal models
- Text generation (recipe synthesis, comment analysis)

Configuration (via .env.local or environment):
- OPENROUTER_API_KEY: required
- OPENROUTER_MODEL: defaults to google/gemini-2.0-flash-001
- OPENROUTER_VISION_MODEL: defaults to google/gemini-2.0-flash-001
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "meta-llama/llama-4-scout"
DEFAULT_VISION_MODEL = "meta-llama/llama-4-scout"
DEFAULT_TIMEOUT_SECONDS = 30
ROOT = Path(__file__).resolve().parents[1]


class AIUnavailable(RuntimeError):
    """Raised when AI calls are not configured or fail."""


def load_local_env() -> None:
    env_path = ROOT / ".env.local"
    if not env_path.exists():
        return
    with env_path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def is_configured() -> bool:
    load_local_env()
    return bool(os.getenv("OPENROUTER_API_KEY"))


def _get_key() -> str:
    load_local_env()
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise AIUnavailable("OPENROUTER_API_KEY is not set")
    return key


def _call_openrouter(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> str:
    api_key = _get_key()
    model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    timeout = int(os.getenv("OPENROUTER_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
    url = f"{OPENROUTER_BASE_URL}/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Dessert Tutorial MVP",
        },
        method="POST",
    )

    try:
        started = time.time()
        print(f"[ai] request model={model} timeout={timeout}s", file=sys.stderr, flush=True)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        elapsed = time.time() - started
        print(f"[ai] response ok in {elapsed:.1f}s", file=sys.stderr, flush=True)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AIUnavailable(f"OpenRouter HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise AIUnavailable(f"OpenRouter request failed: {exc}") from exc

    choices = data.get("choices", [])
    if not choices:
        raise AIUnavailable("OpenRouter returned no choices")
    content = choices[0]["message"]["content"]
    if not content or not content.strip():
        raise AIUnavailable("OpenRouter returned empty content")
    return content


def vision_identify(image_base64: str, categories: List[str]) -> Dict[str, Any]:
    """Send a frame image to the vision model and identify the dessert category."""
    model = os.getenv("OPENROUTER_VISION_MODEL", DEFAULT_VISION_MODEL)
    category_list = "、".join(categories)

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个烘焙甜品识别专家。用户会给你一张烘焙视频的截图，"
                f"请判断这张图里的甜品属于以下哪个品类：{category_list}。"
                "只输出 JSON 格式，包含 dish_name（品类名）、confidence（0-1的置信度）、reason（判断理由，一句话）。"
                "如果无法确定，confidence 设为 0.3 以下并说明原因。"
                "不要输出 Markdown，只输出纯 JSON。"
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}",
                    },
                },
                {
                    "type": "text",
                    "text": "请识别这张图片中的甜品属于什么品类。",
                },
            ],
        },
    ]

    text = _call_openrouter(messages, model=model, temperature=0.1, max_tokens=500)
    return _parse_json_text(text)


def responses_json(
    *,
    system: str,
    user_payload: Dict[str, Any],
    schema_name: str,
    schema: Optional[Dict[str, Any]] = None,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """Call OpenRouter for structured JSON generation (recipes, analysis)."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    text = _call_openrouter(messages, temperature=temperature, max_tokens=4000)
    return _parse_json_text(text)


def _parse_json_text(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        end = next((i for i, l in enumerate(lines) if l.strip() == "```"), len(lines))
        text = "\n".join(lines[:end])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        # Try to find a JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise
