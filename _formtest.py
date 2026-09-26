# -*- coding: utf-8 -*-
"""表单填写随项目走 · 专项自检

守的坑：**导入回来的项目，表单是空的**。

原因不是"没保存"，是**存错了地方**：表单原来只存在浏览器 localStorage 里，
而键是 `urw.form.<项目绝对路径>|组块` —— 项目导出成快照、换台机器导入回来之后
路径变了，键对不上，研究员回来一看：文件都在、图表都在，表单空了，
想接着改都不知道当初填了什么。

现在往项目目录里存一份（`表单填写.json`），快照一打包就跟着走。

跑法：  python _formtest.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import formstate, snapshot                   # noqa: E402
from core.project import Project                       # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, label, extra=None):
    if cond:
        PASS[0] += 1
        print("  [OK] " + label)
    else:
        FAIL[0] += 1
        print("  [!!] " + label + ("" if extra is None else "  —— %s" % (extra,)))


def eq(a, b, label):
    same = a == b
    ok(same, label, None if same else "实际 %r，期望 %r" % (a, b))


def main():
    base = tempfile.mkdtemp(prefix="urw_fs_")
    try:
        root = os.path.join(base, "proj")
        proj = Project(root)
        proj.ensure()
        proj.write_text("contracts/research_brief.md", "# 简报\n")

        print("\n【1】存 / 读")
        eq(formstate.load(proj), {}, "还没存过 → 空字典（不炸）")
        r = formstate.save(proj, "b0_brief",
                           {"purpose": "识别影响续费的因素",
                            "rqs": ["- RQ1 甲：甲", "- RQ2 乙：乙"],
                            "variables": [["满意度", "因变量", "定距", "5 点"]]})
        ok(r.get("ok"), "存成功", r)
        got = formstate.load(proj)
        eq(got["b0_brief"]["purpose"], "识别影响续费的因素", "文字读回来了")
        eq(len(got["b0_brief"]["rqs"]), 2, "列表读回来了")
        eq(got["b0_brief"]["variables"][0][0], "满意度", "表格（二维）也读回来了")
        ok(os.path.exists(proj.safe(formstate.REL)), "文件就叫 %s" % formstate.REL)

        print("\n【2】整块替换：清空一个字段也要记得住")
        formstate.save(proj, "b0_brief", {"purpose": "改了", "rqs": []})
        got2 = formstate.load(proj)
        eq(got2["b0_brief"]["purpose"], "改了", "新值生效")
        eq(got2["b0_brief"]["rqs"], [], "清空的字段就是空的（不是「合并不删」）")
        ok("variables" not in got2["b0_brief"], "上一次有、这次没给的键不再留着")

        print("\n【3】多个组块各存各的，互不影响")
        formstate.save(proj, "b3_survey_design", {"minutes": 8, "parts": ["main"]})
        fs = formstate.load(proj)
        eq(sorted(fs.keys()), ["b0_brief", "b3_survey_design"], "两个组块都在")
        eq(fs["b3_survey_design"]["minutes"], 8, "第二个组块的值对")
        eq(fs["b0_brief"]["purpose"], "改了", "第一个组块没被牵连")

        print("\n【4】边界：空组块名 / 不是字典 / 坏文件")
        ok(not formstate.save(proj, "", {"a": 1}).get("ok"), "没说组块名 → 拒绝")
        ok(not formstate.save(proj, "b0_brief", "不是字典").get("ok"), "内容不是字典 → 拒绝")
        bad = os.path.join(base, "坏项目")
        p2 = Project(bad)
        p2.ensure()
        with open(p2.safe(formstate.REL), "w", encoding="utf-8") as f:
            f.write("{ 这不是 json")
        eq(formstate.load(p2), {}, "文件坏了 → 当空处理，不让工作台起不来")

        print("\n【5】写盘是原子的（写一半不会毁掉上一次的内容）")
        # 实现用的是 tmp + os.replace；这里验"文件内容始终是完整 json"
        formstate.save(proj, "b0_brief", {"purpose": "再来一次"})
        with open(proj.safe(formstate.REL), encoding="utf-8") as f:
            json.load(f)                                   # 解析不了就会抛
        ok(True, "存完之后文件是完整 JSON")
        ok(not os.path.exists(proj.safe(formstate.REL) + ".tmp"), "临时文件没留下")

        print("\n【6】关键：导出快照 → 导入回来，表单还在")
        out = os.path.join(base, "out")
        os.makedirs(out, exist_ok=True)
        info = snapshot.export(root, out, with_history=True)
        with zipfile.ZipFile(info["file"]) as z:
            names = z.namelist()
        ok(any(formstate.REL in n for n in names),
           "快照里带上了 %s" % formstate.REL, names)
        newroot, _note = snapshot.import_snapshot(info["file"], os.path.join(base, "imported"))
        proj3 = Project(newroot)
        got3 = formstate.load(proj3)
        ok(bool(got3.get("b0_brief")), "导入回来读得到表单内容")
        eq(got3["b0_brief"]["purpose"], "再来一次", "内容一模一样（路径变了也不怕）")
        eq(got3["b3_survey_design"]["minutes"], 8, "第二个组块也带过来了")

        print("\n【7】它不该混进「产物」列表（那是给研究结果看的）")
        ok(all(formstate.REL not in a["rel"] for a in proj3.artifacts()),
           "产物列表里没有它", [a["rel"] for a in proj3.artifacts()])
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("\n" + ("全部通过" if FAIL[0] == 0 else "有失败项") + "：%d 通过 / %d 失败\n"
          % (PASS[0], FAIL[0]))
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
