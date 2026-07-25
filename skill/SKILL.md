# SKILL.md - 焙小满烘焙 AI 助手技能封装

## 技能概述

**技能名称**：焙小满烘焙配方生成 Skill

**一句话描述**：基于视频画面识别甜品主体 → 搜索教程库 → 抽取评论经验 → 生成个性化配方的完整 AI Workflow。

**适用场景**：用户观看烘焙短视频时，想要获得适合自己条件的制作方案。

---

## 技能包含的 6 个子 Skill

### Skill 1：视觉甜品识别（Vision Identify）

**触发条件**：用户提供一张烘焙相关图片/视频帧

**输入**：
- `image_base64`：图片的 base64 编码
- `categories`：可选品类列表（如 ["泡芙", "雪媚娘", "巴斯克芝士蛋糕"]）

**输出**：
```json
{
  "dish_name": "品类名",
  "category_key": "品类标识",
  "confidence": 0.92,
  "reason": "判断理由"
}
```

**模型**：多模态视觉模型（meta-llama/llama-4-scout）

**Prompt 模板**：
```
你是一个烘焙甜品识别专家。用户会给你一张烘焙视频的截图，
请判断这张图里的甜品属于以下哪个品类：{categories}。
只输出 JSON 格式，包含 dish_name（品类名）、confidence（0-1的置信度）、reason（判断理由，一句话）。
如果无法确定，confidence 设为 0.3 以下并说明原因。
不要输出 Markdown，只输出纯 JSON。
```

---

### Skill 2：教程检索重排（Retrieval Rerank）

**触发条件**：已识别出甜品品类，需要从教程库中找到相关教程

**输入**：
- `dish_name`：甜品品类名
- `category_key`：品类标识
- `candidates`：候选视频列表（含 video_id, title, description）

**输出**：
```json
[
  {"video_id": "...", "score": 0.96, "reason": "标题明确提到该品类"}
]
```

**模型**：qwen/qwen2.5-vl-72b-instruct

**Prompt 模板**：
```
你是烘焙教程检索助手。用户正在看「{dish_name}」相关内容。
请从以下候选视频中判断哪些是该品类的教程，并按相关度排序。
判断依据：标题、描述中是否提到该甜品或其做法。
输出 JSON 数组，每个元素包含 video_id、score(0-1)、reason(一句话理由)。按 score 降序。
```

---

### Skill 3：教程信息抽取（Tutorial Extraction）

**触发条件**：已检索到相关教程，需要从视频描述和评论中提取结构化配方

**输入**：
- `tutorials`：教程列表（含 video_id, title, description, top_comments）

**输出**：每个教程的结构化信息
```json
[
  {
    "video_id": "...",
    "ingredients": [{"name": "材料", "amount": "用量", "note": "说明"}],
    "tools": ["工具名"],
    "steps": [{"step": 1, "title": "步骤", "action": "操作", "key_state": "状态判断", "time": "时间", "risk": "风险"}],
    "tips_from_comments": ["评论区提示"]
  }
]
```

**模型**：qwen/qwen2.5-vl-72b-instruct

**Prompt 模板**：
```
你是烘焙教程信息抽取专家。根据视频标题、描述和评论区内容，
提取每个教程的结构化配方信息。
重点从描述和评论中找到：材料及用量、工具、步骤流程、关键温度时间、状态判断点。
评论区里用户提到的具体克重、温度、时间、工具替代都是有价值的信息。
如果信息不确定，标注'待确认'而不是编造。
输出 JSON 数组，每个元素对应一个教程。
```

---

### Skill 4：评论区洞察分析（Comment Analysis）

**触发条件**：已检索到相关教程，需要从评论区提取经验洞察

**输入**：
- `video_ids`：视频ID列表
- `comments`：评论列表（含 text, likes, video_id）

**输出**：
```json
{
  "success_cases": ["成功经验"],
  "failure_reasons": [{"problem": "问题", "reason": "原因", "solution": "解决"}],
  "substitutions": [{"need": "缺什么", "suggestion": "替代方案"}],
  "faq": [{"question": "问题", "answer": "回答"}],
  "risk_alerts": ["风险提醒"]
}
```

