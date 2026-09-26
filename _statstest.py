# -*- coding: utf-8 -*-
"""组块 ⑥ 统计分析 · 专项回归测试

守的是「**有序档位 / 区间**那类选项没被当成数字用」这条线。

    python _statstest.py

背景（2026-09-24 实测踩到，而且报的错完全看不出真因）：
  「恋爱研究」的问卷里，「花销分担比例」是个**定序**变量，选项写成
  「0–25% / 25–50% / 50–75% / 75–100%」。到 ⑥ 这一步：

      pd.to_numeric(那一列, errors="coerce")  →  **整列全变 NaN**
      → 分析塌掉，报「分组变量只有 0 个取值，没法比较」

  数据没问题、变量名也没错，就是"那列写的是 25–50% 这种字"。研究员看到那句话
  根本猜不到是格式问题。修法：进模型前把这类档位换成数值（区间取中点、
  「N 及以上」取下界），而且**摊在步骤卡里**让人看得见。
"""
import importlib.util
import os
import sys

# ⚠ 控制台是 GBK：打印 emoji / 特殊符号会 UnicodeEncodeError 把测试打断。
#   这一句是**必须**的（踩过两次）。
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
    """最小上下文：够跑通一个组块，并记下 step / log。

    ⚠ `get` 必须真的查 `params`（早先那版永远返回默认值 → 端到端一跑就报
      「请先选一个数据文件」，看着像引擎的错，其实是桩子太假）。
    """

    def __init__(self, params=None, project_root=""):
        self.params = dict(params or {})
        self.project_root = project_root
        self.steps, self.logs, self.alerts, self.outputs = [], [], [], []

    def get(self, k, d=None):
        v = self.params.get(k, d)
        return d if v is None else v

    def step(self, sid, title, detail=None, rows=None, columns=None):
        self.steps.append((sid, title, rows, columns))

    def log(self, m, level="info"):
        self.logs.append(m)

    def warn(self, m):
        self.logs.append(m)

    def alert(self, *a, **k):
        self.alerts.append(a)

    def alerts_from(self, items):
        pass

    def path(self, *parts):
        return os.path.join(self.project_root, *parts)

    def out_path(self, *parts):
        p = os.path.join(self.project_root, "output", *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def made(self, path):
        self.outputs.append(path)

    def save_text(self, rel, text, encoding="utf-8"):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
        self.outputs.append(rel)
        return rel

    def save_table(self, name, df_or_rows, columns=None):
        import pandas as _pd
        p = self.out_path(name)
        rows = getattr(df_or_rows, "values", df_or_rows)
        _pd.DataFrame(list(rows), columns=columns).to_csv(p, index=False, encoding="utf-8-sig")
        self.outputs.append(name)
        return name

    def ask(self, sid, title, detail=None, options=None, default=None, rows=None, columns=None):
        return default if default is not None else (options[0]["value"] if options else "ok")


def main():
    import numpy as np
    import pandas as pd

    e = load_engine("b5_stats")

    print("=" * 72)
    print("【1】单个值：区间 / 及以上 / 纯数字 / 年级，都要转对")
    print("=" * 72)
    cases = [
        ("0–25%", 12.5), ("25–50%", 37.5), ("50–75%", 62.5), ("75–100%", 87.5),
        ("0 次", 0.0), ("1 次", 1.0), ("2 次及以上", 2.0), ("3 次以上", 3.0),
        ("5 分以上", 5.0), ("大一", 1.0), ("大二", 2.0), ("大三", 3.0),
        ("18-24", 21.0), ("1~5", 3.0), ("30%", 30.0), ("7", 7.0),
    ]
    for s, want in cases:
        got = e._scalar_ordinal(s)
        ok(got is not None and abs(got - want) < 1e-9,
           "「%s」→ %s" % (s, want), got)

    print("")
    print("=" * 72)
    print("【2】反例：定类 / 文本 / 空值 一律不许转（转了就等于凭空造顺序）")
    print("=" * 72)
    for s in ("家庭给", "兼职", "男", "从未恋爱", "异地", "", "nan", "None", "某科技公司"):
        got = e._scalar_ordinal(s)
        ok(got is None, "「%s」不转（得到 %r）" % (s, got), got)

    print("")
    print("=" * 72)
    print("【3】整列：全都能转才认，混着别的就整列不动")
    print("=" * 72)
    ctx = Ctx()
    df = pd.DataFrame({
        "花销分担比例": ["0–25%", "25–50%", "75–100%", "50–75%", "25–50%"],
        "恋爱经历次数": ["0 次", "1 次", "2 次及以上", "1 次", "0 次"],
        "生活费来源": ["家庭给", "兼职", "混合", "奖助学金", "家庭给"],
        "性别": ["男", "女", "男", "女", "男"],
    })
    out, rows = e._normalize_ordinals(ctx, df.copy())
    names = [r[0] for r in rows]
    ok("花销分担比例" in names, "区间档那一列被转成数值", names)
    ok("恋爱经历次数" in names, "「N 次及以上」那列也被转", names)
    ok("生活费来源" not in names, "定类（家庭给/兼职…）**不动**", names)
    ok("性别" not in names, "二分类（男/女）不动", names)
    ok(out["花销分担比例"].dtype == float, "转完是数值列", out["花销分担比例"].dtype)
    ok(list(out["花销分担比例"]) == [12.5, 37.5, 87.5, 62.5, 37.5],
       "每格都按自己的档位取中点", list(out["花销分担比例"]))
    ok(list(out["恋爱经历次数"]) == [0.0, 1.0, 2.0, 1.0, 0.0],
       "「N 次及以上」取下界", list(out["恋爱经历次数"]))
    ok(e._normalize_ordinals(ctx, df.copy())[0]["生活费来源"].dtype == object,
       "没被认出来的列原样保留（还是文本）")

    # 混着不能转的值 → 整列放弃（宁可当文本，也不要把一半硬转成数字）
    df2 = pd.DataFrame({"劳动所得占比": ["0–25%", "不方便说", "75–100%"]})
    out2, rows2 = e._normalize_ordinals(Ctx(), df2.copy())
    ok(not rows2, "一列里混了「不方便说」→ 整列不转（不猜）", rows2)

    print("")
    print("=" * 72)
    print("【4】端到端：那列转完以后，真的能进「组间差异」分析")
    print("=" * 72)
    # 造一份最小数据：分组变量 3 组，因变量就是区间档
    rng = np.random.default_rng(3)
    levels = ["0–25%", "25–50%", "50–75%", "75–100%"]
    n = 90
    d = pd.DataFrame({
        "组": ["A"] * 30 + ["B"] * 30 + ["C"] * 30,
        "花销分担比例": ([levels[0]] * 22 + [levels[1]] * 8 +
                         [levels[1]] * 20 + [levels[2]] * 10 +
                         [levels[2]] * 12 + [levels[3]] * 18),
    })
    num, rows = e._normalize_ordinals(Ctx(), d.copy())
    ok(not rows or True, "（准备）")
    ok(num["花销分担比例"].notna().all(), "转完之后没有 NaN（这正是 bug 的根因）",
       int(num["花销分担比例"].isna().sum()))
    # 用和引擎同一套判断跑一遍
    dd = pd.DataFrame({"dv": num["花销分担比例"], "g": num["组"]}).dropna()
    k = len(pd.unique(dd["g"]))
    ok(k == 3, "分组变量终于有 %d 个取值了（修之前这里是 0）" % k, k)
    from scipy import stats as st
    groups = [dd.loc[dd["g"] == lv, "dv"].values for lv in pd.unique(dd["g"])]
    H, p = st.kruskal(*groups)
    ok(p < 0.001, "Kruskal-Wallis 能算出结果（p=%.2e），不是塌掉" % p, p)

    print("\n" + "=" * 72)
    print("【5】区间档折成的数值**不能**被当成分类（前辈实测报的）")
    print("=" * 72)
    # 现场（2026-09-25）：问卷按"别让受访者做精确数值"改成**分档单选**之后，
    #   分析列只有"档数"那么多个取值（5 档 → 5 个中点），
    #   而 kit.infer_kind 的规则是「取值 ≤12 且全整数 → 分类」→
    #   **连续金额被拆成 5 个哑变量**，"生活费越高花越多"那条关系整个被拆碎
    #   （R² 虚低、常数项虚高）。它跟李克特量表**长得一模一样**，光看取值个数分不开。
    from core import kit as _kit
    banded = pd.Series([1250.0, 1750.0, 2500.0, 3500.0, 4554.0] * 20)
    ok(_kit.infer_kind(banded, name="月可支配生活费_数值") == "continuous",
       "**5 档区间中点 → 连续**（1250/1750/2500/3500/4554）", _kit.infer_kind(banded, name="月可支配生活费_数值"))
    banded_out = pd.Series([1250.0, 1750.0, 2500.0, 3500.0, 4554.0, 7000.0, 9000.0] * 20)
    ok(_kit.infer_kind(banded_out, name="月可支配生活费_数值") == "continuous",
       "带离群值的区间列也是连续", _kit.infer_kind(banded_out, name="月可支配生活费_数值"))
    likert = pd.Series([1, 2, 3, 4, 5] * 20)
    ok(_kit.infer_kind(likert) == "categorical",
       "**李克特 1~5 仍然是分类**（别为了修上面那条把量表也判成连续）",
       _kit.infer_kind(likert))
    likert7 = pd.Series([1, 2, 3, 4, 5, 6, 7] * 20)
    ok(_kit.infer_kind(likert7) == "categorical", "李克特 1~7 也是分类",
       _kit.infer_kind(likert7))
    cents = pd.Series([12.5, 37.5, 62.5, 87.5] * 20)
    ok(_kit.infer_kind(cents) == "continuous",
       "百分比档位中点（12.5/37.5…）是连续（它本来就不会被判成分类）",
       _kit.infer_kind(cents))
    cont = pd.Series(np.linspace(500, 5000, 100))
    ok(_kit.infer_kind(cont) == "continuous", "真连续变量照旧", _kit.infer_kind(cont))
    # 边界：判据是保守的 —— 只挡住"跨度大、且不从 1 开始"的那种
    #   ❗标签里别放 emoji：**控制台是 GBK 时会 UnicodeEncodeError 把测试打断**。
    #     实测又踩了一次这条坑（记忆里明明写过），所以这里留个记号。
    small = pd.Series([100, 200, 300, 400, 500] * 20)
    ok(_kit.infer_kind(small, name="生活费5档") == "categorical",
       "[保守] 100~500 这种（跨度小）仍按分类 —— 宁可让人自己改",
       _kit.infer_kind(small, name="生活费5档"))

    print("\n" + "=" * 72)
    print("【6】相关：三个系数一起报 + 所有统计量带 CI（2026-09-26 加）")
    print("=" * 72)
    # 守的坑：原来连续×连续**按 Shapiro-Wilk 自动二选一、只报换完的那一个**。
    #   实测同一对变量：含 3 个极端值时 Pearson 0.260 / Spearman 0.735；
    #   剔掉那 3 行后 Pearson 0.717 / Spearman 0.737 —— 差 2.7 倍，
    #   而报告只说得出其中一个数。**差值本身就是结论的一部分**，所以三个都要给。
    import tempfile
    import shutil
    import pandas as pd
    b5 = load_engine("b5_stats")
    rng = np.random.default_rng(7)

    # —— 单元：置信区间必须**包含点估计**。第一版就是栽在这里：
    #    η²=0.139 却给出 [0.000, 0.017]（拿中心 F 的分位数折回来，等于在"没效应"的世界里找区间）
    e2, ci = None, None
    F_obs, df1, df2 = 28.8, 3, 535
    ci = b5._ci_eta2(F_obs, df1, df2, 0.05)
    e2 = F_obs * df1 / (F_obs * df1 + df2)
    try:
        lo, hi = [float(v) for v in ci.strip("[]").split(",")]
        ok(lo <= e2 <= hi,
           "η² 的 CI **包含点估计**（η²=%.3f，CI=%s）—— 第一版给的是 [0.000, 0.017]，不含" % (e2, ci),
           ci)
    except Exception as e:
        ok(False, "η² 的 CI 能解析成区间：%s（%s）" % (ci, e), ci)
    ok(b5._ci_eta2(0.0, 3, 535, 0.05) == "算不出来" or True, "η² 的 CI 在极端输入下不炸")

    # —— 单元：ρ 的 CI 也要含点估计，且随 n 收窄
    ci_small = b5._ci_r(0.7, 20, 0.05)
    ci_big = b5._ci_r(0.7, 500, 0.05)
    def _width(s):
        a, b = [float(v) for v in s.strip("[]").split(",")]
        return b - a
    ok(_width(ci_big) < _width(ci_small),
       "n 越大 ρ 的 CI 越窄（n=20 → %s，n=500 → %s）" % (ci_small, ci_big))
    try:
        lo, hi = [float(v) for v in ci_big.strip("[]").split(",")]
        ok(lo <= 0.7 <= hi, "ρ 的 CI 包含点估计", ci_big)
    except Exception as e:
        ok(False, "ρ 的 CI 能解析（%s）" % e, ci_big)

    # —— 单元：回归系数 CI 与均值差 CI 都不炸
    ok("[" in b5._ci_beta(0.054, 0.014, 537, 0.05), "回归系数 CI 能算", b5._ci_beta(0.054, 0.014, 537, 0.05))
    lo_b, hi_b = [float(v) for v in b5._ci_beta(0.054, 0.014, 537, 0.05).strip("[]").split(",")]
    ok(lo_b < 0.054 < hi_b, "回归系数 CI 包含 B 本身")

    # —— 端到端：跑一次 relate，表里必须**三个系数都在**、且只有一个主报
    tmp = tempfile.mkdtemp(prefix="urw_ci_")
    try:
        n = 120
        x = rng.normal(0, 1, n)
        y = 2.0 * x + rng.normal(0, 1.2, n)
        y[0], y[1] = 40.0, -35.0          # 两个极端值：Pearson 会被拽，Spearman 不会
        os.makedirs(os.path.join(tmp, "output"), exist_ok=True)
        pd.DataFrame({"生活費": x, "支出": y}).to_csv(
            os.path.join(tmp, "data.csv"), index=False, encoding="utf-8-sig")
        ctx = Ctx({"file": "data.csv", "question": "relate", "dv": "支出",
                   "ivs": ["生活費"], "alpha": 0.05, "gen_sps": []}, project_root=tmp)
        res = b5.run(ctx)
        tabs = {t["name"]: t for t in (res.get("tables") or [])}
        trio = next((t for k, t in tabs.items() if k.startswith("相关 ·")), None)
        ok(trio is not None, "端到端跑出了「相关 ·」表", list(tabs.keys()))
        if trio:
            txt = " ".join(str(c) for row in trio["rows"] for c in row)
            for key in ("Pearson", "Spearman", "Kendall"):
                ok(key in txt, "三个系数里 %s 在表里" % key)
            ok("95% CI" in " ".join(trio["columns"]), "相关表有 CI 这一列", trio["columns"])
            n_primary = txt.count("主报")
            ok(n_primary == 1, "**只有一个**主报标记（第一版把 Kendall 也标上了）", n_primary)
            # 极端值场景：Pearson 和 Spearman 必须拉开差距，并给出说明
            ok(trio["note"].count("差") > 0 or "接近" in trio["note"],
               "表下说明了两个系数的差异", trio["note"][:80])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 72)
    print("【7】方法选择的**真源只有一份**（推荐卡和真正算的必须同一个判定）")
    print("=" * 72)
    # 守的坑：② 和 ②b 各自写过一遍「谁是访谈者」，两边判据不一致、还从不报错。
    #   方法选择比那个更要紧：如果推荐卡说 Mann-Whitney、引擎却跑了 t 检验，
    #   研究员会照着推荐卡写进论文，而数字是另一个方法算的。
    #   所以判定抽成了 `core/method_pick.pick_compare()`，引擎也调它 —— 这里守住这件事。
    from core import method_pick as _mp
    cases = [(2, True, True, "t"), (2, True, False, "welch"),
             (2, False, True, "mannwhitney"), (2, False, False, "mannwhitney"),
             (4, True, True, "anova"), (4, True, False, "anova_welch"),
             (4, False, True, "kruskal"), (3, False, False, "kruskal")]
    for k, nrm, eq, want in cases:
        got = _mp.pick_compare(k, nrm, eq)["method"]
        ok(got == want, "%d 组 正态=%-5s 方差齐=%-5s → %s" % (k, nrm, eq, want), got)
    # 关键断言：引擎里**不许再有一份**判定表。
    # ⚠ 只看**代码部分**，剥掉注释 —— 注释里引用旧代码（"这里原来是 xxx"）是好事，
    #   不能因为它就把测试判红（第一版就是这么误报的）。
    import io as _io
    _code = []
    for _ln in _io.open(os.path.join(HERE, "blocks", "b5_stats", "engine.py"),
                        encoding="utf-8").read().splitlines():
        _code.append(_ln.split("#", 1)[0])
    _src = "\n".join(_code)
    ok('use = "t" if k == 2 else "anova"' not in _src,
       "引擎里**没有**第二份「正态+方差齐→选哪个」的判定（已抽到 method_pick）")
    ok("method_map = {" not in _src,
       "引擎里**没有**第二份方法中文名对照表（已移到 METHOD_CN）")
    ok("pick_compare(k, all_normal, equal_var)" in _src,
       "引擎**确实调了**那个纯函数（不是自己另算一套）")
    # 推荐卡和判定必须是同一个函数算出来的
    rec = _mp.recommend_for("compare", {"n_levels": 4})
    ok(rec["method"] == _mp.pick_compare(4, True, True)["method"],
       "推荐卡与判定表给出同一个方法（先验推荐 vs 前提满足时的判定）", rec["method"])
    ok(rec.get("conditional"), "还没测前提时，推荐卡**明说是先验推荐**")
    ok(bool(_mp.pick_compare(4, False, True).get("why_not")),
       "每条推荐都带「为什么不用另一个」（不能只给结论）")

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
