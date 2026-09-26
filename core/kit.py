# -*- coding: utf-8 -*-
"""工作台 · 引擎工具箱（给各组的 engine.py 复用）

每个组块都免不了「读文件 → 认变量类型 → 算频数/描述/交叉 → 存图」这几件事，
在这里写一次，组块里就不重复。

⚠ 原则：**数字只在这里产生**。模型永远不碰算术。
"""
import os
import re

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# 画图
# --------------------------------------------------------------------------- #

def setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    plt.rcParams["savefig.bbox"] = "tight"
    return plt


PALETTE = ["#2f6fed", "#37b3a4", "#f0a044", "#e2664f", "#8b6fd4",
           "#5aa9e6", "#7bc96f", "#d98cc4", "#9aa3b2"]


# --------------------------------------------------------------------------- #
# 读文件
# --------------------------------------------------------------------------- #

SUPPORTED = (".csv", ".txt", ".tsv", ".xlsx", ".xlsm", ".xls", ".sav")


def read_table(path):
    """读进来一个 DataFrame。返回 (df, 说明字符串)。"""
    ext = os.path.splitext(path)[1].lower()
    if not os.path.exists(path):
        raise IOError("找不到文件：%s" % path)

    if ext in (".xlsx", ".xlsm"):
        df = pd.read_excel(path, engine="openpyxl")
        how = "openpyxl 读 Excel"
    elif ext == ".xls":
        try:
            df = pd.read_excel(path)
            how = "读旧版 .xls"
        except Exception:
            raise IOError("旧版 .xls 需要 xlrd 包。请在 Excel 里另存为 .xlsx 再导入。")
    elif ext == ".sav":
        try:
            import pyreadstat
            df, meta = pyreadstat.read_sav(path)
            how = "pyreadstat 读 SPSS .sav"
        except ImportError:
            raise IOError("读 .sav 需要 pyreadstat 包（workbench/libs 里应该有）。")
    elif ext in (".tsv", ".txt"):
        df = pd.read_csv(path, sep="\t", encoding="utf-8-sig")
        how = "制表符文本"
    else:
        df, how = None, ""
        for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                df = pd.read_csv(path, encoding=enc)
                how = "CSV（%s）" % enc
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if df is None:
            df = pd.read_csv(path, encoding="utf-8", errors="replace")
            how = "CSV（有乱码字符，已容错）"

    df.columns = [str(c).strip() for c in df.columns]
    # 去掉完全空白的列（问卷导出常带）
    df = df.dropna(axis=1, how="all")
    return df, how


def clean_columns(df):
    """列名统一：去空白、去奇怪符号，重名加序号。"""
    seen = {}
    new = []
    for c in df.columns:
        c = re.sub(r"\s+", " ", str(c)).strip() or "未命名"
        if c in seen:
            seen[c] += 1
            c = "%s_%d" % (c, seen[c])
        else:
            seen[c] = 1
        new.append(c)
    df = df.copy()
    df.columns = new
    return df


# --------------------------------------------------------------------------- #
# 认变量类型
# --------------------------------------------------------------------------- #

def _looks_like_banded_number(nn, name=""):
    """这一列像不像「**间隔档折出来的数值列**」（而不是李克特那种量表题）？

    为什么要专门认这一类（前辈 2026-09-25 实测踩到）：
      问卷里"月可支配生活费"这类金额题，我们不让受访者填精确数值，而是**给区间让他估**
      （1500 以下 / 1500–2000 / …）。分析时每个区间取中点 → 这一列**只有 5 个取值**。
      于是 `infer_kind` 按"取值≤12 且全整数 → 分类"把它判成分类 →
      **回归里被拆成 5 个哑变量**，"生活费越高花越多"那条关系整个被拆碎
      （R² 虚低、常数项虚高）。实测就是这么废掉一次的。

    ⚠ **光看取值分不开它和李克特**：`1/2/3/4/5` 与 `100/200/300/400/500` 只差一个整体平移。
      第一版判据用了"跨度≥20 且最小值≥20"，结果把 `100~500` 也判成了连续 ——
      **被自己的测试当场抓住**。所以这里**改成靠列名透露意图**，数值条件只做兜底：

        · 列名带 `数值 / 金额 / 元 / 支出 / 收入 / 额度` → 明确是数值口径（我们的约定）
        · 否则再看数值（取值 ≥5 个、全整数、min ≥ 1000）—— 只兜"金额型区间"

    为什么这条路靠得住：**列名是研究员自己定的**。区间档折出来的分析列本来就要起名，
    起成 `月可支配生活费_数值` 就是他在说"这是数值口径"。
    判不出来的（比如他偏偏起名叫 `生活费5档`）就**仍然按分类处理**，由人自己改 —— 保守没错。
    """
    s = str(name or "")
    if any(k in s for k in ("_数值", "数值", "金额", "（元）", "(元)", "支出", "收入", "额度")):
        # 名字认了，也还要确保它**真的像数值**（别把 1~5 的"支出满意度"也带走）
        try:
            v = nn.dropna().astype(float)
            return v.nunique() >= 4 and bool((v == v.round()).all()) and (v.max() - v.min()) >= 20
        except Exception:
            return False
    try:
        v = nn.dropna().astype(float)
        if v.nunique() < 5 or not bool((v == v.round()).all()):
            return False
        return v.min() >= 1000 and (v.max() - v.min()) >= 1000
    except Exception:
        return False