**模型**：qwen/qwen2.5-vl-72b-instruct

**Prompt 模板**：
```
你是烘焙教程评论分析专家。以下是多个同品类烘焙教程的真实评论区数据（按点赞排序）。
请从中提炼对做这道甜品有用的结构化洞察，包括：成功经验、失败原因和解决办法、
工具/材料替代方案、高频问题。
所有洞察必须来自评论原文，不要编造。只输出 JSON。
```

---

### Skill 5：基础配方综合（Base Recipe Synthesis）

**触发条件**：已完成教程抽取和评论洞察，需要综合生成基础配方

**输入**：
- `category_key`：品类标识
- `dish_name`：品类名
- `extracted_tutorials`：抽取结果列表
- `comment_insights`：评论洞察

**输出**：
```json
{
  "title": "基础配方标题",
  "serving": "份量",
  "difficulty": "难度",
  "ingredients": [{"name": "材料", "amount": "用量", "note": "说明"}],
  "tools": ["工具"],
  "steps": [{"step": 1, "title": "步骤", "action": "操作", "key_state": "状态判断", "time": "时间", "risk": "风险"}],
  "common_pitfalls": [{"problem": "问题", "reason": "原因", "solution": "解决"}],
  "faq": [{"question": "问题", "answer": "回答"}]
}
```

**模型**：qwen/qwen2.5-vl-72b-instruct

**Prompt 模板**：
```
你是专业烘焙配方整理助手。当前品类是「{dish_name}」。
请综合以下教程抽取结果和评论区洞察，生成一份基础配方 JSON。
基础配方要求：可执行、保守、适合家庭厨房。
材料用量如果多个来源不一致，用范围表达。
步骤要包含关键状态判断（如何知道这步做对了）和风险提示。
只输出 JSON。
```

---

### Skill 6：个性化配方生成（Personalized Recipe）

**触发条件**：用户输入了个性化需求

**输入**：
- `base_recipe`：基础配方
- `user_requirement`：用户需求（如"少糖、空气炸锅、新手"）
- `comment_insights`：评论洞察

**输出**：
```json
{
  "title": "个性化配方标题",
  "summary": "改动摘要",
  "adjustments": ["调整1", "调整2"],
  "ingredients": [...],
  "tools": [...],
  "steps": [...],
  "pitfalls": [...],
  "faq": [...]
}
```

**模型**：qwen/qwen2.5-vl-72b-instruct

**Prompt 模板**：
```
你是烘焙个性化配方助手。当前品类是「{dish_name}」。
请基于基础配方、用户需求和评论区洞察，输出厨房可执行的个性化配方 JSON。
要求：必须体现用户需求；不能删除关键工艺步骤；保留状态判断和避坑提示；
如果用户要求会降低成功率，要明确提示风险；温度时间不确定时用范围表达。
不要输出 Markdown，只输出 JSON。
```

---

## Workflow 编排

```
[用户暂停视频]
    → Skill 1: 视觉识别
        → Skill 2: 检索重排
            → Skill 3: 教程抽取（并行）
            → Skill 4: 评论洞察（并行）
                → Skill 5: 基础配方综合
[用户输入需求]
    → Skill 6: 个性化生成
[输出结果]
```

## 质量保证

每个 Skill 的输出都有校验逻辑：
- 必须返回有效 JSON
- 必须包含规定的必填字段
- 不满足时自动重试一次
- 重试仍失败时使用缓存或降级方案

## 文件清单

```
skill/
├── SKILL.md              # 本文件
├── scripts/
│   ├── ai_client.py      # AI 调用客户端（支持视觉+文本+生图）
│   ├── pipeline.py       # 6 个 Skill 的具体实现
│   └── preprocess.py     # 预处理脚本（批量运行 Skill 2-5）
├── data/
│   ├── category_aliases.json  # 品类别名配置
│   └── generated/             # Skill 输出缓存
└── app/
    └── server.py         # HTTP API 封装
```
