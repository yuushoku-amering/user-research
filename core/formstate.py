# -*- coding: utf-8 -*-
"""工作台 · 表单里填过的东西

**为什么单独存一份到项目目录里**（`表单填写.json`）：

浏览器 localStorage 的键是 `urw.form.<项目路径>|b0_brief` —— 带了**绝对路径**。
项目导出成快照、换台机器导入回来之后路径变了，键就对不上，研究员回来一看：
简报文件都在、图表都在，**表单却是空的**，想接着改都不知道当初填了什么。

所以往项目里存：快照一打包就跟着走。localStorage 仍然留着（刷新不丢），
但**项目里这份是能带走的那份**。

⚠ 存的是「你填了什么」，不是「引擎算出来的」。角色分工：
    · 项目里的 `表单填写.json`   = 研究员填的输入（可带走、可读、人可以手改）
    · contracts/ 与 output/      = 引擎的产物（这个才是"结果"）
"""
import json
import os
import time

REL = "表单填写.json"


def _p(proj):
    return proj.safe(REL)


def load(proj):
    """读回所有组块的填写内容：{block_id: {field: value}}。读不到就是空字典。"""
    p = _p(proj)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    forms = d.get("blocks") if isinstance(d, dict) else None
    return forms if isinstance(forms, dict) else {}


def save(proj, block_id, fields):
    """记下一个组块的填写内容。**整块替换** —— 清空某个字段也要能记下来。"""
    block_id = str(block_id or "").strip()
    if not block_id:
        return {"ok": False, "error": "没说这是哪个组块"}
    if not isinstance(fields, dict):
        return {"ok": False, "error": "填写内容得是个字典"}
    p = _p(proj)
    data = {}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    blocks = data.get("blocks") if isinstance(data, dict) else {}
    if not isinstance(blocks, dict):
        blocks = {}
    # 有些字段是"只读回显"（比如自动读到的文件路径），存了也没用还容易过期。
    # 这里不挑三拣四 —— 存下来最省心，读的时候由前端决定怎么用。
    blocks[block_id] = fields
    data = {
        "note": ("研究员在表单里填过的东西。**这份是可以跟着项目走的** —— "
                 "导出成快照再导入回来，表单里还是这些内容。"
                 "想清空某一栏，就把它的值改成空字符串/空数组（整块替换，不会只合并不删）。"),
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "blocks": blocks,
    }
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)          # 原子替换：写一半断电也不会把上一次的内容毁掉
    return {"ok": True, "block": block_id, "fields": len(fields)}
