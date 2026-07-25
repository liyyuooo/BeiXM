#!/usr/bin/env python3
"""Generate step images for all base recipes using Gemini image model.

Saves images to 前端/public/assets/generated/ and updates base_recipe JSON with paths.
Run: python3 scripts/generate_step_images.py
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "data" / "generated"
IMAGE_DIR = ROOT / "前端" / "public" / "assets" / "generated"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# Use the image-capable key from environment or .env.local
import sys
sys.path.insert(0, str(ROOT / "scripts"))
import ai_client as _aic
_aic.load_local_env()
IMAGE_API_KEY = os.getenv("OPENROUTER_IMAGE_KEY", os.getenv("OPENROUTER_API_KEY", ""))
IMAGE_MODEL = "google/gemini-2.5-flash-image"


def generate_image(prompt: str, output_path: Path, max_retries: int = 2) -> bool:
    """Generate an image and save to output_path."""
    if output_path.exists() and output_path.stat().st_size > 1000:
        print(f"    [cached] {output_path.name}")
        return True

    payload = json.dumps({
        "model": IMAGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
    }).encode()

    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {IMAGE_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            resp = urllib.request.urlopen(req, timeout=60)
            data = json.loads(resp.read())
            msg = data["choices"][0]["message"]
            images = msg.get("images", [])
            if images:
                img_data = images[0]
                url = img_data.get("image_url", {}).get("url", "")
                if url.startswith("data:image"):
                    b64 = url.split(",", 1)[1]
                    output_path.write_bytes(base64.b64decode(b64))
                    print(f"    [ok] {output_path.name} ({output_path.stat().st_size // 1024}KB)")
                    return True
            print(f"    [no image] attempt {attempt + 1}")
        except urllib.error.HTTPError as e:
            print(f"    [http {e.code}] attempt {attempt + 1}")
        except Exception as e:
            print(f"    [error] {e}")
        time.sleep(2)

    return False


def process_recipe(category_key: str):
    recipe_path = GENERATED / f"base_recipe_{category_key}.json"
    if not recipe_path.exists():
        print(f"  No recipe for {category_key}")
        return

    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    dish_name = recipe.get("title", category_key)
    steps = recipe.get("steps", [])

    print(f"\n  {dish_name} ({len(steps)} steps)")

    updated = False
    for step in steps:
        step_num = step.get("step", 0)
        title = step.get("title", "")
        action = step.get("action", "")
        key_state = step.get("key_state", "")

        img_filename = f"{category_key}_step_{step_num:02d}.png"
        img_path = IMAGE_DIR / img_filename
        web_path = f"./public/assets/generated/{img_filename}"

        prompt = (
            f"生成一张烘焙步骤图片。"
            f"甜品：{dish_name}。"
            f"步骤 {step_num}：{title}。"
            f"操作：{action} "
            f"{'关键状态：' + key_state if key_state else ''}"
            f"要求：真实厨房场景，俯视角度，暖色调，清晰展示操作过程和食材状态。"
        )

        print(f"  Step {step_num}: {title}")
        if generate_image(prompt, img_path):
            step["image"] = web_path
            updated = True

    if updated:
        recipe_path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  Updated recipe JSON with image paths")


def main():
    print("Generating step images for all recipes...")
    for cat in ["basque", "puff", "snow_skin_mochi"]:
        print(f"\n{'='*40}")
        print(f"Category: {cat}")
        process_recipe(cat)

    print(f"\n{'='*40}")
    print("Done!")
    print(f"Images saved to: {IMAGE_DIR}")


if __name__ == "__main__":
    main()
