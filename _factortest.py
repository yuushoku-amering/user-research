# -*- coding: utf-8 -*-
"""因子分析 / 效度 · 专项自检（第 4 批）

    python _factortest.py

守四件事：

  1. **已知因子结构要能还原出来**：造 2 个因子、各管 5 道题，看载荷是不是分得开
  2. **varimax 旋转的数学性质**：旋转后准则**必须变大**，但总解释方差**不变**
     （这两个是定义级的性质，错了就是算法错，不是"差不多"）
  3. **KMO 和 Bartlett 是两件事**，而且 Bartlett 的读法**和一般检验相反**（p 小才好）
  4. **因子数不能只看特征值 >1**：要同时给平行分析（题目多时 Kaiser 会高估）
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
from core import factor as FA                # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, label, extra=None):
    if cond:
        PASS[0] += 1
        print("  [OK] " + label)
    else:
        FAIL[0] += 1
        print("  [!!] " + label + ("" if extra is None else "  —— %s" % (extra,)))


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
        return os.path.join(self.project_root, "output", *p)

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
        os.makedirs(os.path.dirname(p), exist_ok=True)
        pd.DataFrame(list(rows), columns=columns).to_csv(p, index=False,
                                                         encoding="utf-8-sig")
        self.outputs.append(name)
        return name

    def ask(self, sid, title, detail=None, options=None, default=None,
            rows=None, columns=None):
        return default if default is not None else (options[0]["value"] if options else "ok")


def two_factor_data(n=600, loading=0.75, corr=0.3, seed=2026, per=5):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    f1 = rng.normal(0, 1, n)
    f2 = corr * f1 + np.sqrt(1 - corr ** 2) * rng.normal(0, 1, n)
    cols = {}
    for i in range(per):
        cols["A%d" % (i + 1)] = loading * f1 + rng.normal(0, np.sqrt(1 - loading ** 2), n)
    for i in range(per):
        cols["B%d" % (i + 1)] = loading * f2 + rng.normal(0, np.sqrt(1 - loading ** 2), n)
    return pd.DataFrame(cols), list(cols)


def main():
    import numpy as np
    import pandas as pd

    print("=" * 72)
    print("【1】已知因子结构要能还原：2 个因子、各管 5 道题")
    print("=" * 72)
    d, cols = two_factor_data()
    res = FA.factor_analyze(d, cols, n_factors=2)
    ok(not res.get("error"), "能跑通", res.get("error"))
    ok(res["n"] == 600 and res["p"] == 10, "样本/题目数对", (res["n"], res["p"]))
    L = np.array(res["loadings"])
    # A* 应当落在同一个因子上，B* 落在另一个；且两组不能混
    a_cols = [i for i, c in enumerate(cols) if c.startswith("A")]
    b_cols = [i for i, c in enumerate(cols) if c.startswith("B")]
    a_factor = set(int(np.argmax(np.abs(L[i]))) for i in a_cols)
    b_factor = set(int(np.argmax(np.abs(L[i]))) for i in b_cols)
    ok(len(a_factor) == 1 and len(b_factor) == 1,
       "A 组 5 题全落在同一个因子上、B 组也是", (a_factor, b_factor))
    ok(a_factor != b_factor, "**两组落在不同的因子**（结构分开了）", (a_factor, b_factor))
    mx = np.abs(L).max(axis=1)
    sec = np.sort(np.abs(L), axis=1)[:, -2]
    ok(bool((mx >= 0.7).all()), "每道题的最大载荷都 ≥0.7", mx.min())
    ok(bool((sec <= 0.2).all()), "**次大载荷都 ≤0.2**（简单结构，没有双重载荷）", sec.max())
    h = np.array(res["communality"])
    ok(bool((h > 0.5).all()), "共同度都 >0.5（题目被因子解释得不错）", h.min())

    print("\n" + "=" * 72)
    print("【2】varimax 的两条**定义级**性质")
    print("=" * 72)
    Lu = np.array(res["loadings_unrotated"])
    Lr = np.array(res["loadings"])
    cu, cr = FA._varimax_criterion(Lu), FA._varimax_criterion(Lr)
    ok(cr > cu,
       "旋转后**准则变大**（%.4f → %.4f）—— 判据写错的话这条会挂" % (cu, cr), (cu, cr))
    su, sr = (Lu ** 2).sum(), (Lr ** 2).sum()
    ok(abs(su - sr) < 1e-9,
       "旋转**不改变**总解释方差（%.4f → %.4f）—— 所以别说「旋转后解释率提高了」" % (su, sr),
       (su, sr))
    # 旋转应当让结构更清楚：简单结构的题数应当增加（次大载荷 ≤0.2 的题更多）
    def simple_count(L):
        a = np.abs(L)
        return int(((a.max(axis=1)) >= 0.4).sum() - (np.sort(a, axis=1)[:, -2] >= 0.4).sum()) \
            if L.shape[1] > 1 else 0
    ok(simple_count(Lr) >= simple_count(Lu),
       "旋转后「只归一个因子」的题**不减少**（%d → %d）" % (simple_count(Lu), simple_count(Lr)))

    print("\n" + "=" * 72)
    print("【3】KMO 与 Bartlett：两件事，而且 Bartlett 读法相反")
    print("=" * 72)
    R = np.array(res["R"])
    bart = FA.bartlett_sphericity(R, res["n"])
    k = FA.kmo(R)
    ok(bart["p"] < 0.001, "真有两因子 → Bartlett **显著**（p=%.2g，p 小才好）" % bart["p"], bart["p"])
    ok(k["kmo"] > 0.8, "KMO 高（%.3f）说明适合做因子分析" % k["kmo"], k["kmo"])
    # 反例：完全无关的题目
    rng = np.random.default_rng(5)
    noise = pd.DataFrame({("N%d" % i): rng.normal(0, 1, 400) for i in range(6)})
    rn = FA.factor_analyze(noise, list(noise), n_factors=1)
    # ⚠ **随机数据的 KMO 期望值是 0.5，不是 0**（我一开始把断言写成 <0.3，被自己的测试纠正了）：
    #   R ≈ 单位阵时 R⁻¹ ≈ 单位阵 → 偏相关 ≈ 原相关 → 两个平方和相等 → KMO ≈ 0.5。
    #   实测（n=400、6 题、200 次抽样）：均值 0.496、范围 [0.437, 0.557]，和解析一致。
    #   所以"低 KMO"的判据只能是"接近 0.5"，不能是"接近 0"。
    ok(0.35 <= rn["kmo"]["kmo"] <= 0.65,
       "**完全无关的题目 → KMO ≈ 0.5**（%.3f；0.5 才是随机数据的理论值，不是 0）"
       % rn["kmo"]["kmo"], rn["kmo"]["kmo"])
    ok(rn["bartlett"]["p"] > 0.05,
       "而且 Bartlett **不显著**（p=%.2f）→ 该说「不适合做因子分析」" % rn["bartlett"]["p"],
       rn["bartlett"]["p"])
    # 关键区分：有结构 vs 没结构，KMO 要拉得开
    ok(k["kmo"] - rn["kmo"]["kmo"] > 0.25,
       "有因子结构 vs 纯随机，KMO 差 %.3f（%.3f vs %.3f）—— 这才是判据"
       % (k["kmo"] - rn["kmo"]["kmo"], k["kmo"], rn["kmo"]["kmo"]))

    print("\n" + "=" * 72)
    print("【4】因子数：Kaiser 与平行分析都要给")
    print("=" * 72)
    ok(res["kaiser_n"] == 2, "Kaiser（特征值>1）给 2 个", res["kaiser_n"])
    ok(res["parallel_n"] == 2, "平行分析也给 2 个", res["parallel_n"])
    ok(res["parallel_line"] is not None and len(res["parallel_line"]) == 10,
       "平行分析的基准线算出来了", len(res["parallel_line"] or []))
    # 题目多、真因子少时，Kaiser 会高估 —— 造这种数据验一下
    d2, cols2 = two_factor_data(n=800, loading=0.45, seed=77, per=10)   # 20 题、载荷低
    res2 = FA.factor_analyze(d2, cols2, n_factors=None)
    line = "Kaiser 说 %d 个、平行分析说 %d 个" % (res2["kaiser_n"], res2["parallel_n"])
    ok(res2["parallel_n"] <= res2["kaiser_n"],
       "弱载荷 × 多题时：**平行分析 ≤ Kaiser**（%s）—— 这正是 Kaiser 会高估的场合" % line,
       (res2["kaiser_n"], res2["parallel_n"]))
    ok(res2["n_factors"] == res2["parallel_n"],
       "自动判断**按平行分析来**（更推荐的那个）",
       (res2["n_factors"], res2["parallel_n"]))

    print("\n" + "=" * 72)
    print("【5】主轴因子（pa）与主成分（pca）要真的不一样")
    print("=" * 72)
    r_pca = FA.factor_analyze(d, cols, n_factors=2, method="pca")
    r_pa = FA.factor_analyze(d, cols, n_factors=2, method="pa")
    diff = max(abs(np.array(r_pca["loadings"]) - np.array(r_pa["loadings"])).max(),
               abs(np.array(r_pca["explained_total"]) - np.array(r_pa["explained_total"])))
    ok(diff > 1e-6,
       "**两种抽取给出的载荷/解释率不同**（最大差 %.4f）—— 报告里必须写清用的哪个" % diff, diff)
    ok(r_pa["explained_total"] < r_pca["explained_total"] + 1e-9,
       "主轴因子的解释率不高于主成分（它只算共同部分）",
       (r_pa["explained_total"], r_pca["explained_total"]))

    print("\n" + "=" * 72)
    print("【6】双重载荷 / 共同度低的题要被抓出来")
    print("=" * 72)
    # 造一道"两边都沾"的题
    d3, cols3 = two_factor_data(seed=31)
    rng3 = np.random.default_rng(3)
    d3 = d3.copy()
    d3["X1"] = 0.5 * d3["A1"] + 0.5 * d3["B1"] + rng3.normal(0, 0.3, len(d3))
    res3 = FA.factor_analyze(d3, cols3 + ["X1"], n_factors=2)
    cross = FA.cross_loading_table(res3)
    ok(any(c["item"] == "X1" for c in cross),
       "人为造的「双重载荷」题被点名了", [c["item"] for c in cross])

    print("\n" + "=" * 72)
    print("【7】边界与容错")
    print("=" * 72)
    ok(FA.factor_analyze(pd.DataFrame({"a": [1., 2], "b": [2., 3]}), ["a", "b"]).get("error"),
       "题目少于 3 道 → 干净报错，不崩")
    const = pd.DataFrame({"a": [1.] * 50, "b": np.random.default_rng(1).normal(0, 1, 50),
                          "c": np.random.default_rng(2).normal(0, 1, 50),
                          "d": np.random.default_rng(3).normal(0, 1, 50)})
    rc = FA.factor_analyze(const, ["a", "b", "c", "d"], n_factors=1)
    ok(rc.get("error") or "a" in rc.get("dropped_constant", []),
       "常数题（全同）被剔掉，不参与（否则相关矩阵奇异、KMO 会算出 nan）",
       rc.get("dropped_constant"))

    print("\n" + "=" * 72)
    print("【8】端到端：④ 里每一组量表都要做（不能只做第一组）")
    print("=" * 72)
    e = importlib.util.spec_from_file_location(
        "eng_b3", os.path.join(HERE, "blocks", "b3_survey", "engine.py"))
    m = importlib.util.module_from_spec(spec_ := e)
    spec_.loader.exec_module(m)
    tmp = tempfile.mkdtemp(prefix="urw_factor_")
    try:
        rng = np.random.default_rng(2026)
        n = 300
        f1, f2 = rng.normal(0, 1, n), rng.normal(0, 1, n)
        cols_e = {}
        for i in range(5):
            cols_e["Q1_%d" % (i + 1)] = np.clip(3 + 0.9 * f1 + rng.normal(0, .6, n), 1, 5).round()
        for i in range(5):
            cols_e["Q2_%d" % (i + 1)] = np.clip(3 + 0.9 * f2 + rng.normal(0, .6, n), 1, 5).round()
        pd.DataFrame(cols_e).to_csv(os.path.join(tmp, "c.csv"), index=False,
                                    encoding="utf-8-sig")
        ctx = Ctx({"file": "c.csv", "tasks": ["factor"], "scale_vars": "",
                   "factor_method": "pca", "factor_n": 0}, project_root=tmp)
        res_e = m.run(ctx)
        names = [t["name"] for t in (res_e.get("tables") or [])]
        ok(sum(1 for x in names if "旋转后因子载荷" in x) == 2,
           "**两组量表都做了**（不是只做第一组）：%s" % [x for x in names if "因子载荷" in x],
           names)
        ok(all(("Q1" in x or "Q2" in x) for x in names if "因子载荷" in x),
           "表名带上了是哪一组（否则两套同名表分不清）", names)
        figs = [f["rel"] for f in (res_e.get("figures") or [])]
        ok(len(figs) == 2, "两张碎石图（文件名不同，不会互相覆盖）", figs)
        for f in figs:
            ok(os.path.exists(os.path.join(tmp, *f.split("/"))), "图落盘：%s" % f)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
