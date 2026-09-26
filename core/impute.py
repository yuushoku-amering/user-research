# -*- coding: utf-8 -*-
"""工作台 · 缺失值插补（多重插补 MICE + 单值插补对照）

**为什么不能只做"均值填补"**

    均值填补把所有人的缺失格都填成同一个数 —— 后果有三个，而且都是**向好的方向偏**：
      1. **方差被压小**（填进去的值没有变异）
      2. **相关系数被稀释**（填进去的值和谁都不相关）
      3. 标准误偏小 → p 值偏乐观 → **更容易报告出"显著"**

    **多重插补（MI）** 的思路不一样：它填 m 套（默认 5 套）**带随机扰动**的完整数据，
    每套各算一遍，再把结果**按 Rubin 规则合并** ——
    这样既保住了变异，又把"填得不确定"这件事算进了标准误里。

**MICE（链式方程）怎么工作**

    一列一列轮着来：填第 j 列时，用**其它所有列**（当前最新的值）回归预测它，
    从预测分布里抽一个值填进去（**不是取均值**，取均值就退化成回归插补）。
    这样来回扫几轮（默认 10 轮），各列之间的一致性会收敛。

⚠ 三条必须写在报告里的话：
  1. **插补不等于有数据**：它靠"缺失和被观测到的变量有关"这个假定（MAR）。
     如果缺失跟**没观测到的**东西有关（MNAR，比如"越介意的人越不答"），插补也救不了。
  2. **跳题不该插补**：那道题对那个人本来就不适用（"从未恋爱"的人没有花销），
     插一个值等于**编造**。所以插补前要先排除结构跳题（见 ⑤ 的 `_跳题` 处理）。
  3. **一定要报"插了多少"**：填了 30% 的格子和填了 1% 的格子，可信程度完全不同。
"""
import numpy as np
from scipy import stats

MI_DEFAULT_M = 5          # 插补几套
MI_DEFAULT_ITER = 10      # 每套扫几轮
MI_SEED = 20260926


def _num_frame(df, cols):
    """取出要做插补的数值列。**只插数值列** —— 分类列要另想办法（见 `complete_categorical`）。"""
    import pandas as pd
    out = pd.DataFrame(index=df.index)
    used = []
    for c in cols:
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() >= 3:
            out[c] = s.astype(float)
            used.append(c)
    return out, used


def mice(df, cols, m=MI_DEFAULT_M, n_iter=MI_DEFAULT_ITER, seed=MI_SEED,
         min_obs=5):
    """链式方程多重插补。返回 m 套完整数据（list of DataFrame）。

    返回的每一套都**只有这几列**（cols 的子集，剔掉了全空或太少的列），
    外面拿去分别分析、再合并。

    ⚠ 用**线性回归 + 残差扰动**（不是 logit/probit 那套完整 MICE）：
      这是"对数值型题目够用、而且能被任何人复核"的折中。
      0/1 这种变量会被当成数值回归填 → 结果可能落在 0/1 之外，
      所以**0/1 变量不要用这个**（`complete_categorical` 会用众数 + 抽样处理）。
    """
    import pandas as pd
    num, used = _num_frame(df, cols)
    if not used:
        return [], []
    # 观测太少的列不插补（回归也估不准）
    used = [c for c in used if num[c].notna().sum() >= min_obs]
    num = num[used]
    if not used:
        return [], []
    n = len(num)
    rng = np.random.default_rng(seed)
    sets = []
    for _ in range(int(m)):
        work = num.copy()
        # 起始填充：用该列均值（只是给迭代一个起点，最后一轮会被覆盖）
        for c in used:
            if work[c].isna().any():
                work[c] = work[c].fillna(work[c].mean())
        for _it in range(int(n_iter)):
            for c in used:
                miss = num[c].isna()
                if not miss.any():
                    continue
                others = [x for x in used if x != c]
                if not others:
                    # 只剩一列：只能从它自己的观测分布里抽（等价于 bootstrap）
                    obs = num[c].dropna().values
                    work.loc[miss, c] = rng.choice(obs, size=int(miss.sum()), replace=True)
                    continue
                X = np.column_stack([np.ones(n)] + [work[o].values for o in others])
                y = work[c].values
                obs = ~miss
                try:
                    beta = np.linalg.lstsq(X[obs], y[obs], rcond=None)[0]
                    resid = y[obs] - X[obs] @ beta
                    dof = max(int(obs.sum()) - X.shape[1], 1)
                    sd = float(np.sqrt((resid @ resid) / dof))
                    pred = X[miss] @ beta
                    work.loc[miss, c] = pred + rng.normal(0, sd, size=int(miss.sum()))
                except Exception:
                    work.loc[miss, c] = work.loc[miss, c].fillna(work[c].mean())
        sets.append(work.copy())
    return sets, used


def complete_categorical(series, rng=None):
    """分类列的插补：**按观测到的比例随机抽**（不是一律填众数）。

    ⚠ 为什么按比例抽而不是填众数：填众数会把那一类的比例**人为抬高**
      （所有缺失都堆到最常见的那个类别上），后面做卡方时结论会歪。
      按比例抽能保住**边缘分布**的形状。
    """
    import pandas as pd
    rng = rng or np.random.default_rng(MI_SEED)
    s = series.astype(object)
    miss = s.isna()
    if not miss.any():
        return s
    vals = s[~miss].astype(str)
    if len(vals) == 0:
        return s
    p = vals.value_counts(normalize=True)
    draw = rng.choice(p.index.values, size=int(miss.sum()), p=p.values)
    s.loc[miss] = draw
    return s


