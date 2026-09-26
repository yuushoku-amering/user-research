# -*- coding: utf-8 -*-
"""组块 ③ · 问卷数据统计

**声明文件**：告诉工作台「我是谁、要什么输入、产出什么、界面上摆哪些控件」。
真正的计算在 engine.py 里——主程序不认识这个组块，只照着下面的声明办事。
"""

BLOCK = {
    "id": "b3_survey",
    "order": 30,
    "num": "④",
    "group": "quant",
    "guard": True,
    "icon": "📊",
    "name": "问卷数据统计",
    "title": "④ 问卷数据统计",
    "short": "问卷统计",
    "desc": "导入问卷导出文件（Excel / CSV / SPSS .sav），产出样本概况、频数分布、"
            "描述统计、交叉表、量表信度。数字全部由 Python 算，模型只负责解释。",

    # 这一步依赖谁：没有也不拦着，只是界面上提醒一下
    "needs": [],
    # 做完的标志：这些文件在项目里出现了
    "produces": ["output/问卷_概要.md"],
    "detect": ["output/问卷_概要.md"],

    "hint": "列名里带序号（如 Q1_1、Q1_2…）的会被自动认成一张量表，可以直接算信度。",

    "form": [
        {
            "key": "file",
            "type": "file",
            "label": "问卷数据文件",
            "required": True,
            "hint": "支持 .xlsx / .csv / .sav。也可以把文件放进项目的 data/ 目录，再从右边挑。",
            "placeholder": "data/survey.xlsx",
        },
        {
            "key": "tasks",
            "type": "checks",
            "label": "要算什么",
            "default": ["profile", "freq", "desc"],
            "options": [
                {"value": "profile", "label": "样本概况"},
                {"value": "freq", "label": "频数分布"},
                {"value": "desc", "label": "描述统计"},
                {"value": "cross", "label": "交叉表 + 卡方"},
                {"value": "alpha", "label": "量表信度 α"},
                {"value": "factor", "label": "因子分析 / 效度（KMO、Bartlett、旋转载荷）"},
                {"value": "open", "label": "开放题关键词"},
            ],
        },
        {
            "key": "cross_vars",
            "type": "textarea",
            "label": "交叉表：要交叉哪几对变量",
            "placeholder": "每行一对，用逗号隔开：\n性别, 常用平台\n年级, 使用频率",
            "hint": "留空的话，会自动挑两个分类变量做一对。",
        },
        {
            "key": "scale_vars",
            "type": "text",
            "label": "量表信度 / 因子分析：题目变量名（可选）",
            "hint": "留空 = 自动猜（列名带序号的同一组题）。这两项**都用这一栏**——"
                    "效度和信度本来就该一起报。",
        },
        {
            "key": "factor_method",
            "type": "select",
            "label": "因子分析：用哪种抽取",
            "default": "pca",
            "options": [
                {"value": "pca", "label": "主成分（看「解释了多少方差」）"},
                {"value": "pa", "label": "主轴因子（看「共同的潜结构」）"},
            ],
            "hint": "⚠ 两者**载荷不一样**，报告里必须写清用的是哪个。"
                    "问卷效度常用主成分；想更贴近「潜变量」的思路用主轴因子。",
        },
        {
            "key": "factor_n",
            "type": "number",
            "label": "因子分析：抽几个因子（0 = 自动判断）",
            "default": 0,
            "hint": "自动判断会同时给 **Kaiser 准则（特征值>1）** 和 **平行分析** 两个建议，"
                    "并按平行分析来抽。⚠ 只看特征值>1 在题目多的时候会高估因子数。",
        },
        {
            "key": "open_var",
            "type": "text",
            "label": "开放题变量名（可选）",
            "placeholder": "比如 Q12_open",
        },
        {
            "key": "top_n",
            "type": "number",
            "label": "频数表每列最多显示几类",
            "default": 15,
            "step": 1,
        },
    ],
}
