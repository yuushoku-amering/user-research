# -*- coding: utf-8 -*-
"""工作台 · 加权分析

**什么时候需要加权**：样本里各类人的**抽中概率不一样**，直接算平均会被抽中多的那类带偏。

    典型场景：
      · 分层抽样：大一抽了 200 人、大四只抽了 30 人，但大四在总体里占比更大
      · 事后加权（raking）：样本的性别比和总体对不上，给偏少的那类更大权重
      · 过度抽样（oversampling）：故意多抽某个小群体，分析时要"还原"回去

⚠ **加权会改变"谁在代表谁"**，所以有三件事必须一起报：
  1. **权重的来源**：这一列是怎么来的（抽样设计？事后校正？）—— 这个是研究员的事，
     程序只负责算，但报告里不写清就没法解释
  2. **有效样本量 n_eff**：加权之后"实际相当于多少人"。它通常**小于**原始 n
     （极端权重会让 n_eff 掉得很厉害），而**标准误要按 n_eff 算**
  3. **设计效应 DEFF = n / n_eff**：加权把标准误**放大了多少倍**。
     DEFF=2 的意思是"等于把样本量砍了一半"，这是最直观的一句话

=== 三条容易错的地方 ===

1. **加权方差不是把 (x−均值)² 乘权重就完事**：还要除以 Σw 的平方修正项。
   用 `Σw(x−x̄)² / (Σw − Σw²/Σw)`（可靠性权重）。不修正的话样本量小时会低估方差。
2. **加权的标准误要按 n_eff 算，不是按 n** —— 否则等于假装"权重没让信息变少"。
3. **权重为 0 等于剔除那个人**；**负权重没有意义**（会算出荒谬的结果）。
   这两种都要在数据检查阶段就报出来。
"""
import numpy as np
from scipy import stats


def check_weights(w):
    """检查权重列：有没有非正数、极端权重、缺失。**分析之前先过这一关。**"""
    w = np.asarray(w, dtype=float)
    n = len(w)
    bad = {}
    bad["n"] = int(n)
    bad["missing"] = int(np.isnan(w).sum())
    w2 = w[~np.isnan(w)]
    bad["n_positive"] = int((w2 > 0).sum())
    bad["n_zero"] = int((w2 == 0).sum())
    bad["n_negative"] = int((w2 < 0).sum())
    if len(w2) and (w2 > 0).any():
        pos = w2[w2 > 0]
        bad["min"] = float(pos.min())
        bad["max"] = float(pos.max())
        bad["max_over_min"] = float(pos.max() / pos.min())
        # 极端权重：单个权重占总量超过 5% 就值得看一眼
        share = pos / pos.sum()
        bad["max_share"] = float(share.max())
        bad["extreme"] = bool(share.max() > 0.05)
        # n_eff（Kish 公式）：权重不齐时"实际相当于多少人"
        bad["n_eff"] = float(pos.sum() ** 2 / (pos ** 2).sum())
        bad["deff"] = float(len(pos) / bad["n_eff"]) if bad["n_eff"] > 0 else None
    bad["ok"] = (bad["n_negative"] == 0 and bad["n_positive"] >= 3)
    return bad


def _wstats(x, w):
    """加权均值 / 方差 / 标准误。**这是所有加权统计量的地基。**"""
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    m = np.isfinite(x) & np.isfinite(w) & (w > 0)
    x, w = x[m], w[m]
    n = len(x)
    if n < 2:
        return None
    sw = float(w.sum())
    mean = float((w * x).sum() / sw)
    # ⚠ 方差要用「可靠性权重」的修正项，不是简单加权平均
    var = float((w * (x - mean) ** 2).sum() / (sw - (w ** 2).sum() / sw))
    # 有效样本量（Kish）—— 标准误按它算，不是按 n
    n_eff = float(sw ** 2 / (w ** 2).sum())
    se = float(np.sqrt(var / n_eff)) if n_eff > 0 else None
    return {"n": int(n), "n_eff": n_eff, "mean": mean, "var": var,
            "sd": float(np.sqrt(max(var, 0))), "se": se, "sum_w": sw}


def weighted_mean(x, w, alpha=0.05):
    """加权均值 + 置信区间（按 n_eff 的自由度）。"""
    s = _wstats(x, w)
    if not s:
        return None
    dfree = max(s["n_eff"] - 1, 1)
    tc = stats.t.ppf(1 - alpha / 2, dfree)
    return {**s, "df": dfree,
            "ci": (s["mean"] - tc * s["se"], s["mean"] + tc * s["se"]),
            "deff": (s["n"] / s["n_eff"]) if s["n_eff"] > 0 else None}