def infer_kind(s, max_cat=12, name=""):
    """一列是「连续」「分类」还是「文本」。

    `name` 传列名：区间档折出来的数值列**跟李克特长得一样**，只能靠列名透露的意图来分
    （见 `_looks_like_banded_number`）。
    """
    nn = s.dropna()
    if len(nn) == 0:
        return "empty"
    if pd.api.types.is_numeric_dtype(nn) or pd.api.types.is_bool_dtype(nn):
        nun = nn.nunique()
        # ⚠ 判据必须是「**所有**取值都是整数」，不能只看 max/min。
        #   踩过的坑：量表均值（1.67 / 2.0 / 3.33…）的 max=5.0、min=1.0 恰好都是整数，
        #   只看首尾就把它误判成分类 → 回归里被拆成十几个哑变量，结果全废。
        try:
            all_int = bool((nn == nn.round()).all())
        except Exception:
            all_int = False
        # ⚠ 「间隔档折出来的数值列」（1250/1750/2500…）不能被当成分类。见上面那个函数。
        if _looks_like_banded_number(nn, name or getattr(s, "name", "")):
            return "continuous"
        if nun <= max_cat and all_int:
            return "categorical"
        return "continuous"
    nun = nn.nunique()
    avg_len = float(nn.astype(str).str.len().mean())
    # 短标签 + 取值少 → 分类；一整句话 → 文本（开放题）
    if nun <= max_cat and avg_len <= 14:
        return "categorical"
    return "text"


def profile_variables(df, max_cat=12):
    """每个变量的类型 + 基本情况，返回 list[dict]。"""
    out = []
    n = len(df)
    for c in df.columns:
        s = df[c]
        kind = infer_kind(s, max_cat, name=c)
        miss = int(s.isna().sum())
        out.append({
            "name": c,
            "kind": kind,
            "n_valid": int(n - miss),
            "n_missing": miss,
            "missing_pct": round(miss / n * 100, 1) if n else 0.0,
            "n_unique": int(s.nunique(dropna=True)),
        })
    return out


def guess_scale_vars(df, min_items=3):
    """猜哪些题构成一张量表：列名去掉末尾序号后同名、且都是 1~7 整数。"""
    groups = {}
    for c in df.columns:
        m = re.match(r"^(.*?)[_\-]?(\d{1,2})$", str(c))
        if not m:
            continue
        stem = m.group(1).strip("_- ")
        if not stem:
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        nn = s.dropna()
        if len(nn) < 5:
            continue
        if nn.min() >= 1 and nn.max() <= 7 and float(nn.max()) == int(nn.max()):
            groups.setdefault(stem, []).append(c)
    return {k: v for k, v in groups.items() if len(v) >= min_items}


# --------------------------------------------------------------------------- #
# 统计
# --------------------------------------------------------------------------- #

def freq_table(s, top=30):
    """频数表：取值 / 频数 / 百分比 / 累计百分比。"""
    nn = s.dropna()
    total = int(len(nn))
    if total == 0:
        return [], 0, 0
    vc = nn.value_counts()
    rows = []
    cum = 0.0
    for val, cnt in vc.items():
        pct = cnt / total * 100
        cum += pct
        rows.append([str(val), int(cnt), round(pct, 1), round(cum, 1)])
    if len(rows) > top:
        head = rows[:top]
        rest = rows[top:]
        head.append(["（其余 %d 类）" % len(rest), sum(r[1] for r in rest),
                     round(sum(r[2] for r in rest), 1), 100.0])
        rows = head
    return rows, total, int(s.isna().sum())


