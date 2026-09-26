# -*- coding: utf-8 -*-
"""项目快照 · 往返自检（存成文件 → 导回来 → 内容一模一样）

    python _snapshottest.py

顺带守三条安全线：
  · 重名项目**绝不覆盖**，会加后缀
  · 快照里有 `..` / 绝对路径 → 拒绝解压
  · 不许把快照存进项目目录自己里面（会自我套娃）
"""
import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import snapshot          # noqa: E402

JOBS = os.path.join(HERE, "_jobs")
TMP = os.path.join(JOBS, "tmp_snapshot")
PASS, FAIL = [], []


def ok(cond, label, extra=""):
    (PASS if cond else FAIL).append(label + ("" if cond else "  ← " + str(extra)))
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else "  ← " + str(extra)))


def build_project(root):
    os.makedirs(os.path.join(root, "contracts"), exist_ok=True)
    os.makedirs(os.path.join(root, "output"), exist_ok=True)
    os.makedirs(os.path.join(root, "_history"), exist_ok=True)
    os.makedirs(os.path.join(root, "__pycache__"), exist_ok=True)
    with open(os.path.join(root, "project.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "测试项目", "created": "2026-09-20"}, f, ensure_ascii=False)
    with open(os.path.join(root, "contracts", "research_brief.md"), "w", encoding="utf-8") as f:
        f.write("# 研究简报\n\n内容带中文，还有 emoji 🐟\n")
    with open(os.path.join(root, "output", "分析报告.md"), "w", encoding="utf-8") as f:
        f.write("# 报告\n\nR²=0.634\n")
    with open(os.path.join(root, "_history", "旧版.md"), "w", encoding="utf-8") as f:
        f.write("覆盖前的备份\n")
    with open(os.path.join(root, "__pycache__", "垃圾.pyc"), "wb") as f:
        f.write(b"\x00\x01\x02")


def tree(root, skip=("__pycache__", "快照信息.json")):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            if f in skip:
                continue
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root).replace("\\", "/")] = open(p, "rb").read()
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)
    proj = os.path.join(TMP, "projects", "测试项目")
    dest = os.path.join(TMP, "我的快照")
    newparent = os.path.join(TMP, "还原到这儿", "projects")
    build_project(proj)

    print("=" * 70)
    print("一、存成一个文件")
    print("=" * 70)
    info = snapshot.export(proj, dest)
    ok(os.path.exists(info["file"]), "文件存下来了", info["file"])
    ok(info["file"].lower().endswith(".urwproj"), "后缀是 .urwproj", info["file"])
    ok("测试项目" in os.path.basename(info["file"]), "文件名里带项目名", os.path.basename(info["file"]))
    ok(zipfile.is_zipfile(info["file"]), "里面确实是个 zip")
    ok(info["files"] == 4, "打包了 4 个文件（含 _history，不含 __pycache__）", info["files"])

    with zipfile.ZipFile(info["file"]) as z:
        names = z.namelist()
    ok("快照信息.json" in names, "里面有一份快照信息.json")
    ok(not any("__pycache__" in n for n in names), "__pycache__ 被排掉了", names)
    ok(any(n.endswith("_history/旧版.md") for n in names), "_history 默认保留")

    mf = snapshot.peek(info["file"])
    ok(mf.get("格式", "").endswith("项目快照"), "身份证写着是本工作台的快照", mf.get("格式"))
    ok(mf.get("原始路径") == os.path.abspath(proj), "记下了原始路径")

    print("")
    print("=" * 70)
    print("二、导回来，内容要对得上")
    print("=" * 70)
    root2, info2 = snapshot.import_snapshot(info["file"], newparent)
    ok(os.path.isdir(root2), "解到了新目录", root2)
    ok(root2 != os.path.abspath(proj), "不是解回原目录")
    a, b = tree(proj), tree(root2)
    a.pop("快照信息.json", None)
    b.pop("快照信息.json", None)
    ok("project.json" in a and "project.json" in b, "两份里都有 project.json")
    a.pop("project.json", None)
    b.pop("project.json", None)
    missing = [k for k in a if k not in b or a[k] != b[k]]
    ok(not missing, "每个文件都一模一样（含中文和 emoji）", missing)
    extra = [k for k in b if k not in a]
    ok(extra == [], "没有多出来的东西（project.json 另算，它记了一笔导入信息）", extra)
    meta = json.load(open(os.path.join(root2, "project.json"), encoding="utf-8"))
    ok(meta.get("imported", {}).get("from") == os.path.basename(info["file"]),
       "project.json 里记下了「这份从哪来」", meta.get("imported"))

    print("")
    print("=" * 70)
    print("三、同一天再存一份 / 重名项目")
    print("=" * 70)
    info3 = snapshot.export(proj, dest)
    ok(info3["file"] != info["file"], "同一分钟再存一份不会覆盖上一份", info3["file"])
    ok(len([f for f in os.listdir(dest) if f.endswith(".urwproj")]) == 2, "文件夹里有两份快照")

    root3, _ = snapshot.import_snapshot(info["file"], newparent)
    ok(root3 != root2, "导入同名项目不会覆盖已有的", root3)
    ok("导入" in os.path.basename(root3), "重名时加了后缀", os.path.basename(root3))
    ok(os.path.isdir(root2), "原来那份还在")

    print("")
    print("=" * 70)
    print("四、几条安全线")
    print("=" * 70)
    try:
        snapshot.export(proj, os.path.join(proj, "快照"))
        ok(False, "不该允许把快照存进项目目录自己里面")
    except ValueError as e:
        ok("项目目录里面" in str(e), "不许存进项目目录自己里面", e)

    try:
        snapshot.import_snapshot(info["file"], dest)     # dest 已存在同名文件没关系，这里测别名
        ok(True, "同名文件不影响导入（会按项目名起目录）")
    except Exception as e:
        ok(False, "同名文件不影响导入", e)

    evil = os.path.join(TMP, "evil.urwproj")
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("project.json", "{}")
        z.writestr("../../被写出来的文件.txt", "不该出现在这儿")
    try:
        snapshot.import_snapshot(evil, newparent)
        ok(False, "带 .. 的快照必须被拒绝")
    except ValueError as e:
        ok("不安全" in str(e), "带 .. 的快照被拒绝了", e)
    ok(not os.path.exists(os.path.join(TMP, "被写出来的文件.txt")), "那个文件确实没被写出来")

    absfile = os.path.join(TMP, "abs.urwproj")
    with zipfile.ZipFile(absfile, "w") as z:
        z.writestr("C:/Windows/坏东西.txt", "x")
    try:
        snapshot.import_snapshot(absfile, newparent)
        ok(False, "带盘符的快照必须被拒绝")
    except ValueError as e:
        ok("不安全" in str(e), "带盘符的快照被拒绝了", e)

    notzip = os.path.join(TMP, "不是快照.txt")
    open(notzip, "w", encoding="utf-8").write("我就是个文本")
    try:
        snapshot.import_snapshot(notzip, newparent)
        ok(False, "不是 zip 的文件必须被拒绝")
    except ValueError as e:
        ok("不是 zip" in str(e) or "快照" in str(e), "不是快照的文件被拒绝了", e)

    print("")
    print("=" * 70)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for x in FAIL:
        print("  ❌ " + x)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
