# -*- coding: utf-8 -*-
"""工作台 · 方法选择（**真源只有这一份**）

**这个模块存在的唯一理由：让"推荐方法"和"实际算的时候选的方法"永远一致。**

    踩过的坑：② 和 ②b 各自写过一遍「谁是访谈者」的判定，两边规则不一致，
    于是出现「② 把提问排掉了、②b 又把它当受访者算进覆盖人数」——**而且从不报错**。
    方法选择是更要紧的地方：如果推荐卡说"用 Mann-Whitney"、引擎却跑了 t 检验，
    研究员会照着推荐卡写进论文，而数字是另一个方法算的。

    所以：判定写成**纯函数**（不吃 ctx、不碰文件），⑥ 的引擎和推荐卡**调同一个**。
    `_statstest.py` 里有一条断言专门守这件事：两边对同一个输入必须给出同一个方法。

**它只做推荐，不做决定。** 返回结构里带 `why_not`（为什么不用另一个），
因为研究员要知道"被排除的理由"才算真的看懂了推荐。
"""

# 方法 key → 中文名（引擎和界面共用，别再各写一份）
METHOD_CN = {
    "t": "独立样本 t 检验",
    "welch": "Welch t 检验（方差不齐）",
    "anova": "单因素方差分析 + Tukey 事后",
    "anova_welch": "方差分析（方差不齐，谨慎解释）",
    "mannwhitney": "Mann-Whitney U（非参数）",
    "kruskal": "Kruskal-Wallis（非参数）",
    "pearson": "Pearson 相关",
    "spearman": "Spearman 秩相关",
    "kendall": "Kendall 秩相关",
    "ols": "多元线性回归（最小二乘）",
    "chi2": "卡方独立性检验",
    "describe": "描述统计",
    # 被试内那一族（2026-09-26 加）
    "paired_t": "配对样本 t 检验",
    "wilcoxon": "Wilcoxon 符号秩检验（配对非参数）",
    "one_t": "单样本 t 检验",
    "partial": "偏相关（扣掉控制变量）",
    "logistic": "二元 logistic 回归",
    "mediation": "中介分析（X → M → Y）",
    "moderation": "调节分析（X 的作用随 W 变化）",
}

# 每条方法的"它假设什么"—— 推荐卡里要一并写出来（不然推荐等于黑箱）
ASSUMES = {
    "t": "因变量近似正态、两组方差差不多",
    "welch": "因变量近似正态（不要求方差相等）",
    "anova": "因变量近似正态、各组方差差不多",
    "anova_welch": "因变量近似正态（不要求方差相等，但解释要谨慎）",
    "mannwhitney": "只要求两组独立；比的是秩次/中位数",
    "kruskal": "只要求各组独立；比的是秩次/中位数",
    "pearson": "两个变量**线性**相关、双变量近似正态",
    "spearman": "只要求**单调**关系（不要求正态、不要求线性）",
    "kendall": "只要求单调；小样本或并列值多时比 Spearman 更稳",
    "ols": "线性、残差独立同分布、无严重共线",
    "chi2": "期望频数 <5 的格子不超过 20%",
    "describe": "无假设",
    "paired_t": "**差值**近似正态（不是原始两列各自正态）—— 配对设计的前提落在差值上",
    "wilcoxon": "只要求差值**关于 0 对称**（比「差值正态」弱得多）",
    "one_t": "这一列近似正态（或样本够大）",
    "partial": "残差近似正态、且控制变量与 x/y 是线性关系",
    "logistic": "各观测独立；不需要**因变量**正态（它只有 0/1 两类）；"
                "但要小心**完全分离**（某个自变量能把两类完美分开时系数会爆）",
    "mediation": "三条回归各自的线性假定；**而且要看时间先后**——"
                 "中介是「X 通过 M 影响 Y」，横截面数据分不出方向",
    "moderation": "线性 + 交互项；样本要够（交互项很吃样本，比只看主效应需要的样本多得多）",
}


