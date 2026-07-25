#!/usr/bin/env python3
"""Local MVP pipeline for dessert tutorial retrieval and recipe generation.

The pipeline is intentionally dependency-free. Vision/OCR output can be passed
in as text now, then replaced by real adapters later.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import ai_client
except ImportError:  # pragma: no cover - direct import works in normal runs.
    ai_client = None


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def log_step(args: argparse.Namespace, message: str) -> None:
    if bool(getattr(args, "verbose", False)):
        print(f"[pipeline] {message}", file=sys.stderr, flush=True)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def normalize_text(parts: Iterable[Optional[str]]) -> str:
    return " ".join(part for part in parts if part).lower()


def load_videos() -> List[Dict[str, Any]]:
    return load_json(DATA_DIR / "videos.json")


def load_comments() -> List[Dict[str, Any]]:
    return load_json(DATA_DIR / "comments.json")


def load_aliases() -> Dict[str, Any]:
    return load_json(DATA_DIR / "category_aliases.json")


def identify_subject(
    video_id: Optional[str] = None,
    frame_caption: str = "",
    ocr_text: str = "",
    title: str = "",
) -> Dict[str, Any]:
    """Identify dessert subject from manual mapping plus text/OCR hints."""

    videos = load_videos()
    aliases = load_aliases()
    video = next((item for item in videos if item["video_id"] == video_id), None)

    text = normalize_text(
        [
            title,
            frame_caption,
            ocr_text,
            video.get("title") if video else "",
            video.get("transcript") if video else "",
            video.get("description") if video else "",
        ]
    )

    scores: Dict[str, int] = {}
    matched_terms: Dict[str, List[str]] = {}
    for category_key, config in aliases.items():
        terms = config["aliases"] + config.get("visual_hints", [])
        matches = [term for term in terms if term.lower() in text]
        scores[category_key] = len(matches)
        matched_terms[category_key] = matches

    if video:
        scores[video["category_key"]] = scores.get(video["category_key"], 0) + 3

    best_key = max(scores, key=scores.get)
    best_score = scores[best_key]
    confidence = 0.55 if best_score == 0 else min(0.98, 0.55 + best_score * 0.1)

    return {
        "dish_name": aliases[best_key]["name"],
        "category_key": best_key,
        "confidence": round(confidence, 2),
        "matched_terms": matched_terms[best_key],
        "source": "manual_mapping_plus_text_ocr",
        "note": "MVP uses manual category mapping as fallback; OCR/frame captions can raise confidence.",
    }


def retrieve_tutorials(category_key: str, limit: int = 5) -> List[Dict[str, Any]]:
    videos = [item for item in load_videos() if item["category_key"] == category_key]
    videos.sort(
        key=lambda item: (
            len(item.get("ingredients", [])) + len(item.get("steps", [])) * 2,
            item.get("stats", {}).get("favorites", 0),
        ),
        reverse=True,
    )
    return videos[:limit]


def retrieve_tutorials_with_ai(category_key: str, dish_name: str = "", limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieve tutorials using AI reranking — always uses AI to judge relevance and rank."""
    all_videos = load_videos()
    if not all_videos:
        return []

    # First filter by category_key as candidates
    matched = [v for v in all_videos if v.get("category_key") == category_key]

    if not ai_client or not ai_client.is_configured():
        return matched[:limit] if matched else all_videos[:limit]

    # Always call AI to rerank and explain why each video is relevant
    aliases = load_aliases()
    dish_display = dish_name or aliases.get(category_key, {}).get("name", category_key)
    system = (
        f"你是烘焙教程检索助手。用户正在看「{dish_display}」相关内容。"
        "请从以下候选视频中判断哪些是该品类的教程，并按相关度排序。"
        "判断依据：标题、描述中是否提到该甜品或其做法。"
        "输出 JSON 数组，每个元素包含 video_id、score(0-1)、reason(一句话理由)。按 score 降序。"
    )
    payload = {
        "query": {"dish_name": dish_display, "category_key": category_key},
        "candidates": [
            {"video_id": v["video_id"], "title": v.get("title", ""), "description": v.get("description", "")[:200]}
            for v in all_videos
        ],
    }
    try:
        result = ai_client.responses_json(system=system, user_payload=payload, schema_name="retrieve")
        rankings = result if isinstance(result, list) else result.get("results", result.get("rankings", []))
        video_map = {v["video_id"]: v for v in all_videos}
        retrieved = []
        for item in rankings:
            vid = item.get("video_id", "")
            if vid in video_map and item.get("score", 0) >= 0.5:
                video_map[vid]["retrieval_score"] = item.get("score", 0)
                video_map[vid]["retrieval_reason"] = item.get("reason", "")
                retrieved.append(video_map[vid])
        return retrieved[:limit] if retrieved else matched[:limit]
    except Exception as exc:
        print(f"[retrieve_ai] fallback: {exc}", file=sys.stderr)
        return matched[:limit] if matched else all_videos[:limit]


