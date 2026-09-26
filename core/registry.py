# -*- coding: utf-8 -*-
"""工作台 · 组块注册表

**主程序不认识任何具体组块。** 它只扫 blocks/ 下的目录，读每个 block.py 里的
`BLOCK` 声明，然后照着声明渲染界面、派任务。

所以——加一个新组块 = 加一个目录，其他文件一行都不用改。
"""
import importlib.util
import os
import traceback

from . import paths


# 左侧栏的分组：工作台不是一条直线流程 —— ⓪ 是两条线共同的起点，
# ① ② ②b 是质性那条线，③ ④ ⑤ ⑥ 是量化那条线，🔒 是素材入口。
RAIL_GROUPS = [
    {"key": "entry", "label": "入口 / 横切", "hint": "所有分析开始之前该做的事"},
    {"key": "qual", "label": "质性线", "hint": "访谈 → 提纲 → 编码 → 编码汇总"},
    {"key": "quant", "label": "量化线", "hint": "问卷 → 设计 → 回收统计 → 预处理 → 统计分析"},
]


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_blocks():
    """返回按 order 排好序的组块声明列表。坏掉的组块只报警，不拖垮整体。"""
    out = []
    if not os.path.isdir(paths.BLOCKS_DIR):
        return out
    for entry in sorted(os.listdir(paths.BLOCKS_DIR)):
        bdir = os.path.join(paths.BLOCKS_DIR, entry)
        bfile = os.path.join(bdir, "block.py")
        if not os.path.isdir(bdir) or not os.path.exists(bfile):
            continue
        try:
            mod = _load_module(bfile, "urw_block_" + entry)
            decl = dict(getattr(mod, "BLOCK"))
        except Exception:
            traceback.print_exc()
            out.append({
                "id": entry, "order": 999, "name": entry, "icon": "⚠",
                "desc": "这个组块加载失败（见服务端日志）", "broken": True,
                "form": [], "produces": [],
            })
            continue
        decl["_module"] = entry
        decl["_dir"] = bdir
        decl.setdefault("id", entry)
        decl.setdefault("order", 999)
        decl.setdefault("form", [])
        decl.setdefault("produces", [])
        decl.setdefault("detect", [])
        decl.setdefault("engine", "engine.py")
        decl["has_engine"] = os.path.exists(os.path.join(bdir, decl["engine"]))
        out.append(decl)
    out.sort(key=lambda b: (b.get("order", 999), b.get("id", "")))

    # 界面上那个编号符号（⓪ ① ②b …）和标题，都从声明里现算，不写死在 name 里。
    # 这样加/挪一步流程只改 order + num，不用满仓库找「①②③」。
    # num = 数字位（① ②b 🔒 这种）；icon = 那个 emoji，两者分开放。
    for b in out:
        num = b.get("num", "")
        b["num"] = num
        b["group"] = b.get("group") or "quant"
        b["title"] = b.get("title") or ((num + " ") if num else "") + b.get("name", b["id"])
    return out


def find(block_id, blocks=None):
    for b in (blocks if blocks is not None else load_blocks()):
        if b.get("id") == block_id:
            return b
    return None


def public(decl):
    """去掉内部字段（下划线开头 + _dir），给前端用。"""
    return {k: v for k, v in decl.items() if not k.startswith("_")}