def describe_table(df, cols):
    """连续变量的描述统计：n / 均值 / 标准差 / 中位数 / 最小 / 最大 / 偏度 / 峰度。"""
    rows = []
    for c in cols:
        if c not in df.columns:
            continue
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(s) == 0:
            continue
        rows.append([
            c, int(len(s)),
            round(float(s.mean()), 3), round(float(s.std(ddof=1)), 3) if len(s) > 1 else None,
            round(float(s.median()), 3), round(float(s.min()), 3), round(float(s.max()), 3),
            round(float(s.skew()), 3) if len(s) > 2 else None,
            round(float(s.kurt()), 3) if len(s) > 3 else None,
        ])
    return rows


def cross_table(df, row, col, max_levels=12):
    """交叉表 + 卡方检验。返回 (rows, columns, extra)。"""
    if row not in df.columns or col not in df.columns:
        raise ValueError("变量不在数据里：%s / %s" % (row, col))
    d = df[[row, col]].dropna()
    if d.empty:
        raise ValueError("这两列没有有效的配对数据")
    if d[row].nunique() > max_levels or d[col].nunique() > max_levels:
        raise ValueError("分类太多（>%d），不适合交叉表" % max_levels)

    ct = pd.crosstab(d[row], d[col])
    # 行百分比（更常看）
    pct = (ct.div(ct.sum(axis=1), axis=0) * 100).round(1)
    ct2 = ct.copy()
    ct2["合计"] = ct.sum(axis=1)
    ct2.loc["合计"] = ct.sum(axis=0)
    ct2.loc["合计", "合计"] = int(ct.values.sum())

    cols_out = [str(row) + " \\ " + str(col)] + [str(c) for c in ct2.columns]
    rows = []
    for idx in ct2.index:
        r = [str(idx)]
        for c in ct2.columns:
            v = ct2.loc[idx, c]
            r.append(int(v) if pd.notna(v) else "")
        rows.append(r)

    # 卡方（用不含合计的那张表）
    extra = {}
    try:
        from scipy import stats
        chi2, p, dof, exp = stats.chi2_contingency(ct.values)
        n = int(ct.values.sum())
        min_dim = min(ct.shape) - 1
        cramers_v = float(np.sqrt(chi2 / (n * min_dim))) if n and min_dim > 0 else None
        small = int((exp < 5).sum())
        extra = {
            "chi2": round(float(chi2), 3), "p": float(p), "dof": int(dof),
            "n": n, "cramers_v": round(cramers_v, 3) if cramers_v is not None else None,
            "cells_expected_lt5": small, "n_cells": int(exp.size),
        }
    except Exception as e:
        extra = {"note": "卡方算不了：%s" % e}

    return rows, cols_out, {"pct": pct, "ct": ct, "extra": extra}


def cronbach_alpha(df, cols):
    """量表信度 Cronbach α。返回 (alpha, n, k, 逐题删除后的 α)。"""
    sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    k = sub.shape[1]
    if k < 2 or len(sub) < 3:
        return None, len(sub), k, []
    var_items = sub.var(axis=0, ddof=1).sum()
    var_total = sub.sum(axis=1).var(ddof=1)
    if var_total <= 0:
        return None, len(sub), k, []
    alpha = k / (k - 1.0) * (1 - var_items / var_total)
    drop = []
    for c in cols:
        rest = [x for x in cols if x != c]
        # ⚠ 这里原来有一行 `a2, _, _, _ = cronbach_alpha(sub, rest) if False else (None, 0, 0, [])`
        #   —— 死代码（`if False`），而且**递归调用自己**、传进去的 `sub` 还带多余列。
        #   它不会执行，所以不会算错；但下一个人读到这里会以为"逐题删除是递归算的"。
        #   跟 `if False` 搭配的那句注释还写着"逐题删除用同样的公式重算"——
        #   说明当时就已经在下面用公式算了，上面那行是**忘了删的**。
        #   这类残留比真 bug 更难缠：它不报错、只在人理解代码时误导人（同一轮里这是第二处）。
        s2 = sub[rest]
        vi = s2.var(axis=0, ddof=1).sum()
        vt = s2.sum(axis=1).var(ddof=1)
        k2 = len(rest)
        a2 = k2 / (k2 - 1.0) * (1 - vi / vt) if vt > 0 else None
        drop.append([c, round(float(a2), 3) if a2 is not None else None])
    return round(float(alpha), 3), int(len(sub)), int(k), drop


def pct(x, digits=1):
    return None if x is None else round(float(x) * 100, digits)


# --------------------------------------------------------------------------- #
# 中文关键词（没装 jieba 时的替代方案）
# --------------------------------------------------------------------------- #

