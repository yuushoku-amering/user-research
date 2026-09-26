# -*- coding: utf-8 -*-
"""组块 ② · 访谈记录编码整理

**声明文件**。把转写稿拆成发言单元，生成一张能直接填的编码工作表。
"""
BLOCK = {
    "id": "b2_coding",
    "order": 20,
    "num": "②",
    "group": "qual",
    "guard": True,
    "icon": "🏷",
    "name": "访谈记录编码整理",
    "title": "② 访谈记录编码整理",
    "short": "访谈编码",
    "desc": "把访谈转写稿拆成「发言单元」，生成一张可以直接填的编码工作表"
            "（开放编码 → 范畴 → 主题），并给出关键词、候选主题线索和引语候选。"
            "**编码本身是你的活**——程序只负责把材料摆整齐、把线索指出来。",
    "needs": ["contracts/interview_guide.md"],
    "produces": ["output/编码工作表.csv"],
    "detect": ["output/编码工作表.csv"],
    "hint": "生成的 CSV 用 Excel 打开就能填；填完把「范畴」「主题」两列汇总，就是编码表。"
            "转写稿如果含真实姓名，先过 🔒 去标识化。",

    "form": [
        {"key": "transcript", "type": "file", "label": "访谈转写稿", "required": True,
         "hint": "支持 .txt / .md / .srt / .csv。「说话人：内容」的格式会自动识别。"},
        {"key": "iv_names", "type": "text", "label": "谁是访谈者（一般不用填）",
         "default": "",
         "hint": "程序按这个顺序认：**你在这里填的** → 稿子开头的 `采访者：` / `访谈者：` → "
                 "**第一个开口的人**。认出来的结果会写进 "
                 "`output/编码工作表_元信息.json`，②b 汇总时读它 —— "
                 "这样就不会把采访者算成一位受访者。"
                 "多个名字用「、」或「,」分开；名字照「说话人」列的样子写，"
                 "去标识化后的 `[姓名1]` 也一样。"
                 "⚠ 别把 `受访者：` 那一行的人填进来 —— 他是受访者，不是采访者。"},
        {"key": "split", "type": "select", "label": "怎么拆发言单元",
         "default": "speaker",
         "options": [
             {"value": "speaker", "label": "按说话人（推荐，转写稿是「张三：…」格式时）"},
             {"value": "para", "label": "按空行/段落"},
             {"value": "sentence", "label": "按句子（每句一行，最细）"},
         ]},
        {"key": "keep_interviewer", "type": "checks", "label": "处理选项",
         "default": ["keep_q"],
         "options": [
             {"value": "keep_q", "label": "保留访谈者的话（提问也是解读线索）"},
             {"value": "drop_short", "label": "丢掉太短的附和（「嗯」「对」「哈哈」）"},
         ]},
        {"key": "min_len", "type": "number", "label": "最短保留多少字", "default": 6, "step": 1},
        {"key": "top_kw", "type": "number", "label": "提取多少个关键词", "default": 25, "step": 5},
    ],
}