def extract_tutorials_with_ai(tutorials: List[Dict[str, Any]], comments_data: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """AI-powered extraction of structured tutorial info from video descriptions and comments."""
    cache_path = DATA_DIR / "generated" / "extracted_tutorials.json"
    if cache_path.exists():
        cached = load_json(cache_path)
        cached_ids = {item["video_id"] for item in cached}
        tutorial_ids = {t["video_id"] for t in tutorials}
        if tutorial_ids.issubset(cached_ids):
            return [item for item in cached if item["video_id"] in tutorial_ids]

    if not ai_client or not ai_client.is_configured():
        return tutorials

    system = (
        "你是烘焙教程信息抽取专家。根据视频标题、描述和评论区内容，"
        "提取每个教程的结构化配方信息。"
        "重点从描述和评论中找到：材料及用量、工具、步骤流程、关键温度时间、状态判断点。"
        "评论区里用户提到的具体克重、温度、时间、工具替代都是有价值的信息。"
        "如果信息不确定，标注'待确认'而不是编造。"
        "输出 JSON 数组，每个元素对应一个教程。"
    )

    tutorial_payloads = []
    comments_by_video = {item["video_id"]: item.get("comments", []) for item in (comments_data or [])}
    for t in tutorials:
        video_comments = comments_by_video.get(t["video_id"], [])
        top_comments = sorted(video_comments, key=lambda c: c.get("likes", 0), reverse=True)[:50]
        tutorial_payloads.append({
            "video_id": t["video_id"],
            "title": t.get("title", ""),
            "description": t.get("description", ""),
            "transcript": t.get("transcript", ""),
            "category": t.get("category", ""),
            "top_comments": [{"text": c["text"], "likes": c.get("likes", 0)} for c in top_comments if c.get("text")],
        })

    payload = {
        "tutorials": tutorial_payloads,
        "required_output_per_tutorial": {
            "video_id": "视频ID",
            "dish_name": "甜品名",
            "ingredients": [{"name": "材料", "amount": "用量", "note": "说明或来源"}],
            "tools": ["工具名"],
            "steps": [{"step": 1, "title": "步骤名", "action": "操作", "key_state": "状态判断", "time": "时间", "temperature": "温度", "risk": "风险"}],
            "flavors": ["口味"],
            "tips_from_comments": ["评论区提到的有用提示"],
        },
    }
    try:
        result = ai_client.responses_json(system=system, user_payload=payload, schema_name="extract_tutorials")
        extracted = result if isinstance(result, list) else result.get("tutorials", result.get("extracted", [result]))
        if extracted:
            save_json(cache_path, extracted)
        return extracted
    except Exception as exc:
        print(f"[extract_ai] fallback: {exc}", file=sys.stderr)
        return tutorials


def summarize_comments(video_ids: List[str]) -> Dict[str, Any]:
    comments_by_video = {
        item["video_id"]: item.get("comments", []) for item in load_comments()
    }
    selected = [
        comment
        for video_id in video_ids
        for comment in comments_by_video.get(video_id, [])
    ]

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in selected:
        grouped[comment.get("label", "其他")].append(comment)

    top_by_group = {
        label: sorted(items, key=lambda item: item.get("likes", 0), reverse=True)[:5]
        for label, items in grouped.items()
    }
    label_counts = Counter(comment.get("label", "其他") for comment in selected)

    return {
        "total_comments_used": len(selected),
        "label_counts": dict(label_counts),
        "top_comments": top_by_group,
        "synthetic_notice": "Current comments are synthetic placeholders and should be replaced with real comments later.",
    }


def analyze_comments_with_ai(video_ids: List[str]) -> Dict[str, Any]:
    fallback = summarize_comments(video_ids)
    if not ai_client or not ai_client.is_configured():
        fallback["ai_status"] = "fallback_no_api_key"
        return fallback

    comments_by_video = {
        item["video_id"]: item.get("comments", []) for item in load_comments()
    }
    selected = []
    for video_id in video_ids:
        video_comments = comments_by_video.get(video_id, [])
        top = sorted(video_comments, key=lambda c: c.get("likes", 0), reverse=True)[:100]
        selected.extend({"video_id": video_id, "text": c.get("text", ""), "likes": c.get("likes", 0)} for c in top if c.get("text"))
    system = (
        "你是烘焙教程评论分析专家。以下是多个同品类烘焙教程的真实评论区数据（按点赞排序）。"
        "请从中提炼对做这道甜品有用的结构化洞察，包括：成功经验、失败原因和解决办法、"
        "工具/材料替代方案、高频问题。"
        "所有洞察必须来自评论原文，不要编造。只输出 JSON。"
    )
    payload = {
        "video_ids": video_ids,
        "comments": selected,
        "required_output": {
            "success_cases": ["被多人验证有效的经验"],
            "failure_reasons": [
                {"problem": "问题", "reason": "可能原因", "solution": "解决建议"}
            ],
            "substitutions": [
                {"need": "用户缺少或想替换的东西", "suggestion": "替代建议"}
            ],
            "faq": [{"question": "高频问题", "answer": "回答"}],
            "risk_alerts": ["容易失败但视频可能没讲清的点"],
        },
    }
    try:
        result = ai_client.responses_json(
            system=system,
            user_payload=payload,
            schema_name="comment_insights",
        )
        result["ai_status"] = "ok"
        result["total_comments_used"] = len(selected)
        result["fallback_summary"] = fallback
        return result
    except Exception as exc:
        fallback["ai_status"] = "fallback_ai_error"
        fallback["ai_error"] = str(exc)
        return fallback


def merge_ingredients(tutorials: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    buckets: Dict[str, List[str]] = defaultdict(list)
    notes: Dict[str, List[str]] = defaultdict(list)
    for tutorial in tutorials:
        for ingredient in tutorial.get("ingredients", []):
            name = ingredient["name"]
            if ingredient.get("amount"):
                buckets[name].append(ingredient["amount"])
            if ingredient.get("note"):
                notes[name].append(ingredient["note"])

    merged = []
    for name, amounts in buckets.items():
        unique_amounts = list(dict.fromkeys(amounts))
        merged.append(
            {
                "name": name,
                "amount": " / ".join(unique_amounts[:3]),
                "note": "；".join(list(dict.fromkeys(notes[name]))[:2]),
            }
        )
    return merged


def synthesize_base_recipe(category_key: str) -> Dict[str, Any]:
    generated_path = DATA_DIR / "generated" / f"{category_key}_base.json"
    if generated_path.exists():
        return load_json(generated_path)

    tutorials = retrieve_tutorials(category_key)
    if not tutorials:
        raise ValueError(f"No tutorials found for category_key={category_key}")

    evidence_ids = [item["video_id"] for item in tutorials]
    comment_summary = summarize_comments(evidence_ids)
    tools = sorted({tool for item in tutorials for tool in item.get("tools", [])})
    flavors = sorted({flavor for item in tutorials for flavor in item.get("flavors", [])})

    return {
        "category": tutorials[0]["category"],
        "category_key": category_key,
        "title": f"基础{tutorials[0]['category']}配方",
        "serving": "待根据真实教程确认",
        "difficulty": "待根据真实教程确认",
        "base_flavor": flavors,
        "ingredients": merge_ingredients(tutorials),
        "tools": tools,
        "steps": tutorials[0].get("steps", []),
        "bake": tutorials[0].get("bake", {}),
        "comment_insights": comment_summary,
        "evidence_videos": evidence_ids,
    }


def synthesize_base_recipe_with_ai(
    category_key: str,
    comment_insights: Optional[Dict[str, Any]] = None,
    extracted_tutorials: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    fallback = synthesize_base_recipe(category_key)
    if not ai_client or not ai_client.is_configured():
        fallback["ai_status"] = "fallback_no_api_key"
        return fallback

    tutorials = extracted_tutorials or retrieve_tutorials(category_key)
    if comment_insights is None:
        comment_insights = analyze_comments_with_ai([item["video_id"] for item in tutorials])
    aliases = load_aliases()
    dish_name = aliases.get(category_key, {}).get("name", category_key)
    has_content = any(t.get("ingredients") or t.get("steps") for t in tutorials)
    system = (
        f"你是专业烘焙配方整理助手。当前品类是「{dish_name}」。"
        "请综合以下教程抽取结果和评论区洞察，生成一份基础配方 JSON。"
        "基础配方要求：可执行、保守、适合家庭厨房。"
        "材料用量如果多个来源不一致，用范围表达。"
        "步骤要包含关键状态判断（如何知道这步做对了）和风险提示。"
        + ("" if has_content else f"教程抽取数据不完整，请结合「{dish_name}」通用知识补充。")
        + "只输出 JSON。"
    )
    payload = {
        "category_key": category_key,
        "tutorials": tutorials,
        "comment_insights": comment_insights,
        "required_output": {
            "category": "品类名",
            "category_key": category_key,
            "title": "基础配方标题",
            "serving": "份量",
            "difficulty": "难度",
            "base_flavor": ["口味"],
            "ingredients": [{"name": "材料", "amount": "用量", "note": "说明"}],
            "tools": ["厨具"],
            "steps": [
                {
                    "step": 1,
                    "title": "步骤名",
                    "action": "操作",
                    "key_state": "状态判断",
                    "time": "时间",
                    "image": "可引用截图路径",
                    "risk": "风险",
                }
            ],
            "bake": {"recommended": "温度时间", "alternatives": ["替代"], "note": "说明"},
            "common_pitfalls": [
                {"problem": "失败表现", "reason": "原因", "solution": "解决办法"}
            ],
            "faq": [{"question": "问题", "answer": "回答"}],
            "evidence_videos": [item["video_id"] for item in tutorials],
        },
    }
    try:
        result = ai_client.responses_json(
            system=system,
            user_payload=payload,
            schema_name="base_recipe",
        )
        result["ai_status"] = "ok"
        result.setdefault("evidence_videos", [item["video_id"] for item in tutorials])
        return result
    except Exception as exc:
        fallback["ai_status"] = "fallback_ai_error"
        fallback["ai_error"] = str(exc)
        return fallback


def personalize_recipe(base: Dict[str, Any], user_requirement: str) -> Dict[str, Any]:
    requirement = user_requirement.lower()
    adjustments: List[str] = []
    tools = list(base.get("tools", []))
    ingredients = list(base.get("ingredients", []))
    steps = list(base.get("steps", []))
    pitfalls = list(base.get("common_pitfalls", []))
    faq = list(base.get("faq", []))

    if any(word in requirement for word in ["少糖", "减糖", "低糖", "控糖"]):
        adjustments.append("糖量降低约 30%，优先减少夹馅糖量，外壳糖量只小幅减少。")
        faq.append(
            {
                "question": "减糖会影响成品吗？",
                "answer": "泡芙外壳糖量较低，少糖主要影响甜味和上色；夹馅减糖更明显也更稳。",
            }
        )

    if "空气炸锅" in requirement or "无烤箱" in requirement:
        adjustments.append("烤箱流程改为空气炸锅小批量烘烤，需要预热并留出膨胀空间。")
        tools = [tool for tool in tools if tool != "烤箱"] + ["空气炸锅"]
        pitfalls.append(
            {
                "problem": "空气炸锅上色快但内部不干",
                "reason": "空间小、热风强，外壳先上色",
                "solution": "先 180°C 定型，再降到 160°C 烤干；单批不要挤太满。",
            }
        )

    if "没有裱花袋" in requirement or "无裱花袋" in requirement:
        adjustments.append("裱花袋替换为厚保鲜袋剪小口，形状会朴素但不影响核心成功率。")
        tools = [tool for tool in tools if tool != "裱花袋"] + ["厚保鲜袋或勺子"]

    if "新手" in requirement or "简单" in requirement:
        adjustments.append("步骤强调状态判断，建议挤小个并保持大小一致，降低夹生和塌陷风险。")
        pitfalls.append(
            {
                "problem": "新手难判断蛋液量",
                "reason": "鸡蛋大小和面粉吸水性不同",
                "solution": "最后 1/4 蛋液慢慢加，看到倒三角就停止。",
            }
        )

    title_prefix = "个性化"
    if adjustments:
        title_prefix = "、".join(
            word
            for word in ["新手" if "新手" in requirement else "", "少糖" if "糖" in requirement else "", "空气炸锅" if "空气炸锅" in requirement else ""]
            if word
        ) or "个性化"

    return {
        "title": f"{title_prefix}版{base['category']}",
        "summary": f"基于 {base['title']}，结合你的需求：{user_requirement}",
        "adjustments": adjustments or ["保留基础配方，仅按用户需求做轻量说明。"],
        "ingredients": ingredients,
        "tools": list(dict.fromkeys(tools)),
        "steps": steps,
        "pitfalls": pitfalls,
        "faq": faq,
        "evidence_videos": base.get("evidence_videos", []),
    }


def personalize_recipe_with_ai(base: Dict[str, Any], user_requirement: str, comment_insights: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fallback = personalize_recipe(base, user_requirement)
    if not ai_client or not ai_client.is_configured():
        fallback["ai_status"] = "fallback_no_api_key"
        return fallback

    dish_name = base.get("category", base.get("dish_name", "甜品"))
    system = (
        f"你是烘焙个性化配方助手。当前品类是「{dish_name}」。"
        "请基于基础配方、用户需求和评论区洞察，输出厨房可执行的个性化配方 JSON。"
        "要求：必须体现用户需求；不能删除关键工艺步骤；保留状态判断和避坑提示；"
        "如果用户要求会降低成功率，要明确提示风险；温度时间不确定时用范围表达。"
        "不要输出 Markdown，只输出 JSON。"
    )
    payload = {
        "base_recipe": base,
        "user_requirement": user_requirement,
        "comment_insights": comment_insights or {},
        "required_output": {
            "title": "个性化配方标题",
            "summary": "改动摘要",
            "adjustments": ["具体改动"],
            "ingredients": [{"name": "材料", "amount": "用量", "note": "说明"}],
            "tools": ["厨具"],
            "steps": [
                {
                    "step": 1,
                    "title": "步骤名",
                    "action": "操作",
                    "key_state": "状态判断",
                    "time": "时间",
                    "image": "截图路径",
                    "risk": "风险",
                }
            ],
            "pitfalls": [
                {"problem": "失败表现", "reason": "原因", "solution": "解决办法"}
            ],
            "faq": [{"question": "问题", "answer": "回答"}],
            "evidence_videos": base.get("evidence_videos", []),
        },
    }
    try:
        result = ai_client.responses_json(
            system=system,
            user_payload=payload,
            schema_name="personalized_recipe",
        )
        result["ai_status"] = "ok"
        result.setdefault("evidence_videos", base.get("evidence_videos", []))
        return result
    except Exception as exc:
        fallback["ai_status"] = "fallback_ai_error"
        fallback["ai_error"] = str(exc)
        return fallback


def run_demo(args: argparse.Namespace) -> Dict[str, Any]:
    log_step(args, "identify subject")
    identified = identify_subject(
        video_id=args.video_id,
        frame_caption=args.frame_caption,
        ocr_text=args.ocr_text,
        title=args.title,
    )
    log_step(args, f"identified {identified['dish_name']} ({identified['category_key']})")
    log_step(args, "retrieve tutorials")
    tutorials = retrieve_tutorials(identified["category_key"])
    log_step(args, f"retrieved {len(tutorials)} tutorials: {', '.join(item['video_id'] for item in tutorials)}")
    use_ai = bool(getattr(args, "ai", False))
    video_ids = [item["video_id"] for item in tutorials]
    log_step(args, "analyze comments")
    comments = (
        analyze_comments_with_ai(video_ids)
        if use_ai
        else summarize_comments([item["video_id"] for item in tutorials])
    )
    log_step(args, f"comment analysis status: {comments.get('ai_status', 'local')}")
    log_step(args, "synthesize base recipe")
    base = (
        synthesize_base_recipe_with_ai(identified["category_key"], comments)
        if use_ai
        else synthesize_base_recipe(identified["category_key"])
    )
    log_step(args, f"base recipe status: {base.get('ai_status', 'local')}")
    log_step(args, "personalize recipe")
    personalized = (
        personalize_recipe_with_ai(base, args.user_requirement)
        if use_ai
        else personalize_recipe(base, args.user_requirement)
    )
    log_step(args, f"personalized recipe status: {personalized.get('ai_status', 'local')}")

    result = {
        "identified": identified,
        "retrieved_tutorials": [
            {
                "video_id": item["video_id"],
                "title": item["title"],
                "category": item["category"],
                "source_video": item["source_video"],
            }
            for item in tutorials
        ],
        "comment_summary": comments,
        "base_recipe": base,
        "personalized_recipe": personalized,
    }
    if args.out:
        save_json(ROOT / args.out, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local dessert recipe MVP pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="Run identify -> retrieve -> synthesize -> personalize.")
    demo.add_argument("--video-id", default="puff_01")
    demo.add_argument("--frame-caption", default="")
    demo.add_argument("--ocr-text", default="")
    demo.add_argument("--title", default="")
    demo.add_argument("--user-requirement", default="我想少糖，用空气炸锅，没有裱花袋，新手。")
    demo.add_argument("--out", default="data/generated/latest_recipe.json")
    demo.add_argument("--ai", action="store_true", help="Use Responses API when CODEX_API_KEY is set.")
    demo.add_argument("--verbose", action="store_true", help="Print pipeline progress to stderr.")

    args = parser.parse_args()
    if args.command == "demo":
        result = run_demo(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