CN_STOP = set("的了是我在有和就不人都一个上也很到说要去你会着没好看自己这那么些什么"
              "可以但因为所以如果还是可能觉得比较非常真的其实然后而且但是就是一直"
              "没有问题时候知道现在应该东西他们我们你们什么怎么这个那个一下已经"
              "有点还有一点那种感觉然后就是说不是这样的话")


def keywords(texts, top=20, min_count=1, extra=None):
    """中文关键词线索。

    ⚠ 实现已经换成**词表驱动的最长匹配**（见 `core/kw.py` 顶部的说明）：
    纯 2-gram 会把 `谈恋爱` 切成 `谈恋`+`恋爱`、把 `期在`（"那阵子**在**准备"的跨词边界）
    当线索 —— 在真实访谈稿上前 25 个里有一小半是碎块，研究员拿去没法用。
    无监督词发现也试过：一份访谈稿才一千来字，样本太小，只能稳定找出 `觉得/就是` 这类虚词。

    `extra`：项目特有的词（引擎会把研究简报的变量名、提纲里的关键词喂进来）。
    长期加词请改 `core/lexicon.txt` —— 那是留给研究员自己的入口，不用改代码。

    返回仍是 [(词, 计数)]，兼容原来的调用方。
    """
    from . import kw
    return [(w, n) for w, n, _occ in kw.keyword_hits(texts, top=top, min_count=min_count,
                                                     extra=extra)]


def regression_diagnostics(Xd, y, beta, names, rules=None):
    """回归诊断 —— 光看系数和 R² 是不够的。

    Xd 是**含常数项**的设计矩阵，names 与列一一对应（names[0] 一般是「(常数项)」）。
    返回：VIF / 标准化系数 / 残差正态性 / 异方差(Breusch-Pagan) / Cook's D / Durbin-Watson。

    为什么这些必须有：
    - 多重共线性（VIF 高）→ 系数变得不稳定，谁重要谁不重要说不清
    - 残差偏态 / 异方差 → p 值不可信
    - 强影响点 → 删掉一个样本结论就翻了

    `rules` 是 `knowledge/统计分析判定.md` 里 `stats.*` 那几条（可选）。
    传了就用它里面的阈值算「有几个影响点」；不传就用代码里的原值。
    """
    from . import knowledge as _kb
    rules_dict = rules if rules is not None else _kb._ns(_kb.stats_rules()[0], "stats")
    rules_dict = rules_dict or {}

    def _g(path, d):
        # ⚠ 这里必须闭包在 **rules_dict** 上，不能是别的名字。
        #   实测踩到（2026-09-26）：原来这个字典叫 `r`，而下面 VIF 循环里
        #   `r = yj - Xj @ bj` 把 `r` **覆盖成了残差数组** ——
        #   于是后面 `_g("regression.cooks_strong", 1)` 是在一个 numpy 数组上取键，
        #   抛异常被 except 吞掉、静默退回代码里的默认值 1.0。
        #   后果：`knowledge/统计分析判定.md` 里那条阈值**改了根本不生效**，
        #   而报告里看起来"按规则判断过了"。这类静默失效比报错难查得多。
        cur = rules_dict
        for kk in path.split("."):
            if not isinstance(cur, dict) or kk not in cur:
                return d
            cur = cur[kk]
        return cur

    from scipy import stats
    Xd = np.asarray(Xd, dtype=float)
    y = np.asarray(y, dtype=float)
    n, k = Xd.shape
    resid = y - Xd @ beta
    dof = max(n - k, 1)
    mse = float(resid @ resid) / dof

    # --- 帽子矩阵对角线 & Cook's D ---
    XtX_inv = np.linalg.pinv(Xd.T @ Xd)
    h = np.einsum("ij,jk,ik->i", Xd, XtX_inv, Xd)
    h = np.clip(h, 0, 1 - 1e-9)
    cooks = (resid ** 2 / (k * mse)) * (h / (1.0 - h) ** 2) if mse > 0 else np.zeros(n)
    n_influential = int((cooks > 4.0 / n).sum())
    n_large = int((cooks > float(_g("regression.cooks_strong", 1))).sum())

    # --- 多重共线性 VIF ---
    vifs = []
    for j in range(1, k):
        Xj = np.delete(Xd, j, axis=1)
        yj = Xd[:, j]
        try:
            bj = np.linalg.lstsq(Xj, yj, rcond=None)[0]
            resid_j = yj - Xj @ bj          # ⚠ 别叫 `r`：那个名字被上面 `_g` 的闭包用着（踩过）
            ss_tot = float(((yj - yj.mean()) ** 2).sum())
            r2j = 1 - float(resid_j @ resid_j) / ss_tot if ss_tot > 0 else 0.0
            vifs.append(float("inf") if r2j >= 1 else 1.0 / (1.0 - r2j))
        except Exception:
            vifs.append(None)

    # --- 标准化系数（用来比较「谁更重要」，未标准化系数做不到）---
    sd_y = float(y.std(ddof=1)) or 1.0
    std_beta = []
    for j in range(1, k):
        try:
            std_beta.append(float(beta[j]) * float(Xd[:, j].std(ddof=1)) / sd_y)
        except Exception:
            std_beta.append(None)

    # --- 残差正态性 ---
    p_norm = None
    if 4 <= len(resid) <= 5000:
        try:
            _, p_norm = stats.shapiro(resid)
            p_norm = float(p_norm)
        except Exception:
            p_norm = None

    # --- 异方差：Breusch-Pagan ---
    lm = p_bp = None
    try:
        e2 = resid ** 2
        b_bp = np.linalg.lstsq(Xd, e2, rcond=None)[0]
        pred = Xd @ b_bp
        ss_tot = float(((e2 - e2.mean()) ** 2).sum())
        ss_res = float(((e2 - pred) ** 2).sum())
        r2_bp = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        lm = float(n * r2_bp)
        p_bp = float(1 - stats.chi2.cdf(lm, max(k - 1, 1)))
    except Exception:
        lm = p_bp = None

    # --- 自相关：Durbin-Watson（≈2 表示没有自相关）---
    dw = None
    try:
        denom = float(resid @ resid)
        if denom > 0:
            dw = float((np.diff(resid) ** 2).sum() / denom)
    except Exception:
        dw = None

    max_vif = max([v for v in vifs if v is not None], default=None)
    return {
        "vifs": vifs, "max_vif": max_vif, "std_beta": std_beta,
        "p_normality": p_norm, "bp_lm": lm, "bp_p": p_bp,
        "dw": dw, "n_influential": n_influential, "n_large_influence": n_large,
        # ⚠ `cooks` 原来**没有返回过** —— 调用方（⑥ 的"结论敏感度"）拿不到逐个样本的
        #   影响值，就没法说"去掉哪几个点结论会翻"。逐个样本的值比"有几个"有用得多。
        "cooks": [float(x) for x in cooks],
        "n": n, "k": k, "mse": mse,
    }


