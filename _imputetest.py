# -*- coding: utf-8 -*-
"""缺失插补 + 加权 · 专项自检（第 5 批）

    python _imputetest.py

守四件事：

  1. **均值填补会把方差压小、把相关稀释** —— 用真值已知的数据把这一点摆出来
  2. **多重插补（MICE）要把真值找回来**：相关、标准差都要接近真值
  3. **Rubin 合并的总方差必须大于组内方差**（多出来的就是"插补的不确定性"）
  4. **加权的两条算术**：加权均值要接近总体真值；权重相等时 DEFF=1、均值不动
"""
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
from core import impute as IM                # noqa: E402
from core import weights as WT               # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, label, extra=None):
    if cond:
        PASS[0] += 1
        print("  [OK] " + label)
    else:
        FAIL[0] += 1
        print("  [!!] " + label + ("" if extra is None else "  —— %s" % (extra,)))


def main():
    import numpy as np
    import pandas as pd
    from scipy import stats

    print("=" * 72)
    print("【1】均值填补的代价：方差被压小、相关被稀释")
    print("=" * 72)
    rng = np.random.default_rng(2026)
    n = 800
    x = rng.normal(0, 1, n)
    y = 0.6 * x + np.sqrt(1 - 0.36) * rng.normal(0, 1, n)
    d = pd.DataFrame({"x": x, "y": y})
    miss = rng.random((n, 2)) < 0.25
    dm = d.copy()
    dm[miss] = np.nan
    cc = dm.dropna()
    mf = dm.copy()
    for c in ("x", "y"):
        mf[c] = mf[c].fillna(mf[c].mean())
    r_cc = float(stats.pearsonr(cc["x"], cc["y"])[0])
    r_mf = float(stats.pearsonr(mf["x"], mf["y"])[0])
    ok(abs(r_cc - 0.6) < 0.08, "完整个案的相关接近真值 0.6（%.3f）" % r_cc, r_cc)
    ok(r_mf < r_cc - 0.06,
       "**均值填补把相关稀释了**（%.3f → %.3f）" % (r_cc, r_mf), (r_cc, r_mf))
    ok(mf["x"].std(ddof=1) < cc["x"].std(ddof=1) - 0.03,
       "**均值填补把标准差压小了**（%.3f → %.3f；真值 1.000）"
       % (cc["x"].std(ddof=1), mf["x"].std(ddof=1)),
       (cc["x"].std(ddof=1), mf["x"].std(ddof=1)))

    print("\n" + "=" * 72)
    print("【2】多重插补要把真值找回来")
    print("=" * 72)
    sets, used = IM.mice(dm, ["x", "y"], m=5, seed=20260926)
    ok(len(sets) == 5, "填了 5 套", len(sets))
    ok(all(len(s) == n for s in sets), "每套都是完整数据（没有缺失）",
       [int(s.isna().sum().sum()) for s in sets])
    ok(all(int(s.isna().sum().sum()) == 0 for s in sets), "一套都不剩缺失")
    sds = [float(s["x"].std(ddof=1)) for s in sets]
    rs = [float(stats.pearsonr(s["x"], s["y"])[0]) for s in sets]
    ok(abs(np.mean(sds) - 1.0) < 0.12,
       "插补后的标准差接近真值 1.000（%.3f）" % np.mean(sds), np.mean(sds))
    ok(abs(np.mean(rs) - 0.6) < 0.12,
       "插补后的相关接近真值 0.600（%.3f）" % np.mean(rs), np.mean(rs))
    ok(np.mean(sds) > mf["x"].std(ddof=1) + 0.05,
       "**多重插补的标准差明显比均值填补大**（%.3f vs %.3f）—— 它保住了变异"
       % (np.mean(sds), mf["x"].std(ddof=1)))
    ok(np.mean(rs) > r_mf + 0.06,
       "**多重插补的相关也比均值填补接近真值**（%.3f vs %.3f）" % (np.mean(rs), r_mf))
    # 可复现：同种子两次
    sets_b, _ = IM.mice(dm, ["x", "y"], m=5, seed=20260926)
    ok(all(np.allclose(a["x"].values, b["x"].values) for a, b in zip(sets, sets_b)),
       "**固定种子 → 两次跑出完全一样的插补数据**（可复现）")

    print("\n" + "=" * 72)
    print("【3】Rubin 合并：总方差必须 > 组内方差")
    print("=" * 72)
    ests, varz = [], []
    for s in sets:
        r = float(stats.pearsonr(s["x"], s["y"])[0])
        z = np.arctanh(r)
        ests.append(z)
        varz.append(1.0 / (len(s) - 3))
    pool = IM.rubin_pool(ests, varz)
    ok(pool is not None and pool["m"] == 5, "合并了 5 套", pool and pool["m"])
    ok(pool["total_var"] > pool["within"],
       "**总方差 > 组内方差**（%.6f > %.6f）—— 多出来的是「插补的不确定性」"
       % (pool["total_var"], pool["within"]))
    ok(pool["fmi"] is not None and 0 <= pool["fmi"] <= 1,
       "缺失信息占比 FMI 在 [0,1]（%.3f）" % pool["fmi"], pool["fmi"])
    lo, hi = pool["ci"]
    r_pool = float(np.tanh(pool["estimate"]))
    ok(lo <= pool["estimate"] <= hi, "合并后的 CI 包含点估计")
    ok(abs(r_pool - 0.6) < 0.12,
       "合并后 r 接近真值（%.3f）" % r_pool, r_pool)
    ok(IM.rubin_pool([1.0], [0.01])["m"] == 1, "只有 1 套时也返回结果（并说明）")
    ok(IM.rubin_pool([], []) is None, "一套都没有 → 返回 None，不崩")

    print("\n" + "=" * 72)
    print("【4】分类列插补：按比例抽，不一律填众数")
    print("=" * 72)
    s = pd.Series(["甲"] * 40 + ["乙"] * 40 + ["丙"] * 20 + [None] * 100)
    rng2 = np.random.default_rng(7)
    filled = IM.complete_categorical(s, rng2)
    ok(int(filled.isna().sum()) == 0, "填满了，没剩缺失")
    props = filled.value_counts(normalize=True)
    ok(abs(props.get("甲", 0) - 0.4) < 0.08 and abs(props.get("乙", 0) - 0.4) < 0.08
       and abs(props.get("丙", 0) - 0.2) < 0.08,
       "填入后各**类别比例接近观测比例**（甲 %.2f、乙 %.2f、丙 %.2f）—— "
       "填众数会把「甲」人为抬高到 0.7" % (props.get("甲", 0), props.get("乙", 0),
                                        props.get("丙", 0)), props.to_dict())
    ok(props.get("甲", 0) < 0.55, "没有全堆到众数上", props.get("甲", 0))

    print("\n" + "=" * 72)
    print("【5】加权：未加权会被「抽偏」带歪，加权把它纠回来")
    print("=" * 72)
    rng3 = np.random.default_rng(2026)
    A = rng3.normal(10, 3, 100000)
    B = rng3.normal(20, 3, 100000)
    pop_mean = (A.mean() + B.mean()) / 2
    sa = rng3.normal(10, 3, 600)
    sb = rng3.normal(20, 3, 150)          # 故意少抽 B
    x3 = np.concatenate([sa, sb])
    g3 = np.array(["A"] * 600 + ["B"] * 150)
    w3 = np.where(g3 == "A", 1.0, 4.0)    # 让加权后两组各占一半
    c = WT.compare_weighted(x3, w3)
    ok(abs(c["plain"]["mean"] - pop_mean) > 2.0,
       "未加权均值被带歪了（%.2f，真值 %.2f）" % (c["plain"]["mean"], pop_mean))
    ok(abs(c["weighted"]["mean"] - pop_mean) < 0.5,
       "**加权后接近总体真值**（%.2f，真值 %.2f）" % (c["weighted"]["mean"], pop_mean))
    # 权重相等时应当"什么都没改变"
    c2 = WT.compare_weighted(x3, np.ones_like(x3))
    ok(abs(c2["deff"] - 1.0) < 1e-9, "权重全相等 → **DEFF = 1**", c2["deff"])
    ok(abs(c2["mean_shift"]) < 1e-9, "权重全相等 → 均值移动 0", c2["mean_shift"])
    ok(abs(c2["se_ratio"] - 1.0) < 1e-9, "权重全相等 → 标准误不变", c2["se_ratio"])
    # 权重不齐时：n_eff < n、标准误变大
    ok(c["weighted"]["n_eff"] < c["weighted"]["n"],
       "权重不齐 → **n_eff < n**（%.0f < %d）"
       % (c["weighted"]["n_eff"], c["weighted"]["n"]))
    ok(c["se_ratio"] > 1.0,
       "而且**标准误被放大**（%.2f 倍）—— 这才是诚实的做法" % c["se_ratio"])
    ok(abs(c["deff"] - 1.56) < 0.2, "DEFF 算出来了（%.2f）" % c["deff"], c["deff"])

    print("\n" + "=" * 72)
    print("【6】权重检查：负权重/零权重/极端权重都要报")
    print("=" * 72)
    chk = WT.check_weights(np.array([1.0, 2.0, -1.0, 0.0, 3.0]))
    ok(chk["n_negative"] == 1, "认出 1 个负权重", chk["n_negative"])
    ok(chk["n_zero"] == 1, "认出 1 个零权重", chk["n_zero"])
    ok(not chk["ok"], "有非正权重 → 标成不可用", chk["ok"])
    chk2 = WT.check_weights(np.array([1.0] * 10))
    ok(chk2["ok"] and abs(chk2["n_eff"] - 10) < 1e-9,
       "权重全相等 → n_eff = n（没有信息损失）", (chk2["n_eff"], chk2["deff"]))
    chk3 = WT.check_weights(np.array([1.0] * 9 + [100.0]))
    ok(chk3["extreme"], "单个权重过大 → 标出「极端权重」", chk3["max_share"])
    ok(chk3["n_eff"] < 5, "而且 n_eff 掉得很厉害（%.1f）—— 一个人顶了很多人" % chk3["n_eff"],
       chk3["n_eff"])

    print("\n" + "=" * 72)
    print("【7】加权相关与加权组间差")
    print("=" * 72)
    xx = rng3.normal(0, 1, 500)
    yy = 0.6 * xx + np.sqrt(1 - 0.36) * rng3.normal(0, 1, 500)
    rc = WT.weighted_corr(xx, yy, rng3.uniform(0.5, 2.0, 500))
    ok(abs(rc["r"] - 0.6) < 0.1, "加权相关接近真值 0.6（%.3f）" % rc["r"], rc["r"])
    ok(rc["n_eff"] <= 500, "n_eff 不超过 n", (rc["n_eff"], rc["n"]))
    d3 = WT.weighted_diff(x3, g3, w3)
    ok(abs(d3["diff"] - 10) < 1.0,
       "加权组间差接近真值 10（%.2f）" % d3["diff"], d3["diff"])
    ok(d3["ci"][0] < d3["diff"] < d3["ci"][1], "差值的 CI 包含点估计")
    ok(WT.weighted_diff(x3, np.array(["A"] * 750), w3) is None,
       "只有一组 → 返回 None（不硬凑）")

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
