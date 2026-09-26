# -*- coding: utf-8 -*-
"""工作台 · 中介与调节（"间接效应"和"在什么条件下"）

**这两个是两个不同的问题，别混**：

    调节（moderation）：**X 对 Y 的作用，随 W 变化**
        「兼职的影响，在生活费高的人身上是不是更强？」
        → 做法：回归里加**交互项 X×W**，看交互项显著不显著

    中介（mediation）：**X 通过 M 影响 Y**
        「生活费来源 → 花钱习惯 → 恋爱支出」（钱是"经由"习惯起作用的）
        → 做法：拆成 a 路径（X→M）和 b 路径（M→Y），间接效应 = a×b

⚠ 为什么中介必须用 **bootstrap** 而不是 Sobel 检验：
  间接效应 a×b 的抽样分布**不是正态的**（两个随机变量相乘），
  而 Sobel 检验假设它正态 → p 值和 CI 都偏。现在的主流做法是 bootstrap 取百分位区间。
  （本模块默认 5000 次、固定种子 —— 每次跑出同一个区间，报告才可复现。）

⚠ 为什么交互项要**先对中**（centering）：
  不对中的话，X 的系数变成"W=0 时 X 的作用"——而 W=0 往往没有实际意义
  （比如"生活费=0"）。对中之后，X 的系数是"在 W 平均水平上 X 的作用"，可解释，
  而且交互项和主效应的共线性会小很多。
"""
import numpy as np
from scipy import stats

from . import regress as R

BOOT_N = 5000
BOOT_SEED = 20260926


def _prep(d, cols):
    """取出需要的列、成对删缺失，返回 (DataFrame, n)。"""
    import pandas as pd
    sub = d[cols].apply(pd.to_numeric, errors="coerce").dropna()
    return sub, len(sub)


def _fit_simple(sub, xcol, ycol):
    """一元回归 y = a + b·x，返回系数 b 及其检验。"""
    X = np.column_stack([np.ones(len(sub)), sub[xcol].values.astype(float)])
    y = sub[ycol].values.astype(float)
    fit = R.ols(X, y)
    return {"b": float(fit["beta"][1]), "se": float(fit["se"][1]),
            "t": float(fit["t"][1]), "p": float(fit["p"][1]),
            "ci": R.ci_beta(fit["beta"][1], fit["se"][1], fit["dof"]),
            "dof": int(fit["dof"]), "n": int(fit["n"])}


