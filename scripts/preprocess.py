#!/usr/bin/env python3
"""Pre-process all categories: extract tutorials, analyze comments, synthesize base recipes.

Results are cached in data/generated/ so the demo runs instantly.
Run once before demo: python3 scripts/preprocess.py
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ai_client
import pipeline

GENERATED = ROOT / "data" / "generated"
GENERATED.mkdir(parents=True, exist_ok=True)

CATEGORIES = {
    "basque": "巴斯克",
    "puff": "泡芙",
    "snow_skin_mochi": "雪媚娘",
}


def validate_extracted(data):
    """Check if extracted tutorial has minimum required fields."""
    if not isinstance(data, list) or len(data) == 0:
        return False
    for item in data:
        if not item.get("ingredients") and not item.get("steps"):
            return False
    return True


def validate_base_recipe(recipe):
    """Check if base recipe has minimum required fields."""
    if not recipe:
        return False
    if not recipe.get("ingredients") or len(recipe["ingredients"]) < 3:
        return False
    if not recipe.get("steps") or len(recipe["steps"]) < 3:
        return False
    return True


def validate_comments(insights):
    """Check if comment insights have substance."""
    if not insights:
        return False
    if insights.get("ai_status") and "fallback" in insights["ai_status"]:
        return False
    return True


def process_category(category_key, dish_name, max_retries=2):
    print(f"\n{'='*60}")
    print(f"Processing: {dish_name} ({category_key})")
    print(f"{'='*60}")

    # Step 1: Retrieve tutorials
    print(f"\n[1/4] Retrieving tutorials for {dish_name}...")
    tutorials = pipeline.retrieve_tutorials_with_ai(category_key, dish_name)
    print(f"  Found {len(tutorials)} tutorials: {[t['video_id'] for t in tutorials]}")

    if not tutorials:
        print(f"  ERROR: No tutorials found for {category_key}")
        return False

    video_ids = [t["video_id"] for t in tutorials]

    # Step 2: Extract tutorial info
    print(f"\n[2/4] Extracting tutorial info...")
    cache_path = GENERATED / f"extracted_{category_key}.json"
    extracted = None

    for attempt in range(max_retries + 1):
        if cache_path.exists() and attempt == 0:
            extracted = json.loads(cache_path.read_text(encoding="utf-8"))
            if validate_extracted(extracted):
                print(f"  Using cached extraction ({len(extracted)} tutorials)")
                break
            else:
                print(f"  Cached extraction invalid, re-running...")

        comments_data = pipeline.load_comments()
        try:
            extracted = pipeline.extract_tutorials_with_ai(tutorials, comments_data)
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            continue

        if validate_extracted(extracted):
            cache_path.write_text(json.dumps(extracted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  Extracted {len(extracted)} tutorials successfully")
            break
        else:
            print(f"  Attempt {attempt+1}: extraction incomplete, retrying...")
            # Clear the general cache so it re-runs
            general_cache = GENERATED / "extracted_tutorials.json"
            if general_cache.exists():
                general_cache.unlink()

    if not validate_extracted(extracted):
        print(f"  WARNING: Extraction still incomplete after {max_retries+1} attempts")

    # Step 3: Analyze comments
    print(f"\n[3/4] Analyzing comments...")
    comment_cache_path = GENERATED / f"comments_{category_key}.json"
    comment_insights = None

    for attempt in range(max_retries + 1):
        if comment_cache_path.exists() and attempt == 0:
            comment_insights = json.loads(comment_cache_path.read_text(encoding="utf-8"))
            if validate_comments(comment_insights):
                print(f"  Using cached comment insights")
                break

        try:
            comment_insights = pipeline.analyze_comments_with_ai(video_ids)
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            continue

        if validate_comments(comment_insights):
            comment_cache_path.write_text(json.dumps(comment_insights, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  Comment insights generated successfully")
            break
        else:
            print(f"  Attempt {attempt+1}: insights incomplete, retrying...")

    # Step 4: Synthesize base recipe
    print(f"\n[4/4] Synthesizing base recipe...")
    recipe_cache_path = GENERATED / f"base_recipe_{category_key}.json"
    base_recipe = None

    for attempt in range(max_retries + 1):
        if recipe_cache_path.exists() and attempt == 0:
            base_recipe = json.loads(recipe_cache_path.read_text(encoding="utf-8"))
            if validate_base_recipe(base_recipe):
                print(f"  Using cached base recipe: {base_recipe.get('title', '?')}")
                break

        try:
            base_recipe = pipeline.synthesize_base_recipe_with_ai(
                category_key, comment_insights, extracted
            )
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            continue

        if validate_base_recipe(base_recipe):
            recipe_cache_path.write_text(json.dumps(base_recipe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  Base recipe: {base_recipe.get('title', '?')}")
            print(f"    {len(base_recipe.get('ingredients',[]))} ingredients, {len(base_recipe.get('steps',[]))} steps")
            break
        else:
            print(f"  Attempt {attempt+1}: recipe incomplete ({len(base_recipe.get('ingredients',[]))} ingredients, {len(base_recipe.get('steps',[]))} steps), retrying...")

    if not validate_base_recipe(base_recipe):
        print(f"  WARNING: Base recipe still incomplete")
        return False

    return True


def main():
    if not ai_client.is_configured():
        print("ERROR: OPENROUTER_API_KEY not configured. Set it in .env.local")
        sys.exit(1)

    print("Dessert Tutorial Pre-processor")
    print(f"Model: {ai_client.load_local_env() or ''}")
    print(f"Videos: {len(pipeline.load_videos())}")
    print(f"Comments: {sum(len(c.get('comments',[])) for c in pipeline.load_comments())}")

    results = {}
    for category_key, dish_name in CATEGORIES.items():
        success = process_category(category_key, dish_name)
        results[category_key] = success
        time.sleep(2)

    print(f"\n{'='*60}")
    print("RESULTS:")
    for k, v in results.items():
        status = "OK" if v else "FAILED"
        print(f"  {CATEGORIES[k]} ({k}): {status}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