# --------------------------------------------------------------------------- #
# 解析研究简报（① 访谈提纲、③ 问卷设计都要用）
# --------------------------------------------------------------------------- #

def _is_placeholder(v):
    """模板里的占位说明（整句被括号包起来的提示）不算内容。"""
    v = (v or "").strip()
    return (v.startswith("（") and v.endswith("）")) or (v.startswith("(") and v.endswith(")")) 


# 变量表：两种写法都要吃
_VAR_HEADER_WORDS = ("变量名", "变量", "指标", "名称")
_VAR_BAD_NAME = re.compile(r"^(#|-|\*|\|)")


def _looks_like_var_header(cells):
    return bool(cells) and (cells[0] or "").strip() in _VAR_HEADER_WORDS


def _looks_like_junk_name(name):
    """不是变量名，是从别处漏进来的正文/标题/半截话。"""
    n = (name or "").strip()
    if not n:
        return True
    if _VAR_BAD_NAME.match(n):
        return True
    if len(n) > 16:                     # 变量名不会是一整句话
        return True
    if re.search(r"[？?。！!；;]", n):   # 疑问句/整句
        return True
    if n.endswith("）") and "（" not in n:
        return True
    return False


def parse_var_table(text):
    """把「关键变量与操作化定义」那段文本解析成 [(变量名, 角色, 测量层次, 操作化), …]。

    两种写法都认：
      1) **Markdown 表格** —— 模型爱写这种，⓪ 的提示词也要求这么写
      2) 每行「变量名, 角色, 测量层次, 怎么测」

    ⚠ 踩过的坑：以前不管三七二十一按逗号劈，而 Markdown 表格的**单元格里本来就有中文逗号**
      （「若门店上架该玩具，我愿意购买」），于是整张表被劈成一堆碎片，
      变量名变成了「五量表」「## 7. 数据条件」这种 —— 下游 ③ 问卷设计照着出了 18 道莫名其妙的题。
    """
    if not text:
        return []
    lines = [l for l in str(text).splitlines() if l.strip()]
    if any(l.strip().startswith("|") for l in lines):
        return _parse_md_var_table(lines)

    out = []
    for l in lines:
        s = l.strip()
        if s.startswith(("#", ">", "```")):
            continue
        parts = [p.strip() for p in re.split(r"[,，\t]+", s)]
        if len(parts) < 2:              # 一行一个词的不是变量行，是从别处漏进来的
            continue
        if not parts or _looks_like_var_header(parts):
            continue
        if _looks_like_junk_name(parts[0]):
            continue
        while len(parts) < 4:
            parts.append("")
        out.append(tuple(parts[:4]))
    return out