def mediation(d, x, m, y, n_boot=BOOT_N, alpha=0.05, seed=BOOT_SEED,
              covariates=None):
    """简单中介：X → M → Y，间接效应 a×b 用 bootstrap 取 CI。

    **它只做一件事**：把 a、b、c（总效应）、c'（直接效应）、a×b（间接效应）
    和它们的区间算出来，并给出中介占比。
    **因果关系它不负责**——那要靠设计（时间先后 / 实验），不是靠统计。
    所以报告里必须写明"这是**统计上的**间接效应，不是因果证明"。

    `covariates` 是控制变量（可选）：三个方程里都要放进去。
    """
    covs = [c for c in (covariates or []) if c not in (x, m, y)]
    cols = [x, m, y] + covs
    sub, n = _prep(d, cols)
    if n < 20:
        return {"error": "有效样本只有 %d，做不了中介分析（建议 ≥ 50）" % n}

    # --- a 路径：X → M（含控制变量）---
    Xa = np.column_stack([np.ones(n), sub[x].values.astype(float)]
                         + [sub[c].values.astype(float) for c in covs])
    a_fit = R.ols(Xa, sub[m].values.astype(float))
    a = float(a_fit["beta"][1])
    a_se, a_p = float(a_fit["se"][1]), float(a_fit["p"][1])

    # --- b 与 c'：Y ~ M + X（含控制变量）---
    Xb = np.column_stack([np.ones(n), sub[m].values.astype(float),
                          sub[x].values.astype(float)]
                         + [sub[c].values.astype(float) for c in covs])
    b_fit = R.ols(Xb, sub[y].values.astype(float))
    b = float(b_fit["beta"][1])
    b_se, b_p = float(b_fit["se"][1]), float(b_fit["p"][1])
    cprime = float(b_fit["beta"][2])
    cp_se, cp_p = float(b_fit["se"][2]), float(b_fit["p"][2])

    # --- c：总效应 Y ~ X（含控制变量）---
    Xc = np.column_stack([np.ones(n), sub[x].values.astype(float)]
                         + [sub[c].values.astype(float) for c in covs])
    c_fit = R.ols(Xc, sub[y].values.astype(float))
    c = float(c_fit["beta"][1])
    c_se, c_p = float(c_fit["se"][1]), float(c_fit["p"][1])

    indirect = a * b

    # --- bootstrap：间接效应的百分位 CI ---
    rng = np.random.default_rng(seed)
    raw = sub.values.astype(float)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        bx = raw[idx]
        try:
            Xa_b = np.column_stack([np.ones(n), bx[:, cols.index(x)]]
                                   + [bx[:, cols.index(c)] for c in covs])
            a_b = np.linalg.lstsq(Xa_b, bx[:, cols.index(m)], rcond=None)[0][1]
            Xb_b = np.column_stack([np.ones(n), bx[:, cols.index(m)],
                                    bx[:, cols.index(x)]]
                                   + [bx[:, cols.index(c)] for c in covs])
            bb = np.linalg.lstsq(Xb_b, bx[:, cols.index(y)], rcond=None)[0]
            boots[i] = a_b * bb[1]
        except Exception:
            boots[i] = np.nan
    boots = boots[~np.isnan(boots)]
    if len(boots) < 100:
        ci_lo = ci_hi = None
    else:
        ci_lo, ci_hi = np.percentile(boots, [alpha / 2 * 100, (1 - alpha / 2) * 100])
    sig = (ci_lo is not None) and (ci_lo > 0 or ci_hi < 0)

    return {
        "x": x, "m": m, "y": y, "covariates": covs, "n": n,
        "a": a, "a_se": a_se, "a_p": a_p, "a_ci": R.ci_beta(a, a_se, a_fit["dof"]),
        "b": b, "b_se": b_se, "b_p": b_p, "b_ci": R.ci_beta(b, b_se, b_fit["dof"]),
        "c": c, "c_se": c_se, "c_p": c_p, "c_ci": R.ci_beta(c, c_se, c_fit["dof"]),
        "c_prime": cprime, "cp_se": cp_se, "cp_p": cp_p,
        "cp_ci": R.ci_beta(cprime, cp_se, b_fit["dof"]),
        "indirect": float(indirect),
        "boot_ci": (float(ci_lo), float(ci_hi)) if ci_lo is not None else None,
        "boot_n": int(len(boots)), "significant": bool(sig),
        "prop_mediated": (float(indirect / c) if abs(c) > 1e-12 else None),
        # 完全中介 / 部分中介的判断：看直接效应还显不显著
        "kind": ("完全中介（直接效应不显著）" if cp_p > alpha else
                 "部分中介（直接效应仍显著）") if sig else "间接效应不显著",
    }


