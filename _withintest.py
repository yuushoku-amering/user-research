# -*- coding: utf-8 -*-
"""被试内 + 偏相关 · 专项自检（第 1 批补齐的功能）

    python _withintest.py

守四件事：

  1. **配对检验的前提落在"差值"上**，不是原始两列各自正态
     —— 只看"两列各自正态吗"就换非参数，会白丢配对带来的检验力
  2. 方向固定（第二列 − 第一列）、并且**写进报告** —— 方向反了结论表述就错
  3. 打平（零差值）**必须报出来** —— 它不参与秩和，但报告里 n 会对不上
  4. 偏相关 = 扣掉控制变量之后的相关 —— 用「共同原因」造的假相关能被打回原形
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
from core import method_pick as mp            # noqa: E402
from core import within as W                  # noqa: E402

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
    import numpy as np

    print("=" * 72)
    print("【1】配对 t：手工可核的数字 + 方向")
    print("=" * 72)
    rng = np.random.default_rng(42)
    pre = rng.normal(60, 10, 80)
    post = pre + rng.normal(3, 6, 80)
    r = W.ttest_paired(post, pre)
    ok(r["n_pair"] == 80, "有效配对 80", r["n_pair"])
    ok(r["mean_diff"] > 0, "差值为正（后测 − 前测 = 升高）", r["mean_diff"])
    # 方向反了会怎样：均值差变号、但双尾 p 不变（这一点必须知道）
    r_rev = W.ttest_paired(pre, post)
    ok(abs(r_rev["mean_diff"] + r["mean_diff"]) < 1e-9,
       "**方向反了均值差变号**", (r["mean_diff"], r_rev["mean_diff"]))
    ok(abs(r_rev["p"] - r["p"]) < 1e-12,
       "**但双尾 p 不变**（所以方向必须靠报告的表述来固定）", (r["p"], r_rev["p"]))
    lo, hi = r["ci"]
    ok(lo < r["mean_diff"] < hi, "差值均值的 CI 包含点估计", r["ci_str"])
    ok(r["dz"] is not None and r["dz"] > 0, "效应量 d_z 算出来了", r["dz"])

    print("\n" + "=" * 72)
    print("【2】前提落在**差值**上（不是原始两列）")
    print("=" * 72)
    # 两列各自都偏（指数分布），但差值正态 —— 这种该用配对 t，不该被赶去非参数
    base = rng.exponential(scale=20, size=200)
    post2 = base + rng.normal(2, 3, 200)
    e = load_engine("b5_stats")
    nd_raw_a = e._normality(base, 0.05)
    nd_raw_b = e._normality(post2, 0.05)
    nd_diff = e._normality(W.diffs(post2, base), 0.05)
    ok(nd_raw_a["ok"] is False and nd_raw_b["ok"] is False,
       "原始两列各自都**不正态**（指数分布）", (nd_raw_a["detail"][:30],))
    ok(nd_diff["ok"] is True,
       "但**差值**是正态的 → 应该用配对 t，不该被赶去非参数", nd_diff["detail"][:60])
    pick = mp.pick_within(True, bool(nd_diff["ok"]))
    ok(pick["method"] == "paired_t", "判定给出配对 t", pick["method"])
    ok("前提落在差值上" in pick["why"] or "差值" in pick["why"],
       "推荐理由里点明了「前提看差值」", pick["why"][:60])

    print("\n" + "=" * 72)
    print("【3】打平（零差值）必须报出来")
    print("=" * 72)
    a = rng.normal(50, 8, 100)
    b = a.copy()
    b[:30] = a[:30]                       # 30 人完全没变
    b[30:] = a[30:] + rng.normal(4, 5, 70)
    w = W.wilcoxon_paired(b, a)
    ok(w["n_pair"] == 100, "总配对数 100", w["n_pair"])
    ok(w["n_zero"] == 30, "认出 30 对前后完全一样", w["n_zero"])
    ok(w["n_use"] == 70, "实际参与秩和的是 70 对", w["n_use"])
    ok("30 对" in (w["zero_note"] or ""), "**警告里写明了打平多少对**", w["zero_note"][:60])
    ok(w["rank_biserial"] is not None and -1 <= w["rank_biserial"] <= 1,
       "配对版 rank-biserial 在 [-1, 1] 内", w["rank_biserial"])
    # 推荐里也要提示（不是换方法，是提醒"别把不显著读成没关系"）
    pk = mp.pick_within(True, False, n_zero_ratio=0.30)
    ok(any("打平" in x for x in pk["why_not"]), "推荐卡也提示了打平的影响",
       pk["why_not"])

    print("\n" + "=" * 72)
    print("【4】单样本 t + 退化情形不崩")
    print("=" * 72)
    r4 = W.ttest_one(a, 50)
    ok(r4["n"] == 100 and r4["cohens_d"] is not None,
       "单样本 t 能算（**第一版这里把数组当标量，直接 TypeError**）",
       (r4["n"], r4["cohens_d"]))
    ok(r4["ci"][0] < r4["mean"] < r4["ci"][1], "均值的 CI 包含点估计", r4["ci_str"])
    degenerate = W.ttest_paired(np.array([12., 14., 16.]), np.array([10., 12., 14.]))
    ok(degenerate.get("degenerate") is True,
       "差值全相等时**被标成退化**（而不是报一个 p=0 当结论）", degenerate.get("degenerate"))
    ok("没有变异" in (degenerate.get("degenerate_note") or ""),
       "并且解释了「p=0 不等于效应极大」", (degenerate.get("degenerate_note") or "")[:40])

    print("\n" + "=" * 72)
    print("【5】偏相关：把「共同原因」造成的假相关打回原形")
    print("=" * 72)
    n = 200
    z = rng.normal(0, 1, n)
    x = z + rng.normal(0, 0.6, n)
    y = z + rng.normal(0, 0.6, n)
    import pandas as pd
    d = pd.DataFrame({"x": x, "y": y, "共同原因": z})
    pc = e._partial_corr(d, "x", "y", ["共同原因"], 0.05)
    from scipy import stats as _st
    r_raw = float(_st.pearsonr(x, y)[0])
    ok(r_raw > 0.5, "不扣控制变量时，看起来明显相关（r=%.3f）" % r_raw, r_raw)
    ok(abs(pc["r"]) < 0.25,
       "扣掉共同原因后关系基本消失（偏相关 r=%.3f）" % pc["r"], pc["r"])
    ok(pc["df"] == n - 3, "自由度 = n − 2 − k（k=1 个控制变量）", pc["df"])
    # 和手工「残差相关」对一遍
    def resid(v, c):
        b_ = np.polyfit(c, v, 1)
        return v - np.polyval(b_, c)
    man = float(_st.pearsonr(resid(x, z), resid(y, z))[0])
    ok(abs(man - pc["r"]) < 1e-9, "和手工「残差相关」完全一致", (man, pc["r"]))
    pc2 = e._partial_corr(d, "x", "y", [], 0.05)
    ok(abs(pc2["r"] - r_raw) < 1e-9,
       "不给控制变量时，偏相关**等于**普通相关（同一个定义）", (pc2["r"], r_raw))

    print("\n" + "=" * 72)
    print("【6】端到端：配对分支 + 偏相关分支都能跑，且推荐与实际一致")
    print("=" * 72)
    tmp = tempfile.mkdtemp(prefix="urw_within_")
    try:
        pd.DataFrame({
            "编号": ["S%03d" % i for i in range(120)],
            "干预前": pre[:120] if len(pre) >= 120 else rng.normal(60, 10, 120),
            "干预后": (pre[:120] if len(pre) >= 120 else rng.normal(60, 10, 120))
                      + rng.normal(3, 6, 120),
            "x": x[:120], "y": y[:120], "共同原因": z[:120],
        }).to_csv(os.path.join(tmp, "c.csv"), index=False, encoding="utf-8-sig")

        ctx = Ctx({"file": "c.csv", "question": "within", "pair_a": "干预前",
                   "pair_b": "干预后", "alpha": 0.05, "gen_sps": ["sps"]},
                  project_root=tmp)
        res = e.run(ctx)
        names = [t["name"] for t in (res.get("tables") or [])]
        ok(any("配对样本 t" in n_ for n_ in names) or any("Wilcoxon" in n_ for n_ in names),
           "配对分支跑出了检验结果", names)
        ok(any("方法推荐" in n_ for n_ in names), "配对也有推荐卡", names)
        # 推荐和实际必须一致（先验推荐时都应是配对 t）
        rec = [t for t in res["tables"] if "方法推荐" in t["name"]][0]
        rec_method = rec["rows"][0][1]
        real = [n_ for n_ in names if n_.startswith("检验结果")][0]
        ok(("配对样本 t" in rec_method and "配对样本 t" in real)
           or ("Wilcoxon" in rec_method and "Wilcoxon" in real),
           "**推荐的方法和实际跑的是同一个**（%s vs %s）" % (rec_method, real))
        ok(os.path.exists(os.path.join(tmp, "output", "分析_语法.sps")),
           "生成了 SPSS 复核语法")

        ctx2 = Ctx({"file": "c.csv", "question": "relate", "dv": "y", "ivs": ["x"],
                    "controls": ["共同原因"], "alpha": 0.05, "gen_sps": []},
                   project_root=tmp)
        res2 = e.run(ctx2)
        names2 = [t["name"] for t in (res2.get("tables") or [])]
        ok(any("偏相关" in n_ for n_ in names2), "偏相关卡片出来了", names2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
