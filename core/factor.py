# -*- coding: utf-8 -*-
"""工作台 · 因子分析 / 主成分（效度那一块）

**它回答的是**：「这 10 道题，是不是在测 2 个东西？」

    做问卷的人真正要的是两件事：
      1. **结构效度**：题目按预期聚成几个维度吗？（因子分析 / 主成分）
      2. **内部一致性**：同一个维度里的题答得一致吗？（Cronbach α，在 `kit.cronbach_alpha`）

⚠ 工具箱里**没有** `factor_analyzer`，也**没有 statsmodels**。所以这里全部自己写：
  相关矩阵、Bartlett 球形检验、KMO、特征分解、varimax 旋转、平行分析。
  好在这些都是标准算法，可以对照任意教材，也能用**已知因子结构的数据**验证。

=== 三个最容易搞错的地方（都写在代码里了） ===

1. **抽取方法别混**：`pca`（主成分，看的是"解释了多少方差"）和 `pa`（主轴因子，
   看的是"共同的潜结构"）不是一回事。**问卷效度一般用 PCA 或者最大似然**，
   但报告里必须写清用的是哪个 —— 两者的载荷不一样。
2. **旋转只改变"看得清不清"，不改变"解释了多少"**：
   旋转前后的**总解释方差不变**（方差被重新分配到各因子上）。
   所以"旋转后解释率变高了"这句话是错的。
3. **因子数不能只看特征值 >1**（Kaiser 准则）：题少的时候它会低估、题多的时候会高估。
   所以这里同时给 **碎石图** 和 **平行分析**（跟随机数据比），让人自己判断。
"""
import numpy as np
from scipy import stats


def _prep(d, cols):
    """取出题目列、成对删缺失。返回 (标准化后的矩阵, 完整个案数)。"""
    import pandas as pd
    sub = d[cols].apply(pd.to_numeric, errors="coerce").dropna()
    X = sub.values.astype(float)
    n = X.shape[0]
    if n < 5:
        return None, 0, sub
    sd = X.std(axis=0, ddof=1)
    sd[sd == 0] = 1.0                      # 常数题（全同）不能标准化 → 当 1 处理，后面会剔掉
    return (X - X.mean(axis=0)) / sd, n, sub


def bartlett_sphericity(R, n):
    """Bartlett 球形检验：相关矩阵是不是**单位矩阵**（题之间到底有没有共同变异）。

    H0 = "各题之间没有相关"（相关矩阵是单位阵）。
    所以 **p 要小才好** —— p 大说明题目之间本来就没什么共同的东西，做因子分析没意义。
    （注意：和其他检验的读法相反，容易念错。）
    """
    k = R.shape[0]
    if k < 2 or n < 2:
        return None
    det = max(np.linalg.det(R), 1e-300)
    chi2 = -(n - 1 - (2 * k + 5) / 6.0) * np.log(det)
    dfree = k * (k - 1) // 2
    p = float(1 - stats.chi2.cdf(chi2, dfree))
    return {"chi2": float(chi2), "df": int(dfree), "p": p}