def pick_compare(k, all_normal=True, equal_var=True):
    """组间差异该用什么方法。**这就是 ⑥ 引擎里原来那段判定的唯一实现。**

    k      : 组数
    all_normal : 各组是否都近似正态（前提检验结论）
    equal_var  : 方差是否齐（Levene 结论）

    返回 {"method", "why", "why_not", "assumes"}。
    """
    k = int(k or 0)
    if k < 2:
        return {"method": None, "why": "少于两组，没法比",
                "why_not": [], "assumes": ""}
    if all_normal and equal_var:
        m = "t" if k == 2 else "anova"
        if k == 2:
            wn = "不用 Welch：两组方差齐（Levene 不显著），Welch 只在方差不齐时才更稳"
        else:
            wn = "不用 Kruskal-Wallis：前提满足时参数方法检验力更高，没必要用秩方法"
    elif all_normal and not equal_var:
        m = "welch" if k == 2 else "anova_welch"
        wn = ("不用普通 t 检验/方差分析：方差不齐（Levene 显著），"
              "等方差版本的标准误算小了、p 值会偏乐观")
    else:
        m = "mannwhitney" if k == 2 else "kruskal"
        wn = ("不用 t 检验/方差分析：正态性不满足。"
              "大样本下 t 对正态偏离其实比较耐受，但既然前提没过，"
              "秩方法更稳妥——代价是检验力略低（真效应小时更不容易检出）")
    return {"method": m, "why": _compare_why(k, all_normal, equal_var),
            "why_not": [wn], "assumes": ASSUMES.get(m, "")}


def _compare_why(k, all_normal, equal_var):
    bits = ["%d 组" % k]
    bits.append("正态性%s" % ("满足" if all_normal else "不满足"))
    bits.append("方差%s" % ("齐" if equal_var else "不齐"))
    return "、".join(bits) + " → 按判定表选"


def pick_relate(n_iv=1, normal_xy=True, has_categorical_iv=False, dv_binary=False):
    """关系/预测该用什么方法。

    n_iv=1 → 相关；n_iv>=2 → 多元回归
    **dv_binary=True → 二元 logistic 回归**（因变量只有两类）

    ⚠ 为什么因变量是两类就必须换模型：线性回归的预测值可以超出 [0,1]、
      残差也不可能是正态的（因变量只有两个值）。拿 OLS 去拟合 0/1 因变量，
      系数虽然"能算出来"，但**标准误和 p 值都是错的**——这是很常见的一处硬用。
    """
    n_iv = int(n_iv or 0)
    if n_iv == 0:
        return {"method": None, "why": "没给自变量", "why_not": [], "assumes": ""}
    if dv_binary:
        return {"method": "logistic",
                "why": "因变量**只有两类**（0/1）→ 二元 logistic 回归（%d 个自变量）" % n_iv,
                "why_not": [
                    "**不用线性回归**：预测值会超出 0~1，残差也不可能正态 → "
                    "系数看着能算，但标准误和 p 值都是错的",
                    "不看 R²：logistic 没有 R²，看的是 McFadden 伪 R²、"
                    "以及**分类正确率比「瞎猜最大类」好多少**",
                ],
                "assumes": ASSUMES["logistic"]}
    if n_iv >= 2:
        return {"method": "ols", "why": "%d 个自变量 + 连续因变量 → 多元线性回归" % n_iv,
                "why_not": ["不用逐个做相关：那样看不出「控制了其它变量之后」各自的作用"
                            + ("，而你有分类自变量，更需要一起放进模型" if has_categorical_iv else "")],
                "assumes": ASSUMES["ols"]}
    if n_iv == 1:
        m = "pearson" if normal_xy else "spearman"
        wn = ("不用 Pearson 当主报：正态性不满足（它受极端值影响也大）"
              if not normal_xy else
              "不用 Spearman 当主报：两个变量都近似正态时，Pearson 对**线性**关系更敏感")
        return {"method": m,
                "why": "单个自变量 + 连续因变量 → 相关（主报 %s）" % METHOD_CN[m],
                "why_not": [wn,
                            "**三个系数都会报出来**（Pearson/Spearman/Kendall）——"
                            "它们回答的是不同问题，差多少本身就是结论的一部分"],
                "assumes": ASSUMES[m]}
    return {"method": None, "why": "没给自变量", "why_not": [], "assumes": ""}


