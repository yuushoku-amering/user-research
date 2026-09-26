# -*- coding: utf-8 -*-
"""项目列表 / 新建项目 · 专项自检

守两个真踩过的坑（都会让**研究员的项目从下拉里消失**）：

  1. 新建项目时路径被拼了两次 `projects/` → 建在 `projects/projects/<名字>` 里，
     列表只认一层 → 看不到它。
  2. 列表把「装着项目的文件夹」本身当成一个项目 → 下拉里多出一项叫 "projects"，
     而里面真正的项目一个都不显示。

两个坑都在真项目上发生过（2026-09-22 建「某大学大学生恋爱情况研究」时）。

跑法：  python _projectlisttest.py
"""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core.project import Project, create_project, list_projects   # noqa: E402

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
    base = tempfile.mkdtemp(prefix="urw_proj_")
    try:
        parent = os.path.join(base, "projects")

        print("\n【1】新建项目：不该被拼成 projects/projects/<名字>")
        p = create_project(parent, "恋爱情况研究")
        ok(os.path.isdir(os.path.join(parent, "恋爱情况研究")),
           "建在 <项目之家>/projects/<名字> 下")
        ok(not os.path.isdir(os.path.join(parent, "projects")),
           "没有多出一层 projects/projects")
        ok(os.path.exists(os.path.join(p.root, "project.json")), "项目的 project.json 写出来了")

        print("\n【2】列表里看得见它")
        names = [x["name"] for x in list_projects(base)]
        ok("恋爱情况研究" in names, "新项目出现在下拉里", names)
        ok("projects" not in names, "「projects 文件夹」没有被当成项目", names)

        print("\n【3】目录被套错了（projects/projects/<名字>）也找得回来")
        odd = os.path.join(base, "projects")
        inner = os.path.join(odd, "projects", "被套错的项目")
        os.makedirs(os.path.join(inner, "contracts"), exist_ok=True)
        with open(os.path.join(inner, "project.json"), "w", encoding="utf-8") as f:
            f.write('{"name": "被套错的项目"}')
        got = [x["name"] for x in list_projects(base)]
        ok("被套错的项目" in got, "嵌在两层里的项目也能被列出来", got)
        ok("projects" not in got, "同时那个容器文件夹仍然不算项目", got)

        print("\n【4】没标记的普通目录不该被当成项目")
        junk = os.path.join(odd, "随手记的笔记")
        os.makedirs(junk, exist_ok=True)
        got2 = [x["name"] for x in list_projects(base)]
        ok("随手记的笔记" not in got2, "空目录不当项目", got2)

        print("\n【5】重名要挡住")
        try:
            create_project(parent, "恋爱情况研究")
            ok(False, "重名应该报错，结果没报")
        except ValueError as e:
            ok("已经有一个" in str(e), "重名会报错：%s" % e)

        print("\n【6】名字里的非法字符要挡住")
        for bad in ["a/b", "a\\b", "a:b", "a*b", "  "]:
            try:
                create_project(parent, bad)
                ok(False, "「%s」应该被拒" % bad)
            except ValueError:
                ok(True, "「%s」被拒了" % bad)

        print("\n【7】嵌套扫描别无限往下钻（三级以外不再当项目）")
        deep = os.path.join(odd, "projects", "projects", "很深的地方")
        os.makedirs(os.path.join(deep, "output"), exist_ok=True)
        got3 = [x["name"] for x in list_projects(base)]
        ok("很深的地方" not in got3, "超过两层的就不列了（免得把数据子目录也当项目）", got3)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("\n" + ("全部通过" if FAIL[0] == 0 else "有失败项") + "：%d 通过 / %d 失败\n"
          % (PASS[0], FAIL[0]))
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
