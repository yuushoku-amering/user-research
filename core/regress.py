# -*- coding: utf-8 -*-
"""工作台 · 回归与广义线性模型

**为什么要有这个模块**：`_ols` 原来埋在 `b5_stats/engine.py` 里、只有那一个地方用。
但**中介、调节、逻辑回归、多重插补全都要用它** —— 不抽出来，
就会变成四份各自实现的回归，而"四份实现"正是这个项目反复吃过的亏
（②/②b 各写一遍「谁是访谈者」，两边不一致还从不报错）。

所以：**回归的算法只有这一份**。⑥ 的引擎、中介分析、逻辑回归、插补，全部 import 它。

包含：
    ols()                   最小二乘（含标准误 / t / p / R² / 调整 R² / F）
    logistic()              二元 logistic（IRLS），含 OR 与 OR 的 CI
    hosmer_lemeshow()       拟合优度
    classify_table()        分类表 / 正确率 / 敏感度 / 特异度
    cohens_d() / ci_* 等     效应量与区间（也从引擎搬过来，全局一份）
"""
import numpy as np
from scipy import stats

# 迭代上限：GLM 的 IRLS 一般十几步就收敛；给到 100 是"防止死循环"，不是"正常要这么多步"
IRLS_MAX_ITER = 100
IRLS_TOL = 1e-10


# --------------------------------------------------------------------------- #
# 效应量与区间（原来散在引擎里，现在全局一份）
# --------------------------------------------------------------------------- #

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


def ci_beta(b, se, df, alpha=0.05):
    """回归系数的置信区间：B ± t(α/2, df) × SE。

    和均值差是同一个道理 —— **只报 B 和 p 不够**：
    B=0.054 配 SE=0.014 和配 SE=0.140，p 都可能显著，但可信程度差一个量级。
    """
    try:
        b, se, df = float(b), float(se), float(df)
        if df <= 0 or se != se:
            return "—"
        tcrit = stats.t.ppf(1 - alpha / 2, df)
        return "[%.3f, %.3f]" % (b - tcrit * se, b + tcrit * se)
    except Exception:
        return "—"


def ci_r(r, n, alpha=0.05):
    """相关系数的置信区间（Fisher z 变换）。"""
    try:
        n = int(n)
        if n < 4 or r is None:
            return "—"
        r = max(min(float(r), 0.999999), -0.999999)
        z = np.arctanh(r)
        se = 1.0 / np.sqrt(n - 3)
        zc = stats.norm.ppf(1 - alpha / 2)
        return "[%.3f, %.3f]" % (np.tanh(z - zc * se), np.tanh(z + zc * se))
    except Exception:
        return "—"


def ci_or(b, se, alpha=0.05):
    """**优势比 OR 的置信区间** —— logistic 里最该报的东西。

    做法：先在**对数尺度**上算 b 的 CI（Wald），再取指数。
    ⚠ 一定要在对数尺度上算：OR 的抽样分布是偏的（右偏），
      直接对 OR 加减标准误会算出下界为负的荒谬区间。
    """
    try:
        b, se = float(b), float(se)
        if se != se or se <= 0:
            return "—"
        zc = stats.norm.ppf(1 - alpha / 2)
        return "[%.3f, %.3f]" % (np.exp(b - zc * se), np.exp(b + zc * se))
    except Exception:
        return "—"


def cohens_d(a, b):
    """独立样本 Cohen's d（合并标准差）。

    两组的量纲可互换 —— 用标量公式、不用 `.var()`，
    因为 pandas 的 `.var()` 会按列算（传 Series 进来会得到 Series，不是标量）。
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return None
    sp2 = ((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2)
    if sp2 <= 0:
        return None
    return float((a.mean() - b.mean()) / np.sqrt(sp2))


def ci_cohens_d(d, n1, n2, alpha=0.05):
    """Cohen's d 的置信区间（正态近似，样本小时偏窄）。"""
    try:
        d, n1, n2 = float(d), int(n1), int(n2)
        if n1 < 2 or n2 < 2:
            return "—"
        se = np.sqrt(1.0 / n1 + 1.0 / n2 + d * d / (2.0 * (n1 + n2)))
        z = stats.norm.ppf(1 - alpha / 2)
        return "[%.3f, %.3f]" % (d - z * se, d + z * se)
    except Exception:
        return "—"


# --------------------------------------------------------------------------- #
# 最小二乘
# --------------------------------------------------------------------------- #