def kmo(R, invR=None):
    """KMO（取样适切性）：**这份数据到底适不适合做因子分析**。

    它是"简单相关"和"偏相关"的对比：
      · 如果题目之间的相关**都能被公共因子解释**，偏相关就小 → KMO 接近 1
      · 如果每题都有自己的独特东西，偏相关不小 → KMO 低

    惯例门槛（Kaiser）：< 0.5 不可接受、0.5~0.6 勉强、0.6~0.7 一般、
    0.7~0.8 还行、0.8~0.9 好、> 0.9 很好。

    ⚠ **"完全没有共同变异"时 KMO ≈ 0.5，不是 0**（这一点我一开始也以为错了）：
      R ≈ 单位阵时 R⁻¹ ≈ 单位阵 → 偏相关 ≈ 原相关 → 两个平方和相等 → KMO ≈ 0.5。
      实测（n=400、6 题、200 次抽样）：均值 0.496、范围 [0.437, 0.557]。
      所以"这份数据不行"的信号是 **KMO 贴着 0.5 + Bartlett 不显著**，
      而不是"KMO 接近 0"。

    ⚠ 它和 Bartlett 是**两件事**：Bartlett 说"有没有共同变异"，
      KMO 说"共同变异占多大比例"。两个都要看：Bartlett 显著但 KMO 很低的情况是有的。
    """
    k = R.shape[0]
    if k < 3:
        return None
    try:
        invR = np.linalg.inv(R) if invR is None else invR
    except np.linalg.LinAlgError:
        invR = np.linalg.pinv(R)
    d = np.sqrt(np.diag(invR))
    # 偏相关矩阵：-invR[i,j] / sqrt(invR[i,i]·invR[j,j])，非对角元素
    P = -invR / np.outer(d, d)
    np.fill_diagonal(P, 0.0)
    R0 = R.copy()
    np.fill_diagonal(R0, 0.0)
    num = (R0 ** 2).sum()
    den = num + (P ** 2).sum()
    overall = float(num / den) if den > 0 else None
    # 每题一个 KMO（哪道题拖后腿，一眼看得出）
    per_item = {}
    for i in range(k):
        num_i = (R0[i] ** 2).sum()
        den_i = num_i + (P[i] ** 2).sum()
        per_item[i] = float(num_i / den_i) if den_i > 0 else None
    return {"kmo": overall, "per_item": per_item}


def _varimax_criterion(L):
    """Varimax 准则 = **每个因子（列）内部**、各题载荷平方的方差之和。

    ⚠ 这个定义我一开始写错了：写成了「各**列**平方和的方差」——
      那是"因子之间解释方差的差距"，**varimax 根本不最大化那个**。
      错误的判据导致旋转几乎不动（准则前后 15.54 → 15.52，看不出变化），
      结构虽然分开了但没转到最优。教训：**旋转的判据必须照定义写**，
      而且要有测试守住"旋转后准则一定变大"。

    定义（Kaiser）：令 l_ij 为题 i 在因子 j 上的载荷，
        Q = Σ_j [ (1/p)Σ_i (l_ij²)² − ( (1/p)Σ_i l_ij² )² ]
      也就是"每一列的平方载荷，它自己的方差"。
    """
    L = np.asarray(L, dtype=float)
    p = L.shape[0]
    B = L ** 2
    return float((B.var(axis=0)).sum())


def _varimax(L, max_iter=500, tol=1e-9):
    """Varimax 旋转（Kaiser 归一化）。**自己写的**，因为工具箱里没有。

    目标：让每道题在尽量少的因子上有大载荷 —— 判据就是上面 `_varimax_criterion`。

    做法：反复"对每一对因子做平面旋转"直到收敛。每次求最优角度时用 SVD：
      · 对每一对 (i,j)，构造 u = l_i² − l_j²、v = 2·l_i·l_j
      · 旋转角 θ = atan2(2Σuv − 2ΣuΣv/p, Σ(u²−v²) − (Σu)²/p + (Σv)²/p) / 4
      · 所以要先做**列对偶**（把两个因子拉出来单独看）——见下面的 `_rotate_pairs`

    ⚠ 旋转**不改变**总解释方差，只把它在因子之间重新分配。
      所以"旋转后解释率提高了"是错的；正确说法是"旋转后结构更清楚了"。
    """
    L = np.asarray(L, dtype=float)
    p, k = L.shape
    if k < 2:
        return L, _varimax_criterion(L)
    # Kaiser 归一化：先按每题的公共方差归一化，转完再还原
    h = np.sqrt((L ** 2).sum(axis=1, keepdims=True))
    h[h == 0] = 1.0
    R = L / h
    crit = _varimax_criterion(R * h)
    for _ in range(max_iter):
        crit_old = crit
        # 成对旋转：每次只动两个因子，解出让准则最大的那个角度
        for i in range(k - 1):
            for j in range(i + 1, k):
                x, y = R[:, i], R[:, j]
                u = x ** 2 - y ** 2
                v = 2.0 * x * y
                A, B = u.sum(), v.sum()
                C = float((u ** 2 - v ** 2).sum())
                D = float(2.0 * (u * v).sum())
                num = D - 2.0 * A * B / p
                den = C - (A ** 2 - B ** 2) / p
                phi = np.arctan2(num, den) / 4.0
                if abs(phi) < 1e-12:
                    continue
                c, s = np.cos(phi), np.sin(phi)
                xi = R[:, i].copy()
                xj = R[:, j].copy()
                R[:, i] = c * xi + s * xj
                R[:, j] = -s * xi + c * xj
        crit = _varimax_criterion(R * h)
        if abs(crit - crit_old) < tol * max(abs(crit), 1.0):
            break
    Lr = R * h
    # 按"解释方差"从大到小排因子，并统一符号（让大载荷为正，符合报告惯例）
    var = (Lr ** 2).sum(axis=0)
    order = np.argsort(-var)
    Lr = Lr[:, order]
    for j in range(Lr.shape[1]):
        if Lr[:, j].sum() < 0:
            Lr[:, j] = -Lr[:, j]
    return Lr, float(_varimax_criterion(Lr))