def weighted_corr(x, y, w, alpha=0.05):
    """加权相关（加权协方差 ÷ 两个加权标准差）。

    ⚠ 它的自由度也按 **n_eff** 走，所以 p 值会比不加权时**更保守** ——
      这是对的："权重不齐"本身就让信息变少了。
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    w = np.asarray(w, dtype=float)
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(w) & (w > 0)
    x, y, w = x[m], y[m], w[m]
    if len(x) < 4:
        return None
    sw = w.sum()
    mx = (w * x).sum() / sw
    my = (w * y).sum() / sw
    cxy = (w * (x - mx) * (y - my)).sum() / (sw - (w ** 2).sum() / sw)
    vx = (w * (x - mx) ** 2).sum() / (sw - (w ** 2).sum() / sw)
    vy = (w * (y - my) ** 2).sum() / (sw - (w ** 2).sum() / sw)
    if vx <= 0 or vy <= 0:
        return None
    r = float(cxy / np.sqrt(vx * vy))
    n_eff = float(sw ** 2 / (w ** 2).sum())
    dfree = max(n_eff - 2, 1)
    rr = max(min(r, 0.999999), -0.999999)
    t = rr * np.sqrt(dfree / max(1 - rr ** 2, 1e-12))
    p = float(2 * (1 - stats.t.cdf(abs(t), dfree)))
    se_z = 1.0 / np.sqrt(max(dfree - 1, 1))
    zc = stats.norm.ppf(1 - alpha / 2)
    ci = (float(np.tanh(np.arctanh(rr) - zc * se_z)),
          float(np.tanh(np.arctanh(rr) + zc * se_z)))
    return {"r": r, "n": int(len(x)), "n_eff": n_eff, "df": dfree,
            "t": float(t), "p": p, "ci": ci}


def weighted_diff(x, group, w, alpha=0.05):
    """加权组间均值差（两组）：加权均值差 + 按 n_eff 算的 t 检验。

    只做两组 —— 多组的话应该用加权方差分析，这里明确不做（不硬凑）。
    """
    x = np.asarray(x, dtype=float)
    g = np.asarray(group)
    w = np.asarray(w, dtype=float)
    m = np.isfinite(x) & np.isfinite(w) & (w > 0)
    x, g, w = x[m], g[m], w[m]
    levels = [v for v in dict.fromkeys(g.tolist())]
    if len(levels) != 2:
        return None
    a = x[g == levels[0]]
    wa = w[g == levels[0]]
    b = x[g == levels[1]]
    wb = w[g == levels[1]]
    sa, sb = _wstats(a, wa), _wstats(b, wb)
    if not sa or not sb:
        return None
    diff = sb["mean"] - sa["mean"]
    se = float(np.sqrt(sa["se"] ** 2 + sb["se"] ** 2))
    dfree = max(min(sa["n_eff"], sb["n_eff"]) - 1, 1)
    t = diff / se if se > 0 else None
    p = float(2 * (1 - stats.t.cdf(abs(t), dfree))) if t is not None else None
    tc = stats.t.ppf(1 - alpha / 2, dfree)
    return {"levels": [str(levels[0]), str(levels[1])],
            "mean_a": sa["mean"], "mean_b": sb["mean"], "diff": diff,
            "se": se, "t": t, "p": p, "df": dfree,
            "ci": (diff - tc * se, diff + tc * se),
            "n_eff_a": sa["n_eff"], "n_eff_b": sb["n_eff"],
            "deff": (sa["n"] + sb["n"]) / (sa["n_eff"] + sb["n_eff"])
            if (sa["n_eff"] + sb["n_eff"]) > 0 else None}


def compare_weighted(x, w, alpha=0.05):
    """**未加权 vs 加权并排** —— 这是加权分析最该给人看的东西。

    加权到底改变了什么？看两个数就够：
      · 均值动了多少（动了说明样本构成和总体不一致）
      · **DEFF**（设计效应）—— 标准误被放大多少倍
        DEFF = 2 就是"等于把样本量砍了一半"，这句话最好懂。

    如果 DEFF 接近 1，说明权重**几乎没起作用**，那就要问一句"这个权重是怎么来的"。
    """
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    m = np.isfinite(x) & np.isfinite(w) & (w > 0)
    x2, w2 = x[m], w[m]
    if len(x2) < 3:
        return None
    plain = {"n": int(len(x2)), "mean": float(x2.mean()),
             "sd": float(x2.std(ddof=1)),
             "se": float(x2.std(ddof=1) / np.sqrt(len(x2)))}
    wt = weighted_mean(x2, w2, alpha)
    if not wt:
        return None
    return {"plain": plain, "weighted": wt,
            "mean_shift": wt["mean"] - plain["mean"],
            "se_ratio": (wt["se"] / plain["se"]) if plain["se"] > 0 else None,
            "deff": wt.get("deff"),
            "n_eff": wt["n_eff"]}