def pick_assoc(n_levels_a=0, n_levels_b=0, cells_expected_lt5_ratio=None):
    """两个分类变量该用什么方法。"""
    ok = cells_expected_lt5_ratio is None or cells_expected_lt5_ratio <= 0.20
    if not ok:
        return {"method": "chi2",
                "why": "两个分类变量 → 卡方，但**期望频数 <5 的格子超过 20%%**，结论不稳",
                "why_not": ["小格子太多时不该直接报卡方：应先把小类合并，"
                            "或改用 Fisher 精确检验（2×2 时）"],
                "assumes": ASSUMES["chi2"], "unreliable": True}
    return {"method": "chi2", "why": "两个分类变量 → 交叉表 + 卡方独立性检验",
            "why_not": ["不拿「哪个格子贡献最大」当结论：那是事后挑格子，属于探索"],
            "assumes": ASSUMES["chi2"]}


def pick(kind, **kw):
    """统一入口：`pick("compare", k=4, all_normal=False, equal_var=False)`。"""
    kind = (kind or "").strip()
    if kind == "compare":
        return pick_compare(kw.get("k"), kw.get("all_normal", True),
                            kw.get("equal_var", True))
    if kind == "within":
        return pick_within(kw.get("has_two_cols", True),
                           kw.get("diff_normal", True),
                           kw.get("n_zero_ratio"))
    if kind == "relate":
        if int(kw.get("n_controls") or 0) > 0 and int(kw.get("n_iv") or 1) <= 1 \
                and not kw.get("dv_binary"):
            return pick_partial(int(kw["n_controls"]), kw.get("normal_xy", True))
        return pick_relate(kw.get("n_iv", 1), kw.get("normal_xy", True),
                           kw.get("has_categorical_iv", False),
                           kw.get("dv_binary", False))
    if kind == "assoc":
        return pick_assoc(kw.get("n_levels_a", 0), kw.get("n_levels_b", 0),
                          kw.get("cells_expected_lt5_ratio"))
    return {"method": "describe",
            "why": "没有明确的比较/预测目标 → 先做描述统计，看清分布再说",
            "why_not": ["不硬套检验：没有假设就没有可检验的东西"],
            "assumes": ASSUMES["describe"]}


def pick_within(has_two_cols=True, diff_normal=True, n_zero_ratio=None):
    """**被试内**（同一批人的前后测 / 配对测量）该用什么方法。

    和 `pick_compare` 的关键区别：**前提检验落在"差值"上，不是原始两列**。
      · 前后测两列各自偏得厉害、但**差值**近似正态 → 配对 t 完全没问题
      · 只看"两列是否各自正态"就下结论，会把该用配对 t 的场合误判成非参数
        （这是很常见的一处误用）

    `n_zero_ratio`：差值恰好为 0 的比例。打平多的时候符号秩的检验力会明显下降，
    这时要在推荐里点出来（不是换方法，而是提醒"别把不显著读成没关系"）。
    """
    if not has_two_cols:
        return {"method": "one_t",
                "why": "只有一列 + 一个要比较的参照值 → 单样本 t 检验",
                "why_not": ["不做配对：配对要求同一批人测了两次（或可一一对应的两列），"
                            "你这里只有一列"],
                "assumes": ASSUMES["one_t"]}
    m = "paired_t" if diff_normal else "wilcoxon"
    wn = ("不用 Wilcoxon：差值的正态性满足时，配对 t 检验力更高"
          if diff_normal else
          "不用配对 t：**差值**偏离正态。注意前提落在差值上，"
          "原始两列各自不正态并不构成问题")
    why_not = [wn]
    if n_zero_ratio is not None and n_zero_ratio >= 0.20:
        why_not.append("⚠ 有 %.0f%% 的配对前后完全一样（打平）—— 符号秩会丢掉它们、"
                       "检验力下降。不显著时别直接读成「没变化」，"
                       "可以再看符号检验或配对 t 作对照" % (n_zero_ratio * 100))
    return {"method": m,
            "why": "同一批人测了两次（配对数据）→ %s；前提看**差值**" % METHOD_CN[m],
            "why_not": why_not, "assumes": ASSUMES.get(m, "")}