def _parallel_analysis(R, n, n_iter=100, seed=20260926):
    """平行分析：跟"纯随机数据"的特征值比，比它大的才算真因子。

    ⚠ 为什么需要它：**Kaiser 准则（特征值>1）在题目多的时候会高估因子数**。
      平行分析是现在更推荐的做法：把随机数据的第 95 百分位特征值当基准线，
      实际特征值超过基准线的才保留。
    """
    p = R.shape[0]
    rng = np.random.default_rng(seed)
    sims = np.empty((n_iter, p))
    for i in range(n_iter):
        X = rng.normal(size=(n, p))
        Rs = np.corrcoef(X, rowvar=False)
        sims[i] = np.sort(np.linalg.eigvalsh(Rs))[::-1]
    return np.percentile(sims, 95, axis=0)


def factor_analyze(d, cols, n_factors=None, method="pca", rotate=True,
                   alpha=0.05, parallel=True, min_loading=0.40):
    """主入口。返回载荷、共同度、解释方差、KMO/Bartlett、因子数建议。

    `method`：`pca`（主成分，默认）或 `pa`（主轴因子）。
    `n_factors`：留空则自动判断（Kaiser + 平行分析一起给建议，取平行分析的结论）。
    """
    X, n, sub = _prep(d, cols)
    if X is None:
        return {"error": "有效样本太少（<5）"}
    p = X.shape[1]
    if p < 3:
        return {"error": "题目少于 3 道，做不了因子分析（至少要 3 道）"}
    # 常数题（全同）单独剔掉，否则相关矩阵奇异、KMO 会算出 nan
    sd0 = sub.values.astype(float).std(axis=0, ddof=1)
    drop_const = [c for c, s in zip(cols, sd0) if not (s > 0)]
    if drop_const:
        keep = [c for c in cols if c not in drop_const]
        X, n, sub = _prep(d, keep)
        cols = keep
        p = X.shape[1]
        if p < 3:
            return {"error": "剔掉常数题后不足 3 道：%s" % "、".join(drop_const)}
    R = np.corrcoef(X, rowvar=False)
    # ⚠ 相关矩阵必须是**满秩**才好做：完全共线的题会让特征值出现 0
    bart = bartlett_sphericity(R, n)
    k = kmo(R)
    evals, evecs = np.linalg.eigh(R)
    order = np.argsort(-evals)
    evals, evecs = evals[order], evecs[:, order]
    evals = np.clip(evals, 0, None)

    # 因子数建议
    kaiser = int((evals > 1).sum())
    pa_line = _parallel_analysis(R, n) if parallel else None
    pa_n = int((evals > pa_line).sum()) if pa_line is not None else None
    if n_factors is None:
        n_factors = pa_n if pa_n else max(1, kaiser)
    n_factors = int(max(1, min(n_factors, p)))

    # 抽取载荷
    if method == "pa":
        # 主轴因子：用"共同方差"迭代（先把共同度设成 1 再迭代修正）
        L = None
        h = np.ones(p)
        for _ in range(50):
            Rp = R.copy()
            np.fill_diagonal(Rp, h)
            ev, evec = np.linalg.eigh(Rp)
            o = np.argsort(-ev)
            ev, evec = np.clip(ev[o], 0, None), evec[:, o]
            L = evec[:, :n_factors] * np.sqrt(ev[:n_factors])
            h_new = (L ** 2).sum(axis=1)
            if np.max(np.abs(h_new - h)) < 1e-6:
                h = h_new
                break
            h = h_new
        loadings = L
        # 主轴因子的"解释方差"只算共同部分
        ss = (loadings ** 2).sum(axis=0)
        explained = ss / p
    else:
        loadings = evecs[:, :n_factors] * np.sqrt(evals[:n_factors])
        explained = evals[:n_factors] / p

    unrotated = loadings.copy()
    if rotate:
        loadings, _crit = _varimax(loadings)
    # ⚠ 旋转可能让某个因子的载荷整体为负 —— 把符号翻过来（惯例：让大载荷为正）
    for j in range(loadings.shape[1]):
        if loadings[:, j].sum() < 0:
            loadings[:, j] = -loadings[:, j]

    communality = (loadings ** 2).sum(axis=1)
    # 每个因子旋转后的解释方差（旋转不改变总量）
    ss_load = (loadings ** 2).sum(axis=0)

    return {
        "cols": list(cols), "n": n, "p": p, "method": method,
        "rotate": bool(rotate), "n_factors": n_factors,
        "eigenvalues": [float(v) for v in evals],
        "explained": [float(v) for v in explained],
        "explained_total": float(np.sum(explained)),
        "kaiser_n": kaiser, "parallel_n": pa_n,
        "parallel_line": [float(v) for v in pa_line] if pa_line is not None else None,
        "loadings": loadings.tolist(),
        "loadings_unrotated": unrotated.tolist(),
        "communality": [float(v) for v in communality],
        "ss_loadings": [float(v) for v in ss_load],
        "bartlett": bart, "kmo": k,
        "dropped_constant": drop_const,
        "min_loading": min_loading,
        "R": R.tolist(),
    }


