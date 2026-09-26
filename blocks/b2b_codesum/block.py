# -*- coding: utf-8 -*-
"""组块 ②b · 编码汇总（范畴 → 主题）

**声明文件**。读研究员填完的编码工作表，把「开放编码 → 范畴 → 主题」数成
一张能直接放进报告的汇总表，并挑出编码里的毛病。
"""
BLOCK = {
    "id": "b2b_codesum",
    "order": 21,
    "num": "②b",
    "group": "qual",
    "guard": True,
    "icon": "🧮",
    "name": "编码汇总（范畴 → 主题）",
    "title": "②b 编码汇总（范畴 → 主题）",
    "short": "编码汇总",
    "desc": "读你填完的编码工作表，把散在各段的码数成一张能放进报告的汇总表："
            "每个主题由哪些范畴撑起来、覆盖了几位受访者、几段证据、最该引哪句原话。"
            "**它只统计你写的码，不替你编码**；它负责挑毛病——"
            "哪些主题其实只有一个人提过、哪些范畴只有一条证据。",
    "needs": ["output/编码工作表.csv"],
    "produces": ["output/编码汇总.md", "output/编码汇总_主题.csv",
                 "output/编码汇总_范畴.csv", "output/编码_主题矩阵.csv",
                 "contracts/coded_transcript.md"],
    "detect": ["output/编码汇总.md"],
    "hint": "先在 Excel 里把 ② 生成的编码工作表填完（开放编码 / 范畴 / 主题 三列）。"
            "一个格子里填多个码，用 、或 ； 分开。没填全也能跑——它会告诉你卡在哪一步。",

    "form": [
        {"key": "coded_file", "type": "file", "label": "填好的编码工作表",
         "default": "output/编码工作表.csv",
         "hint": "② 生成的那张 CSV（或你自己另存的 Excel）。"},
        {"key": "min_cover", "type": "number", "label": "主题至少覆盖几位受访者", "default": 2, "step": 1,
         "hint": "只被一个人提到的主题，程序会点名——那不是错，但报告里不能写成普遍现象。"},
        {"key": "max_themes", "type": "number", "label": "主题数上限", "default": 6, "step": 1,
         "hint": "超过就提醒「归得太细」。定性研究的主题一般 3~6 个。"},
        {"key": "quote_n", "type": "number", "label": "每个主题挑几条候选引语", "default": 3, "step": 1},
        {"key": "iv_names", "type": "text", "label": "谁是访谈者（一般不用填）",
         "default": "",
         "hint": "程序按这个顺序认：**你在这里填的** → ② 留下的元信息"
                 "（`output/编码工作表_元信息.json`，② 跑完自动写）→ "
                 "编码表里带的 `采访者：` → **第一个开口的人**。"
                 "访谈者的提问不计入证据段数、也不算一位受访者。"
                 "多场访谈拼在一张表里时，第二场的采访者最容易被算成新受访者"
                 "（覆盖人数虚高，会改结论）—— 上面几招都没认出来时，"
                 "就在这里写名字，多个用「、」或「,」分开。"},
        {"key": "opts", "type": "checks", "label": "处理选项", "default": ["list_uncoded"],
         "options": [
             {"value": "list_uncoded", "label": "把没编码的段落单独列出来"},
             {"value": "keep_interviewer", "label": "访谈者的提问也算「已编码」（不算漏编）"},
         ]},
    ],
}