def pick_partial(n_controls=1, normal=True):
    """偏相关（有控制变量时）。"""
    if n_controls <= 0:
        return pick_relate(1, normal)
    return {"method": "partial", "why": "扣掉 %d 个控制变量之后看 x 与 y 还剩多少关系"
            % n_controls,
            "why_not": ["不直接报普通相关：那会把控制变量造成的共同变化算成「两者有关」"],
            "assumes": ASSUMES["partial"]}


def pick_mediated(has_mediator=False, has_moderator=False, n=None):
    """中介 / 调节该用哪个。

    ⚠ 这两件事**经常被混为一谈**，但它们是不同的问题：
      · 调节：X 的作用**随 W 变化**（问"在什么条件下更强/更弱"）
      · 中介：X **通过 M** 影响 Y（问"为什么/经由什么"）

    填了中介变量就做中介，填了调节变量就做调节；两个都填就两个都做（分开报）。
    """
    out = []
    if has_mediator:
        out.append({"method": "mediation",
                    "why": "填了「中介变量」→ X 经由 M 影响 Y，间接效应 a×b 用 bootstrap 取区间",
                    "why_not": [
                        "**不用 Sobel 检验**：间接效应 a×b 的抽样分布不是正态的，"
                        "Sobel 假设正态 → p 值和区间都偏",
                        "⚠ 它只说明**统计上**存在间接路径；"
                        "「X 真的导致 Y」要靠时间先后或实验设计，不是靠这个检验",
                    ],
                    "assumes": ASSUMES["mediation"]})
    if has_moderator:
        out.append({"method": "moderation",
                    "why": "填了「调节变量」→ X 对 Y 的作用随 W 变化，看**交互项**",
                    "why_not": [
                        "**交互项要先对中**（centering）：不对中的话 X 的系数变成"
                        "「W=0 时 X 的作用」，而 W=0 常常没有实际意义",
                        "⚠ 交互项很吃样本：主效应显著不保证交互项能检出来",
                    ],
                    "assumes": ASSUMES["moderation"]})
    if not out:
        return None
    return out


def override_compare(k, want):
    """研究员在前提检验那个检查点上**改主意**时用。

    `want` 取 "param"（坚持参数方法）或 "nonparam"（换秩方法）。

    ⚠ 为什么要单独抽出来：引擎里原来自己写了两行
      `use = "t" if k == 2 else "anova"` / `use = "mannwhitney" if k == 2 else "kruskal"`——
      那就是**第二份判定**，和 `pick_compare` 的对应关系只是"碰巧一致"。
      哪天给某条规则加个特例（比如 3 组且方差不齐时默认 Welch），
      这两行不会跟着变，于是"推荐的"和"覆盖后的"指向不同方法，而且没人会发现。
    """
    k = int(k or 0)
    if want == "param":
        return "t" if k == 2 else "anova"
    return "mannwhitney" if k == 2 else "kruskal"


def truth_table_compare():
    """把"什么情况用哪个方法"列成一张表（给界面/文档做单一样本）。

    ⚠ 它的意义：**判定规则只有一份**。文档、界面说明、测试的期望值，
       都从这张表来 —— 就不会出现"说明书写 t 检验、代码跑 Welch"那种事。
    """
    out = []
    for k in (2, 3):
        for nrm in (True, False):
            for eq in (True, False):
                r = pick_compare(k, nrm, eq)
                out.append({"组数": k, "正态": nrm, "方差齐": eq,
                            "方法": r["method"], "中文名": METHOD_CN.get(r["method"], ""),
                            "为什么不用另一个": (r.get("why_not") or [""])[0]})
    return out


