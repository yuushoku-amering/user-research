# -*- coding: utf-8 -*-
"""组块 ④ · 数据预处理

**声明文件**。把原始数据变成「能拿去分析」的数据：缺失、异常值、反向题、合成变量。
"""
BLOCK = {
    "id": "b4_prep",
    "order": 40,
    "num": "⑤",
    "group": "quant",
    "guard": True,
    "icon": "🧹",
    "name": "数据预处理",
    "title": "⑤ 数据预处理",
    "short": "预处理",
    "desc": "缺失值处理、异常值标记、反向题重编码、量表合成变量。产出 clean_data.csv "
            "和一份「每一步做了什么」的处理日志——可复现的关键就在这份日志。",
    "needs": [],
    "produces": ["output/clean_data.csv"],
    "detect": ["output/clean_data.csv"],
    "hint": "处理日志会写进 output/预处理日志.md，务必和 clean_data.csv 一起存档。",

    "form": [
        {"key": "file", "type": "file", "label": "原始数据", "required": True,
         "placeholder": "data/survey.xlsx"},
        {"key": "missing", "type": "select", "label": "缺失值怎么处理",
         "default": "keep",
         "options": [
             {"value": "keep", "label": "先不动，只报告"},
             {"value": "listwise", "label": "整行删除（只保留完整作答）"},
             {"value": "skipdiff", "label": "只删真漏答，跳题的人留着（结构跳题≠漏答）"},
             {"value": "mice", "label": "⭐ 多重插补（MICE，填 m 套带扰动的数据）"},
             {"value": "mean", "label": "用均值填补（连续变量）"},
             {"value": "median", "label": "用中位数填补（连续变量，抗异常值）"},
             {"value": "mode", "label": "用众数填补（分类变量）"},
             {"value": "col50", "label": "删掉缺失超过 50% 的列"},
         ],
         "hint": "⚠ **空白有两种意思**：一种是「这题对我本来就不适用」（结构跳题，"
                 "比如没谈过恋爱的人不答花销题），一种是「该答没答」（真漏答）。"
                 "「整行删除」会把**跳题的人整群删掉**——而那往往正是要分析的一个子群体，"
                 "报告里还看不出来。分不清就先选「只删真漏答」。\n"
                 "⚠ **别用均值填补当默认**：它把方差压小、把相关稀释、让 p 值偏乐观。"
                 "要用填补就用**多重插补（MICE）**——它会填 m 套带随机扰动的数据，"
                 "既保住变异、又把「填得不确定」算进标准误。"},
        {"key": "mice_m", "type": "number", "label": "多重插补：填几套", "default": 5, "step": 1,
         "hint": "惯例 5~20 套。套数越多越稳，但也越慢。缺失比例高的时候要多填几套。"},
        {"key": "mice_iter", "type": "number", "label": "多重插补：每套扫几轮", "default": 10,
         "step": 5,
         "hint": "链式方程（MICE）会一列一列轮着填、来回扫几轮直到收敛。10 轮通常够。"},
        {"key": "mice_seed", "type": "number", "label": "多重插补：随机种子", "default": 20260926,
         "hint": "固定种子 → 每次跑出同一批插补数据（**可复现**）。换种子可以看结果的稳定性。"},
        {"key": "max_missing_col", "type": "number", "label": "删列的缺失阈值（%）",
         "default": 50, "step": 5},
        {"key": "reverse", "type": "textarea", "label": "反向题（每行一个）",
         "placeholder": "Q3, 5\nQ7, 5",
         "hint": "写出「变量名, 量表最大值」，程序会按 (最大值+1)-原值 重编码。"},
        {"key": "composite", "type": "textarea", "label": "合成变量（每行一个）",
         "placeholder": "满意度 = mean(Q1, Q2, Q3)\n使用意愿 = Q4 + Q5",
         "hint": "支持 mean(...) 求平均、sum(...) 或 + 求和。合成后会自动算一次信度。"},
        {"key": "outlier", "type": "select", "label": "异常值怎么标",
         "default": "z3",
         "options": [
             {"value": "none", "label": "不标"},
             {"value": "z3", "label": "标准分 |z| > 3"},
             {"value": "iqr", "label": "箱线图 1.5 倍 IQR 之外"},
         ],
         "hint": "只做**标记**，不自动删——是不是真异常要你判断。"},
    ],
}
