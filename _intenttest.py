# -*- coding: utf-8 -*-
"""⑥ 意图 → 推荐 → 数据能力 · 专项自检

守的是这一整套设计的**骨架**：

  1. 大白话 → 问题类型：**规则匹配**，不靠模型（模型通道默认是关的）
  2. 意图 → 方法推荐：**确定性**，而且和引擎真正算的时候**同一个函数**（防分叉）
  3. 数据答不了的事，要在推荐之后**马上**说，并给出**能做什么**（不能只拦不给路）
  4. 「数据能支持什么」那份知识库**可以自己加条目**，但字段缺了要报出来、不许猜

    python _intenttest.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    # 理论上到不了这里：项目要求 Python 3.7+，那时 reconfigure 一定存在。
    # 真到了这里说明 Python 太老 —— UTF-8 保护**没生效**，必须让人知道，
    # 不能"静静跳过"（那等于假装有保护）。
    print("[warn] Python too old: sys.stdout.reconfigure missing, "
          "the UTF-8 guard did NOT take effect (needs Python 3.7+)")
except Exception as _e:
    # 别的失败是 bug（比如编码名写错），要叫出来，不许静默
    print("[warn] stdout/stderr UTF-8 guard failed: %r" % (_e,))

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import knowledge as kb              # noqa: E402
from core import method_pick as mp            # noqa: E402

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
    def __init__(self, params=None, project_root=""):
        self.params = dict(params or {})
        self.project_root = project_root
        self.steps, self.logs, self.alerts, self.outputs = [], [], [], []

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
        pd.DataFrame(list(rows), columns=columns).to_csv(p, index=False,
                                                         encoding="utf-8-sig")
        self.outputs.append(name)
        return name

    def ask(self, sid, title, detail=None, options=None, default=None,
            rows=None, columns=None):
        return default if default is not None else (options[0]["value"] if options else "ok")


def main():
    print("=" * 72)
    print("【1】大白话 → 问题类型：纯规则，不许依赖模型")
    print("=" * 72)
    cases = [
        ("兼职的同学是不是更倾向于 AA", "compare"),
        ("不同年级的人恋爱支出不一样吗", "compare"),
        ("生活费越高恋爱花得越多吗", "relate"),
        ("两个分类变量有没有关联", "assoc"),
        ("责任认知和松动情境做个交叉表", "assoc"),
        ("我想先看看数据长什么样", "describe"),
    ]
    for txt, want in cases:
        got = mp.guess_kind(txt)[0]
        ok(got == want, "「%s」→ %s" % (txt, want), got)
    ok(mp.guess_kind("") == ("", ""), "空意图 → 不猜（返回空，交给表单）")

    print("\n" + "=" * 72)
    print("【2】推荐和判定**同一个函数**（防分叉，最要紧的一条）")
    print("=" * 72)
    # 真源在 method_pick：引擎里不许再有第二份判定（用编译后的代码查，剥掉注释）
    import io
    code = "\n".join(ln.split("#", 1)[0] for ln in
                     io.open(os.path.join(HERE, "blocks", "b5_stats", "engine.py"),
                             encoding="utf-8").read().splitlines())
    ok("pick_compare(k, all_normal, equal_var)" in code,
       "引擎调的是 `method_pick.pick_compare`")
    ok("_mpr." not in code and "_mp0." not in code,
       "没有残留的旧别名（改名漏改会让卡片**静默消失**）")
    # 真值表：文档/界面/测试都用这一份
    tt = mp.truth_table_compare()
    ok(len(tt) == 8, "真值表 8 行（组数 2/3 × 正态 × 方差齐）", len(tt))
    ok(all(r["方法"] and r["中文名"] and r["为什么不用另一个"] for r in tt),
       "真值表每行都有方法、中文名、和「为什么不用另一个」")
    # 覆盖后的选择也必须走同一个模块
    ok(mp.override_compare(4, "param") == "anova" and
       mp.override_compare(4, "nonparam") == "kruskal" and
       mp.override_compare(2, "param") == "t" and
       mp.override_compare(2, "nonparam") == "mannwhitney",
       "检查点上「坚持参数/换非参数」也走同一个模块（不是引擎里另写两行）")

    print("\n" + "=" * 72)
    print("【3】数据答不了的事：要命中、要给替代、不能只拦不给路")
    print("=" * 72)
    ents, err = kb.data_bounds()
    ok(len(ents) >= 4, "知识库读到了条目（%d 条）" % len(ents), len(ents))
    ok(not err, "没有读文件/字段的错", err)
    for e in ents:
        for k in ("id", "触发词", "要求", "现在给你什么", "降级路径", "为什么"):
            if not e.get(k):
                ok(False, "条目 %s 字段齐全" % e.get("id"), "缺 %s" % k)
                break
        else:
            continue
    ok(all(e.get("现在给你什么") and e.get("降级路径") for e in ents),
       "**每一条**都既说「现在给你什么」也说「降级路径」（只拦不给路会把学生堵死）")
    # 命中
    h1 = [x for x in kb.check_data_bounds("花钱多的同学是不是更容易分手") if x.get("id")]
    ok(any(x["id"] == "cross_section_no_causal" for x in h1),
       "「更容易」命中横截面不能推因果", [x["id"] for x in h1])
    ok(bool(h1 and h1[0].get("降级路径")), "命中后带降级路径", h1[:1])
    h2 = [x for x in kb.check_data_bounds("生活费每多一千块，支出多多少") if x.get("id")]
    ok(any(x["id"] == "banded_no_marginal_effect" for x in h2),
       "「每多」命中「区间档位没有边际效应」", [x["id"] for x in h2])
    h3 = [x for x in kb.check_data_bounds("恋爱次数和分担比例有关系吗") if x.get("id")]
    ok(not h3, "普通问法**不该**乱命中（假警报会让人不再相信提醒）", h3)

    print("\n" + "=" * 72)
    print("【4】端到端：意图卡 + 推荐卡 + 数据能力卡都要出，且顺序对")
    print("=" * 72)
    e = load_engine("b5_stats")
    tmp = tempfile.mkdtemp(prefix="urw_intent_")
    try:
        import pandas as pd
        rng = __import__("numpy").random.default_rng(3)
        n = 60
        df = pd.DataFrame({
            "支出": rng.normal(200, 40, n).round(1),
            "来源": rng.choice(["家庭给", "兼职", "混合"], n),
            "年级": rng.choice(["大一", "大二", "大三"], n),
        })
        df.to_csv(os.path.join(tmp, "c.csv"), index=False, encoding="utf-8-sig")
        ctx = Ctx({"file": "c.csv", "intent": "兼职的同学是不是更容易花得多",
                   "question": "compare", "dv": "支出", "group": "来源",
                   "alpha": 0.05, "gen_sps": []}, project_root=tmp)
        res = e.run(ctx)
        names = [t["name"] for t in (res.get("tables") or [])]
        ok(any("我理解你想知道什么" in n_ for n_ in names), "出了「意图卡」", names)
        ok(any("方法推荐" in n_ for n_ in names), "出了「方法推荐」卡", names)
        ok(any("数据答不了" in n_ for n_ in names),
           "出了「数据答不了」卡（因为写了「更容易」）", names)
        # 顺序：意图 → 推荐 → 数据能力
        def idx(key):
            for i, n_ in enumerate(names):
                if key in n_:
                    return i
            return -1
        i_int, i_rec, i_bnd = idx("理解"), idx("方法推荐"), idx("数据答不了")
        ok(i_int < i_rec < i_bnd,
           "顺序是 意图 → 推荐 → 数据能力（先说建议、再说限制）",
           (i_int, i_rec, i_bnd))
        ok(bool(ctx.alerts), "数据答不了时**同时弹了提醒**（不只写进表里）")

        # 缺变量时：不许崩，要告诉人补什么
        # ⚠ 这句里**故意**放"更容易"（触发词）—— 上一版我用的是"更不容易分手"，
        #   那里面没有触发词，于是这条断言其实什么都没测到（自己给自己放的假）
        ctx2 = Ctx({"file": "c.csv", "intent": "花钱多的同学是不是更容易分手",
                    "question": "auto", "alpha": 0.05, "gen_sps": []},
                   project_root=tmp)
        res2 = e.run(ctx2)
        ok((res2 or {}).get("stopped"), "缺变量时是「停下让你补」，不是抛异常")
        nm2 = [t["name"] for t in ((res2 or {}).get("tables") or [])]
        ok(any("还差" in x for x in nm2), "而且给出了「还差什么」那张表", nm2)
        ok(any("数据答不了" in x for x in nm2),
           "**缺变量也要先给数据能力提醒**（这是最该看到的时候）", nm2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