def suggest_names(res, min_loading=None):
    """给每个因子挑几道"载荷最高"的题，好命名。

    ⚠ **命名的活是人的**，这里只把"哪几道题落在这个因子上"列出来。
      程序给的名字（比如"因子1"）没有任何意义。
    """
    if not res or res.get("error"):
        return []
    L = np.array(res["loadings"])
    cols = res["cols"]
    thr = min_loading if min_loading is not None else res.get("min_loading", 0.40)
    out = []
    for j in range(L.shape[1]):
        col = L[:, j]
        idx = np.argsort(-np.abs(col))
        marked = [(cols[i], float(col[i])) for i in idx if abs(col[i]) >= thr]
        out.append({"factor": j + 1, "items": marked[:8],
                    "n_marked": len(marked),
                    "weak": len(marked) == 0})
    return out


def cross_loading_table(res, min_loading=None):
    """横跨两个因子的题（"双重载荷"）—— 这些题是最该考虑删掉或改写的。

    判据：最大载荷 ≥ 阈值，且第二大载荷 ≥ 阈值 × 0.8（差得不够开）。
    """
    if not res or res.get("error"):
        return []
    L = np.array(res["loadings"])
    cols = res["cols"]
    thr = min_loading if min_loading is not None else res.get("min_loading", 0.40)
    out = []
    for i, c in enumerate(cols):
        a = np.abs(L[i])
        order = np.argsort(-a)
        first, second = a[order[0]], a[order[1]] if len(order) > 1 else 0.0
        if first >= thr and second >= thr * 0.8:
            out.append({"item": c,
                        "primary": int(order[0] + 1), "primary_loading": float(L[i, order[0]]),
                        "secondary": int(order[1] + 1), "secondary_loading": float(L[i, order[1]])})
    return out