def _body_line_count(s):
    """这一行算不算「小节的内容」？

    ⚠ 踩过两次，都是同一类误报：
      1) ⓪ 会给空小节补占位说明（`（未填）`），体检把**模板自己写的字**当成内容 →
         「假设」那节明明本来就空着，却被标成「有内容却没读出来」。
      2) 后来我用「长度 ≤ 24 的括号句才算占位」去挡，结果占位写成
         `（未填。质性研究可以没有假设；量化研究里假设能把后面的统计方法定下来。）`
         这种带解释的长句又漏了 —— **占位就该按"整句被括号包起来"判断，别用长度**。
      引用行（`>`）和表格行（`|`）也不算内容。
    """
    t = s.strip()
    if not t:
        return False
    if t.startswith((">", "|", "```")):
        return False
    return not _is_placeholder(t)


def brief_section_report(path):
    """读研究简报，回报「哪一节我认出来了、哪一节有内容但我没认出来」。

    为什么要这个：契约文件是流程之间的事实 API，一旦解析失败（比如变量表被写成
    手写文字而不是表格），下游会拿着**空的东西**照样往下跑，界面上还一片正常
    （实测：③ 会给出「0 个变量 → 0 道题」的摘要，并且照样落盘）。
    所以解析结果必须能自己说清「我认到了什么、什么没认到」，而不是只写一条日志。
    """
    rep = {"exists": False, "sections": [], "variables": 0, "rqs": 0, "hyps": 0,
           "purpose": "", "population": "", "background": "", "path": path or "",
           "failed": []}
    if not path or not os.path.exists(path):
        return rep
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return brief_section_report_text(f.read(), path)
        except UnicodeDecodeError:
            continue
        except OSError:
            return rep
    return rep


def brief_section_report_text(text, path=""):
    """同上，但直接吃文本。

    两件事共用一份实现 —— 一份给「落盘的简报」（③ 读别人的），
    一份给「刚写完还没落盘的」（⓪ 检查自己写出去的东西）。
    两处各写一遍的话，早晚会走散。
    """
    rep = {"exists": True, "sections": [], "variables": 0, "rqs": 0, "hyps": 0,
           "purpose": "", "population": "", "background": "", "path": path,
           "failed": []}
    info = parse_brief(text or "")
    heads = []
    cur = None
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if s.startswith("#"):
            cur = {"title": s.lstrip("#").strip().replace("**", ""), "body": 0}
            heads.append(cur)
            continue
        if cur and _body_line_count(s):
            cur["body"] += 1

    def find(*keys):
        for h in heads:
            if any(k in h["title"] for k in keys):
                return h
        return None

    # 只把「解析失败会让下游拿到空东西」的小节列进来。
    # 「目标人群与抽样」故意不做失败判定：它只是背景信息，没有下游靠它做计算
    # （踩过：那一节写成「10 位深访」就被标成解析失败，纯属噪音 —— 误报多了提示就没人看了）。
    who = [("研究问题", ("研究问题", "RQ"), len(info["rqs"])),
           ("假设", ("假设", "H"), len(info["hyps"])),
           ("关键变量与操作化定义", ("关键变量", "变量与操作化", "变量表"), len(info["variables"])),
           ("研究目的", ("研究目的",), 1 if info["purpose"] else 0)]
    for label, keys, got in who:
        h = find(*keys)
        rep["sections"].append({
            "label": label,
            "present": bool(h),
            "body_lines": h["body"] if h else 0,
            "parsed": got,
            # 有内容、却一个都没认出来 —— 这就是「静默降级」的现场
            "failed": bool(h and h["body"] > 0 and got == 0),
        })
    # 人群那节只做「在不在」的记录，不参与失败判定
    hp = find("目标人群", "抽样")
    rep["sections"].append({
        "label": "目标人群与抽样", "present": bool(hp),
        "body_lines": hp["body"] if hp else 0, "parsed": 1 if info["population"] else 0,
        "failed": False,
    })
    rep["variables"] = len(info["variables"])
    rep["rqs"] = len(info["rqs"])
    rep["hyps"] = len(info["hyps"])
    rep["purpose"] = info["purpose"]
    rep["population"] = info["population"]
    rep["background"] = info["background"]
    rep["failed"] = [s for s in rep["sections"] if s["failed"]]
    return rep