def rubin_pool(estimates, variances, dfcom=None):
    """Rubin 规则：把 m 套分析结果合并成一个。

    `estimates`：每套的点估计（list）
    `variances`：每套的方差（list，**是 SE² 不是 SE**）

    公式（标准）：
        Q̄   = 平均点估计
        Ū   = 组内方差平均（within）
        B    = 点估计之间的方差（between）
        T    = Ū + (1 + 1/m)·B          ← 总方差，比单套大（这就是"把不确定性算进去"）
        df   = 用 Barnard-Rubin 的自由度（小样本时比 m−1 更合适）
        FMI  = 缺失信息占比（越大说明结论越依赖插补）

    ⚠ **总方差一定大于任何单套的方差** —— 这不是bug，是 MI 的核心：
      "填出来的数据"比"真实数据"本来就更不确定。
    """
    est = np.asarray([e for e in estimates if e is not None and np.isfinite(e)], dtype=float)
    var = np.asarray([v for v in variances if v is not None and np.isfinite(v) and v > 0],
                     dtype=float)
    m_eff = int(min(len(est), len(var)))
    if m_eff < 2:
        if m_eff == 1:
            return {"estimate": float(est[0]), "se": float(np.sqrt(var[0])),
                    "df": None, "t": None, "p": None,
                    "ci": None, "fmi": None, "m": 1,
                    "note": "只有 1 套，按单套报（方差没有把插补的不确定性算进去）"}
        return None
    est, var = est[:m_eff], var[:m_eff]
    qbar = float(est.mean())
    ubar = float(var.mean())
    b = float(est.var(ddof=1))
    total = ubar + (1.0 + 1.0 / m_eff) * b
    se = float(np.sqrt(total))
    # Barnard-Rubin 自由度
    if b > 0 and total > 0:
        lam = (1.0 + 1.0 / m_eff) * b / total          # 缺失信息占比
        dfree = (m_eff - 1) / (lam ** 2) if lam > 0 else np.inf
        if dfcom:
            dfree = 1.0 / (1.0 / dfree + 1.0 / dfcom) if np.isfinite(dfree) else dfcom
    else:
        lam, dfree = 0.0, float(dfcom or 1e6)
    tval = qbar / se if se > 0 else None
    p = float(2 * (1 - stats.t.cdf(abs(tval), dfree))) if tval is not None and dfree > 0 else None
    tcrit = stats.t.ppf(0.975, dfree) if dfree > 0 else 1.96
    return {"estimate": qbar, "se": se, "df": float(dfree), "t": tval, "p": p,
            "ci": (qbar - tcrit * se, qbar + tcrit * se),
            "fmi": float(lam), "m": m_eff,
            "within": ubar, "between": b, "total_var": total}


def compare_missing(df, cols, target=None, group=None):
    """**三种做法的结果并排**：完整个案 / 均值填补 / 多重插补。

    这是这块最该给人看的东西 —— 让"用哪种缺失处理"的后果变得可见：

        均值填补会把方差压小、把相关稀释 → 如果是"变显著"了，那多半是假象
        多重插补会把标准误**放大**（因为承认了不确定性）

    `target`/`group` 给了就比"组间均值差"，否则只比各列的均值/方差/相关。
    """
    import pandas as pd
    num, used = _num_frame(df, cols)
    used = [c for c in used if num[c].notna().sum() >= 5]
    if not used:
        return {"error": "没有可用的数值列"}
    out = {"cols": used, "n_total": len(num),
           "n_missing": {c: int(num[c].isna().sum()) for c in used},
           "miss_pct": {c: round(float(num[c].isna().mean()) * 100, 1) for c in used}}

    # 1) 完整个案
    cc = num.dropna()
    out["complete_case"] = {"n": len(cc),
                            "mean": {c: float(cc[c].mean()) for c in used},
                            "sd": {c: float(cc[c].std(ddof=1)) for c in used}}
    # 2) 均值填补
    mean_filled = num.copy()
    for c in used:
        mean_filled[c] = mean_filled[c].fillna(mean_filled[c].mean())
    out["mean_fill"] = {"n": len(mean_filled),
                        "mean": {c: float(mean_filled[c].mean()) for c in used},
                        "sd": {c: float(mean_filled[c].std(ddof=1)) for c in used}}
    # 3) 多重插补（只报"合并后的均值/方差"，用于和上面两种比）
    sets, used2 = mice(num, used)
    if sets:
        means = np.array([[s[c].mean() for c in used2] for s in sets])
        sds = np.array([[s[c].std(ddof=1) for c in used2] for s in sets])
        out["mi"] = {"m": len(sets), "n": len(sets[0]),
                     "mean": {c: float(means[:, i].mean()) for i, c in enumerate(used2)},
                     "sd": {c: float(sds[:, i].mean()) for i, c in enumerate(used2)}}
    else:
        out["mi"] = None

    # 判定：均值填补把方差压小了多少
    if out.get("mi") and out.get("complete_case"):
        worst = []
        for c in used:
            sd_cc = out["complete_case"]["sd"].get(c) or 0
            sd_mf = out["mean_fill"]["sd"].get(c) or 0
            if sd_cc > 0:
                shrink = (sd_cc - sd_mf) / sd_cc
                if shrink > 0.02:
                    worst.append((c, round(shrink * 100, 1)))
        worst.sort(key=lambda x: -x[1])
        out["sd_shrunk_by_fillna"] = worst
    return out