def moderation(d, x, w, y, alpha=0.05, covariates=None):
    """调节：Y ~ X + W + X×W（**变量先对中**，再看交互项）。

    返回：三个系数 + 交互项检验、**简单斜率**（W 取低/中/高时的 X 效应）、
    以及 **Johnson-Neyman 区间**（W 在哪个范围内时 X 的效应显著）。
    """
    covs = [c for c in (covariates or []) if c not in (x, w, y)]
    cols = [x, w, y] + covs
    sub, n = _prep(d, cols)
    if n < 30:
        return {"error": "有效样本只有 %d，做不了调节分析（交互项很吃样本）" % n}

    xs = sub[x].values.astype(float)
    ws = sub[w].values.astype(float)
    ys = sub[y].values.astype(float)
    # ⚠ 对中：让"X 的系数"变成"W 在平均水平时 X 的作用"，可解释；
    #   同时把交互项与主效应之间的共线性降下来。
    xc = xs - xs.mean()
    wc = ws - ws.mean()
    inter = xc * wc
    X = np.column_stack([np.ones(n), xc, wc, inter]
                        + [sub[c].values.astype(float) for c in covs])
    fit = R.ols(X, ys)
    b_x = float(fit["beta"][1])
    b_w = float(fit["beta"][2])
    b_int = float(fit["beta"][3])
    p_int = float(fit["p"][3])
    dof = int(fit["dof"])

    # --- 简单斜率：X 对 Y 的作用 = b_x + b_int·W（W 已对中）---
    def slope_at(w_val):
        est = b_x + b_int * w_val
        # 斜率的标准误：Var(b1) + w²Var(b3) + 2w·Cov(b1,b3)
        v1 = fit["XtX_inv"][1, 1] * (float(fit["resid"] @ fit["resid"]) / dof)
        v3 = fit["XtX_inv"][3, 3] * (float(fit["resid"] @ fit["resid"]) / dof)
        c13 = fit["XtX_inv"][1, 3] * (float(fit["resid"] @ fit["resid"]) / dof)
        se = np.sqrt(max(v1 + w_val ** 2 * v3 + 2 * w_val * c13, 0))
        t = est / se if se > 0 else np.nan
        p = float(2 * (1 - stats.t.cdf(abs(t), dof))) if se > 0 else None
        return {"w_centered": float(w_val), "w_actual": float(w_val + ws.mean()),
                "slope": float(est), "se": float(se), "t": float(t), "p": p,
                "ci": R.ci_beta(est, se, dof)}

    sd_w = float(wc.std(ddof=1))
    slopes = [slope_at(-sd_w), slope_at(0.0), slope_at(sd_w)]

    # --- Johnson-Neyman：解 |(b1 + b3·w) / SE(w)| = t_crit 的 w ---
    tcrit = stats.t.ppf(1 - alpha / 2, dof)
    # (b1 + b3 w)² = tcrit² · (v1 + w² v3 + 2 w c13)
    v1 = fit["XtX_inv"][1, 1] * (float(fit["resid"] @ fit["resid"]) / dof)
    v3 = fit["XtX_inv"][3, 3] * (float(fit["resid"] @ fit["resid"]) / dof)
    c13 = fit["XtX_inv"][1, 3] * (float(fit["resid"] @ fit["resid"]) / dof)
    A = b_int ** 2 - tcrit ** 2 * v3
    B = 2 * (b_x * b_int - tcrit ** 2 * c13)
    C = b_x ** 2 - tcrit ** 2 * v1
    roots = []
    if abs(A) < 1e-12:
        if abs(B) > 1e-12:
            roots = [-C / B]
    else:
        disc = B ** 2 - 4 * A * C
        if disc >= 0:
            roots = [(-B - np.sqrt(disc)) / (2 * A), (-B + np.sqrt(disc)) / (2 * A)]
    roots = sorted(r + ws.mean() for r in roots)

    return {"x": x, "w": w, "y": y, "n": n, "dof": dof, "covariates": covs,
            "b_x": b_x, "b_w": b_w, "b_int": b_int, "p_int": p_int,
            "int_ci": R.ci_beta(b_int, float(fit["se"][3]), dof),
            "x_ci": R.ci_beta(b_x, float(fit["se"][1]), dof),
            "significant": bool(p_int <= alpha),
            "slopes": slopes, "jn_roots": roots,
            "w_mean": float(ws.mean()), "w_sd": sd_w,
            "r2": fit["r2"], "fit": fit}