def brief_variables(path):
    """从研究简报文件里把变量表读回来（界面上那张表格的「读回」按钮就用它）。

    为什么要在后端读、而不是前端自己解析：**界面显示的和引擎用的必须是同一套规则**。
    前端再写一份解析，早晚会和 kit.parse_brief 走散，那时候表格里看到的变量
    和 ③ 出题用的变量就对不上了 —— 这种不一致最难查。
    """
    if not path or not os.path.exists(path):
        return []
    txt = ""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                txt = f.read()
            break
        except UnicodeDecodeError:
            continue
        except OSError:
            return []
    return (parse_brief(txt).get("variables") or [])


def _parse_md_var_table(lines):
    header, out = None, []
    for l in lines:
        s = l.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip().strip("*").strip() for c in s.strip("|").split("|")]
        if not any(cells):
            continue
        if all(re.match(r"^[-:\s]*$", c or "-") for c in cells):
            continue                                   # |---|---| 分隔行
        if header is None:
            header = cells
            continue

        def col(*names):
            for n in names:
                for i, h in enumerate(header):
                    if n and n in h:
                        return i
            return None

        i_name = col("变量名", "变量", "指标", "名称")
        i_role = col("角色", "变量角色")
        i_lvl = col("测量层次", "测量", "层次")
        i_op = col("操作化", "怎么测", "定义")

        def get(i):
            return cells[i] if (i is not None and 0 <= i < len(cells)) else ""

        name = get(i_name) if i_name is not None else (cells[0] if cells else "")
        if _looks_like_junk_name(name):
            continue
        out.append((name, get(i_role), get(i_lvl), get(i_op)))
    return out


def brief_sections(text):
    """按小节把简报里的原文抠出来，给界面上的文本框「填回表单」用。

    和 `parse_brief` 的区别：那个把 RQ/变量拆成结构（引擎要），
    这个**保留原文的换行和列表**（人要看的）。

    ⚠ 只取「有内容」的小节：整节是「（未填）」占位就返回空字符串，
      不然一按「填回表单」就把占位符写进文本框，看着像填了其实是废话。
    """
    out = {"background": "", "purpose": "", "rqs": "", "hypotheses": "",
           "population": "", "constraints": "", "variables": ""}
    if not text:
        return out
    # 小节标题 → 表单字段。用「关键词包含」匹配，免得编号变了就对不上
    MAP = [
        ("background", ("背景", "业务问题")),
        ("purpose", ("研究目的", "一句话目的")),
        ("rqs", ("研究问题",)),
        ("hypotheses", ("假设",)),
        ("population", ("目标人群", "抽样")),
        ("variables", ("关键变量", "操作化")),
        ("constraints", ("约束", "伦理")),
    ]
    cur = None
    buf = []
    secs = {}

    def flush():
        if cur:
            secs[cur] = "\n".join(buf).strip()

    for ln in text.split("\n"):
        s = ln.strip()
        if s.startswith("#"):
            flush()
            title = s.lstrip("#").strip()
            cur = None
            for key, words in MAP:
                if any(w in title for w in words):
                    cur = key
                    break
            buf = []
            continue
        if cur:
            buf.append(ln.rstrip())
    flush()

    for key, body in secs.items():
        body = _strip_placeholder(body)
        # 「一句话目的：xxx」这种前缀去掉，只留值
        if key == "purpose":
            body = re.sub(r"^\s*[-*]?\s*一句话目的\s*[:：]\s*", "", body).strip()
        if key == "background":
            # 简报里有时会把「纳入/排除标准」也塞在背景小节（引擎这么写的），
            # 那些属于人群；这里不清洗，原文照给，人自己看着改。
            pass
        out[key] = body
    return out


def _strip_placeholder(body):
    """整节都是占位符（（未填）之类）→ 当空；顺手丢掉引擎自己加的提醒行。"""
    lines = [x for x in (body or "").split("\n") if x.strip()]
    if not lines:
        return ""
    real = []
    for x in lines:
        if _is_placeholder(x):
            continue
        # ⓪ 写简报时会往「约束与伦理」尾巴加一句系统提醒，那不是研究员填的内容
        if x.strip().startswith("- 提醒：") or x.strip().startswith("提醒：直接标识符"):
            continue
        real.append(x)
    if not real:
        return ""
    return "\n".join(real).strip()