def recommend_for(kind, data_summary=None):
    """**推荐卡**的统一入口：给一个"问题类型 + 数据长什么样"，回一段能看的推荐。

    `data_summary` 是轻量摘要（只有引擎知道数据长什么样），支持的键：
      · n_rows        样本量
      · n_levels      分了几组（compare）
      · n_iv          自变量个数（relate）
      · normal        正态性是否满足（None = 还没测）
      · equal_var     方差是否齐（None = 还没测）
      · cells_lt5_ratio  期望频数<5 的格子占比（assoc）

    ⚠ 它和引擎**调同一个 `pick()`**，所以推荐的方法与真正跑的方法不会分叉。
    正态性/方差齐还没测时（None），推荐里会写明"这是**先验推荐**，
    真正的判定要看跑出来的前提检验"——不能让研究员以为推荐就是结论。
    """
    ds = dict(data_summary or {})
    if kind == "compare":
        pri = ds.get("normal") is None or ds.get("equal_var") is None
        r = pick_compare(int(ds.get("n_levels") or ds.get("k") or 2),
                         bool(ds.get("normal", True)), bool(ds.get("equal_var", True)))
        r["conditional"] = pri
        if pri:
            r["why"] = ("先按「两组以上、用均值比较」推荐；**真正用哪个方法要看跑出来的"
                        "正态性与方差齐性检验**——前提不满足时会自动换秩方法，"
                        "并在结果里告诉你换了、为什么换")
    elif kind == "relate":
        n_iv = int(ds.get("n_iv") or 1)
        r = pick_relate(n_iv, bool(ds.get("normal_xy", True)),
                        bool(ds.get("has_categorical_iv", False)))
        r["conditional"] = n_iv < 2
    elif kind == "within":
        # ⚠ `diff_normal=None` 表示**还没测**（推荐发生在前提检验之前）。
        #   第一版写成 `bool(ds.get("diff_normal", True))`——`bool(None)` 是 False！
        #   于是"还没测"被当成"不正态"，推荐了 Wilcoxon，而实际跑的是配对 t，
        #   **推荐卡和真实方法当场对不上**（测试抓到的）。
        #   正确做法：未知时按"假定成立"走（这是先验推荐），但把 conditional 标上，
        #   让推荐卡自己写明"真正用哪个要看跑出来的前提检验"。
        _dn = ds.get("diff_normal")
        r = pick_within(bool(ds.get("has_two_cols", True)),
                        True if _dn is None else bool(_dn),
                        ds.get("n_zero_ratio"))
        r["conditional"] = _dn is None
        if r["conditional"]:
            r["why"] = ("先按「同一批人测了两次 → 配对检验」推荐；**真正用哪个要看差值的"
                        "正态性**（注意前提落在差值上，不是原始两列）")
    elif kind == "assoc":
        r = pick_assoc(ds.get("n_levels_a", 0), ds.get("n_levels_b", 0),
                       ds.get("cells_lt5_ratio"))
        r["conditional"] = False
    else:
        r = pick("describe")
        r["conditional"] = False
    r["kind"] = kind
    return r


def guess_kind(text):
    """从一句大白话猜"这属于哪类问题"。**规则匹配，不用模型**。

    模型通道关着也要能用，所以这里必须有兜底。猜不准没关系——
    界面上那几个字是可改的，研究员自己一点就纠正了。

    ⚠ 顺序有讲究，别随便调：
      · "分类/卡方/两类"要先于"关联"判——**"关联"这个词两组都用得上**，
        但"两个分类变量有关联吗"问的是卡方那一类（实测被判成 relate 了）
      · "比"类要先于"关系"类判："谁更高"往往同时含"关系"字样
    """
    t = str(text or "")
    if not t.strip():
        return "", ""
    for words, kind, label in (
            # ⚠ 「前后测」要先于「差异」判：「前后测有没有差异」两组词都命中，
            #   但它是**配对**设计，不能用独立样本 t（那样会白丢配对带来的检验力）
            (["前后测", "前测", "后测", "配对", "同一批人", "干预前", "干预后",
              "两个时间点", "重复测量", "before", "after"], "within", "配对/前后测"),
            (["交叉表", "卡方", "两个分类", "分类变量", "两类", "占比", "分布"], "assoc",
             "分类关联"),
            (["不一样", "有差异", "更高", "更低", "多于", "少于", "差别", "比一", "相比",
              "哪个更", "谁更", "组间", "区分", "是不是更", "更倾向于", "更愿意",
              "更倾向"], "compare", "组间差异"),
            (["相关", "有关系", "影响", "预测", "能解释", "关联", "越高", "越多",
              "有没有关系"], "relate", "关系与预测"),
            (["了解", "看看", "现状", "长什么样", "描述"], "describe", "描述与统计")):
        hit = [w for w in words if w in t]
        if hit:
            return kind, "命中「%s」" % "、".join(hit[:3])
    return "", ""