def design(df, cols, kinds=None):
    """把自变量摊成设计矩阵（**含常数项**）。返回 (X, 名字列表)。

    · 真·分类变量 → 拆哑变量（去掉第一类当参照）
    · 其它（连续 / 有序量表）→ 直接用数值
    ⚠ 有序量表**按分数用**、不拆哑变量：拆了等于丢掉顺序信息、还白吃自由度
      （踩过：价格敏感度 1~5 被拆成 4 个哑变量，VIF 飙到 7 以上）。
    """
    import pandas as pd
    parts, names = [np.ones(len(df))], ["(常数项)"]
    for c in cols:
        s = df[c]
        if kinds and kinds.get(c) == "categorical":
            d = pd.get_dummies(s.astype(str), prefix=c, drop_first=True, dtype=float)
            for col in d.columns:
                parts.append(d[col].values.astype(float))
                names.append(str(col))
        else:
            parts.append(pd.to_numeric(s, errors="coerce").values.astype(float))
            names.append(str(c))
    return np.column_stack(parts), names


def ols(X, y):
    """最小二乘回归（没有 statsmodels，就自己算 —— 公式是标准的，可对照任意教材）。

    ⚠ 返回里的自由度键叫 **`dof`**（不是 `df`）。调用方用错键名会 KeyError，
      而这个键在给系数置信区间时是必需的。踩过一次，所以写在这里提醒。
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    Xd = X if X.shape[1] and X[:, 0].std() == 0 else np.column_stack([np.ones(n), X])
    k = Xd.shape[1]
    XtX = Xd.T @ Xd
    try:
        XtX_inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        XtX_inv = np.linalg.pinv(XtX)
    beta = XtX_inv @ Xd.T @ y
    resid = y - Xd @ beta
    dof = n - k
    if dof <= 0:
        raise ValueError("样本量 %d 撑不住 %d 个自变量，先减少自变量或增加样本" % (n, k - 1))
    sigma2 = float(resid @ resid) / dof
    se = np.sqrt(np.diag(XtX_inv) * sigma2)
    with np.errstate(divide="ignore", invalid="ignore"):
        tvals = beta / se
    pvals = 2 * (1 - stats.t.cdf(np.abs(tvals), dof))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    ss_res = float(resid @ resid)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    adj = 1 - (1 - r2) * (n - 1) / dof if dof > 0 else None
    F = (r2 / (k - 1)) / ((1 - r2) / dof) if k > 1 and r2 < 1 else None
    pF = (1 - stats.f.cdf(F, k - 1, dof)) if F is not None else None
    return {"beta": beta, "se": se, "t": tvals, "p": pvals, "dof": dof,
            "r2": r2, "adj_r2": adj, "F": F, "pF": pF, "n": n, "k": k,
            "resid": resid, "XtX_inv": XtX_inv}


# --------------------------------------------------------------------------- #
# 二元 logistic（IRLS）
# --------------------------------------------------------------------------- #

def encode_binary(s):
    """把因变量编码成 0/1。返回 (y, 类别顺序, 原始取值列表)。

    ⚠ **"哪一类算 1"必须写进报告**：OR 的方向完全取决于它。
      规则（写死、可预期）：取值按升序排，**最后一个算 1**。
      于是 "否/是" → 是=1、"0/1" → 1=1、"未付费/付费" → 付费=1。
    """
    import pandas as pd
    v = s.dropna()
    levels = sorted(set(str(x) for x in v.unique()))
    if len(levels) != 2:
        return None, levels, []
    pos = levels[-1]
    y = (s.astype(str) == pos).astype(float).values
    return y, levels, levels


def logistic(X, y, max_iter=IRLS_MAX_ITER, tol=IRLS_TOL):
    """二元 logistic 回归（IRLS，自己写的 —— 工具箱里没有 statsmodels）。

    算法就是标准的迭代重加权最小二乘：
        p = 1/(1+exp(-Xb)) ；W = p(1-p) ；z = Xb + (y-p)/W ；b ← (X'WX)⁻¹X'Wz
    收敛判据用**系数最大变化量**（比看似然增量直观，也不容易早停）。

    返回：系数、标准误、z、p、**OR 与 OR 的 CI**、对数似然、McFadden 伪 R²、
          AIC/BIC、以及收敛情况。
    """
    from scipy.linalg import solve
    y = np.asarray(y, dtype=float)
    n = len(y)
    k = X.shape[1]
    beta = np.zeros(k)
    converged, it_used, last_step = False, 0, np.inf
    # 迭代前的空模型：只有常数项、用样本比例 —— 拿来算 McFadden 伪 R²
    p0 = float(np.clip(y.mean(), 1e-9, 1 - 1e-9))
    ll_null = float(np.sum(y * np.log(p0) + (1 - y) * np.log(1 - p0)))
    for it in range(max_iter):
        eta = X @ beta
        eta = np.clip(eta, -700, 700)              # 防溢出（logistic 溢出会变 inf/nan）
        p = 1.0 / (1.0 + np.exp(-eta))
        W = np.clip(p * (1 - p), 1e-10, None)
        z = eta + (y - p) / W
        XtWX = X.T @ (X * W[:, None])
        XtWz = X.T @ (W * z)
        try:
            new_beta = solve(XtWX, XtWz, assume_a="sym")
        except Exception:
            new_beta = np.linalg.pinv(XtWX) @ XtWz
        last_step = float(np.max(np.abs(new_beta - beta)))
        beta = new_beta
        it_used = it + 1
        if last_step < tol:
            converged = True
            break
    eta = np.clip(X @ beta, -700, 700)
    p = 1.0 / (1.0 + np.exp(-eta))
    W = np.clip(p * (1 - p), 1e-12, None)
    XtWX = X.T @ (X * W[:, None])
    try:
        cov = np.linalg.inv(XtWX)
    except np.linalg.LinAlgError:
        cov = np.linalg.pinv(XtWX)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        zvals = beta / se
    pvals = 2 * (1 - stats.norm.cdf(np.abs(zvals)))
    ll = float(np.sum(y * np.log(np.clip(p, 1e-12, 1)) +
                      (1 - y) * np.log(np.clip(1 - p, 1e-12, 1))))
    return {"beta": beta, "se": se, "z": zvals, "p": pvals, "p_hat": p,
            "ll": ll, "ll_null": ll_null,
            "pseudo_r2": 1 - ll / ll_null if ll_null < 0 else None,
            "aic": 2 * k - 2 * ll, "bic": k * np.log(n) - 2 * ll,
            "n": n, "k": k, "converged": converged, "iters": it_used,
            "last_step": last_step, "cov": cov}


def lr_test(logit_res, k_full=None):
    """似然比检验：这个模型整体比空模型好多少。返回 (LR, df, p)。"""
    try:
        lr = 2 * (logit_res["ll"] - logit_res["ll_null"])
        dfree = logit_res["k"] - 1
        return float(lr), int(dfree), float(1 - stats.chi2.cdf(lr, max(dfree, 1)))
    except Exception:
        return None, None, None


def classify_table(y, p_hat, cut=0.5):
    """分类表 + 正确率 + 敏感度/特异度。

    ⚠ **正确率会被类别不平衡骗**：正例只占 5% 时，把所有个案都预测成"否"
      也有 95% 正确率。所以必须同时报**基准正确率**（最大类占比），
      让人一眼看出"这个模型到底比瞎猜好多少"。
    """
    y = np.asarray(y, dtype=float)
    pred = (np.asarray(p_hat, dtype=float) >= cut).astype(float)
    tp = int(np.sum((pred == 1) & (y == 1)))
    tn = int(np.sum((pred == 0) & (y == 0)))
    fp = int(np.sum((pred == 1) & (y == 0)))
    fn = int(np.sum((pred == 0) & (y == 1)))
    n = len(y)
    base = max(float((y == 1).mean()), float((y == 0).mean())) if n else None
    acc = (tp + tn) / n if n else None
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn, "n": n,
            "accuracy": acc, "baseline": base,
            "sensitivity": tp / (tp + fn) if (tp + fn) else None,
            "specificity": tn / (tn + fp) if (tn + fp) else None,
            "lift": (acc - base) if (acc is not None and base is not None) else None}


def hosmer_lemeshow(y, p_hat, groups=10):
    """Hosmer-Lemeshow 拟合优度检验。

    H0 = "预测值和实际值没有系统偏差"，所以**p 大才好**（和一般检验相反，容易读错）。
    做法：按预测概率排序、等分成 g 组，比每组的"实际正例数 vs 期望正例数"。

    ⚠ 样本量小或预测概率高度重合时结果不稳；分组数 g 也会影响 p 值。
      所以报告里**必须写出用了几个组**，不能只丢一个 p。
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p_hat, dtype=float)
    n = len(y)
    g = int(min(groups, max(2, n // 5)))
    if g < 2 or n < 10:
        return None, "—", g
    order = np.argsort(p)
    y, p = y[order], p[order]
    chunks = np.array_split(np.arange(n), g)
    hl = 0.0
    rows = []
    for ch in chunks:
        if len(ch) == 0:
            continue
        # ⚠ 去掉常量：np.array_split 给的是数组，`ch[0]` 才是下标
        o1 = float(y[ch].sum())
        e1 = float(p[ch].sum())
        n_i = len(ch)
        rows.append((n_i, o1, e1, o1 / n_i, e1 / n_i))
        for e, o in ((e1, o1), (n_i - e1, n_i - o1)):
            if e > 1e-9:
                hl += (o - e) ** 2 / e
    dfree = g - 2
    pval = float(1 - stats.chi2.cdf(hl, dfree)) if dfree > 0 else None
    return {"hl": float(hl), "df": dfree, "p": pval, "groups": g,
            "rows": rows}, pval, g
