# -*- coding: utf-8 -*-
"""工作台 · 被试内检验（单样本 / 配对）

**为什么单独一个模块**：⑥ 的引擎已经两千行，而"配对"这一族（配对 t、Wilcoxon 符号秩、
单样本 t）是**自成一套**的：数据形状不同（不是"分组"，是"两列"或"一列 vs 一个常数"），
效应量的算法也不同。塞进引擎只会让那两千行更长、更容易出错。

⚠ 但它**不是**第二份判定：方法选哪个仍然走 `core/method_pick.pick_within()`
（和 ⑥ 调同一个函数）。这里只负责"给定方法，怎么算、给什么数"。

一个重要的设计：**配对 = 先做差，再看这个差**。
    配对 t 检验  ≡  对「差值」做单样本 t 检验（H0: 差值的总体均值 = 0）
    Wilcoxon 符号秩 ≡ 对「差值」的符号秩检验
所以下面两族共用一个"差值"的概念，代码也只有一份。
"""
import numpy as np
from scipy import stats


def diffs(x, y):
    """配对数据的差值 d = x - y（按对相减，缺失成对删除）。

    ⚠ 方向要固定并写进报告：「x − y」。方向反了的话：
       · 均值差的正负号会反过来
       · 配对 t 的 p 值**不变**（双尾），但单尾和结论的方向表述会错
       · 效应量 rank-biserial 的符号也会反
    所以别让调用方随便换顺序，由 `pick_within` 那边定下来（通常「后测 − 前测」）。
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = ~(np.isnan(x) | np.isnan(y))
    return x[m] - y[m]


def ci_mean_t(v, alpha=0.05):
    """均值的置信区间（t 分布）。"""
    v = np.asarray(v, dtype=float)
    v = v[~np.isnan(v)]
    n = len(v)
    if n < 2:
        return None
    se = float(v.std(ddof=1)) / np.sqrt(n)
    tc = stats.t.ppf(1 - alpha / 2, n - 1)
    return (float(v.mean()) - tc * se, float(v.mean()) + tc * se)


def ci_mean_diff_t(d, alpha=0.05):
    """**配对差**的均值置信区间 —— 这是配对检验最该报的那个数。

    比“两组各自均值和 CI”有用得多：配对设计的信息全在**差值**里，
    差值 CI 不跨 0 ⇔ 配对 t 显著。
    """
    return ci_mean_t(d, alpha)


def cohens_dz(d, alpha=0.05, want_ci=True):
    """配对设计的效应量 Cohen's d_z = 差值均值 / 差值标准差。

    ⚠ 必须叫 d_z 不叫 d：配对设计和独立样本的 d **不是一回事**，
      混着报会让 meta 分析的人算错。d_z 通常比独立样本 d 大（因为配对消掉了个体差异）。
    """
    d = np.asarray(d, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 2:
        return None, "—"
    sd = float(d.std(ddof=1))
    if sd <= 0:
        return None, "—"
    dz = float(d.mean()) / sd
    if not want_ci:
        return dz, "—"
    # 近似：SE(d_z) ≈ sqrt(1/n + d_z²/(2n))
    try:
        se = np.sqrt(1.0 / n + dz * dz / (2.0 * n))
        z = stats.norm.ppf(1 - alpha / 2)
        return dz, "[%.3f, %.3f]" % (dz - z * se, dz + z * se)
    except Exception:
        return dz, "—"


def rank_biserial_paired(d):
    """Wilcoxon 符号秩的效应量：配对版 rank-biserial r。

    做法和教科书一致：分别算正差和负差的秩和，`r = (T+ − T−) / (T+ + T−)`。
    ⚠ 它和独立样本那个 rank-biserial 公式**长得像但不是一回事**
      （独立样本用 U 算，这里用秩和算）——别互相套用。
    """
    d = np.asarray(d, dtype=float)
    d = d[~np.isnan(d)]
    d = d[d != 0]
    if len(d) == 0:
        return None
    r = stats.rankdata(np.abs(d))
    tp = float(r[d > 0].sum())
    tn = float(r[d < 0].sum())
    if tp + tn <= 0:
        return None
    return (tp - tn) / (tp + tn)


def wilcoxon_paired(x, y, alpha=0.05):
    """Wilcoxon 符号秩检验（配对）。返回一个装好了所有该报的数的 dict。

    包含：统计量、p、**零差值（打平）的个数**、中位数差、效应量、以及零差值处理方式。

    ⚠ 零差值（打平）是个真问题、必须报出来：
      · 打平的对**不参与**秩和，但会影响"有效对数"
      · 打平很多时（比如前后测一样的人占三成），符号秩的检验力会明显下降，
        这时该考虑改用**符号检验**（只看方向、不看幅度）或配对 t
      · scipy 默认 `zero_method="wilcox"` 丢掉零差值 —— 丢掉几个必须让人知道，
        不然报告里 n 对不上（"我明明有 50 对，怎么只说 43 对"）
    """
    d = diffs(x, y)
    n_pair = len(d)                     # 成对完整的数据（差值非缺失）
    n_zero = int(np.sum(d == 0))
    d_nz = d[d != 0]
    out = {"n_pair": int(n_pair), "n_zero": n_zero, "n_use": int(len(d_nz)),
           "method": "Wilcoxon 符号秩", "zero_note": ""}
    if n_pair == 0:
        return {**out, "stat": None, "p": None, "error": "没有可用的配对（差值全缺失）"}
    if len(d_nz) == 0:
        return {**out, "stat": None, "p": None,
                "error": "所有配对的差值都是 0，没有可检验的变异"}
    try:
        r = stats.wilcoxon(d_nz, alternative="two-sided", method="auto")
        stat, p = float(r.statistic), float(r.pvalue)
    except Exception as e:
        # 样本很小时精确分布算不出来 → 退回正态近似，并**说明**了
        try:
            r = stats.wilcoxon(d_nz, alternative="two-sided", method="asymptotic")
            stat, p = float(r.statistic), float(r.pvalue)
            out["zero_note"] = "样本较小，用了正态近似（精确分布算不出来）"
        except Exception as e2:
            return {**out, "stat": None, "p": None, "error": "Wilcoxon 算不出来：%s" % e2}
    rb = rank_biserial_paired(d_nz)
    med = float(np.median(d))
    out.update({
        "stat": stat, "p": p, "rank_biserial": rb,
        "median_diff": med,
        "median_ci": _median_ci_boot(d, alpha),
        "iqr_diff": (float(np.percentile(d, 25)), float(np.percentile(d, 75))),
    })
    if n_zero:
        out["zero_note"] = ("**%d 对（占 %.0f%%）前后完全一样**，它们不参与秩和 —— "
                            "所以实际用上的是 %d 对。打平多的时候符号秩的检验力会下降，"
                            "可以再看看**符号检验**（只看方向、不看幅度）或配对 t 作对照。"
                            % (n_zero, n_zero / max(n_pair, 1) * 100, len(d_nz)))
    return out


def _median_ci_boot(v, alpha=0.05, n_boot=2000, seed=20260926):
    """中位数的 bootstrap 置信区间（配对差值用）。

    ⚠ 中位数没有像均值那样的闭式 CI（要估计密度），所以用 bootstrap。
      固定种子 —— 每次跑出同一个区间，报告才可复现。
    """
    v = np.asarray(v, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) < 5:
        return None, "—"
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(n_boot, len(v)))
    meds = np.median(v[idx], axis=1)
    lo, hi = np.percentile(meds, [alpha / 2 * 100, (1 - alpha / 2) * 100])
    return (float(lo), float(hi)), "[%.3f, %.3f]" % (lo, hi)


def ttest_paired(x, y, alpha=0.05):
    """配对样本 t 检验。"""
    d = diffs(x, y)
    n = len(d)
    out = {"method": "配对样本 t 检验", "n_pair": int(n)}
    if n < 2:
        return {**out, "error": "配对少于 2 对，做不了配对 t 检验"}
    # ⚠ 差值全相等（方差 0）时 scipy 会抛一堆 "Precision loss / catastrophic cancellation"
    #   的 RuntimeWarning —— 那是**数学上退化**（所有人变化量一模一样），不是程序坏了。
    #   但让它刷屏会淹没真正的警告，所以这里局部压掉，并在结果里点明这个退化情形。
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            t, p = stats.ttest_rel(x, y)
            sk = float(stats.skew(d)) if n > 2 else None
            ku = float(stats.kurtosis(d)) if n > 3 else None
    sd_d = float(d.std(ddof=1))
    out.update({"stat": float(t), "p": float(p),
                "mean_diff": float(d.mean()),
                "sd_diff": sd_d,
                "kurtosis": ku, "skew": sk,
                "degenerate": sd_d == 0})
    if sd_d == 0:
        out["degenerate_note"] = ("**所有配对的差值完全一样**（差值标准差 = 0）——"
                                  "这时 t 是无穷、p 是 0，但那个 p 没有意义："
                                  "它说明的是「没有变异」，不是「效应极大」。"
                                  "先回去看数据是不是被改过（比如两列其实是同一列）。")
    ci = ci_mean_diff_t(d, alpha)
    out["ci"] = ci
    out["ci_str"] = "[%.3f, %.3f]" % ci if ci else "—"
    dz, dz_ci = cohens_dz(d, alpha)
    out["dz"], out["dz_ci"] = dz, dz_ci
    return out


def ttest_one(x, mu0=0.0, alpha=0.05):
    """单样本 t 检验：这一列的均值是不是等于某个数（默认 0）。"""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    out = {"method": "单样本 t 检验", "n": int(n), "mu0": float(mu0)}
    if n < 2:
        return {**out, "error": "样本少于 2 个，做不了单样本 t 检验"}
    t, p = stats.ttest_1samp(x, mu0)
    out.update({"stat": float(t), "p": float(p), "mean": float(x.mean()),
                "sd": float(x.std(ddof=1))})
    ci = ci_mean_t(x, alpha)
    out["ci"] = ci
    out["ci_str"] = "[%.3f, %.3f]" % ci if ci else "—"
    # ⚠ Cohen's d = （均值 − 参照值）/ 标准差 —— 是**两个标量相除**。
    #   这里第一版写成 `(x - mu0) / x.std(...)`，那是**数组除标量**（一个向量！），
    #   再 float() 就 TypeError。测试里当场抓到了（"only size-1 arrays can be converted"）。
    sd = float(x.std(ddof=1))
    out["cohens_d"] = (float(x.mean()) - float(mu0)) / sd if sd > 0 else None
    return out
