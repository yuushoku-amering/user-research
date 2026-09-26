# -*- coding: utf-8 -*-
"""组块 ⑤ 数据预处理 · 专项自检

守的是「**空白有两种意思**」这条 —— 结构跳题 ≠ 漏答。

    python _preptest.py

背景（2026-09-26 实测踩到）：
  「没谈过恋爱的人不答花销题」是**按设计跳题**（这道题对他不适用），
  而"该答没答"才是**真漏答**。原来两者在数据里都是空白，⑤ 又只有"整行删除"一个选项，
  于是 **41 位从未恋爱的人整群被删掉**，报告里还把这记成"缺失率 2.9%"——
  分析样本从"全体学生"悄悄变成"谈过恋爱的学生"，而报告里一个字都没说。

  现在生成侧会写哨兵值 `<不适用>` + `_跳题` 标记列，⑤ 多了「只删真漏答」这个选项。
"""
import importlib.util
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PASS = [0]
FAIL = [0]


def ok(cond, label, extra=None):
    if cond:
        PASS[0] += 1
        print("  [OK] " + label)
    else:
        FAIL[0] += 1
        print("  [!!] " + label + ("" if extra is None else "  —— %s" % (extra,)))


def load_engine(block):
    spec = importlib.util.spec_from_file_location(
        "eng_" + block, os.path.join(HERE, "blocks", block, "engine.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Ctx(object):
    """够跑通一个组块的最小上下文（get 必须真查 params —— 桩子太假会误导调试）。"""

    def __init__(self, params=None, project_root=""):
        self.params = dict(params or {})
        self.project_root = project_root
        self.steps, self.logs, self.alerts, self.outputs = [], [], [], []
        self._rules_field = ""

    def get(self, k, d=None):
        v = self.params.get(k, d)
        return d if v is None else v

    def log(self, m, level="info"):
        self.logs.append("[%s] %s" % (level, m))

    def warn(self, m):
        self.logs.append("[warn] %s" % m)

    def alert(self, msg, *a, **k):
        self.alerts.append(msg)

    def alerts_from(self, items):
        pass

    def step(self, sid, title, detail=None, rows=None, columns=None):
        self.steps.append((sid, title, detail))

    def path(self, *p):
        return os.path.join(self.project_root, *p)

    def out_path(self, *p):
        d = os.path.join(self.project_root, "output")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, *p)

    def made(self, path):
        self.outputs.append(path)

    def save_text(self, rel, text, encoding="utf-8"):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
        self.outputs.append(rel)
        return rel

    def save_table(self, name, rows, columns=None):
        import pandas as pd
        p = self.out_path(name)
        pd.DataFrame(list(rows), columns=columns).to_csv(p, index=False, encoding="utf-8-sig")
        self.outputs.append(name)
        return name


def make_project(tmp):
    """造一份带**两种空白**的小数据：结构跳题 + 真漏答。

    6 个人：2 位"从未恋爱"（花销题写哨兵值）、1 位谈过恋爱但漏填了一个格。
    """
    import pandas as pd
    S = "<不适用>"
    rows = [
        # 编号, 恋爱状态, 月均恋爱支出, 花销分担比例, 年级,     _跳题
        ["R01", "从未恋爱", S, S, "大一", True],
        ["R02", "从未恋爱", S, S, "大二", True],
        ["R03", "恋爱中", "200", "25–50%", "大三", False],
        ["R04", "恋爱中", "300", None, "大三", False],        # ← 真漏答（该答没答）
        ["R05", "已分手", "150", "0–25%", "大四", False],
        ["R06", "恋爱中", "250", "50–75%", "大二", False],
    ]
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "output"), exist_ok=True)
    pd.DataFrame(rows, columns=["受访者编号", "恋爱状态", "月均恋爱支出",
                                "花销分担比例", "年级", "_跳题"]).to_csv(
        os.path.join(tmp, "data", "raw.csv"), index=False, encoding="utf-8-sig")


def main():
    e = load_engine("b4_prep")
    tmp = tempfile.mkdtemp(prefix="urw_prep_")
    try:
        make_project(tmp)

        print("=" * 72)
        print("【1】哨兵值要被认出来（`<不适用>` 是「不适用」，不是漏答）")
        print("=" * 72)
        ctx = Ctx({"file": "data/raw.csv", "missing": "keep", "outlier": "none"},
                  project_root=tmp)
        e.run(ctx)
        logs = " ".join(ctx.logs)
        ok("结构跳题" in logs and "2" in logs, "认出了 2 位结构跳题", logs[:200])
        ok("哨兵值" in logs or "不适用" in logs, "报告了哨兵值被转成缺失", logs[:200])

        print("\n" + "=" * 72)
        print("【2】「只删真漏答」：跳题的人**留下**，漏答的人删掉")
        print("=" * 72)
        ctx2 = Ctx({"file": "data/raw.csv", "missing": "skipdiff", "outlier": "none"},
                   project_root=tmp)
        res2 = e.run(ctx2)
        out = os.path.join(tmp, "output", "clean_data.csv")
        import pandas as pd
        d2 = pd.read_csv(out, encoding="utf-8-sig")
        ok(len(d2) == 5, "6 → 5 行：只删了那个真漏答的（R04）", len(d2))
        ok("R04" not in list(d2["受访者编号"].astype(str)),
           "真漏答的 R04 被删掉了", list(d2["受访者编号"]))
        ok("R01" in list(d2["受访者编号"].astype(str))
           and "R02" in list(d2["受访者编号"].astype(str)),
           "**两位结构跳题的人留下来了**（老做法会把他们也删掉）",
           list(d2["受访者编号"]))
        ok("_跳题" not in list(d2.columns), "`_跳题` 标记列不进分析数据（它是说明，不是变量）")
        ok(int(d2["月均恋爱支出"].isna().sum()) == 2,
           "留下的跳题者在那道题上仍是空白（交给各分析按对排除）",
           int(d2["月均恋爱支出"].isna().sum()))

        print("\n" + "=" * 72)
        print("【3】老做法「整行删除」：仍然能用，但要**警告它把跳题的人删了**")
        print("=" * 72)
        ctx3 = Ctx({"file": "data/raw.csv", "missing": "listwise", "outlier": "none"},
                   project_root=tmp)
        e.run(ctx3)
        d3 = pd.read_csv(out, encoding="utf-8-sig")
        ok(len(d3) == 3, "整行删除：6 → 3 行（跳题的 2 位 + 漏答的 1 位都被删）", len(d3))
        ok("包含结构跳题的人" in " ".join(ctx3.logs),
           "**明确警告**了「这里面包含结构跳题的人」——不能悄悄删", ctx3.logs[-1][:160])

        print("\n" + "=" * 72)
        print("【4】没有跳题标记时：不能误判、也不能崩")
        print("=" * 72)
        import pandas as pd2
        p2 = os.path.join(tmp, "data", "plain.csv")
        pd2.DataFrame({"编号": ["A", "B", "C"], "得分": [1, None, 3]}).to_csv(
            p2, index=False, encoding="utf-8-sig")
        ctx4 = Ctx({"file": "data/plain.csv", "missing": "skipdiff", "outlier": "none"},
                   project_root=tmp)
        res4 = e.run(ctx4)
        ok(res4 and not ctx4.logs[-1].startswith("[warn]"),
           "没有跳题标记时也能跑（退回按整行删除）", ctx4.logs[-1][:120])
        ok("没认出结构跳题" in " ".join(ctx4.logs),
           "并说明白「这批数据里没有跳题标记」", ctx4.logs[-1][:160])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
