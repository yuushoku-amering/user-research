# -*- coding: utf-8 -*-
"""模型通道自测（**会真的调用一次 DeepSeek**，消耗少量额度）

    python _llmtest.py                        # 默认 ⓪ 研究设计，用案例项目的口述需求
    python _llmtest.py b5_stats               # 换一个组块
    python _llmtest.py b0_brief <项目目录>     # 指定项目

跑完会把「待确认」标记数出来——模型该编的地方编没编、该留的地方留没留，
一眼就能看出来。测完自动把模型开关关回去（省钱）。
"""
import json
import os
import re
import shutil
import sys
import time
import urllib.request

# ⚠ 控制台是 GBK：打印 emoji / 特殊符号会 UnicodeEncodeError 把测试打断。
#   这一句是**必须**的（踩过两次）。
try:
    sys.stdout.reconfigure(encoding=utf-8, errors=replace)
    sys.stderr.reconfigure(encoding=utf-8, errors=replace)
except Exception:
    pass


HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8765"
BLOCK = sys.argv[1] if len(sys.argv) > 1 else "b0_brief"


def _pick_project():
    """靶子项目：命令行给的 > 旁边的案例项目 > 用**现场造**的素材临时拼一个。

    原来写死成某个真实案例项目的绝对路径 —— 别人 clone 下来没有那个项目，
    跑起来只会报「目录不存在」，而真正被测的（模型通道）根本还没轮到。
    """
    if len(sys.argv) > 2:
        return os.path.abspath(sys.argv[2])
    real = os.path.abspath(os.path.join(HERE, "..", "projects", "小鹰扫描_付费转化研究"))
    if os.path.isdir(real):
        return real
    tmp = os.path.join(HERE, "_jobs", "tmp_llm_proj")
    os.makedirs(os.path.join(tmp, "samples"), exist_ok=True)
    sys.path.insert(0, HERE)
    from _fixtures import build_all
    build_all()
    src = os.path.join(HERE, "_jobs", "fixtures")
    for name in ("研究员口述需求.txt", "research_brief.md",
                 "访谈转写稿_小周.txt", "访谈转写稿_小林.txt"):
        f = os.path.join(src, name)
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(tmp, "samples", name))
    return tmp


PROJECT = _pick_project()

CONF_RE = re.compile(r"[（(【\[]\s*(待确认|待补充|待定|TBD)\s*[:：]?\s*([^）)】\]]*?)\s*[）)】\]]")


def params_for(block, project):
    """给组块准备一份「界面上填了什么」。"""
    p = {}
    if block == "b0_brief":
        src = os.path.join(project, "samples", "研究员口述需求.txt")
        if os.path.exists(src):
            with open(src, "r", encoding="utf-8", errors="replace") as f:
                p["background"] = f.read().strip()
        p["data_types"] = ["survey", "interview"]
    return p


def post(path, data, timeout=400):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    out = []
    out.append("=" * 70)
    out.append("模型通道自测 · 组块 %s · 项目 %s" % (BLOCK, os.path.basename(PROJECT)))
    out.append("=" * 70)

    params = params_for(BLOCK, PROJECT)
    out.append("1) 表单内容：%s" % ("、".join(params.keys()) or "（空）"))

    cfg = post("/api/config/save", {"config": {"llm": {"enabled": True}}})
    out.append("2) 打开模型通道：ok=%s" % cfg.get("ok"))

    t0 = time.time()
    out.append("3) 调用 /api/llm（可能要 30~120 秒）…")
    try:
        r = post("/api/llm", {"block_id": BLOCK, "params": params, "project": PROJECT})
    except Exception as e:
        out.append("   调用失败：%s" % e)
        r = {"ok": False}

    out.append("   耗时 %.1fs" % (time.time() - t0))
    if r.get("ok"):
        text = r.get("text", "")
        out.append("   ok=True  model=%s  模型自报耗时=%ss" % (r.get("model"), r.get("seconds")))
        out.append("   任务书：%s" % r.get("task_file"))
        fields = r.get("fields") or {}
        out.append("   解析出的小节：%d 个（%s）" % (
            len(fields), "、".join(fields.keys()) or "—"))
        if r.get("missing_fields"):
            out.append("   没解析出来的小节：%s" % "、".join(r["missing_fields"]))

        marks = CONF_RE.findall(text)
        out.append("")
        out.append("4) 待确认项：**%d 处**（这些会在界面右边侧栏里一条条过）" % len(marks))
        for i, (kind, hint) in enumerate(marks[:15], 1):
            out.append("   %2d. %s：%s" % (i, kind, hint or "（模型没说要确认什么）"))
        if not marks:
            out.append("   ⚠ 一处都没有——要么材料确实够全，要么模型在编。看下面正文自己判断。")

        out.append("")
        out.append("-" * 70)
        out.append(text)
        out.append("-" * 70)
    else:
        out.append("   ok=False")
        out.append("   error: %s" % r.get("error"))
        if r.get("status"):
            out.append("   status: %s" % json.dumps(r["status"], ensure_ascii=False))

    post("/api/config/save", {"config": {"llm": {"enabled": False}}})
    out.append("")
    out.append("5) 已把模型通道关回 false（要用再点界面上的开关）")

    p = os.path.join(HERE, "_jobs", "llmtest.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("OK -> %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