def parse_brief(text):
    """从研究简报里把 目的 / RQ / 假设 / 变量表 / 人群 抠出来。

    ⚠ 别靠「第几列」猜——不同人写的简报列数不一样（4 列 / 5 列都常见），
      所以先抓表头行，再按表头名字定位「角色」「测量层次」。
    """
    out = {"purpose": "", "rqs": [], "hyps": [], "variables": [],
           "population": "", "background": ""}
    if not text:
        return out
    sec = ""
    buf = []
    headers = None
    for ln in text.split("\n"):
        s = ln.strip().replace("**", "")          # 去掉加粗标记，免得正则被星号卡住
        if s.startswith("#"):
            sec = s.lstrip("#").strip()
            buf = []
            headers = None
            continue
        if not s:
            continue

        if sec.startswith("3.") and s.startswith(("-", "*")):
            m = re.match(r"^[-*]\s*RQ\s*\d+\s*([^*：:]*)\s*[:：]\s*(.*)$", s, re.I)
            if m:
                tag, body = m.group(1).strip(), m.group(2).strip()
                v = ("%s：%s" % (tag, body)) if tag else body
                if v and not _is_placeholder(v):
                    out["rqs"].append(v)

        elif sec.startswith("4.") and s.startswith(("-", "*")):
            m = re.match(r"^[-*]\s*H\s*\d+\s*[:：]?\s*(.*)$", s, re.I)
            if m:
                v = m.group(1).strip()
                if v and not _is_placeholder(v):
                    out["hyps"].append(v)

        elif sec.startswith("6.") and s.startswith("|"):
            cells = [c.strip().strip("*") for c in s.strip("|").split("|")]
            if len(cells) < 3 or re.match(r"^[-:\s]+$", cells[0] or "-"):
                continue
            if headers is None and cells[0] in ("变量", "变量名", "指标", "名称"):
                headers = cells
                continue

            def _col(*names):
                """先精确匹配表头，再退回「包含」。表头写成「操作化定义（怎么测）」时，
                精确匹配是找不到的（踩过一次：那一列一直读成空）。"""
                if not headers:
                    return None
                for n in names:
                    if n in headers:
                        return headers.index(n)
                for n in names:
                    for i, h in enumerate(headers):
                        if n and n in h:
                            return i
                return None

            ri, mi = _col("角色", "类型"), _col("测量层次", "测量", "层次")
            oi = _col("操作化", "怎么测", "定义")
            name = cells[0]
            if not name or _is_placeholder(name):
                continue
            # 没抓到表头时，只认「后面几列有内容」的行 ——
            # 从别处漏进来的正文行长得像 `| 不需要 |  |  |  |`，就是这么滤掉的
            if headers is None and not any(c.strip() for c in cells[1:]):
                continue
            # 变量名得像变量名：不是标题、不是整句话、不是半截括号话
            if _looks_like_junk_name(name):
                continue
            out["variables"].append([
                name,
                cells[ri] if (ri is not None and ri < len(cells)) else "",
                cells[mi] if (mi is not None and mi < len(cells)) else "",
                # 第 4 位是「怎么测」。下游 ③ 靠它决定题型：
                # 「开放式填写最高可接受价格（元）」就不该被出成李克特
                cells[oi] if (oi is not None and oi < len(cells)) else "",
            ])

        elif sec.startswith("2.") and "一句话目的" in s:
            v = s.split("：", 1)[-1].strip()
            if v and not _is_placeholder(v):
                out["purpose"] = v
        elif sec.startswith("2.") and not out["purpose"] and not _is_placeholder(s):
            # 回退：第 2 节里没写「一句话目的：」这个标签时，就取这一节的第一行有效内容。
            # （踩过：手写或简写的简报只写「识别影响因素」一行，原来一律读成空，
            #   于是体检把它标成「有内容却没读出来」—— 那是解析器太死，不是研究员的错。）
            out["purpose"] = s[:200]
        elif sec.startswith("1.") and len(s) > 8 and not _is_placeholder(s):
            buf.append(s)
            out["background"] = " ".join(buf)[:400]
        elif sec.startswith("5.") and len(s) > 4 and not _is_placeholder(s):
            buf.append(s)
            out["population"] = " ".join(buf)[:300]
    return out


def fmt_p(p):
    if p is None:
        return "—"
    if p < 1e-4:
        return "%.2g" % p
    return "%.4f" % p
