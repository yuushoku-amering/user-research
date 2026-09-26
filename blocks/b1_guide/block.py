# -*- coding: utf-8 -*-
"""组块 ① · 访谈提纲设计

**声明文件**。读研究简报，产出半结构式提纲：暖场 → 主问题（按 RQ 组织）→ 追问 → 收尾。
"""
BLOCK = {
    "id": "b1_guide",
    "order": 10,
    "num": "①",
    "group": "qual",
    # 这道关：跑之前先看项目里有没有「还没脱敏、但能认出手机/邮箱/身份证」的素材
    # （见 core/guard.py；不是硬拦，是让你确认知悉）
    "guard": True,
    "icon": "📝",
    "name": "访谈提纲设计",
    "title": "① 访谈提纲设计",
    "short": "访谈提纲",
    "desc": "读研究简报，把研究问题摊成一份能直接拿去用的半结构式提纲："
            "开场与知情同意 → 暖场 → 按 RQ 分块的主问题与追问角度 → 收尾，"
            "外加一份访谈者备忘（哪些问法会引导受访者）。",
    "needs": ["contracts/research_brief.md"],
    "produces": ["contracts/interview_guide.md"],
    "detect": ["contracts/interview_guide.md"],
    "hint": "提纲是骨架不是剧本——每个 RQ 下给的是「提问角度」，现场挑 2~3 个问就够，问多了会变成审讯。",

    "llm": {
        "title": "让模型根据研究简报写提纲初稿",
        "prompt": """根据材料里的研究简报，写一份半结构式访谈提纲初稿。

结构：
## 0. 开场与知情同意
## 1. 暖场（3 题）
## 2. 主问题
## 3. 深挖
## 4. 收尾（2 题）

第 2 节要**按 RQ 分块**：每个 RQ 下面给 2~3 个主问题，每个主问题配 1~2 个追问。
每个问题后面用括号标注它服务于哪个 RQ。

硬性要求（违反了这份提纲就不能用）：
- 问题必须**口语化**，像真人说话，不要书面语
- 必须**开放**：绝不能是「你是不是因为 X 才 Y」这种封闭式或引导式问法
- 一次只问一件事，不要一句话里塞两个问题
- 不要问「你觉得这个功能好不好用」——要问「你上次用它是什么时候？当时怎么样？」
- 深挖那一节只写材料里真正提到的点，不要自己加话题""",
        "materials": ["contracts/research_brief.md"],
        "output_rules": "- 直接输出 Markdown 提纲，从 `# 访谈提纲` 开始。\n"
                        "- 不要前言、不要解释、不要包在代码块里。",
    },

    "form": [
        {"key": "brief", "type": "file", "label": "研究简报（自动读）",
         "default": "contracts/research_brief.md",
         "hint": "默认读组块 ⓪ 的产物。没有也能跑，只是提纲会缺研究问题那一层。"},
        {"key": "audience", "type": "text", "label": "受访者是谁", "required": True,
         "placeholder": "比如：近 30 天内流失的 Android 老玩家"},
        {"key": "duration", "type": "number", "label": "访谈时长（分钟）", "default": 45, "step": 5},
        {"key": "style", "type": "select", "label": "访谈形式",
         "default": "semi",
         "options": [
             {"value": "semi", "label": "半结构式（有提纲，可追问）"},
             {"value": "deep", "label": "深度访谈（少提纲，多倾听）"},
             {"value": "focus", "label": "焦点小组（6-8 人，重互动）"},
         ]},
        {"key": "focus", "type": "textarea", "label": "特别想挖的点（每行一个，可留空）",
         "placeholder": "闪退到底影响了哪些具体场景\n数值改动前后，玩家的投入感受变化"},
        {"key": "channels", "type": "text", "label": "招募渠道（可留空）",
         "placeholder": "比如：游戏内弹窗 + 官方 QQ 群"},
    ],
}
