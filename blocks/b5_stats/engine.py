# -*- coding: utf-8 -*-
"""组块 ⑤ 统计分析 · 引擎（工作流的心脏）

流程固定成四拍，每一拍都留痕：

    1. 决策树   —— 按「研究问题 + 变量类型 + 组数 + 样本量」选方法，并写明理由
    2. 前提检验 —— 正态性 / 方差齐性
    3. 算       —— Python 出数（scipy / numpy），**模型不参与算术**
    4. 双轨     —— 同时生成 .sps，可以在 SPSS 里复核同一件事

原则：能说清楚「为什么用这个方法」比算得快更重要。
"""
import os
import re
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq      # 非中心 F 反解 η² 的置信区间要用

_HERE = os.path.dirname(os.path.abspath(__file__))
_WB = os.path.dirname(os.path.dirname(_HERE))
if _WB not in sys.path:
    sys.path.insert(0, _WB)
from core import kit          # noqa: E402


# =========================================================================== #
# 小工具
# =========================================================================== #

def _f(x, d=3):
    if x is None:
        return "—"
    try:
        v = float(x)
    except Exception:
        return str(x)
    if v != v or v in (float("inf"), float("-inf")):
        return "—"
    return ("%%.%df" % d) % v


def _p(p):
    return kit.fmt_p(p)


def _sig(p, alpha):
    if p is None:
        return "—"
    return "显著" if p < alpha else "不显著"


def _spss_name(c):
    n = re.sub(r"[^\w\u4e00-\u9fa5]", "_", str(c)).strip("_")
    if not n:
        n = "v"
    if re.match(r"^\d", n):
        n = "v_" + n
    return n[:60]


# 知识库里的统计判定阈值（run() 里从 knowledge/统计分析判定.md 读进来）。
# 先给空字典：万一有别的函数在 run() 之前被调用，_sr_get 会干净地退回默认值。
_SR = {}


def _sr_get(path, default):
    """从知识库规则里取值（`knowledge/统计分析判定.md`）。

    读不到就用代码里的原值 —— 但「读不到」这件事会在 run() 里被报出来，
    不会变成「检查过了，没问题」。
    """
    cur = _SR
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _is_ordinal_scale(s):
    """是不是「1~5 / 1~7 这种有序量表题」。

    踩过一次：价格敏感度是 1~5 的李克特单题，被当成分类拆成 4 个哑变量，
    于是 VIF 飙到 7 以上、还白吃 3 个自由度，报告里全是「共线性偏高」的警告。
    有序量表题在回归里**按分数用**才是常规做法（等于假设了「5 比 4 高一点」这个顺序）。

    判据（样本量 / 取值个数 / 是否整数 / 取值是否连续）都能在知识库里改。
    """
    nn = pd.to_numeric(s, errors="coerce").dropna()
    if len(nn) < int(_sr_get("ordinal_scale.min_n", 10)):
        return False
    if not (nn == nn.round()).all():
        return False
    u = sorted(set(int(v) for v in nn.unique()))
    if not (int(_sr_get("ordinal_scale.min_levels", 3))
            <= len(u) <= int(_sr_get("ordinal_scale.max_levels", 7))):
        return False
    return u[0] >= 0 and (u[-1] - u[0]) <= int(_sr_get("ordinal_scale.max_span", 8)) \
        and u == list(range(u[0], u[-1] + 1))


def _dummies(df, cols, kinds):
    """把自变量摊成设计矩阵：连续 / 有序量表直接用分数，真·分类才做哑变量（去掉第一类）。"""
    parts, names = [], []
    for c in cols:
        s = df[c]
        if kinds.get(c) == "categorical" and not _is_ordinal_scale(s):
            d = pd.get_dummies(s.astype(str), prefix=c, drop_first=True, dtype=float)
            for col in d.columns:
                parts.append(d[col].values.astype(float))
                names.append(str(col))
        else:
            parts.append(pd.to_numeric(s, errors="coerce").values.astype(float))
            names.append(str(c))
    if not parts:
        return np.zeros((len(df), 0)), []
    return np.column_stack(parts), names


def _ols(X, y):
    """最小二乘回归（没有 statsmodels，就自己算——公式是标准的）。"""
    n = len(y)
    Xd = np.column_stack([np.ones(n), X])
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
            "r2": r2, "adj_r2": adj, "F": F, "pF": pF, "n": n, "k": k}


def _cohens_d(a, b):
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return None
    sp2 = ((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2)
    if sp2 <= 0:
        return None
    return float((a.mean() - b.mean()) / np.sqrt(sp2))


def _normality(x, alpha=0.05):
    x = np.asarray(pd.to_numeric(pd.Series(x), errors="coerce").dropna(), dtype=float)
    if len(x) < 4:
        return {"test": "样本太少", "ok": None, "detail": "n=%d，没法判断" % len(x)}
    if len(x) > 5000:
        sk, ku = float(stats.skew(x)), float(stats.kurtosis(x))
        ok = abs(sk) < 1.0 and abs(ku) < 2.0
        return {"test": "偏度/峰度（n>5000）", "ok": ok,
                "detail": "偏度 %.2f、峰度 %.2f（|偏度|<1、|峰度|<2 视为近似正态）" % (sk, ku)}
    W, p = stats.shapiro(x)
    return {"test": "Shapiro-Wilk", "ok": bool(p > alpha), "p": float(p),
            "detail": "W=%.4f, p=%s（n=%d）" % (W, kit.fmt_p(p), len(x))}


# =========================================================================== #
# 主流程
# =========================================================================== #

def _scalar_ordinal(s):
    """把一个「有序档位 / 区间」文本转成它代表的数值；转不了就返回 None。

    问卷里的有序题，选项常常就是这么写的（真实简报里到处都是）：

        「0–25%」「25–50%」「50–75%」「75–100%」   → 取区间中点 12.5 / 37.5 / 62.5 / 87.5
        「2 次及以上」「3 次以上」「5 分以上」        → 取下界 2 / 3 / 5
        「0 次」「1 次」「大一」「1~5」              → 0 / 1 / 1 / 3（「大一」按 1 算）

    ⚠ 为什么必须做这一步（2026-09-24 实测踩到）：
      「花销分担比例」是个**定序**变量，选项就是那四个区间。它进 ⑥ 的时候
      `pd.to_numeric(errors="coerce")` 一转换 → **整列全变 NaN** → 分析直接塌掉，
      报的是「分组变量只有 0 个取值，没法比较」——**一个完全看不出真因的错误**
      （数据没问题、变量名也没错，就是那列是「25–50%」这种写法）。
      有序档位按中点当分数用是常规做法（等于承认「75–100% 比 50–75% 高」），
      而且转换是**可见的**：步骤卡里会写清哪几列被转成了什么。
    """
    t = str(s).strip()
    if not t or t.lower() in ("nan", "none", "null"):
        return None
    t = (t.replace("％", "%").replace("—", "-").replace("–", "-")
          .replace("－", "-").replace("～", "~").replace("〜", "~").replace("至", "-"))
    # ① 「a-b」区间 → 中点（a、b 都可以带单位/百分号）。
    #    ⚠ 破折号有好几种写法：—–－ 还有 ~（「1~5」这种量表区间也常见）。
    #      早先只认「-」，于是「1~5」这种写法整列都当文本（测试当场抓到了）。
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*[%]?\s*[-~]\s*(-?\d+(?:\.\d+)?)\s*[%]?\s*[^\d]*$", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return (a + b) / 2.0
    # ② 「a 及以上 / 以上 / 以下 / 以内 / 起」→ 取下界
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*[%]?\s*(及以上|以上|以下|以内|起|多|余)", t)
    if m:
        return float(m.group(1))
    # ③ 「a 次 / a 个 / a 分 / 纯数字 / a%」→ 数字本身
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*[%]?\s*[^\d]*$", t)
    if m:
        return float(m.group(1))
    # ④ 「大一 / 大二 / 大三 / 大四」
    m = re.match(r"^大\s*([一二三四五六七八九十])$", t)
    if m:
        cn = "一二三四五六七八九十"
        return float(cn.index(m.group(1)) + 1)
    return None


def _ordinal_series(col):
    """整列试一遍：**全都能转**才认（避免把「家庭给 / 兼职」这种定类硬转成数字）。"""
    vals = [v for v in col if str(v).strip() not in ("", "nan", "None")]
    if not vals:
        return None
    out, seen = [], []
    for v in vals:
        x = _scalar_ordinal(v)
        if x is None:
            return None
        out.append(x)
        if str(v).strip() not in seen:
            seen.append(str(v).strip())
    # 至少要 2 档、不超过 8 档，否则不像"有序档位"（太多档更可能是自由填的数）
    if not (2 <= len(seen) <= 8):
        return None
    s = pd.Series([_scalar_ordinal(v) if str(v).strip() not in ("", "nan", "None") else np.nan
                   for v in col], index=col.index, dtype=float)
    return s, seen


def _normalize_ordinals(ctx, df):
    """把「有序档位 / 区间」那几列换成它们的数值表示。返回 (新表, 说明行)。"""
    rows = []
    for c in list(df.columns):
        s = df[c]
        if not (s.dtype == object or str(s.dtype).startswith("str")):
            continue
        got = _ordinal_series(s)
        if not got:
            continue
        num, labels = got
        # 字符串形式数字（"1"/"2"）本来就是数字，不用转
        if all(re.match(r"^-?\d+(\.\d+)?$", x) for x in labels):
            continue
        df[c] = num
        rows.append([c, "%d 档" % len(labels),
                     " / ".join(labels[:5]) + ("…" if len(labels) > 5 else ""),
                     "→ " + " / ".join(("%g" % _scalar_ordinal(x)) for x in labels[:5])
                     + ("…" if len(labels) > 5 else "")])
    return df, rows


def run(ctx):
    file_rel = (ctx.get("file") or "").strip().strip('"')
    if not file_rel:
        raise ValueError("请先选一个数据文件")
    path = file_rel if os.path.isabs(file_rel) else ctx.path(file_rel)
    df, how = kit.read_table(path)
    df = kit.clean_columns(df)
    # 「0–25% / 25–50%」这类**有序档位**换成数值（取中点），否则整列会被 to_numeric 变成 NaN、
    # 分析塌掉还报一个看不出真因的错。转换摊在步骤卡里，看得见。
    df, ord_rows = _normalize_ordinals(ctx, df)
    if ord_rows:
        ctx.step("ordinals", "有序档位转成数值（%d 列）" % len(ord_rows),
                 "区间取中点、「N 及以上」取下界 —— 这样它们才能进均值 / 回归。"
                 "原始档位标签仍保留在上一份数据里。",
                 rows=ord_rows, columns=["变量", "档数", "原来的选项", "换成"])
        ctx.log("有序档位转数值 %d 列：%s"
                % (len(ord_rows), "、".join(r[0] for r in ord_rows)))
    ctx.log("读入 %s → %d 行 × %d 列（%s）" % (os.path.basename(path), df.shape[0], df.shape[1], how))
    ctx.step("read", "读数据",
             "%s → %d 行 × %d 列（%s）" % (os.path.basename(path), df.shape[0], df.shape[1], how))

    # 判定阈值从知识库读（knowledge/统计分析判定.md）—— 研究员能改的那部分。
    # 读不到就退回代码里的原值，并且**报出来**（静默用默认值 = 假装检查过了）。
    from core import knowledge as _kb
    _sr, _serr = _kb.stats_rules()
    SR = _kb._ns(_sr, "stats")
    ctx.alerts_from(_kb.check_stats_rules(_sr, _serr))
    globals()["_SR"] = SR          # 给 _is_ordinal_scale 这些辅助函数用

    try:
        alpha = float(ctx.get("alpha") or SR.get("alpha_default") or 0.05)
    except Exception:
        alpha = float(SR.get("alpha_default") or 0.05)
    fallback = ctx.get("fallback") or "nonparam"
    gen = ctx.get("gen_sps") or []
    if isinstance(gen, str):
        gen = [gen]

    dv = (ctx.get("dv") or "").strip()
    group = (ctx.get("group") or "").strip()
    ivs = ctx.get("ivs") or []
    if isinstance(ivs, str):
        ivs = [x.strip() for x in re.split(r"[,，\s]+", ivs) if x.strip()]
    ivs = [x for x in ivs if x]

    def _as_list(v):
        """表单里的多选值可能是 list，也可能是一串文本（命令行/旧任务回放时会这样）。"""
        if isinstance(v, str):
            return [x.strip() for x in re.split(r"[,，;；\s]+", v) if x.strip()]
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    controls = _as_list(ctx.get("controls"))       # 偏相关的控制变量
    pair_a = (ctx.get("pair_a") or "").strip()     # 配对：第一列
    pair_b = (ctx.get("pair_b") or "").strip()     # 配对：第二列
    mediator = (ctx.get("mediator") or "").strip()   # 中介变量 M（X → M → Y）
    moderator = (ctx.get("moderator") or "").strip()  # 调节变量 W（X 的作用随它变）
    weight = (ctx.get("weight") or "").strip()       # 权重列（加权分析用，可为空）

    # ⚠ 把**列名**也传进去：区间档折出来的数值列（5 个中点）跟李克特 1~5 长得一模一样，
    #   只有列名透露意图（`_数值` 这种）。不传列名的话金额会被拆成哑变量（实测踩过）。
    kinds = {c: kit.infer_kind(df[c], name=c) for c in df.columns}
    # 有序量表题（1~5 / 1~7 整数）单独标出来：它们既是「分类」也是「有顺序的分数」
    ordinal = set(c for c in df.columns
                  if kinds[c] == "categorical" and _is_ordinal_scale(df[c]))
    question = ctx.get("question") or "auto"

    # ---------- 步骤：变量类型体检（把「我怎么认的」摊开给研究员看）----------
    KIND_CN = {"continuous": "连续", "categorical": "分类", "text": "文本", "empty": "空列"}
    kind_rows = []
    for c in df.columns:
        s = df[c]
        nn = s.dropna()
        if len(nn) == 0:
            reason = "整列都是空的"
        elif c in ordinal:
            reason = ("取值 %d 个整数且连成一段 → 有序量表题。当分组变量时按类别用，"
                      "进回归时按分数用（比拆哑变量省自由度）" % nn.nunique())
        elif kinds[c] == "continuous":
            reason = "有小数或取值很多 → 当连续变量"
        elif kinds[c] == "categorical":
            reason = "取值 %d 种、全是整数 → 当分类变量" % nn.nunique()
        else:
            reason = "取值 %d 种、是长文本 → 当文本" % nn.nunique()
        kind_rows.append([c, "定序量表" if c in ordinal else KIND_CN.get(kinds[c], kinds[c]),
                          int(nn.nunique()),
                          round(float(s.isna().mean()) * 100, 1), reason])
    n_cont = sum(1 for v in kinds.values() if v == "continuous")
    n_cat = sum(1 for v in kinds.values() if v == "categorical")
    ctx.step("kinds", "认变量类型", "连续 %d 个 · 分类 %d 个 · 文本 %d 个"
             % (n_cont, n_cat, sum(1 for v in kinds.values() if v == "text")),
             rows=kind_rows, columns=["变量", "我判成", "取值数", "缺失%", "为什么"])
    ctx.log("变量类型：连续 %d · 分类 %d · 文本 %d" % (
        n_cont, n_cat, sum(1 for v in kinds.values() if v == "text")))

    # ---------- 检查点：类型判断对不对 ----------
    _ans = ctx.ask(
        "kinds_ok",
        "变量类型认完了：连续 %d 个、分类 %d 个 —— 有认错的吗？" % (n_cont, n_cat),
        "认错类型会直接改变结果。典型例子：量表均值（1.67 / 2.0 / 3.33…）如果被当成分类，"
        "回归里会被拆成一堆哑变量，结果就废了。\n"
        "上面那张表里重点看你要分析的那几个变量。",
        options=[
            {"value": "ok", "label": "没问题，继续", "hint": "按这个判断往下走"},
            {"value": "stop", "label": "停一下，我要先改", "hint": "回去处理数据或变量命名，再重跑"},
        ],
        default="ok",
    )
    if _ans == "stop":
        ctx.log("研究员要求停下：变量类型需要先处理", "warn")
        return {
            "summary": "按你的要求停在这里 —— 变量类型需要先处理，本次没有产出任何文件。",
            "stopped": True,
            "tables": [{"name": "变量类型体检", "columns": ["变量", "我判成", "取值数", "缺失%", "为什么"],
                        "rows": kind_rows,
                        "note": "规则：全是整数且取值少 → 分类；有小数或取值多 → 连续；长文本 → 文本。"}],
            "figures": [], "markdown": [],
            "notes": "改完再跑一次就行。",
        }

    # ---------- 决策树 第 1 步：这是什么问题 ----------
    # ⚠ 先用**大白话意图**（如果研究员写了）：意图能给出更真实的"想知道什么"，
    #   而且它里面可能藏着**数据答不了的问法**（"更容易""每多"…）——
    #   那种要在推荐方法**之前**就说，不然会给人一个"能算"的错觉。
    # ⚠ 方法选择的真源：**只 import 一次、放在最前面**。
    #   踩过：一开始只在 compare 分支里 `from core import method_pick as _mp`，
    #   而意图卡/推荐卡在前面就要用它 → 走 describe/relate 时直接 NameError。
    from core import method_pick as _mp

    plan = []
    intent = (ctx.get("intent") or "").strip()
    intent_kind, intent_why = ("", "")
    if intent:
        intent_kind, intent_why = _mp.guess_kind(intent)

    if question == "auto":
        if group and dv:
            question, why = "compare", "填了「分组变量 + 因变量」"
        elif mediator or moderator:
            # ⚠ 这条要排在「因变量+自变量」前面：填了中介/调节就是明确在问
            #   "经由什么" 或 "在什么条件下"，比"有关系吗"更具体。
            question, why = "causal", ("填了「%s」" %
                                       ("、".join([x for x in ("中介变量" if mediator else "",
                                                               "调节变量" if moderator else "") if x])))
        elif dv and ivs:
            question, why = "relate", "填了「因变量 + 自变量」"
        elif len(ivs) >= 2:
            question, why = "assoc", "填了两个以上变量、没指定因变量"
        else:
            question, why = "describe", "没有明确的比较/预测目标"
        # 意图猜出来的类型优先于"看表单猜"——他亲口说的是更可靠的信号；
        # 但**只在表单没给出明确方向时**才改（表单是显式选择，不该被猜的东西覆盖）
        if intent_kind and intent_kind != question and not (group or dv or ivs):
            question, why = intent_kind, "按你写的那句话判断（%s）" % intent_why
        plan.append(["判断研究问题", why, "→ %s" % {
            "compare": "组间差异（比均值）", "within": "配对/前后测",
            "causal": "中介/调节", "relate": "关系与预测（相关/回归）",
            "assoc": "分类关联（卡方）", "describe": "描述与信度"}[question]])

    tables, figures, md, text_out = [], [], [], []
    concl = ""
    slug = "分析"          # 产物文件名里带上「这次分析的是什么」，多次分析不会互相覆盖
    # 本次跑了哪些检验 —— 统一登记，最后做一次「多重比较总账」。
    # ⚠ 为什么要收集而不是"算出来的当时就报"：单看一个 p 值永远看不出多重比较问题，
    #   必须**攒起来看总数**（1 个 5%、5 个 23%、10 个 40%）。
    ledger_entries = []

    # ---------- 意图卡：把你说的、我理解成的，摊开（可改）----------
    if intent:
        tables.append({
            "name": "我理解你想知道什么",
            "columns": ["项", "内容"],
            "rows": [["你说的原话", intent],
                     ["我理解成", "%s（%s）" % (
                         {"compare": "比较几组人的某个指标", "relate": "看两个/多个变量的关系",
                          "assoc": "看两个分类变量有没有关联",
                          "describe": "先描述现状"}.get(question, question),
                         intent_why or "按表单填的内容判断")],
                     ["用到的变量", "因变量 %s ｜ 分组 %s ｜ 自变量 %s" % (
                         dv or "—", group or "—", "、".join(ivs) or "—")]],
            "note": "**这份理解对不对由你判断**——上面任一项不对，回去改表单里的变量再跑。"
                    "程序不会替你猜变量，它只把你说的和表单填的摆在一起。",
        })

    if question == "compare" and not (dv and group):
        # ⚠ **变量还没填完，不是崩溃，是"请你补上"**（2026-09-26 发现）。
        #   原来这里直接 raise，于是——研究员写了一句大白话、程序按那句话猜出"这是组间差异"、
        #   然后**报错退出**，连"我按哪句话猜的、你该补哪两个变量"都没说。
        #   而这时候最该看到的是**前面那两张卡**（我知道你想问什么 / 这句话数据答不答得了）。
        #   所以缺变量时：把已经算出来的东西一起返回，并指名要他填什么。
        _need = []
        if not dv:
            _need.append("因变量（要比的那个指标，比如「月均恋爱支出_数值」）")
        if not group:
            _need.append("分组变量（比如「生活费来源」「年级」）")
        tables.append({
            "name": "还差两个选择，我就能算了",
            "columns": ["要填的", "说明"],
            "rows": [["因变量 / 关注指标", "要比的那个连续指标"],
                     ["分组变量", "分成哪几组（两组 → t 检验；三组以上 → 方差分析）"],
                     ["（可选）自变量", "想同时控制别的变量就填"]],
            "note": "**我按你那句话判断这是「组间差异」类问题**，但变量得你来指——"
                    "程序不替你猜「哪一列是花钱」（猜错了你会拿到一张看着对、"
                    "其实答错问题的表）。"
                    "上面那张「我理解你想知道什么」和「数据答不了的部分」都可以先看。",
        })
        # ⚠ 缺变量时**也要**把「数据答不了」那件事说出来（测试抓到的顺序问题）：
        #   这一刻研究员正要决定「换个问法还是换数据」，最该看到的就是它。
        try:
            from core import knowledge as _kb
            for _h in _kb.check_data_bounds(intent):
                if isinstance(_h, dict) and _h.get("id"):
                    tables.append({
                        "name": "⚠ 你这句话里，有一部分是**这份数据答不了**的",
                        "columns": ["你说到的", "要回答它需要", "我现在能给你", "想要真答案就得"],
                        "rows": [[_h["id"], "、".join(_h.get("要求") or []),
                                  _h.get("现在给你什么") or "—",
                                  _h.get("降级路径") or "—"]],
                        "note": "**这不是「不能做」，而是「能做什么」**：第三列就是我现在能给的。",
                    })
        except Exception:
            pass
        return {
            "summary": "还差变量没选：%s —— 填完再跑一次就行。" % "；".join(_need),
            "stopped": True,
            "tables": tables, "figures": [], "markdown": [],
            "notes": "这次没有产出任何文件（没算就不会有数字，免得半截报告被当成结果）。",
        }


    # ---------- 推荐卡：我建议用什么方法、为什么、为什么不用另一个 ----------
    # ⚠ 判定**调 `core/method_pick.pick()`** —— 和下面真正算的时候是**同一个函数**。
    #   各写一遍的代价：研究员照着推荐卡把方法写进论文，而数字是另一个方法算的。
    try:
        # ⚠ 这里先不看数据（正态性要等真跑才知道），所以推荐是**先验的**：
        #   卡片里会写明"真正用哪个方法要看跑出来的前提检验"。不能让人以为推荐就是结论。
        _ds = {}
        if question == "compare":
            _ds = {"n_levels": (int(df[group].nunique(dropna=True)) if group and group in df.columns else 0)}
        elif question == "within":
            # ⚠ 配对这一族要看**差值**的正态性 —— 这里还没算，所以传 None 表示"待定"，
            #   推荐卡会写明"这是先验推荐"。
            _ds = {"has_two_cols": bool(pair_a and pair_b), "diff_normal": None}
        elif question == "relate":
            _ds = {"n_iv": len(ivs), "n_controls": len(controls),
                   "has_categorical_iv": any(kinds.get(c) == "categorical" for c in ivs)}
        _rec = _mp.recommend_for(question, _ds)
        if _rec.get("method"):
            _rows = [["我建议用", _mp.METHOD_CN.get(_rec["method"], _rec["method"])],
                     ["为什么", _rec.get("why") or "—"]]
            if _rec.get("assumes"):
                _rows.append(["它假设什么", _rec["assumes"]])
            for i, wn in enumerate(_rec.get("why_not") or []):
                _rows.append(["不用另一个（%d）" % (i + 1) if i == 0 else "以及", wn])
            if _rec.get("conditional"):
                _rows.append(["⚠ 这是先验推荐",
                              "真正用哪个要看**跑出来的前提检验**（正态性/方差齐性）；"
                              "不满足时我会自动换、并告诉你换了什么、为什么"])
            tables.append({
                "name": "方法推荐（主推一个 + 为什么不用另一个）",
                "columns": ["项", "内容"], "rows": _rows,
                "note": "你**可以不听我的**：下面表单里能把方法细节改掉，"
                        "或者跑完在前提检验那个检查点上改主意。"
                        "推荐存在的意义是让你知道「被排除的理由」，而不是替你做决定。",
            })
            # 备选方法：写出来，好让人知道"还有哪些路"
            if question == "compare":
                _alt = [_mp.METHOD_CN[m] for m in ("t", "welch", "anova", "mannwhitney", "kruskal")
                        if m != _rec["method"]]
            elif question == "relate" and len(ivs) <= 1:
                _alt = [_mp.METHOD_CN[m] for m in ("pearson", "spearman", "kendall")
                        if m != _rec["method"]]
            else:
                _alt = []
            if _alt:
                tables.append({
                    "name": "还有哪些备选方法",
                    "columns": ["备选", "它适合什么情况"],
                    "rows": [[m, _mp.ASSUMES.get(
                        [k for k, v in _mp.METHOD_CN.items() if v == m][0], "—")]
                        for m in _alt],
                    "note": "**跑一遍备选看看**这件事值得做：把两个方法的结果并排看，"
                            "你才知道自己的结论是不是只依赖某一种算法。"
                            "（现在要手动换方法重跑；一键并排是待做的。）",
                })
    except Exception as e:
        ctx.log("方法推荐没做出来（不影响分析）：%s" % e, "warn")

    # ---------- 数据能力卡：有些问法数据本身答不了 ----------
    # ⚠ 放在**推荐卡之后**（顺序是刻意的）：先说「我建议用什么」，
    #   再说「不过你这句话里有一部分数据答不了」——
    #   反过来的话，人第一眼看到「答不了」会以为整件事做不成。
    if intent:
        try:
            from core import knowledge as _kb
            _hits = _kb.check_data_bounds(intent)
            _real = [h for h in _hits if isinstance(h, dict) and h.get("id")]
            if _real:
                tables.append({
                    "name": "⚠ 你这句话里，有一部分是**这份数据答不了**的",
                    "columns": ["你说到的", "要回答它需要", "我现在能给你", "想要真答案就得"],
                    "rows": [[h["id"] + "（命中「%s」）" % "、".join(h.get("命中词") or []),
                              "、".join(h.get("要求") or []),
                              h.get("现在给你什么") or "—",
                              h.get("降级路径") or "—"] for h in _real],
                    "note": "**这不是「不能做」，而是「能做什么」**：上面第三列就是我现在能给你的东西。\n"
                            "为什么必须说：不说的后果是给你一个看起来很专业的表，"
                            "而它的结论**超出了数据的支持范围**——审稿人/导师一问就崩。\n"
                            "（这份清单在 `knowledge/数据能支持什么.md`，**可以自己加条目**。）",
                })
                ctx.alert("你写的意图里有一处**数据答不了**的问法：%s —— "
                          "我在推荐方法后面马上说明了（结果里有那张表）。"
                          % "、".join(h["id"] for h in _real),
                          level="warn", kind="internal",
                          fix="看那张「数据答不了」的表：第三列是我能给你的替代，"
                              "第四列是要真答案得补什么数据。")
            for h in _hits:
                if not isinstance(h, dict) or h.get("id"):
                    continue
                ctx.alert(str(h.get("msg") or "数据能力清单没读成"), level="warn",
                          kind="internal", fix=str(h.get("fix") or ""))
        except Exception as e:
            ctx.log("数据能力检查没做出来（不影响分析）：%s" % e, "warn")

    md.append("# 统计分析报告\n")
    md.append("> 数据：`%s`（%s），%d 行 × %d 列" % (file_rel, how, df.shape[0], df.shape[1]))
    md.append("> 显著性水平 α = %.3f；生成时间：%s\n" % (alpha, time.strftime("%Y-%m-%d %H:%M")))

    # 数据能力那几条也进 markdown（放在报告头之后，好读）
    if intent:
        try:
            from core import knowledge as _kb
            for _h in _kb.check_data_bounds(intent):
                if not isinstance(_h, dict) or not _h.get("id"):
                    continue
                md.append("\n### ⚠ 数据答不了的部分（%s）\n" % _h["id"])
                md.append("- **要回答它需要**：%s\n" % "、".join(_h.get("要求") or []))
                md.append("- **我现在能给你**：%s\n" % (_h.get("现在给你什么") or "—"))
                md.append("- **想要真答案就得**：%s\n" % (_h.get("降级路径") or "—"))
                md.append("- **为什么**：%s\n" % (_h.get("为什么") or "—"))
        except Exception:
            pass

    sps_cmds = []          # 收集 SPSS 命令
    sps_prelude = []       # 跑分析前要先做的准备（比如把分类变量拆成哑变量）

    # ======================================================================= #
    if question == "compare":
        for v in (dv, group):
            if v not in df.columns:
                raise ValueError("数据里没有变量「%s」" % v)

        plan.append(["变量类型", "因变量 %s = %s" % (dv, kinds.get(dv)),
                     "连续 → 比均值；非连续的话下面的结果只作参考"],)
        d = pd.DataFrame({dv: pd.to_numeric(df[dv], errors="coerce"), group: df[group]}).dropna()
        levels = list(pd.unique(d[group]))
        k = len(levels)
        if k < 2:
            raise ValueError("分组变量「%s」只有 %d 个取值，没法比较" % (group, k))
        plan.append(["分了几组", "%s 有 %d 组：%s" % (group, k, "、".join(str(x) for x in levels[:8])),
                     "2 组 → t 检验；3 组以上 → 方差分析"])

        groups = [d.loc[d[group] == lv, dv].values.astype(float) for lv in levels]
        ns = [len(g) for g in groups]
        plan.append(["样本量", "各组 n = %s" % "、".join(str(x) for x in ns),
                     "任一组 < 30 时结论要谨慎" if min(ns) < 30 else "样本量够用"])

        # 前提检验
        norms = [_normality(g, alpha) for g in groups]
        all_normal = all(n["ok"] for n in norms if n["ok"] is not None)
        lev_p = None
        try:
            if k == 2:
                lev_p = float(stats.levene(groups[0], groups[1]).pvalue)
            else:
                lev_p = float(stats.levene(*groups, center="median").pvalue)
        except Exception as e:
            ctx.log("方差齐性算不了：%s" % e, "warn")
        equal_var = (lev_p is None) or (lev_p > alpha)

        plan.append(["正态性", "；".join(
            "%s: %s" % (lv, norms[i]["detail"]) for i, lv in enumerate(levels[:5])),
            "满足" if all_normal else "不满足 → 走非参数方法"])
        plan.append(["方差齐性", ("Levene p=%s" % _p(lev_p)) if lev_p is not None else "没算出来",
                     ("齐 → 用等方差版本" if equal_var else "不齐 → 用 Welch 校正或非参数")])

        # ⚠ 方法选择**调纯函数**（`core/method_pick.py`），不在这里写第二遍判定。
        #   为什么：推荐卡（给研究员看的那张"我建议用 X"）必须和这里算出的是**同一个**。
        #   各写一遍的代价我们已经在 ②/②b 上付过一次（两边判据不一致、还从不报错）——
        #   在这里代价更大：研究员会照着推荐卡把方法写进论文，而数字是另一个方法算的。
        _pick = _mp.pick_compare(k, all_normal, equal_var)
        use = _pick["method"]
        method_map = _mp.METHOD_CN          # 中文名也只留一份

        forced = False
        if not all_normal and fallback == "keep" and use in ("mannwhitney", "kruskal"):
            forced = True
        if fallback == "stop" and not all_normal:
            plan.append(["结论", "前提（正态性）不满足，按你的设置停在这里",
                         "没有做检验——先决定是换方法还是修数据"])
            tables.append({"name": "分析计划（决策树）", "columns": ["步骤", "依据", "结论"],
                           "rows": plan})
            md.append("## 决策树\n")
            md.append("| 步骤 | 依据 | 结论 |")
            md.append("|---|---|---|")
            for r in plan:
                md.append("| %s | %s | %s |" % tuple(r))
            md_text = "\n".join(md)
            ctx.save_text("output/分析报告.md", md_text)
            return {"summary": "按设置停在前提检验（正态性不满足）", "tables": tables,
                    "figures": [], "markdown": [{"name": "分析报告.md",
                                                 "rel": "output/分析报告.md", "text": md_text}]}

        # ⚠ 这里原来又写了一份中英对照表（`method_map = {...}`）——
        #   已经移到 `core/method_pick.py` 的 `METHOD_CN`，两处各一份迟早会不一致。
        _why_use = _pick.get("why") or "以上前提合起来"
        plan.append(["选定方法", _why_use, method_map[use]])
        if _pick.get("why_not"):
            # 把"为什么不用另一个"也写进决策树 —— 研究员要知道**被排除的理由**才算看懂
            plan.append(["为什么不用另一个", _pick["why_not"][0], "（备选方法仍可手动选）"])

        # ---------- 检查点：前提不满足时，当场问研究员 ----------
        if not all_normal or not equal_var:
            bad = []
            if not all_normal:
                bad.append("正态性不满足")
            if not equal_var:
                bad.append("方差齐性不满足")
            param_alt = "t 检验" if k == 2 else "方差分析"
            _ans2 = ctx.ask(
                "method",
                "前提检验发现「%s」，我打算改用「%s」" % ("、".join(bad), method_map[use]),
                "%s 假设数据近似正态、各组方差差不多。前提不满足还硬用，p 值可能偏小"
                "（更容易报出「显著」）。\n"
                "换非参数方法比的是秩次 / 中位数，不依赖正态假设，代价是检验力略低。\n"
                "也可以坚持用参数方法——我会在报告里把这个风险标出来。"
                % param_alt,
                options=[
                    {"value": "nonparam", "label": "换成 %s" % method_map[use],
                     "hint": "推荐：前提不满足时的标准做法"},
                    {"value": "keep", "label": "坚持用 %s" % param_alt,
                     "hint": "结果里会标注「前提不满足」的风险"},
                    {"value": "stop", "label": "停在这里",
                     "hint": "我想先看看数据，或者换个变量再分析"},
                ],
                default=("keep" if fallback == "keep" else "nonparam"),
            )
            if _ans2 == "stop":
                ctx.log("研究员要求停下：前提不满足，先不往下算", "warn")
                return {
                    "summary": "按你的要求停在这里 —— 前提不满足，本次没有往下算。",
                    "stopped": True,
                    "tables": [
                        {"name": "分析计划（到此为止）", "columns": ["步骤", "依据", "结论"], "rows": plan},
                        {"name": "前提检验", "columns": ["前提", "结果"],
                         "rows": [["正态性", "；".join(
                             "%s: %s" % (lv, norms[i]["detail"]) for i, lv in enumerate(levels[:5]))],
                             ["方差齐性", ("Levene p=%s" % _p(lev_p)) if lev_p is not None else "没算出来"]]},
                    ],
                    "figures": [], "markdown": [],
                    "notes": "要不要换个变量、或者先把数据修一修？改完再跑一次。",
                }
            if _ans2 == "keep":
                use = _mp.override_compare(k, "param")
                ctx.log("按研究员要求，仍使用参数方法（前提不满足，已标注）", "warn")
            elif _ans2 == "nonparam" and use in ("t", "welch", "anova", "anova_welch"):
                use = _mp.override_compare(k, "nonparam")
            plan.append(["研究员的决定", "在检查点上拍板",
                         {"nonparam": "同意改用 %s" % method_map[use],
                          "keep": "坚持参数方法（前提不满足的风险已标注）"}.get(_ans2, _ans2)])

        ctx.log("选定方法：%s" % use)
        ctx.step("method", "选定方法", method_map[use])
        slug = "%s_by_%s" % (_safe(dv), _safe(group))

        # 描述统计表（每组带均值 CI——只报均值不报区间，读者分不清"准"和"不准"）
        desc_rows = []
        for i, lv in enumerate(levels):
            g = groups[i]
            if len(g) > 1:
                se = float(g.std(ddof=1)) / np.sqrt(len(g))
                tc = stats.t.ppf(1 - alpha / 2, len(g) - 1)
                mci = "[%.2f, %.2f]" % (g.mean() - tc * se, g.mean() + tc * se)
            else:
                mci = "—"
            desc_rows.append([str(lv), len(g), round(float(g.mean()), 3), mci,
                              round(float(g.std(ddof=1)), 3) if len(g) > 1 else None,
                              round(float(np.median(g)), 3)])
        tables.append({"name": "各组描述统计", "columns": ["组", "n", "均值", "均值的 95% CI",
                                                          "标准差", "中位数"],
                       "rows": desc_rows,
                       "note": "先看这张表：组间差多少、组内散不散，比 p 值更值得先看。"
                               "**两个组的 CI 明显分开**，比 p<.05 更能说明差异是真的。"})

        # 主检验
        res_rows, concl, method_name = [], "", ""
        if use in ("t", "welch", "mannwhitney"):
            a, b = groups[0], groups[1]
            if use == "mannwhitney":
                U, p = stats.mannwhitneyu(a, b, alternative="two-sided")
                rb = 1 - 2 * U / (len(a) * len(b))          # rank-biserial
                rb_p, rb_z = _rank_biserial_p(rb, len(a), len(b))
                method_name = "Mann-Whitney U"
                res_rows = [["U", _f(U, 1)], ["p", _p(p)],
                            ["效应量 rank-biserial r", _f(rb)],
                            ["  └ 95% CI（近似）", _ci_rb(rb, len(a), len(b), alpha)],
                            ["  └ 效应量的 p", _p(rb_p)],
                            ["中位数", "%s vs %s" % (_f(np.median(a)), _f(np.median(b)))]]
            else:
                t, p = stats.ttest_ind(a, b, equal_var=(use == "t"))
                dval = _cohens_d(a, b)
                method_name = "独立样本 t 检验" if use == "t" else "Welch t 检验"
                res_rows = [["t", _f(t)], ["df", _f(len(a) + len(b) - 2, 1)], ["p", _p(p)],
                            ["均值差", _f(a.mean() - b.mean())],
                            ["  └ 95% CI（均值差）", _ci_mean_diff(a, b, alpha)],
                            ["Cohen's d", _f(dval)],
                            ["  └ 95% CI（近似）",
                             _ci_cohens_d(dval, len(a), len(b), alpha) if dval is not None else "—"]]
            concl = "%s 与 %s 在「%s」上%s（p=%s，α=%.2f）" % (
                levels[0], levels[1], dv, _sig(p, alpha), _p(p), alpha)
            # ⚠ SPSS 的 T-TEST / NPAR TESTS 的**分组变量必须是数字**。
            #   我们的分组常常是「无/有」这种字符串，直接写进去 SPSS 会报
            #   「在仅允许数字变量的位置使用了字符串变量」然后停掉（踩过）。
            gname, glines = _sps_code_var(d, group, levels)
            sps_prelude.extend(glines)
            if use != "mannwhitney":
                dval = _cohens_d(a, b)
                if dval is not None:
                    concl += "；效应量 d=%s（%s），95%% CI %s" % (
                        _f(dval), _d_judge(dval), _ci_cohens_d(dval, len(a), len(b), alpha))
                concl += "；均值差 95%% CI %s" % _ci_mean_diff(a, b, alpha)
                sps_cmds.append("T-TEST GROUPS=%s(1 2)\n  /VARIABLES=%s\n  /CRITERIA=CI(.95)\n"
                                "  /MISSING=ANALYSIS." % (gname, _spss_name(dv)))
            else:
                # ⚠ 原来这条**静默没有效应量**（只在参数检验那边加），
                #   于是"非参数检验"的成绩单上只有 U 和 p —— 读者不知道差异有多大。
                concl += "；效应量 rank-biserial r=%s，95%% CI %s（p=%s）" % (
                    _f(rb), _ci_rb(rb, len(a), len(b), alpha), _p(rb_p))
                concl += "；中位数 %s vs %s" % (_f(np.median(a)), _f(np.median(b)))
                sps_cmds.append("NPAR TESTS\n  /MANN-WHITNEY=%s BY %s(1 2)\n  /MISSING ANALYSIS." % (
                    _spss_name(dv), gname))
        else:
            if use == "kruskal":
                H, p = stats.kruskal(*groups)
                n_all = sum(len(g) for g in groups)
                eps2 = (H - k + 1) / (n_all - k) if n_all > k else None
                method_name = "Kruskal-Wallis"
                # ⚠ 秩检验的 ε² **没有可靠的置信区间**（不像 η² 能走非中心 F）。
                #   与其编一个"看起来像 CI"的数（那是假精确），不如明说不给——
                #   差异的**大小**去看下面「事后两两比较」那张表里的 rank-biserial r。
                res_rows = [["H", _f(H)], ["df", str(k - 1)], ["p", _p(p)],
                            ["效应量 ε²", _f(eps2)],
                            ["  └ 95% CI", "见下方两两比较的 rank-biserial r"]]
            else:
                F, p = stats.f_oneway(*groups)
                ss_b = sum(len(g) * (g.mean() - d[dv].mean()) ** 2 for g in groups)
                ss_t = float(((d[dv] - d[dv].mean()) ** 2).sum())
                eta2 = ss_b / ss_t if ss_t > 0 else None
                eta2ci = _ci_eta2(F, k - 1, len(d) - k, alpha) if eta2 is not None else "—"
                method_name = "单因素方差分析"
                res_rows = [["F", _f(F)], ["df", "%d, %d" % (k - 1, len(d) - k)], ["p", _p(p)],
                            ["η²（效应量）", _f(eta2)],
                            ["  └ 95% CI", eta2ci]]
            concl = "%d 组在「%s」上%s（p=%s，α=%.2f）" % (k, dv, _sig(p, alpha), _p(p), alpha)
            # 多组也一样：SPSS 的分组变量必须数字化（并且 1..k 编号要跟 Python 的分组顺序一致）
            gname, glines = _sps_code_var(d, group, levels)
            sps_prelude.extend(glines)
            if use == "kruskal":
                sps_cmds.append("NPAR TESTS\n  /K-W=%s BY %s(1 %d)\n  /MISSING ANALYSIS." % (
                    _spss_name(dv), gname, k))
            else:
                sps_cmds.append("ONEWAY %s BY %s\n  /STATISTICS DESCRIPTIVES HOMOGENEITY\n"
                                "  /POSTHOC=TUKEY ALPHA(%.2f)\n  /MISSING ANALYSIS." % (
                                    _spss_name(dv), gname, alpha))

        tables.append({"name": "检验结果 · %s" % method_name,
                       "columns": ["指标", "值"], "rows": res_rows, "note": concl})

        # 事后比较（3 组以上且主效应显著）
        if k >= 3 and p is not None and p < alpha:
            post_rows = _posthoc(groups, levels, use, alpha)
            if post_rows:
                tables.append({"name": "事后两两比较", "columns": post_rows[0], "rows": post_rows[1:],
                               "note": "多组比较做了多重校正，别只看单个 p 值下结论。"})

        md.append("## 一、决策树（为什么用这个方法）\n")
        md.append("| 步骤 | 依据 | 结论 |")
        md.append("|---|---|---|")
        for r in plan:
            md.append("| %s | %s | %s |" % tuple(r))
        md.append("\n## 二、结果\n")
        md.append("**%s**：%s\n" % (method_name, concl))
        md.append("| 指标 | 值 |")
        md.append("|---|---|")
        for r in res_rows:
            md.append("| %s | %s |" % tuple(r))
        md.append("")

        if "fig" in gen:
            try:
                plt = kit.setup_matplotlib()
                fig, ax = plt.subplots(figsize=(7.4, 3.9))
                bp = ax.boxplot(groups, labels=[str(l) for l in levels], patch_artist=True,
                                widths=0.55)
                for i, box in enumerate(bp["boxes"]):
                    box.set_facecolor(kit.PALETTE[i % len(kit.PALETTE)])
                    box.set_alpha(0.75)
                for med in bp["medians"]:
                    med.set_color("#1e2430")
                ax.set_ylabel(dv)
                ax.set_title("%s 在 %s 各组的分布" % (dv, group), fontsize=11)
                for i, g in enumerate(groups):
                    ax.text(i + 1, g.mean(), "M=%.2f" % g.mean(), ha="center",
                            va="bottom", fontsize=9, color="#334155")
                fn = "fig_分析_%s_by_%s.png" % (_safe(dv), _safe(group))
                fp = ctx.out_path(fn)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                fig.tight_layout(); fig.savefig(fp); plt.close(fig)
                ctx.made(fp)
                figures.append({"rel": "output/" + fn, "name": "%s × %s 箱线图" % (dv, group),
                                "caption": "箱体是中间 50% 的人，M 是均值"})
            except Exception as e:
                ctx.log("画图失败：%s" % e, "warn")

        # 登记本次的检验（主检验 + 事后两两）—— 供最后的「多重比较总账」
        # ⚠ 事后比较已经在表内做了 Bonferroni（`_posthoc`），所以这里标出来，
        #   免得总账把"校正过的 p"再当成一次原始检验去校正（那是重复校正）。
        try:
            ledger_entries.append({
                "label": "%s 在 %s 各组上的差异" % (dv, group),
                "kind": method_name, "p": float(p),
                "n": int(sum(len(g) for g in groups)),
                "exploratory": False})
            if k >= 3 and p is not None and p < alpha:
                ledger_entries.append({
                    "label": "事后两两比较（%d 组，已做 Bonferroni）" % k,
                    "kind": "posthoc", "p": None, "n": None,
                    "exploratory": True})
        except Exception:
            pass

    # ======================================================================= #
    elif question == "within":
        # 配对 / 前后测（2026-09-26 加）
        # ⚠ 和「组间差异」最要紧的区别：**前提检验落在差值上**。
        #   前后测两列各自偏得厉害、但差值近似正态 → 配对 t 完全没问题。
        #   只看"两列是否各自正态"就换非参数，会白丢配对带来的检验力。
        from core import within as _within
        a_col, b_col = pair_a, pair_b
        if not a_col or not b_col:
            tables.append({
                "name": "配对检验需要两列",
                "columns": ["要填的", "说明"],
                "rows": [["第一列", "一般是前测 / 基线（`pair_a`）"],
                         ["第二列", "一般是后测 / 随访（`pair_b`）"]],
                "note": "差值按 **第二列 − 第一列** 算，方向会写进报告。"
                        "两列必须**一一对应同一个人**——不是两组不同的人。",
            })
            return {"summary": "还差配对的列没选（第一列 / 第二列）—— 填完再跑一次。",
                    "stopped": True, "tables": tables, "figures": [], "markdown": [],
                    "notes": "这次没有产出文件。"}
        for v in (a_col, b_col):
            if v not in df.columns:
                raise ValueError("数据里没有变量「%s」" % v)
        slug = "配对_%s_%s" % (_safe(a_col), _safe(b_col))
        pa = pd.to_numeric(df[a_col], errors="coerce")
        pb = pd.to_numeric(df[b_col], errors="coerce")
        d_all = _within.diffs(pb.values, pa.values)      # 方向：后测 − 前测
        n_pair = len(d_all)
        n_zero = int(np.sum(d_all == 0))
        plan.append(["变量", "%s（第一列）与 %s（第二列）" % (a_col, b_col),
                     "配对数据 → 差值 d = 第二列 − 第一列"])
        plan.append(["有效配对", "n = %d%s" % (n_pair,
                     "（其中 %d 对前后完全一样）" % n_zero if n_zero else ""),
                     "配对 <30 时结论要谨慎" if n_pair < 30 else "配对数量够用"])
        if n_pair < 2:
            raise ValueError("有效配对只有 %d 对，做不了配对检验" % n_pair)

        # 前提：**对差值**做正态性（不是原始两列）
        nd = _normality(d_all, alpha)
        plan.append(["正态性（**看差值**）", nd["detail"],
                     "差值正态 → 配对 t；否则 → Wilcoxon 符号秩"])

        rec = _mp.pick_within(True, bool(nd["ok"]),
                              n_zero_ratio=(n_zero / n_pair if n_pair else None))
        use = rec["method"]
        plan.append(["选定方法", rec["why"], _mp.METHOD_CN.get(use, use)])
        for wn in (rec.get("why_not") or []):
            plan.append(["要注意", wn, ""])

        # 描述统计：两列各自的均值 + 差值的均值/中位数
        desc_rows = [
            [a_col + "（第一列）", n_pair, _f(np.nanmean(pa.values)), _f(np.nanstd(pa.values, ddof=1))],
            [b_col + "（第二列）", n_pair, _f(np.nanmean(pb.values)), _f(np.nanstd(pb.values, ddof=1))],
        ]
        tables.append({"name": "两列各自的情况", "columns": ["列", "n", "均值", "标准差"],
                       "rows": desc_rows,
                       "note": "⚠ **别只看这两列的均值差**：配对设计的信息在**差值**里"
                               "（同一批人，个体差异被消掉了，所以检验力比独立样本高）。"})

        res_rows, concl, method_name = [], "", ""
        if use == "paired_t":
            r = _within.ttest_paired(pb.values, pa.values, alpha)
            method_name = "配对样本 t 检验"
            res_rows = [["t", _f(r["stat"])], ["df", str(r["n_pair"] - 1)],
                        ["p", _p(r["p"])],
                        ["差值均值（后 − 前）", _f(r["mean_diff"])],
                        ["  └ 95% CI", r["ci_str"]],
                        ["差值标准差", _f(r["sd_diff"])],
                        ["效应量 Cohen's d_z", _f(r["dz"])],
                        ["  └ 95% CI（近似）", r["dz_ci"]]]
            concl = "「%s」相对「%s」%s（配对 t：t=%s, df=%d, p=%s，差值均值 %s，95%% CI %s）" % (
                b_col, a_col, _sig(r["p"], alpha), _f(r["stat"]), r["n_pair"] - 1,
                _p(r["p"]), _f(r["mean_diff"]), r["ci_str"])
            if r.get("degenerate"):
                res_rows.append(["⚠ 退化情形", "差值全相等"])
                concl += "。⚠ **所有配对的差值完全一样**（差值标准差 = 0）——" \
                         "这时 p 没有实际意义，先检查数据是不是被改过"
            sps_prelude.append("")
            sps_cmds.append("T-TEST PAIRS=%s WITH %s (PAIRED)\n  /CRITERIA=CI(.95)\n"
                            "  /MISSING=ANALYSIS." % (_spss_name(b_col), _spss_name(a_col)))
            ledger_entries.append({"label": "配对 t：%s − %s" % (b_col, a_col),
                                   "kind": "paired_t", "p": r["p"], "n": r["n_pair"],
                                   "exploratory": False})
        else:
            r = _within.wilcoxon_paired(pb.values, pa.values, alpha)
            method_name = "Wilcoxon 符号秩检验"
            if r.get("error"):
                raise ValueError("Wilcoxon 算不出来：%s" % r["error"])
            res_rows = [["统计量 W", _f(r["stat"])], ["p", _p(r["p"])],
                        ["差值中位数（后 − 前）", _f(r["median_diff"])],
                        ["  └ 95% CI（bootstrap）", r["median_ci"][1]],
                        ["差值四分位距", "%s ~ %s" % (_f(r["iqr_diff"][0]), _f(r["iqr_diff"][1]))],
                        ["效应量 rank-biserial r", _f(r["rank_biserial"])],
                        ["参与秩和的配对", "%d（另有 %d 对前后一样，不参与）"
                         % (r["n_use"], r["n_zero"])]]
            concl = "「%s」相对「%s」%s（Wilcoxon 符号秩：p=%s，差值中位数 %s，95%% CI %s）" % (
                b_col, a_col, _sig(r["p"], alpha), _p(r["p"]),
                _f(r["median_diff"]), r["median_ci"][1])
            if r.get("zero_note"):
                res_rows.append(["⚠ 打平（零差值）", r["zero_note"]])
            sps_cmds.append("NPAR TESTS\n  /WILCOXON=%s WITH %s (PAIRED)\n  /MISSING ANALYSIS."
                            % (_spss_name(b_col), _spss_name(a_col)))
            ledger_entries.append({"label": "Wilcoxon 配对：%s − %s" % (b_col, a_col),
                                   "kind": "wilcoxon", "p": r["p"], "n": r["n_pair"],
                                   "exploratory": False})

        tables.append({"name": "检验结果 · %s" % method_name,
                       "columns": ["指标", "值"], "rows": res_rows, "note": concl})
        ctx.step("method", "选定方法（配对）", method_name)

        md.append("## 一、决策树（为什么用这个方法）\n")
        md.append("| 步骤 | 依据 | 结论 |")
        md.append("|---|---|---|")
        for r2 in plan:
            md.append("| %s | %s | %s |" % tuple(r2))
        md.append("\n## 二、结果\n%s\n" % concl)

        if "fig" in gen:
            try:
                plt = kit.setup_matplotlib()
                fig, ax = plt.subplots(figsize=(7.0, 3.6))
                ax.hist(d_all, bins=min(20, max(6, n_pair // 8)),
                        color="#2f6fed", alpha=0.75, edgecolor="white")
                ax.axvline(0, color="#94a3b8", lw=1.4, ls="--")
                ax.axvline(float(np.median(d_all)), color="#e2664f", lw=1.8)
                ax.set_xlabel("差值（%s − %s）" % (b_col, a_col))
                ax.set_ylabel("人数")
                ax.set_title("配对差值分布（红=中位数，灰虚线=0）", fontsize=11)
                fn = "fig_分析_配对_%s_%s.png" % (_safe(b_col), _safe(a_col))
                fp = ctx.out_path(fn)
                fig.tight_layout(); fig.savefig(fp); plt.close(fig)
                ctx.made(fp)
                figures.append({"rel": "output/" + fn,
                                "name": "配对差值分布 %s − %s" % (b_col, a_col),
                                "caption": "整块分布偏在 0 的哪一侧，就是「变了多少」的方向"})
            except Exception as e:
                ctx.log("画图失败：%s" % e, "warn")

    # ======================================================================= #
    elif question == "causal":
        # 中介 / 调节（2026-09-26 加，第 3 批）
        # ⚠ 它和「关系与预测」是两回事，所以单独一支：
        #   · relate 问"谁和谁有关"
        #   · causal 问"**经由什么**（中介）"或"**在什么条件下**（调节）"
        from core import mediate as _md
        if not dv:
            raise ValueError("中介/调节需要指定因变量（Y）")
        if not (mediator or moderator):
            raise ValueError("请至少填一个：中介变量（M）或调节变量（W）")
        for v in ([dv] + ([mediator] if mediator else []) +
                  ([moderator] if moderator else []) + ivs + controls):
            if v and v not in df.columns:
                raise ValueError("数据里没有变量「%s」" % v)
        xs = [c for c in ivs if c and c != dv]
        if not xs:
            raise ValueError("中介/调节需要一个自变量 X（填在「自变量」那一栏）")
        x = xs[0]

        md.append("## 一、你在问哪一类问题\n")
        md.append("- **中介**问的是「**经由什么**」：X → M → Y\n")
        md.append("- **调节**问的是「**在什么条件下更强**」：X 的作用随 W 变化\n")
        md.append("\n⚠ 两者都**只给统计上的关系**；「X 真的导致 Y」要靠时间先后或实验设计。\n")

        if mediator:
            _med = _md.mediation(df, x, mediator, dv, alpha=alpha,
                                 covariates=controls)
            if _med.get("error"):
                ctx.alert(_med["error"], level="warn", kind="internal")
            else:
                slug = "中介_%s_%s_%s" % (_safe(x), _safe(mediator), _safe(dv))
                plan.append(["研究问题", "X 经由 M 影响 Y", "→ 中介分析（间接效应 a×b）"])
                plan.append(["变量", "X=%s ｜ M=%s ｜ Y=%s%s" % (
                    x, mediator, dv,
                    "｜控制：" + "、".join(_med["covariates"]) if _med["covariates"] else ""),
                    "三条回归（X→M、M→Y、X→Y）"])
                plan.append(["间接效应的区间", "**bootstrap %d 次**（百分位法）" % _med["boot_n"],
                             "不用 Sobel：a×b 的分布不正态"])
                rows = [
                    ["a：X → M", _f(_med["a"]), _f(_med["a_se"]), _p(_med["a_p"]), _med["a_ci"]],
                    ["b：M → Y（控制 X）", _f(_med["b"]), _f(_med["b_se"]), _p(_med["b_p"]), _med["b_ci"]],
                    ["c：X → Y（总效应）", _f(_med["c"]), _f(_med["c_se"]), _p(_med["c_p"]), _med["c_ci"]],
                    ["c′：X → Y（控制 M 后）", _f(_med["c_prime"]), _f(_med["cp_se"]),
                     _p(_med["cp_p"]), _med["cp_ci"]],
                    ["**间接效应 a×b**", _f(_med["indirect"]), "—", "—",
                     "[%.3f, %.3f]" % _med["boot_ci"] if _med["boot_ci"] else "—"],
                ]
                if _med["prop_mediated"] is not None:
                    rows.append(["中介占比 a×b / c", "%.1f%%" % (_med["prop_mediated"] * 100),
                                 "—", "—", "—"])
                tables.append({
                    "name": "中介分析（X → M → Y）",
                    "columns": ["路径", "系数", "标准误", "p", "95% CI"],
                    "rows": rows,
                    "note": "**看最后一行**：间接效应 a×b 的 bootstrap 区间**不跨 0** 才算有中介。"
                            "判断：%s（n=%d）。\n"
                            "⚠ bootstrap 区间用的是**百分位法**，不做偏差校正；"
                            "固定种子所以每次跑出来一样（可复现）。" % (_med["kind"], _med["n"]),
                })
                concl = "间接效应 a×b=%s，bootstrap 95%% CI [%.3f, %.3f] → %s；" \
                        "总效应 c=%s，控制 M 后直接效应 c′=%s" % (
                            _f(_med["indirect"]), _med["boot_ci"][0], _med["boot_ci"][1],
                            _med["kind"], _f(_med["c"]), _f(_med["c_prime"]))
                ctx.step("method", "中介分析", concl[:80])
                ledger_entries.append({
                    "label": "中介间接效应 %s→%s→%s" % (x, mediator, dv),
                    "kind": "mediation",
                    # bootstrap 区间不跨 0 ⇔ 显著，换算成一个"等效 p"没法做，
                    # 所以用区间的定性结论登记（p 记成 0.049 / 0.051 表示两端）
                    "p": 0.049 if _med["significant"] else 0.51,
                    "n": _med["n"], "exploratory": False})
                md.append("### 中介结果\n%s\n" % concl)
                md.append("| 路径 | 系数 | 标准误 | p | 95% CI |")
                md.append("|---|---|---|---|---|")
                for r2 in rows:
                    md.append("| " + " | ".join(str(x2) for x2 in r2) + " |")
                md.append("")

        if moderator:
            _mod = _md.moderation(df, x, moderator, dv, alpha=alpha,
                                  covariates=controls)
            if _mod.get("error"):
                ctx.alert(_mod["error"], level="warn", kind="internal")
            else:
                slug = "调节_%s_%s_%s" % (_safe(x), _safe(moderator), _safe(dv))
                plan.append(["研究问题", "X 的作用随 W 变化", "→ 调节分析（交互项）"])
                plan.append(["变量", "X=%s ｜ W=%s ｜ Y=%s" % (x, moderator, dv),
                             "X、W **都先对中**再加交互项"])
                plan.append(["交互项", "b=%s，p=%s" % (_f(_mod["b_int"]), _p(_mod["p_int"])),
                             "**%s**" % ("有调节作用" if _mod["significant"] else "没有证据说有调节")])
                from core import regress as _rgm
                rows = [
                    ["X 主效应（W 平均时）", _f(_mod["b_x"]), _p(
                        _mod["fit"]["p"][1]), _mod["x_ci"]],
                    ["W 主效应", _f(_mod["b_w"]), _p(_mod["fit"]["p"][2]),
                     _rgm.ci_beta(_mod["b_w"], float(_mod["fit"]["se"][2]), _mod["dof"])],
                    ["**X×W 交互项**", _f(_mod["b_int"]), _p(_mod["p_int"]), _mod["int_ci"]],
                ]
                tables.append({
                    "name": "调节分析（交互项）",
                    "columns": ["项", "系数", "p", "95% CI"], "rows": rows,
                    "note": "**只看交互项那一行**：它显著才叫有调节作用；"
                            "X 主效应显著**不等于**有调节。\n"
                            "（X、W 都已对中，所以「X 主效应」= 在 W 平均值上 X 的作用。）",
                })
                sl_rows = [[("W 偏低（%.2f）" % s["w_actual"] if i == 0 else
                             "W 平均（%.2f）" % s["w_actual"] if i == 1 else
                             "W 偏高（%.2f）" % s["w_actual"]),
                            _f(s["slope"]), _f(s["se"]), _p(s["p"]), s["ci"],
                            _sig(s["p"], alpha) if s["p"] is not None else "—"]
                           for i, s in enumerate(_mod["slopes"])]
                tables.append({
                    "name": "简单斜率（W 取低/中/高时 X 的作用）",
                    "columns": ["W 的位置", "X 的斜率", "标准误", "p", "95% CI", "结论"],
                    "rows": sl_rows,
                    "note": "简单斜率就是「在 W 等于某个值时，X 每变 1 个单位 Y 变多少」。"
                            "低/高取的是**均值 ±1 个标准差**（这是惯例，也可以自己换点看）。",
                })
                if _mod["jn_roots"]:
                    tables.append({
                        "name": "Johnson-Neyman：W 在什么范围内 X 的作用显著",
                        "columns": ["项", "值"],
                        "rows": [["转折点（W 的实际值）",
                                  "、".join("%.3f" % v for v in _mod["jn_roots"])],
                                 ["W 的均值 ± 标准差",
                                  "%.2f ± %.2f" % (_mod["w_mean"], _mod["w_sd"])]],
                        "note": "两个转折点把 W 分成三段：中间一段 X 的作用**不显著**，"
                                "两端显著（或反过来）。它比「只报 ±1SD 两个点」信息量大得多 —— "
                                "但转折点可能落在数据的实际范围之外，那种要说明。",
                    })
                concl = "交互项 b=%s（95%% CI %s，p=%s）→ %s；" \
                        "X 的简单斜率从 W 低时的 %s 变到 W 高时的 %s" % (
                            _f(_mod["b_int"]), _mod["int_ci"], _p(_mod["p_int"]),
                            "**有调节作用**" if _mod["significant"] else "没有证据说有调节",
                            _f(_mod["slopes"][0]["slope"]), _f(_mod["slopes"][2]["slope"]))
                ctx.step("method", "调节分析", concl[:80])
                ledger_entries.append({
                    "label": "调节交互项 %s×%s（%s）" % (x, moderator, dv),
                    "kind": "moderation", "p": _mod["p_int"], "n": _mod["n"],
                    "exploratory": False})
                md.append("### 调节结果\n%s\n" % concl)

        # 画一张简单斜率图（有调节时才有意义）
        if moderator and "fig" in gen:
            try:
                _mod2 = _md.moderation(df, x, moderator, dv, alpha=alpha,
                                       covariates=controls)
                if _mod2.get("slopes"):
                    plt = kit.setup_matplotlib()
                    fig, ax = plt.subplots(figsize=(6.6, 4.0))
                    xs_line = np.linspace(-2, 2, 50)
                    for i, s in enumerate(_mod2["slopes"]):
                        yy_line = (s["slope"]) * xs_line
                        ax.plot(xs_line, yy_line, lw=1.9,
                                color=kit.PALETTE[i % len(kit.PALETTE)],
                                label="W 偏低" if i == 0 else ("W 平均" if i == 1 else "W 偏高"))
                    ax.axhline(0, color="#94a3b8", lw=1)
                    ax.axvline(0, color="#94a3b8", lw=1)
                    ax.set_xlabel("%s（已对中）" % x)
                    ax.set_ylabel("%s 的预测变化" % dv)
                    ax.set_title("简单斜率：X 对 Y 的作用随 W 怎么变", fontsize=11)
                    ax.legend(fontsize=9, frameon=False)
                    fn = "fig_分析_调节_%s_%s.png" % (_safe(x), _safe(moderator))
                    fp = ctx.out_path(fn)
                    # ⚠ `out_path()` **只拼路径、不建目录** —— 别的分支都自己 makedirs，
                    #   这里第一版漏了，于是报 "No such file or directory ...\output\fi…"，
                    #   而且被 except 吞成一条 warn，图上什么都不显示（端到端才看出来）。
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                    fig.tight_layout(); fig.savefig(fp); plt.close(fig)
                    ctx.made(fp)
                    figures.append({"rel": "output/" + fn,
                                    "name": "简单斜率图 %s × %s" % (x, moderator),
                                    "caption": "三条线越不平行，说明调节作用越强"})
            except Exception as e:
                ctx.log("简单斜率图画不出来：%s" % e, "warn")

    # ======================================================================= #
    elif question == "relate":
        if not dv:
            raise ValueError("「关系与预测」需要指定因变量（要预测的那个指标）")
        ivs = [c for c in ivs if c in df.columns and c != dv]
        if not ivs:
            raise ValueError("至少要有一个自变量（可以和数据里任意一列比较）")
        slug = ("相关_%s_%s" % (_safe(dv), _safe(ivs[0]))) if len(ivs) == 1 \
            else ("回归_%s" % _safe(dv))

        if len(ivs) == 1:
            x, y = ivs[0], dv
            d = pd.DataFrame({x: pd.to_numeric(df[x], errors="coerce"),
                              y: pd.to_numeric(df[y], errors="coerce")}).dropna()
            nx, ny = _normality(d[x], alpha), _normality(d[y], alpha)
            use_pearson = bool(nx["ok"] and ny["ok"])
            plan.append(["变量类型", "%s(%s) 与 %s(%s)" % (x, kinds.get(x), y, kinds.get(y)),
                         "都是连续 → 可以算相关"])

            # ⚠ **三个系数一起算、一起报**（2026-09-26 修）。原来这里按 Shapiro-Wilk 的 p
            #   自动二选一，然后只报换完的那一个 —— 实测同一对变量：
            #   含极端值时 Pearson 0.260 / Spearman 0.735，剔掉 3 个点后变成 0.717 / 0.737。
            #   差 2.7 倍，而报告里只有其中一个数、还说不出另一个是多少。
            #   而且这三个数回答的是**不同问题**（线性 / 单调 / 秩一致），
            #   不是"哪个对"——它们差多少本身就是结论的一部分。
            trio, gap_note = _corr_trio(d, x, y, alpha)
            method_name = "Pearson 相关" if use_pearson else "Spearman 秩相关"
            _pk = trio.get("pearson") or {}
            _sk = trio.get("spearman") or {}
            r = _pk.get("r", 0.0) if use_pearson else _sk.get("r", 0.0)
            p = _pk.get("p") if use_pearson else _sk.get("p")

            plan.append(["正态性", "%s: %s；%s: %s" % (x, nx["detail"], y, ny["detail"]),
                         "都正态 → 以 Pearson 为主；否则以 Spearman 为主。"
                         "**但三个系数都会报出来**，选哪个由你看差值决定"])
            plan.append(["三个系数", "Pearson / Spearman / Kendall 一起算",
                         "它们回答不同问题：线性 / 单调 / 秩一致。差值大 = 关系非线性或受极端值影响"])
            plan.append(["选定主报", "按上面正态性那条",
                         "%s —— 但下表三个都在，别只看这一个" % method_name])

            if use_pearson:
                sps_cmds.append("CORRELATIONS\n  /VARIABLES=%s %s\n  /PRINT=TWOTAIL NOSIG\n  /MISSING=PAIRWISE." % (
                    _spss_name(x), _spss_name(y)))
            else:
                sps_cmds.append("NONPAR CORR\n  /VARIABLES=%s %s\n  /PRINT=SPEARMAN TWOTAIL NOSIG\n  /MISSING=PAIRWISE." % (
                    _spss_name(x), _spss_name(y)))

            # 三个系数并排（各自带 CI）—— 这张表就是这一轮修复的核心产物
            trio_rows = []
            primary_key = "pearson" if use_pearson else "spearman"
            for key, label, means in (
                    ("pearson", "Pearson r（线性）", "线性关系的强度，受极端值影响大"),
                    ("spearman", "Spearman ρ（单调）", "单调关系的强度，不受极端值影响"),
                    ("kendall", "Kendall τ（秩一致）", "秩一致性，小样本/并列值多时更稳")):
                t = trio.get(key)
                if not t:
                    trio_rows.append([label, "—", "—", "—", "算不出来"])
                    continue
                # ⚠ 只能有一个主报。原来写成 `(key == "pearson") == use_pearson`，
                #   于是 Kendall 会跟着 Spearman 一起被标上「主报」（实测渲染出来两个）。
                star = "  **← 主报**" if key == primary_key else ""
                trio_rows.append([label + star, _f(t["r"]), t["ci"], _p(t["p"]), means])
            tables.append({
                "name": "相关 · %s × %s" % (x, y),
                "columns": ["种类", "系数", "95% CI", "p", "它回答的问题"],
                "rows": trio_rows,
                "note": ("**这一对变量给了三个系数，是因为它们量的是不同东西。** " + gap_note +
                         " 判断「有多强」看系数绝对值，判断「有多准」看 CI 宽窄——"
                         "p 只回答「是不是 0」。相关不等于因果。"),
            })

            # 单独一张"主报哪个"的表，把选择摊开
            tables.append({
                "name": "主报哪个系数（我为什么这样选）",
                "columns": ["依据", "结论"],
                "rows": [
                    ["正态性", "都满足 → 用 Pearson；否则用 Spearman（秩相关不要求正态）"],
                    ["实际判定", "%s: %s ｜ %s: %s" % (x, nx["test"], y, ny["test"])],
                    ["我主报", method_name],
                    ["⚠ 但这不代表另一个没用", gap_note or "三个系数差异不大，读法一致"],
                ],
                "note": "选主报只是「哪个更适合当主指标」，不是「另一个可以不看」。",
            })

            # ---------- 偏相关：扣掉控制变量之后还剩多少关系 ----------
            # ⚠ 为什么值得单独一张表：**"看起来有关"往往是第三个变量同时推高了两边**。
            #   实测：x 与 y 的普通相关 r=0.671，扣掉共同原因 z 之后掉到 −0.129 ——
            #   结论整个反过来。不报这一张，研究员会拿 0.671 去写"两者高度相关"。
            if controls:
                pc = _partial_corr(pd.DataFrame({x: pd.to_numeric(df[x], errors="coerce"),
                                                 y: pd.to_numeric(df[y], errors="coerce"),
                                                 **{c: pd.to_numeric(df[c], errors="coerce")
                                                    for c in controls if c in df.columns}}),
                                   x, y, [c for c in controls if c in df.columns], alpha)
                if pc:
                    _r0 = _pk.get("r")
                    _drop = (abs(_r0) - abs(pc["r"])) if _r0 is not None else None
                    tables.insert(len(tables) - 1, {
                        "name": "偏相关（扣掉控制变量之后）",
                        "columns": ["项", "值"],
                        "rows": [["控制变量", "、".join(pc["controls"])],
                                 ["普通 Pearson r（不扣）", _f(_r0)],
                                 ["偏相关 r（扣掉后）", _f(pc["r"])],
                                 ["  └ 95% CI", pc["ci"]],
                                 ["p", _p(pc["p"])],
                                 ["自由度 df", str(pc["df"])],
                                 ["有效 n", str(pc["n"])]],
                        "note": ("**扣掉 %s 之后，关系从 %s 变成 %s**%s\n"
                                 "偏相关就是「把这个变量按住不动，再看这两个还剩多少关系」——"
                                 "它和 SPSS 的 `PARTIAL CORR` 是同一个定义，数字应当对得上。"
                                 % ("、".join(pc["controls"]), _f(_r0), _f(pc["r"]),
                                    ("（掉了 %.3f，说明**原来的相关有相当一部分是它造成的**）"
                                     % _drop) if (_drop is not None and _drop >= 0.10)
                                    else "（变化不大，说明这段关系不是它造成的）")),
                    })
                    concl += "。扣掉「%s」之后偏相关 r=%s（p=%s，df=%d）" % (
                        "、".join(pc["controls"]), _f(pc["r"]), _p(pc["p"]), pc["df"])
                    ledger_entries.append({
                        "label": "偏相关 %s × %s（控制 %s）" % (x, y, "、".join(pc["controls"])),
                        "kind": "partial", "p": pc["p"], "n": pc["n"],
                        "exploratory": False})
                    sps_cmds.append("PARTIAL CORR\n  /VARIABLES=%s %s BY %s\n"
                                    "  /SIGNIFICANCE=TWOTAIL\n  /MISSING=LISTWISE."
                                    % (_spss_name(x), _spss_name(y),
                                       " ".join(_spss_name(c) for c in pc["controls"])))
                    md.append("\n### 偏相关\n")
                    md.append("控制「%s」之后，r 从 %s 变成 %s（p=%s）。\n"
                              % ("、".join(pc["controls"]), _f(_r0), _f(pc["r"]), _p(pc["p"])))
                else:
                    ctx.alert("偏相关没算出来（控制变量可能有缺失或类型不对）—— "
                              "已经跳过它，其余结果不受影响。", level="warn", kind="internal")

            concl = "%s 与 %s 之间的**单调**关系%s（ρ=%s，95%% CI %s，p=%s，n=%d）" % (
                x, y, _r_judge(_sk.get("r")), _f(_sk.get("r")),
                _sk.get("ci", "—"), _p(_sk.get("p")), len(d))
            concl += "；线性读法下 Pearson r=%s（95%% CI %s，p=%s）" % (
                _f(_pk.get("r")), _pk.get("ci", "—"), _p(_pk.get("p")))
            if gap_note:
                concl += "。⚠ " + gap_note

            md.append("## 一、决策树\n")
            md.append("| 步骤 | 依据 | 结论 |")
            md.append("|---|---|---|")
            for r2 in plan:
                md.append("| %s | %s | %s |" % tuple(r2))
            md.append("\n## 二、结果\n%s\n" % concl)

            if "fig" in gen:
                try:
                    plt = kit.setup_matplotlib()
                    fig, ax = plt.subplots(figsize=(6.4, 4.2))
                    ax.scatter(d[x], d[y], s=22, alpha=0.6, color="#2f6fed", edgecolors="none")
                    z = np.polyfit(d[x], d[y], 1)
                    xs = np.linspace(d[x].min(), d[x].max(), 50)
                    ax.plot(xs, np.polyval(z, xs), color="#e2664f", lw=1.8)
                    ax.set_xlabel(x); ax.set_ylabel(y)
                    ax.set_title("%s × %s（Pearson r=%s ／ Spearman ρ=%s）"
                                 % (x, y, _f(_pk.get("r")), _f(_sk.get("r"))), fontsize=11)
                    fn = "fig_分析_相关_%s_%s.png" % (_safe(x), _safe(y))
                    fp = ctx.out_path(fn)
                    fig.tight_layout(); fig.savefig(fp); plt.close(fig)
                    ctx.made(fp)
                    figures.append({"rel": "output/" + fn, "name": "散点图 %s × %s" % (x, y),
                                    "caption": "红线是简单回归线；标题里两个系数都写了"})
                except Exception as e:
                    ctx.log("画图失败：%s" % e, "warn")

            # 登记：三个系数**各算一个检验**（它们问的是同一个问题的三种读法，
            # 但按"跑了多少次检验"的实情，确实算了三次——总账要如实）。
            for _key, _nm in (("pearson", "Pearson r"), ("spearman", "Spearman ρ"),
                              ("kendall", "Kendall τ")):
                _t = trio.get(_key)
                if _t:
                    ledger_entries.append({
                        "label": "%s × %s（%s）" % (x, y, _nm), "kind": _key,
                        "p": _t["p"], "n": _t["n"], "exploratory": False})

            # ---------- 结论敏感度：去掉几个个体，结论还一样吗 ----------
            # ⚠ 这一段是这一轮最重要的补充。实测：3 行（0.5%）就能让 r 从 0.72 掉到 0.26，
            #   而原来的报告一个字都不提。**它不删数据，只把"结论由谁决定"摆出来。**
            sens = _sensitivity(d, x, y, alpha)
            if sens and sens.get("n_flagged"):
                if sens.get("all"):
                    a_, b_ = sens["all"], sens["clean"]
                    sens_rows = [
                        ["含全部", a_["n"], _f(a_["r"]), _p(a_["p"]), _f(a_["r2"])],
                        ["去掉那 %d 个" % sens["n_flagged"], b_["n"], _f(b_["r"]),
                         _p(b_["p"]), _f(b_["r2"])],
                    ]
                else:
                    sens_rows = [["含全部", sens["n"], "—", "—", "—"]]
                if sens.get("cases"):
                    sens_rows += [["  · 第 %d 行（x=%s, y=%s, Cook's D=%s）"
                                   % (c[0], _f(c[1]), _f(c[2]), _f(c[3], 2)),
                                   "", "", "", ""] for c in sens["cases"][:5]]
                _flip = sens.get("flip")
                tables.append({
                    "name": "结论敏感度（去掉影响大的个体还成立吗）",
                    "columns": ["版本", "n", "Pearson r", "p", "R²"],
                    "rows": sens_rows,
                    "note": (
                        "⚠ **结论由少数个体决定**：去掉这 %d 个（占 %.1f%%），"
                        "r 从 %s 变成 %s、R² 从 %s 变成 %s。"
                        "**这不代表他们是「坏数据」**——删不删、怎么处理是你的事；"
                        "但报告里必须写明这一点，否则别人复现不出来。"
                        % (sens["n_flagged"], sens["n_flagged"] / max(sens["n"], 1) * 100,
                           _f(a_["r"]) if sens.get("all") else "—",
                           _f(b_["r"]) if sens.get("all") else "—",
                           _f(a_["r2"]) if sens.get("all") else "—",
                           _f(b_["r2"]) if sens.get("all") else "—")
                        if _flip else
                        "去掉影响最大的 %d 个个体后，结论没变（r 只动了 %s）——"
                        "说明这个关系不是几个极端值撑起来的，可以更放心。"
                        % (sens["n_flagged"], _f(sens.get("delta_r", 0)))),
                })
                if _flip:
                    ctx.alert("**结论对少数个体敏感**：去掉 %d 个影响大的个体后，"
                              "相关系数从 %s 变成 %s。"
                              % (sens["n_flagged"],
                                 _f(a_["r"]) if sens.get("all") else "—",
                                 _f(b_["r"]) if sens.get("all") else "—"),
                              level="warn", kind="internal",
                              fix="先回去看这几行是不是录入错误 / 异常作答（表里列了是哪几行）；"
                                  "**不要只为了让结果好看就删掉它们**——"
                                  "删的话理由要写进报告，并且两版都报。")
                    md.append("\n### ⚠ 结论敏感度\n")
                    md.append("去掉 %d 个影响大的个体后，r 从 %s 变成 %s、R² 从 %s 变成 %s —— "
                              "**结论由少数个体决定**，报告里必须写明。\n"
                              % (sens["n_flagged"],
                                 _f(a_["r"]) if sens.get("all") else "—",
                                 _f(b_["r"]) if sens.get("all") else "—",
                                 _f(a_["r2"]) if sens.get("all") else "—",
                                 _f(b_["r2"]) if sens.get("all") else "—"))
        # ---------- 两条路：因变量两类走 logistic，否则走最小二乘 ----------
        # ⚠ OLS 那段抽成函数是**必须**的：不抽的话走 logistic 时它照样执行一遍
        #   （把结果覆盖掉、还白算一遍）。抽完 `else:` 才真的是二选一。
        def _ols_regression():
            """多元线性回归 + 完整诊断 + 结论敏感度。"""
            # ⚠ nonlocal 只写真的会被重新赋值的那个（rows）。
            #   写 `nonlocal xnames` 会报 no binding —— run() 里没给 xnames 赋过值。
            nonlocal rows
            cols = ivs + [dv]
            d = df[cols].copy()
            d[dv] = pd.to_numeric(d[dv], errors="coerce")
            for c in ivs:
                if kinds.get(c) != "categorical":
                    d[c] = pd.to_numeric(d[c], errors="coerce")
            d = d.dropna()
            if len(d) < 10:
                raise ValueError("有效样本只有 %d 行，做不了回归" % len(d))
            X, xnames = _dummies(d, ivs, kinds)
            # ⚠ SPSS 那边的 REGRESSION **只吃数字变量**。Python 已经把分类变量拆成哑变量了，
            #   生成的语法也必须照做，否则 SPSS 会报「在仅允许数字变量的位置使用了字符串变量」
            #   然后整个命令停掉 —— 导出的 HTML 里只有一句报错、没有结果表（踩过）。
            pre_lines, sp_names = _sps_cat_prelude(d, ivs, kinds)
            sps_prelude.extend(pre_lines)
            y = d[dv].values.astype(float)
            fit = _ols(X, y)
            plan.append(["变量", "因变量 %s；自变量 %s" % (dv, "、".join(ivs)),
                         "多个自变量 → 多元线性回归"])
            plan.append(["样本量", "n=%d，参数 %d 个" % (fit["n"], fit["k"] - 1),
                         "一般每个自变量至少 10~20 个样本" if fit["n"] < 20 * (fit["k"] - 1)
                         else "样本量够用"])
            plan.append(["选定方法", "连续因变量 + 多个自变量", "多元线性回归（最小二乘）"])

            # ---------- 回归诊断：光看系数和 R² 是不够的 ----------
            Xd = np.column_stack([np.ones(len(y)), X])
            dia = kit.regression_diagnostics(Xd, y, fit["beta"], ["（常数项）"] + list(xnames))
            sbeta = dia.get("std_beta") or []

            rows = [["（常数项）", _f(fit["beta"][0]), _f(fit["se"][0]),
                     _f(fit["t"][0]), _p(fit["p"][0]),
                     _ci_beta(fit["beta"][0], fit["se"][0], fit["dof"], alpha), "—"]]
            for i, nm in enumerate(xnames, start=1):
                sb = sbeta[i - 1] if (i - 1) < len(sbeta) else None
                rows.append([nm, _f(fit["beta"][i]), _f(fit["se"][i]),
                             _f(fit["t"][i]), _p(fit["p"][i]),
                             _ci_beta(fit["beta"][i], fit["se"][i], fit["dof"], alpha),
                             _f(sb)])
            tables.append({
                "name": "回归系数",
                "columns": ["项", "B", "标准误", "t", "p", "95% CI", "标准化 β"],
                "rows": rows,
                "note": "B 是「其它不变时，这一项每变 1 个单位，因变量变多少」，受量纲影响；"
                        "**横向比「谁更重要」要看标准化 β**（绝对值越大越重要）。"
                        "**看 95% CI 有没有跨过 0**：跨 0 = 这个系数的方向都不确定，"
                        "别只看 p 值是不是 <.05。",
            })

            vifs = dia.get("vifs") or []
            diag_rows = []
            for i, nm in enumerate(xnames):
                v = vifs[i] if i < len(vifs) else None
                if v is None:
                    continue
                judge = ("严重共线 ⚠" if v > float(_sr_get("regression.vif_serious", 10))
                 else ("需注意" if v > float(_sr_get("regression.vif_watch", 5)) else "OK"))
                diag_rows.append([nm, _f(v, 2), judge])
            pn = dia.get("p_normality")
            diag_rows.append(["残差正态性（Shapiro-Wilk）", _p(pn),
                              "OK" if (pn is None or pn > alpha) else "残差偏离正态 ⚠"])
            bp = dia.get("bp_p")
            diag_rows.append(["异方差（Breusch-Pagan）", _p(bp),
                              "OK" if (bp is None or bp > alpha) else "存在异方差 ⚠"])
            dw = dia.get("dw")
            diag_rows.append(["自相关（Durbin-Watson）", _f(dw, 2),
                              "OK" if (dw is None or float(_sr_get("regression.dw_low", 1.5))
                      <= dw <= float(_sr_get("regression.dw_high", 2.5)))
            else "可能自相关 ⚠"])
            ninf = dia.get("n_influential") or 0
            nlarge = dia.get("n_large_influence") or 0
            influ_val = "%d 个 > 4/n" % ninf + ("，其中 %d 个 > 1" % nlarge if nlarge else "")
            influ_judge = ("OK" if not ninf else
                           ("有 %d 个大影响点 ⚠" % nlarge if nlarge else "个别点偏大，看一眼就行"))
            diag_rows.append(["强影响点（Cook's D）", influ_val, influ_judge])
            tables.append({
                "name": "回归诊断", "columns": ["项目", "值", "判断"], "rows": diag_rows,
                "note": "VIF>10 = 严重共线性（系数不稳，别拿它排重要性）。"
                        "⚠ 但要注意：**分类变量拆成哑变量之后，同一组的各档之间天然相关，VIF 会偏高**——"
                        "这是编码方式造成的，不用慌；真正该警惕的是不同概念之间的共线。\n"
                        "残差偏态 / 异方差 → p 值可能偏乐观；强影响点看 Cook's D："
                        "> 4/n 只是「值得看一眼」，**> 1 才算真正的大影响点**。",
            })

            fit_rows = [["R²", _f(fit["r2"])], ["调整 R²", _f(fit["adj_r2"])],
                        ["F", _f(fit["F"])], ["p(F)", _p(fit["pF"])],
                        ["n", fit["n"]], ["自变量个数", fit["k"] - 1]]
            tables.append({"name": "模型整体", "columns": ["指标", "值"], "rows": fit_rows,
                           "note": "R² 说明这些自变量一起解释了多少变异（不是因果，也不是预测力的唯一标准）。"})
            plan.append(["模型拟合", "R²=%s，调整 R²=%s，F 检验 p=%s" % (
                _f(fit["r2"]), _f(fit["adj_r2"]), _p(fit["pF"])),
                "整体%s" % _sig(fit["pF"], alpha)])

            # ---------- 检查点：诊断有问题才停下来问 ----------
            problems = []
            mv = dia.get("max_vif")
            if mv is not None and mv > float(_sr_get("regression.vif_serious", 10)):
                problems.append("多重共线性（VIF 最大 %.1f）" % mv)
            elif mv is not None and mv > float(_sr_get("regression.vif_watch", 5)):
                problems.append("共线性偏高（VIF 最大 %.1f）" % mv)
            if pn is not None and pn <= alpha:
                problems.append("残差偏离正态")
            if bp is not None and bp <= alpha:
                problems.append("存在异方差")
            if nlarge:
                problems.append("%d 个强影响点（Cook's D > 1）" % nlarge)

            diag_md = ["### 回归诊断\n", "| 项目 | 值 | 判断 |", "|---|---|---|"]
            for r2 in diag_rows:
                diag_md.append("| " + " | ".join(str(x) for x in r2) + " |")
            diag_md.append("")

            if problems:
                _ans3 = ctx.ask(
                    "diag",
                    "回归诊断发现：%s —— 结果还信得过吗？" % "、".join(problems),
                    "这些不算「算错了」，而是**结论要打折扣**：\n"
                    "· 共线性高 → 单个变量的系数不稳定，别拿它排重要性\n"
                    "· 残差偏态 / 异方差 → p 值可能偏乐观，别只看星号\n"
                    "· 强影响点 → 值得回去看那几个样本是不是异常作答\n\n"
                    "继续的话，我会把这些写进报告的「局限」里。",
                    options=[
                        {"value": "ok", "label": "知道了，继续出报告", "hint": "诊断结果会进报告的局限一节"},
                        {"value": "stop", "label": "停一下，我先看数据", "hint": "本次不生成报告"},
                    ],
                    default="ok",
                    rows=diag_rows, columns=["项目", "值", "判断"],
                )
                if _ans3 == "stop":
                    ctx.log("研究员要求停下：回归诊断有问题，先看数据", "warn")
                    return {
                        "summary": "按你的要求停在这里 —— 回归诊断有问题，本次没有生成报告。",
                        "stopped": True,
                        "tables": [
                            {"name": "分析计划（到此为止）", "columns": ["步骤", "依据", "结论"], "rows": plan},
                            {"name": "回归诊断", "columns": ["项目", "值", "判断"], "rows": diag_rows,
                             "note": "先把这些问题处理掉，结论才站得住。"},
                        ],
                        "figures": [], "markdown": [],
                        "notes": "修完数据再跑一次就行。",
                    }

            concl = "回归模型整体%s（F=%s, p=%s），R²=%s（调整后 %s）；样本 n=%d" % (
                _sig(fit["pF"], alpha), _f(fit["F"]), _p(fit["pF"]),
                _f(fit["r2"]), _f(fit["adj_r2"]), fit["n"])
            if problems:
                concl += "。⚠ 诊断发现：%s" % "、".join(problems)

            md.append("## 一、决策树\n")
            md.append("| 步骤 | 依据 | 结论 |")
            md.append("|---|---|---|")
            for r2 in plan:
                md.append("| %s | %s | %s |" % tuple(r2))
            md.append("\n## 二、回归结果\n%s\n" % concl)
            md.append("| 项 | B | 标准误 | t | p | 95% CI | 标准化 β |")
            md.append("|---|---|---|---|---|---|---|")
            for r2 in rows:
                md.append("| " + " | ".join(str(x) for x in r2) + " |")
            md.append("")
            md.extend(diag_md)

            sps_cmds.append("REGRESSION\n  /MISSING LISTWISE\n  /STATISTICS COEFF OUTS R ANOVA\n"
                            "  /CRITERIA=PIN(.05) POUT(.10)\n  /NOORIGIN\n  /DEPENDENT %s\n"
                            "  /METHOD=ENTER %s." % (_spss_name(dv),
                                                    " ".join(sp_names)))

            if "fig" in gen:
                try:
                    plt = kit.setup_matplotlib()
                    names = ["(常数)"] + xnames
                    bs = list(fit["beta"])[1:]
                    ps = list(fit["p"])[1:]
                    order = np.argsort(np.abs(bs))
                    fig, ax = plt.subplots(figsize=(7.0, max(2.6, 0.42 * len(bs) + 1.4)))
                    colors = ["#2f6fed" if ps[i] < alpha else "#9aa3b2" for i in order]
                    ax.barh([xnames[i][:24] for i in order], [bs[i] for i in order],
                            color=colors)
                    ax.axvline(0, color="#94a3b8", lw=1)
                    ax.set_xlabel("回归系数 B")
                    ax.set_title("各自变量对「%s」的作用（蓝=显著）" % dv, fontsize=11)
                    fn = "fig_分析_回归_%s.png" % _safe(dv)
                    fp = ctx.out_path(fn)
                    fig.tight_layout(); fig.savefig(fp); plt.close(fig)
                    ctx.made(fp)
                    figures.append({"rel": "output/" + fn, "name": "回归系数图",
                                    "caption": "蓝色表示 p<%.2f" % alpha})
                except Exception as e:
                    ctx.log("画图失败：%s" % e, "warn")

            # 登记回归：整体 F 一次 + **每个系数各一次**。
            # ⚠ 系数那几次是很多人忽略的：一张回归表上 4 个自变量就报了 4 个 p 值，
            #   它们同样会累积假阳性（"哪个自变量显著"就是在挑最显著的那个）。
            try:
                ledger_entries.append({
                    "label": "回归整体 F 检验（%s）" % dv, "kind": "F",
                    "p": fit["pF"], "n": fit["n"], "exploratory": False})
                for _i, _nm in enumerate(xnames):
                    ledger_entries.append({
                        "label": "回归系数 %s（%s）" % (_nm, dv), "kind": "beta",
                        "p": fit["p"][_i + 1], "n": fit["n"], "exploratory": False})
            except Exception:
                pass

            # ---------- 回归版的「结论敏感度」----------
            # 用**最强影响点**做对照：去掉 Cook's D 最大的那几个，主系数和 R² 会怎样。
            # ⚠ 为什么回归这条更要紧：实测那份数据 3 行就能让 R² 从 0.51 掉到 0.07，
            #   而 ⑥ 原来只把 Cook's D 标成"值得看一眼"，**没说结论依赖它**。
            try:
                Xd0 = np.column_stack([np.ones(len(y)), X])
                _dia = kit.regression_diagnostics(Xd0, y, fit["beta"],
                                                  ["（常数项）"] + list(xnames))
                _cooks = _dia.get("cooks") or []
                if _cooks and len(_cooks) == len(y):
                    _arr = np.asarray(_cooks, dtype=float)
                    _thr = 4.0 / len(y)
                    # ⚠ 只用**明确阈值**（Cook's D > 4/n，跟知识库那条一致），
                    #   不要"找不到就取前 1%"——那会让人不知道"这 6 个"是怎么来的，
                    #   而且以后数据量一变、被去掉的人数就跟着变，没法复现。
                    _flag = np.where(_arr > _thr)[0]
                    _keep = np.ones(len(y), dtype=bool)
                    _keep[_flag] = False
                    if _keep.sum() > fit["k"] + 2:
                        fit2 = _ols(X[_keep], y[_keep])
                        b0 = list(fit["beta"])[1]
                        b1 = list(fit2["beta"])[1]
                        r2_0, r2_1 = fit["r2"], fit2["r2"]
                        _flip = (abs(r2_0 - r2_1) >= 0.10) or \
                                ((_pk := list(fit["p"])[1]) is not None
                                 and ((_pk <= alpha) != (list(fit2["p"])[1] <= alpha)))
                        sens2 = [["含全部", fit["n"], _f(r2_0), _f(b0), _p(fit["p"][1])],
                                 ["去掉 %d 个强影响点" % len(_flag), fit2["n"],
                                  _f(r2_1), _f(b1), _p(fit2["p"][1])]]
                        tables.append({
                            "name": "结论敏感度（去掉强影响点后还成立吗）",
                            "columns": ["版本", "n", "R²", "第一个自变量 B", "它的 p"],
                            "rows": sens2,
                            "note": ("⚠ **结论受少数个体影响**（R² 从 %s 到 %s）。"
                                     "怎么处理是你的事，但报告里要写明。"
                                     % (_f(r2_0), _f(r2_1))) if _flip else
                                    ("去掉影响最大的 %d 个个体后，R² 只从 %s 动到 %s —— "
                                     "模型不是几个极端点撑起来的。" % (len(_flag), _f(r2_0), _f(r2_1))),
                        })
                        if _flip:
                            ctx.alert("**回归结论对少数个体敏感**：去掉 %d 个强影响点后，"
                                      "R² 从 %s 变成 %s。"
                                      % (len(_flag), _f(r2_0), _f(r2_1)),
                                      level="warn", kind="internal",
                                      fix="先回去看这几行（回归诊断表里有 Cook's D）。"
                                          "**不要只为了让 R² 好看就删**；"
                                          "要删就写清理由，并且两版并报。")
                            md.append("\n### ⚠ 结论敏感度\n")
                            md.append("去掉 %d 个强影响点后，R² 从 %s 变成 %s —— "
                                      "报告里必须写明这一点。\n"
                                      % (len(_flag), _f(r2_0), _f(r2_1)))
            except Exception as e:
                ctx.log("回归版的结论敏感度没算出来（不影响上面的结果）：%s" % e, "warn")

    # ======================================================================= #

        # ---------- 因变量只有两类 → 二元 logistic（2026-09-26 加）----------
        # ⚠ 为什么必须分出来：拿线性回归拟合 0/1 因变量，**系数看着能算出来，
        #   但标准误和 p 值都是错的**（预测值会超出 0~1、残差不可能正态）。
        #   这是很常见的一处硬用，而且它不会报错——只会给你一张"像那么回事"的表。
        _dv_levels = sorted(set(str(x) for x in df[dv].dropna().unique())) \
            if dv in df.columns else []
        _dv_binary = (kinds.get(dv) == "categorical" and len(_dv_levels) == 2)
        if _dv_binary:
            from core import regress as _rg
            cols = ivs + [dv]
            dd = df[cols].copy()
            for c in ivs:
                if kinds.get(c) != "categorical":
                    dd[c] = pd.to_numeric(dd[c], errors="coerce")
            dd = dd.dropna()
            if len(dd) < 20:
                raise ValueError("有效样本只有 %d 行，logistic 回归太少了" % len(dd))
            y, levels_y, _ = _rg.encode_binary(dd[dv])
            if y is None:
                raise ValueError("因变量「%s」不是两类，做不了二元 logistic" % dv)
            pos_label = levels_y[-1]        # 升序的最后一个算 1（规则写死、可预期）
            X, xnames = _rg.design(dd, ivs, kinds)
            fitL = _rg.logistic(X, y)
            plan.append(["变量", "因变量 %s（**两类**：%s）" % (dv, " / ".join(levels_y)),
                         "两类因变量 → 二元 logistic 回归"])
            plan.append(["哪一类算「1」", "**%s**" % pos_label,
                         "OR 的方向完全取决于这个 —— 报告里必须写明"])
            plan.append(["样本量", "n=%d，参数 %d 个" % (fitL["n"], fitL["k"] - 1),
                         "一般每个自变量至少 10~20 个个案"
                         if fitL["n"] < 20 * (fitL["k"] - 1) else "样本量够用"])
            plan.append(["收敛", "%s（%d 步）" % ("已收敛" if fitL["converged"] else "**未收敛**",
                                                fitL["iters"]),
                         "未收敛时系数不可信" if not fitL["converged"] else "正常"])
            slug = "logistic_%s" % _safe(dv)

            rows = []
            for i, nm in enumerate(xnames):
                b = float(fitL["beta"][i])
                se = float(fitL["se"][i])
                rows.append([nm, _f(b), _f(se), _f(fitL["z"][i]), _p(fitL["p"][i]),
                             _f(float(np.exp(b)), 3), _rg.ci_or(b, se, alpha)])
            tables.append({
                "name": "logistic 回归系数",
                "columns": ["项", "B（对数尺度）", "标准误", "z", "p", "OR=exp(B)", "OR 的 95% CI"],
                "rows": rows,
                "note": "**看 OR 不看看 B**：OR > 1 = 这一项越大越容易落到「%s」那一类；"
                        "OR < 1 = 越小越容易。OR 的 CI **不跨 1** 才算稳。"
                        "（CI 是在对数尺度上算好再取指数的 —— OR 的分布是偏的，"
                        "直接加减标准误会算出负的下界。）" % pos_label,
            })
            lr, lrdf, lrp = _rg.lr_test(fitL)
            tables.append({
                "name": "模型整体",
                "columns": ["指标", "值"],
                "rows": [["对数似然", _f(fitL["ll"])],
                         ["似然比检验 LR", _f(lr)], ["df", str(lrdf)], ["p", _p(lrp)],
                         ["McFadden 伪 R²", _f(fitL["pseudo_r2"])],
                         ["AIC", _f(fitL["aic"], 1)], ["BIC", _f(fitL["bic"], 1)],
                         ["n", str(fitL["n"])]],
                "note": "**logistic 没有 R²**，别拿伪 R² 和线性回归的 R² 比大小——"
                        "它不是「解释了多少变异」，只是一个相对拟合指标（0.2~0.4 就算不错）。",
            })
            ct = _rg.classify_table(y, fitL["p_hat"])
            hl, hlp, hlg = _rg.hosmer_lemeshow(y, fitL["p_hat"])
            cls_rows = [["正确率", "%.3f" % ct["accuracy"]],
                        ["基准（全猜最大类）", "%.3f" % ct["baseline"]],
                        ["比基准好", "%+.3f" % ct["lift"]],
                        ["敏感度（真阳率）", _f(ct["sensitivity"])],
                        ["特异度（真阴率）", _f(ct["specificity"])],
                        ["分类表", "TP=%d TN=%d FP=%d FN=%d"
                         % (ct["tp"], ct["tn"], ct["fp"], ct["fn"])]]
            if hl:
                cls_rows.append(["Hosmer-Lemeshow", "χ²=%s, df=%d, p=%s（%d 组）"
                                 % (_f(hl["hl"], 2), hl["df"], _p(hl["p"]), hlg)])
            tables.append({
                "name": "分类效果与拟合优度",
                "columns": ["指标", "值"], "rows": cls_rows,
                "note": "⚠ **正确率会被类别不平衡骗**：如果正例只占 5%%，"
                        "全都猜「否」也有 95%% 正确率 —— 所以要跟「基准」比。"
                        "Hosmer-Lemeshow 的 H0 是「拟合没有偏差」，**p 大才好**"
                        "（和一般检验相反，最容易读错）。",
            })
            concl = ("二元 logistic（1 = 「%s」）：模型整体%s（LR=%s, df=%d, p=%s），"
                     "McFadden 伪 R²=%s；分类正确率 %.3f，比基准 %+.3f" % (
                         pos_label, _sig(lrp, alpha), _f(lr), lrdf, _p(lrp),
                         _f(fitL["pseudo_r2"]), ct["accuracy"], ct["lift"]))
            if not fitL["converged"]:
                concl += "。⚠ **迭代没收敛**，系数不可信，先看是不是有自变量把两类完全分开了"
            ctx.step("method", "选定方法", "二元 logistic 回归（因变量两类，1 = %s）" % pos_label)
            ledger_entries.append({
                "label": "logistic 整体 LR 检验（%s）" % dv, "kind": "LR",
                "p": lrp, "n": fitL["n"], "exploratory": False})
            for _i, _nm in enumerate(xnames[1:], start=1):
                ledger_entries.append({
                    "label": "logistic 系数 %s（%s）" % (_nm, dv), "kind": "beta",
                    "p": fitL["p"][_i], "n": fitL["n"], "exploratory": False})
            md.append("## 一、决策树\n")
            md.append("| 步骤 | 依据 | 结论 |")
            md.append("|---|---|---|")
            for r2 in plan:
                md.append("| %s | %s | %s |" % tuple(r2))
            md.append("\n## 二、logistic 结果\n%s\n" % concl)
            md.append("| 项 | B | 标准误 | z | p | OR | OR 的 95% CI |")
            md.append("|---|---|---|---|---|---|---|")
            for r2 in rows:
                md.append("| " + " | ".join(str(x) for x in r2) + " |")
            md.append("")
            # SPSS：LOGISTIC REGRESSION（它吃 0/1 数字因变量）
            sps_prelude.append("COMPUTE __y = %s." % " ".join(
                [] ) if False else "COMPUTE __y = 0.")
            sps_prelude.append("IF (%s = '%s') __y = 1." % (_spss_name(dv), pos_label))
            sps_prelude.append("EXECUTE.")
            sps_cmds.append("LOGISTIC REGRESSION VARIABLES __y\n"
                            "  /METHOD=ENTER %s\n  /PRINT=CI(95) GOODFIT\n"
                            "  /CRITERIA=PIN(0.05) POUT(0.10) ITERATE(20) CUT(0.5)."
                            % " ".join(_spss_name(c) for c in xnames[1:]))
            # SPSS：LOGISTIC REGRESSION 只吃 0/1 数字因变量，先造一列 __y
            sps_prelude.append("COMPUTE __y = 0.")
            sps_prelude.append("IF (%s = '%s') __y = 1." % (_spss_name(dv), pos_label))
            sps_prelude.append("EXECUTE.")
            sps_cmds.append("LOGISTIC REGRESSION VARIABLES __y\n"
                            "  /METHOD=ENTER %s\n  /PRINT=CI(95) GOODFIT\n"
                            "  /CRITERIA=PIN(0.05) POUT(0.10) ITERATE(20) CUT(0.5)."
                            % " ".join(_spss_name(c) for c in xnames[1:]))
        else:
            _ols_regression()
    elif question == "assoc":
        cand = [c for c in ([dv, group] + ivs) if c and c in df.columns]
        cand = list(dict.fromkeys(cand))
        if len(cand) < 2:
            cats = [c for c in df.columns if kinds.get(c) == "categorical"]
            if len(cats) < 2:
                raise ValueError("没找到两个分类变量，做不了卡方")
            cand = cats[:2]
            ctx.log("没指定变量，自动选了：%s × %s" % (cand[0], cand[1]))
        a, b = cand[0], cand[1]
        slug = "卡方_%s_%s" % (_safe(a), _safe(b))
        rows, cols_out, info = kit.cross_table(df, a, b)
        ex = info["extra"]
        plan.append(["研究问题", "两个分类变量之间有没有关联", "→ 卡方独立性检验"])
        plan.append(["变量", "%s（%d 类）与 %s（%d 类）" % (
            a, df[a].nunique(), b, df[b].nunique()), "分类 × 分类 → 卡方"])
        if ex.get("chi2") is not None:
            plan.append(["前提", "期望频数<5 的格子 %d/%d" % (
                ex.get("cells_expected_lt5", 0), ex.get("n_cells", 0)),
                "超过 20% 的格子期望频数<5 时卡方不可靠" if
                (ex.get("cells_expected_lt5", 0) / max(ex.get("n_cells", 1), 1)) > 0.2
                else "满足常见经验标准"])
        concl = "χ²=%s, df=%s, p=%s, n=%s；Cramér's V=%s（%s）" % (
            _f(ex.get("chi2")), ex.get("dof"), _p(ex.get("p")), ex.get("n"),
            _f(ex.get("cramers_v")), _v_judge(ex.get("cramers_v")))
        tables.append({"name": "交叉表 · %s × %s" % (a, b), "columns": cols_out, "rows": rows,
                       "note": concl})
        tables.append({"name": "分析计划（决策树）", "columns": ["步骤", "依据", "结论"], "rows": plan})
        md.append("## 一、决策树\n")
        md.append("| 步骤 | 依据 | 结论 |")
        md.append("|---|---|---|")
        for r2 in plan:
            md.append("| %s | %s | %s |" % tuple(r2))
        md.append("\n## 二、结果\n%s\n" % concl)
        sps_cmds.append("CROSSTABS\n  /TABLES=%s BY %s\n  /STATISTICS=CHISQ PHI\n"
                        "  /CELLS=COUNT EXPECTED ROW COLUMN TOTAL." % (
                            _spss_name(a), _spss_name(b)))
        # 登记卡方。⚠ 交叉表的格子多时，这个检验其实是"整张表一起看"的，
        #   所以标成确认性；但**看到显著再去挑哪个格子**就是探索了 —— 报告里会提醒。
        try:
            if ex.get("p") is not None:
                ledger_entries.append({
                    "label": "卡方：%s × %s" % (a, b), "kind": "chi2",
                    "p": ex.get("p"), "n": ex.get("n"), "exploratory": False})
        except Exception:
            pass

    # ======================================================================= #
    else:      # describe
        slug = "描述统计"
        rows = kit.describe_table(df, [c for c in df.columns if kinds.get(c) == "continuous"])
        plan.append(["研究问题", "没有明确的比较/预测目标", "→ 先做描述统计，看清分布"])
        tables.append({"name": "描述统计", "columns": ["变量", "n", "均值", "标准差", "中位数",
                                                       "最小", "最大", "偏度", "峰度"],
                       "rows": rows,
                       "note": "偏度绝对值 >1 提示明显偏斜，这时均值可能不是「典型值」，看中位数更稳。"})
        cont = [c for c in df.columns if kinds.get(c) == "continuous"]
        cats = [c for c in df.columns if kinds.get(c) == "categorical"]
        plan.append(["变量盘点", "连续 %d 个、分类 %d 个" % (len(cont), len(cats)),
                     "分类变量用频数看，连续变量看下面这张表"])
        tables.append({"name": "分析计划（决策树）", "columns": ["步骤", "依据", "结论"], "rows": plan})
        md.append("## 决策树\n")
        md.append("| 步骤 | 依据 | 结论 |")
        md.append("|---|---|---|")
        for r2 in plan:
            md.append("| %s | %s | %s |" % tuple(r2))
        md.append("")
        if cont:
            sps_cmds.append("DESCRIPTIVES VARIABLES=%s\n  /STATISTICS=MEAN STDDEV MIN MAX SEMEAN."
                            % " ".join(_spss_name(c) for c in cont[:20]))
        if cats:
            sps_cmds.append("FREQUENCIES VARIABLES=%s\n  /ORDER=ANALYSIS."
                            % " ".join(_spss_name(c) for c in cats[:20]))

    # ---------- 决策树表统一放最前面 ---------- #
    if not any(t["name"].startswith("分析计划") for t in tables):
        tables.insert(0, {"name": "分析计划（决策树）", "columns": ["步骤", "依据", "结论"],
                          "rows": plan,
                          "note": "这张表回答「为什么用这个方法」——每一步的判断依据都在这里。"})

    # ---------- 加权（如果填了权重列）：未加权 vs 加权并排 ----------
    # ⚠ 放在"多重比较总账"之前、所有分析之后 —— 它是**补充视角**，不替换上面的结果。
    #   关键不是"加权后的数"，而是"加权改变了什么"：均值动了多少 + DEFF 有多大。
    if weight and weight in df.columns:
        try:
            from core import weights as _wt
            wcol = pd.to_numeric(df[weight], errors="coerce")
            chk = _wt.check_weights(wcol.values)
            tables.append({
                "name": "权重检查（先过这一关再看结果）",
                "columns": ["项", "值"],
                "rows": [["权重列", weight],
                         ["原始 n", str(chk["n"])],
                         ["缺失", str(chk["missing"])],
                         ["≤0 的权重", "%d 个" % (chk["n_zero"] + chk["n_negative"])],
                         ["最大/最小", ("%.1f" % chk["max_over_min"]) if chk.get("max_over_min") else "—"],
                         ["单个权重最大占比", ("%.1f%%" % (chk["max_share"] * 100))
                          if chk.get("max_share") else "—"],
                         ["有效样本量 n_eff", ("%.1f" % chk["n_eff"]) if chk.get("n_eff") else "—"],
                         ["设计效应 DEFF", ("%.2f" % chk["deff"]) if chk.get("deff") else "—"]],
                "note": "⚠ **≤0 的权重没有意义**（0 = 剔除那个人、负数会算出荒谬结果），"
                        "上面有就得先处理。\n"
                        "**权重不齐会让信息变少**：n_eff 小于原始 n，DEFF = n / n_eff。"
                        "DEFF=2 的意思是「等于把样本量砍了一半」—— 这句话最好懂。",
            })
            if chk["n_negative"] or chk["n_zero"]:
                ctx.alert("权重列「%s」里有 %d 个 ≤0 的值 —— 负权重没有意义，"
                          "0 等于剔除那个人。先回去处理这些值。"
                          % (weight, chk["n_zero"] + chk["n_negative"]),
                          level="warn", kind="internal")
            if chk.get("extreme"):
                ctx.alert("权重列里**单个权重占了总量的 %.1f%%** —— 有人的话被放得很大，"
                          "结论可能被少数个案主导。" % (chk["max_share"] * 100),
                          level="warn", kind="internal",
                          fix="看一下那个个案的权重是怎么来的；必要时**截尾**"
                              "（把权重上限压到某个倍数）。")
            # 未加权 vs 加权：拿因变量（或第一个连续变量）比
            _targets = []
            if dv and dv in df.columns and pd.to_numeric(df[dv], errors="coerce").notna().sum() > 3:
                _targets.append(dv)
            else:
                for c in df.columns:
                    if kinds.get(c) == "continuous" and c != weight:
                        _targets.append(c)
                        break
            for tc in _targets[:2]:
                cv = _wt.compare_weighted(pd.to_numeric(df[tc], errors="coerce").values,
                                          wcol.values, alpha)
                if not cv:
                    continue
                tables.append({
                    "name": "未加权 vs 加权 · %s" % tc,
                    "columns": ["版本", "n", "n_eff", "均值", "标准误", "95% CI"],
                    "rows": [
                        ["未加权", str(cv["plain"]["n"]), "—",
                         _f(cv["plain"]["mean"]), _f(cv["plain"]["se"]), "—"],
                        ["加权", str(cv["weighted"]["n"]),
                         _f(cv["weighted"]["n_eff"], 1), _f(cv["weighted"]["mean"]),
                         _f(cv["weighted"]["se"]),
                         "[%.3f, %.3f]" % cv["weighted"]["ci"]],
                    ],
                    "note": "**均值移动 %+.3f**（动了说明样本的构成和总体不一致，"
                            "加权把它纠回来了）；标准误放大 **%.2f 倍**、DEFF=**%.2f**。\n"
                            "⚠ 如果 DEFF 接近 1，说明这个权重**几乎没起作用** —— "
                            "那就该问一句「这个权重到底是怎么来的」。\n"
                            "⚠ 加权会改变「谁在代表谁」：报告里必须写清**权重的来源**"
                            "（抽样设计？事后校正？），否则别人没法解释这个数。"
                            % (cv["mean_shift"], cv["se_ratio"] or 0, cv["deff"] or 0),
                })
            md.append("\n## 加权分析（补充视角）\n")
            md.append("权重列：`%s`；n=%d、n_eff=%.1f、DEFF=%.2f。"
                      "**加权不替换上面的结果，只是并排给你另一版** —— "
                      "两者差多少，就说明样本构成偏了多少。\n"
                      % (weight, chk["n"], chk.get("n_eff") or 0, chk.get("deff") or 0))
        except Exception as e:
            ctx.log("加权那部分没做出来（不影响上面的分析）：%s" % e, "warn")
    elif weight:
        ctx.alert("权重列「%s」不在数据里 —— 已跳过加权分析。" % weight,
                  level="warn", kind="internal")

    # ---------- 多重比较总账（把这次的检验登进簿子，并把累计情况摆出来）----------
    # ⚠ 为什么"累计"而不是"只看这一次"：多重比较的风险是**整个项目**累积的。
    #   单跑一次看一个 p 值永远看不出问题（1 个检验 5%、5 个 23%、10 个 40%）。
    #   登记簿落在项目里（`output/检验登记簿.json`），跑几次就攒几次。
    #   它**只登记、不自动改结论** —— 哪几条会掉出显著只作陈述，用不用校正是研究员的判断。
    try:
        from core import multiple as _multi
        added = _multi.register(ctx.project_root, ledger_entries, source=slug)
        led = _multi.load(ctx.project_root)
        if added:
            ctx.log("检验登记簿 +%d 条（累计 %d 条）" % (added, len(led["entries"])))
        corp = _multi.correct(led["entries"], alpha)
        if corp["total"]:
            sum_lines = _multi.summarize(corp, led["entries"])
            tables.append({
                "name": "多重比较总账",
                "columns": ["项", "值"],
                "rows": [["本次登记", "%d 个检验（确认性 %d、探索性 %d）"
                          % (corp["total"], corp["n_confirm"], corp["n_explore"])],
                         ["本次这批的假阳性风险", "约 %.0f%%（`1−0.95^n`）"
                          % (corp["familywise"] * 100)],
                         ["Bonferroni 门槛（α/m）", "%.5f" % corp["bonferroni"]["thr"]],
                         ["FDR(BH) 门槛", "%.5f" % corp["fdr"]["thr"]],
                         ["按 Bonferroni 会掉出显著", "%d 条%s"
                          % (len(corp["dropped_by_bonf"]),
                             ("：" + "、".join(corp["dropped_by_bonf"][:5]))
                             if corp["dropped_by_bonf"] else "")],
                         ["按 FDR 会掉出显著", "%d 条%s"
                          % (len(corp["dropped_by_fdr"]),
                             ("：" + "、".join(corp["dropped_by_fdr"][:5]))
                             if corp["dropped_by_fdr"] else "")]],
                "note": "登记簿在 `output/检验登记簿.json`（跨多次分析累计）。"
                        "**校正不会替你改结论**：它只说明「哪几条会掉出去」。"
                        "报告里至少要写清「共 N 个检验、做了/没做校正、用的哪种」。",
            })
            md.append("\n## 多重比较（总账）\n")
            for ln in sum_lines:
                md.append("- " + ln)
            md.append("")
            ctx.step("multicomp", "多重比较总账",
                     "累计登记 %d 个检验（确认性 %d、探索性 %d）——"
                     "至少一个假阳性的概率约 %.0f%%。"
                     % (corp["total"], corp["n_confirm"], corp["n_explore"],
                        corp["familywise"] * 100),
                     rows=[["Bonferroni 门槛", "%.5f" % corp["bonferroni"]["thr"],
                            "%d 条会掉出" % len(corp["dropped_by_bonf"])],
                           ["FDR(BH) 门槛", "%.5f" % corp["fdr"]["thr"],
                            "%d 条会掉出" % len(corp["dropped_by_fdr"])]],
                     columns=["方法", "门槛", "影响"])
    except Exception as e:
        ctx.log("多重比较总账没做出来（不影响上面的结果）：%s" % e, "warn")

    # ---------- 生成 .sps ---------- #
    if "sps" in gen and sps_cmds:
        from core import spss as spss_mod
        csv_abs = path
        sps = _build_sps(df, csv_abs, sps_cmds, how, alpha, prelude=sps_prelude)
        sps_name = "分析_语法_%s.sps" % slug
        # ⚠ 语法要用 **GBK** 写：SPSS 按本机代码页读语法文件，
        #   UTF-8 的中文进去全是乱码，连里面的文件路径都会被读坏（踩过）
        ctx.save_text("output/" + sps_name, sps, encoding=spss_mod.syntax_encoding())
        ctx.save_text("output/分析_语法.sps", sps, encoding=spss_mod.syntax_encoding())
        text_out.append({"name": "SPSS 语法（可复核同一件事）", "rel": "output/" + sps_name,
                         "text": sps, "mono": True})
        ctx.log("生成 SPSS 语法 → output/%s（按 %s 编码，SPSS 才读得懂）"
                % (sps_name, spss_mod.syntax_encoding()))
        md.append("\n## 附：SPSS 复核\n")
        md.append("同一件事的 SPSS 语法在 `output/%s`。"
                  "在 SPSS 里跑一遍，数字应当和上面一致——两边对得上，报告才站得住。" % sps_name)

    # ---------- 用 SPSS 真跑一遍，把它的输出带回来 ---------- #
    #   有人更习惯看 SPSS 的输出样式（三线表、脚注、成对的统计量），
    #   而且「Python 一遍 + SPSS 一遍，两边对得上」本身就是复核。
    #   ⚠ 走的是**生产作业**（`-production` + .spj）—— SPSS 专门为自动化设计的那条路。
    #     试过 `-runsyntax`：它走的是 `openSyntaxDocument`（打开，不是跑），
    #     实测 SPSS 一闪就没了、什么也不产出。
    html_out = []
    spss_info = None
    if "spss_run" in gen and sps_cmds and any(t.get("rel", "").endswith(".sps") for t in text_out):
        from core import spss as spss_mod
        sps_rel = next(t["rel"] for t in text_out if t.get("rel", "").endswith(".sps"))
        html_name = "SPSS输出_%s.html" % slug
        html_rel = "output/" + html_name
        html_abs = ctx.path(html_rel)
        exe = spss_mod.find_exe()
        spss_mod.add_banner(ctx.path(sps_rel), autorun=False)
        spss_mod.prepare_syntax(ctx.path(sps_rel), html_abs)

        if not exe:
            spss_info = {"mode": "none", "sps": sps_rel, "html": html_rel,
                         "ok": False, "error": "config.json 里的 spss_exe 指向的文件不存在"}
            ctx.log("没配 SPSS，跳过（Python 那一遍不受影响）", "warn")
        else:
            ctx.step("spss", "用 SPSS 的生产作业跑一遍",
                     "生成 `.spj` 作业文件（输出格式、路径、编码都写在里面），"
                     "用 `stats.exe -production` 跑它 —— SPSS 跑完自己退出，不用碰界面。")
            res = spss_mod.run_production(ctx.project_root, sps_rel, html_rel,
                                          progress=lambda m: ctx.log(m))
            if res.get("ok"):
                ctx.log("SPSS 跑完了：%.1fs，输出 %.1f KB"
                        % (res.get("seconds") or 0, (res.get("size") or 0) / 1024.0))
                spss_info = {"mode": "production", "ok": True, "sps": sps_rel,
                             "html": html_rel, "seconds": res.get("seconds"),
                             "spj": res.get("spj"), "error": "",
                             "warning": res.get("warning") or ""}
                if res.get("warning"):
                    ctx.log("⚠ " + res["warning"], "warn")
                ctx.made(html_abs)
                ready, html_text = spss_mod.collect(html_abs)
                if ready:
                    html_out.append({"name": html_name, "rel": html_rel, "text": html_text})
            else:
                ctx.log("生产作业没跑通：%s" % res.get("error"), "warn")
                r = spss_mod.open_syntax(exe, ctx.path(sps_rel), autorun=False)
                spss_info = {"mode": "gui", "ok": bool(r.get("ok")),
                             "sps": sps_rel, "html": html_rel,
                             "error": res.get("error") or r.get("error") or "",
                             "autorun": False,
                             "already_open": bool(r.get("already"))}
                if r.get("ok") and not r.get("already"):
                    ctx.log("已经退回界面那条路：SPSS 打开了，请按 Ctrl+A、Ctrl+R 运行")

        if spss_info.get("mode") == "production" and spss_info.get("ok"):
            tables.append({
                "name": "SPSS 复核",
                "columns": ["项目", "结果"],
                "rows": [["跑法", "生产作业 `stats.exe -production`（跑完自己退出，不用碰界面）"],
                         ["耗时", "%.1f 秒" % (spss_info.get("seconds") or 0)],
                         ["SPSS 输出", "output/" + html_name],
                         ["作业文件", spss_info.get("spj") or ""]],
                "note": "下面「SPSS 自己的输出」那一块就是它导出的原文，样式是 SPSS 的。"
                        "数字应当和上面 Python 算的一致。",
            })
            md.append("\n### SPSS 自己的输出\n")
            md.append("SPSS 已用**生产作业**跑完（%.1f 秒），输出见 `output/%s`，"
                      "结果页里也直接显示了。**数字应当和上面的 Python 结果一致**——"
                      "对不上就说明有一边错了，先查数据读进来对不对。"
                      % (spss_info.get("seconds") or 0, html_name))
        elif spss_info.get("mode") == "gui" and spss_info.get("ok"):
            # ⚠ 这里**不在这里等**：人可能不在电脑前。引擎先交回控制权，
            #   前端盯着那个 HTML，一出现就收回来显示。
            tables.append({
                "name": "SPSS 复核",
                "columns": ["项目", "结果"],
                "rows": [["状态", "生产作业没跑通，已退回界面那条路"],
                         ["原因", (spss_info.get("error") or "")[:200]],
                         ["你要做的", "在 SPSS 窗口里按 Ctrl+A 全选，再按 Ctrl+R 运行"],
                         ["跑完", "SPSS 会把输出导成 HTML，工作台会自动收回来显示在下面"],
                         ["语法文件", sps_rel]],
                "note": "Python 那一遍的结果不受影响，照常可以用。",
            })
            md.append("\n### SPSS 自己的输出\n")
            md.append("生产作业那条路没跑通（%s），已退回界面：**SPSS 已经打开**，"
                      "在窗口里按 `Ctrl+A` 全选、`Ctrl+R` 运行。跑完工作台会自动把输出收回来。"
                      % (spss_info.get("error") or "未知"))
        else:
            tables.append({
                "name": "SPSS 复核",
                "columns": ["项目", "结果"],
                "rows": [["状态", "没能调起来"], ["原因", spss_info.get("error") or "未知"],
                         ["退路", "语法在 %s，自己在 SPSS 里打开跑一遍，结果应当一致" % sps_rel]],
                "note": "Python 那一遍的结果不受影响，照常可以用。",
            })
            md.append("\n### SPSS 自己的输出\n")
            md.append("这一遍**没能调起 SPSS**：%s\n\n语法文件在 `%s`，"
                      "自己打开跑一遍，结果和上面的数字应当一致。"
                      % (spss_info.get("error") or "未知", sps_rel))

    md_text = "\n".join(md)
    rep_name = "分析报告_%s.md" % slug
    ctx.save_text("output/" + rep_name, md_text)
    ctx.save_text("output/分析报告.md", md_text)            # 固定名（组块完成标志看它）
    ctx.save_table("分析_结果汇总_%s.csv" % slug,
                   [[t["name"], "；".join(str(x) for x in (t.get("note") or "").split("。")[:1])]
                    for t in tables], ["分析项", "说明"])

    ctx.log("完成：%d 张表，%d 张图" % (len(tables), len(figures)))
    return {
        "summary": concl or "分析完成，见下表",
        "tables": tables,
        "figures": figures,
        "markdown": [{"name": rep_name, "rel": "output/" + rep_name, "text": md_text}],
        "text": text_out,
        "html": html_out,
        "spss": spss_info,
        "notes": "决策树表说明了每一步为什么这么走；前提不满足时已按你的设置处理。",
    }


# =========================================================================== #
# 辅助
# =========================================================================== #

def _safe(s):
    return re.sub(r"[^\w\u4e00-\u9fa5]+", "_", str(s)).strip("_")[:38] or "x"


def _spss_lit(v):
    s = str(v)
    if re.match(r"^-?\d+(\.\d+)?$", s):
        return s
    return "'%s'" % s.replace("'", "''")


def _ci_mean_diff(a, b, alpha):
    """均值差的 95% 置信区间（Welch 自由度）。"""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return "—"
    v1, v2 = a.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(v1 / n1 + v2 / n2)
    if se <= 0:
        return "—"
    df = (v1 / n1 + v2 / n2) ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    tcrit = stats.t.ppf(1 - alpha / 2, df)
    diff = a.mean() - b.mean()
    return "[%.3f, %.3f]" % (diff - tcrit * se, diff + tcrit * se)


def _d_judge(d):
    d = abs(float(d))
    return "小" if d < 0.2 else "小~中" if d < 0.5 else "中" if d < 0.8 else "大"


def _r_judge(r):
    a = abs(float(r))
    if a < 0.1:
        return "几乎不"
    if a < 0.3:
        return "弱"
    if a < 0.5:
        return "中等"
    if a < 0.7:
        return "较强"
    return "强"


def _v_judge(v):
    if v is None:
        return "—"
    a = abs(float(v))
    return "弱关联" if a < 0.1 else "弱~中" if a < 0.3 else "中等" if a < 0.5 else "强"


def _ci_r(r, n, alpha):
    """相关系数的置信区间（Fisher z 变换）。

    ⚠ 为什么必须给：p 只说明"不是 0"，CI 才说明"有多大、有多不准"。
      实测那份数据 r=0.732、n=539，没有 CI 的话没人知道它是 [0.69, 0.77] 还是 [0.2, 0.95]。
      只报 p 不报 CI 是这类报告最常被审稿人抓的地方。

    对 Spearman ρ 用同一条公式是**通行做法**（近似），这里沿用，并在报告里注明是近似。
    """
    try:
        n = int(n)
        if n < 4 or r is None:
            return "—"
        r = max(min(float(r), 0.999999), -0.999999)
        z = np.arctanh(r)
        se = 1.0 / np.sqrt(n - 3)
        zcrit = stats.norm.ppf(1 - alpha / 2)
        lo, hi = np.tanh(z - zcrit * se), np.tanh(z + zcrit * se)
        return "[%.3f, %.3f]" % (lo, hi)
    except Exception:
        return "—"


def _ci_beta(b, se, df, alpha):
    """回归系数的置信区间：B ± t(α/2, df) × SE。

    和 `_ci_mean_diff` 是同一个道理——**只报 B 和 p 不够**：
    B=0.054 配 SE=0.014 和配 SE=0.140，p 可能都能显著，但可信程度差一个量级。
    """
    try:
        b, se, df = float(b), float(se), float(df)
        if df <= 0 or se != se:
            return "—"
        tcrit = stats.t.ppf(1 - alpha / 2, df)
        return "[%.3f, %.3f]" % (b - tcrit * se, b + tcrit * se)
    except Exception:
        return "—"


def _rank_biserial_p(rb, n1, n2):
    """rank-biserial r 的 p（正态近似）。

    ⚠ 为什么单独算：`stats.mannwhitneyu` 只给 U 和 p，不给这个效应量的 p。
      而效应量**必须带显著性**才能说"这个差异有多大"——
      单看 rb=0.05 分不清"几乎没有"和"样本太小测不出来"。
    """
    try:
        n1, n2 = int(n1), int(n2)
        if n1 < 2 or n2 < 2 or rb is None:
            return None, "—"
        se = np.sqrt((n1 + n2 + 1.0) / (3.0 * n1 * n2))
        if se <= 0:
            return None, "—"
        z = abs(float(rb)) / se
        return float(2 * (1 - stats.norm.cdf(z))), "z=%.3f" % z
    except Exception:
        return None, "—"


def _ci_eta2(F, df1, df2, alpha):
    """η² 的置信区间 —— 用**非中心 F 分布**反解。

    ⚠ 这里第一版写错了，记下来别再犯：原来拿「(中心)F 的 α/2 和 1−α/2 分位数」折回 η²，
      等于**在"没有效应"的世界里找区间**，所以结果永远贴着 0——
      实测 η²=0.139 给出 [0.000, 0.017]，**区间根本不含点估计**。
      那种"看起来像 CI"的数是假精确，比不给更糟。

    正确做法：F 在非中心参数 λ = η²·(df1+df2+1)/(1−η²) 下服从非中心 F。
    找两个 λ：一个让观测 F 落在第 97.5 百分位（→ η² 下界），
    一个让它落在第 2.5 百分位（→ η² 上界）。λ 越大分布越靠右，所以两界不会反。
    """
    try:
        F, df1, df2, alpha = float(F), float(df1), float(df2), float(alpha)
        if F <= 0 or df1 <= 0 or df2 <= 0:
            return None
        lam_of = lambda e2: e2 * (df1 + df2 + 1.0) / max(1e-9, 1.0 - e2)
        eta2_of = lambda lam: lam / (lam + df1 + df2 + 1.0)
        hi_lam = brentq(lambda L: stats.ncf.cdf(F, df1, df2, L) - 0.975,
                        0.0, 1e5, xtol=1e-4)
        lo_lam = brentq(lambda L: stats.ncf.cdf(F, df1, df2, L) - 0.025,
                        0.0, 1e5, xtol=1e-4)
        a, b = max(0.0, eta2_of(lo_lam)), min(1.0, eta2_of(hi_lam))
        # ⚠ 端点要**排序**再输出。λ 越大非中心 F 越靠右，所以两个解的大小关系
        #   跟直觉相反 —— 实测直接拼出来是 `[0.190, 0.086]`（左大右小）。
        #   这不是"看着别扭"，是**读的人会把区间读反**（而且我的测试就是靠这条抓住的）。
        return "[%.3f, %.3f]" % (min(a, b), max(a, b))
    except Exception:
        return "算不出来"


def _ci_cohens_d(d, n1, n2, alpha):
    """Cohen's d 的置信区间（非中心 t 的大样本近似）。

    近似做法：用 d 的标准误 SE_d ≈ sqrt(1/n1 + 1/n2 + d²/(2(n1+n2)))
    正太近似给区间。样本小时会偏窄，报告里写明是近似。
    """
    try:
        d, n1, n2 = float(d), int(n1), int(n2)
        if n1 < 2 or n2 < 2:
            return "—"
        se = np.sqrt(1.0 / n1 + 1.0 / n2 + d * d / (2.0 * (n1 + n2)))
        z = stats.norm.ppf(1 - alpha / 2)
        return "[%.3f, %.3f]" % (d - z * se, d + z * se)
    except Exception:
        return "—"


def _ci_rb(rb, n1, n2, alpha):
    """rank-biserial r 的置信区间（正态近似），支持负值。

    ⚠ 不能拿 Pearson 那套 Fisher z 硬套 —— rb 的抽样分布不是那个形状，
      而这个效应量**可以是负的**（表示方向相反），所以单独算。
    """
    try:
        rb, n1, n2 = float(rb), int(n1), int(n2)
        if n1 < 2 or n2 < 2:
            return "—"
        se = np.sqrt((n1 + n2 + 1.0) / (3.0 * n1 * n2))
        z = stats.norm.ppf(1 - alpha / 2)
        return "[%.3f, %.3f]" % (rb - z * se, rb + z * se)
    except Exception:
        return "—"


def _sensitivity(d, x, y, alpha):
    """**结论敏感度**：去掉几个"影响特别大"的个体，结论还是不是同一个？

    ⚠ 为什么必须做（2026-09-26 实测踩到，而且是最要命的一条）：
      实测那份数据里 **3 行（0.5%）决定结论** ——
        含这 3 行：Pearson r = 0.260、OLS R² = 0.067、峰度 237.6
        剔除之后：Pearson r = 0.717、OLS R² = 0.514、峰度 0.63
      而原来那条路**一个提醒都不给**，报告就照着 0.068 写下去了。
      ⑥ 的回归诊断里其实算了 Cook's D，但**只标记、不处理**，也没说"结论依赖它"。

    这个函数做三件事：
      1. 按 Cook's D（> 4/n 值得看、> 1 是强影响点）找出"值得看一眼"的个体
      2. **把结论在两版之间对照**（含全部 / 去掉那几个人）
      3. 给出**结论敏感度**判断：是不是"去掉少数几个点结论就反过来"

    ⚠ 它**不删数据、不改主结果** —— 只把事实摆出来，删不删、怎么处理是研究员的事。
      "为了让 R² 好看而删真实数据"是绝对不许的；但"知道结论由谁决定"是必须的。
    """
    try:
        d = d.dropna()
        n = len(d)
        if n < 10:
            return None
        dx = d[x].values.astype(float)
        dy = d[y].values.astype(float)
        Xd = np.column_stack([np.ones(n), dx])
        XtX_inv = np.linalg.pinv(Xd.T @ Xd)
        beta = XtX_inv @ Xd.T @ dy
        resid = dy - Xd @ beta
        dof = n - 2
        sigma2 = float(resid @ resid) / dof
        h = np.einsum("ij,jk,ik->i", Xd, XtX_inv, Xd)      # 杠杆值
        cook = (resid ** 2 / (2 * sigma2)) * (h / np.maximum(1 - h, 1e-12))
        thr_flag = 4.0 / n
        flag = np.where(cook > thr_flag)[0]
        strong = np.where(cook > 1.0)[0]

        def _fit(mask):
            xx, yy = dx[mask], dy[mask]
            try:
                r, p = stats.pearsonr(xx, yy)
            except Exception:
                return None
            b = np.polyfit(xx, yy, 1)
            yh = np.polyval(b, xx)
            ss_tot = float(((yy - yy.mean()) ** 2).sum())
            r2 = 1 - float(((yy - yh) ** 2).sum()) / ss_tot if ss_tot > 0 else None
            return {"n": int(mask.sum()), "r": float(r), "p": float(p), "r2": r2,
                    "median_y": float(np.median(yy))}

        allm = np.ones(n, dtype=bool)
        keep = np.ones(n, dtype=bool)
        keep[flag] = False
        if keep.sum() < 6 or not len(flag):
            return {"n": n, "n_flagged": int(len(flag)), "n_strong": int(len(strong)),
                    "threshold": thr_flag,
                    "cases": [[int(i + 1), float(dx[i]), float(dy[i]), float(cook[i])]
                              for i in strong[:10]],
                    "flip": False}

        a, b = _fit(allm), _fit(keep)
        if not a or not b:
            return None
        # 「结论翻了」怎么判：显著性变了，或者相关系数动了 0.15 以上
        sig_a, sig_b = a["p"] <= alpha, b["p"] <= alpha
        flip = (sig_a != sig_b) or (abs(a["r"] - b["r"]) >= 0.15) \
            or (abs((a["r2"] or 0) - (b["r2"] or 0)) >= 0.10)
        return {
            "n": n, "n_flagged": int(len(flag)), "n_strong": int(len(strong)),
            "threshold": thr_flag, "all": a, "clean": b, "flip": bool(flip),
            "delta_r": abs(a["r"] - b["r"]),
            "delta_r2": abs((a["r2"] or 0) - (b["r2"] or 0)),
            "cases": [[int(i + 1), float(dx[i]), float(dy[i]), float(cook[i])]
                      for i in flag[:10]],
        }
    except Exception:
        return None


def _partial_corr(d, x, y, controls, alpha):
    """偏相关：**扣掉控制变量之后**，x 和 y 还剩多少关系。

    算法就一句话：把 x 和 y 各自对控制变量做回归、取残差，再算两个残差的相关。
    —— 这和 SPSS 的 `PARTIAL CORR` 是同一个定义，数字应当对得上。

    ⚠ 什么情况下必须用它（不然会得出错结论）：
      身高和阅读能力正相关，但扣掉年龄之后就不剩什么了 —— 因为年龄同时推高了两者。
      「看起来有关」往往是**第三个变量同时推高了两边**，偏相关就是把这个变量按住再看。

    自由度：n − 2 − k（k = 控制变量个数）—— 比普通相关少掉 k 个，CI 要用这个 df 折算。
    """
    try:
        cols = [x, y] + list(controls or [])
        dd = d[cols].dropna()
        n = len(dd)
        k = len(controls or [])
        if n < k + 4:
            return None
        res = {}
        for v in (x, y):
            if k:
                X = np.column_stack(
                    [np.ones(n)] +
                    [pd.to_numeric(dd[c], errors="coerce").values.astype(float)
                     for c in controls])
            else:
                X = np.ones((n, 1))
            yv = pd.to_numeric(dd[v], errors="coerce").values.astype(float)
            beta = np.linalg.pinv(X.T @ X) @ X.T @ yv
            res[v] = yv - X @ beta
        r, p = stats.pearsonr(res[x], res[y])
        df = n - 2 - k
        ci = "—"
        if df > 1:
            rr = max(min(float(r), 0.999999), -0.999999)
            se = 1.0 / np.sqrt(max(df - 1, 1))
            zc = stats.norm.ppf(1 - alpha / 2)
            ci = "[%.3f, %.3f]" % (np.tanh(np.arctanh(rr) - zc * se),
                                   np.tanh(np.arctanh(rr) + zc * se))
        return {"r": float(r), "p": float(p), "df": int(df), "n": n,
                "k_controls": k, "ci": ci, "controls": list(controls or [])}
    except Exception:
        return None


def _corr_trio(d, x, y, alpha):
    """同一对变量上把 **Pearson / Spearman / Kendall 三个系数一起**算出来。

    ⚠ 为什么必须三个一起给（2026-09-26 实测踩到，会直接改结论）：
      同一份数据、同一对变量，只因为"选哪个系数"，结论能差几倍——
        含极端值时：Pearson r=0.260、Spearman ρ=0.735
        剔掉那 3 个极端值：Pearson r=0.717、Spearman ρ=0.737
      原来的流程按 Shapiro-Wilk 的 p 值**自动换方法**，然后只报换完的那一个，
      **不告诉研究员还有另一个数、更不说两者差多少**。

      而且这三个数回答的是**不同问题**：
        · Pearson  = 线性关系的强度（受极端值影响大）
        · Spearman = 单调关系的强度（不受极端值影响，但对"非线性"不敏感）
        · Kendall  = 秩一致性（小样本/并列值多时更稳）
      所以不是"哪个对"，而是"它们差多少、差在哪"——那本身就是要写进报告的信息。
    """
    out = {}
    try:
        r, p = stats.pearsonr(d[x], d[y])
        out["pearson"] = {"r": float(r), "p": float(p),
                          "ci": _ci_r(r, len(d), alpha), "n": len(d)}
    except Exception:
        out["pearson"] = None
    try:
        r, p = stats.spearmanr(d[x], d[y])
        out["spearman"] = {"r": float(r), "p": float(p),
                           "ci": _ci_r(r, len(d), alpha), "n": len(d)}
    except Exception:
        out["spearman"] = None
    try:
        r, p = stats.kendalltau(d[x], d[y])
        out["kendall"] = {"r": float(r), "p": float(p),
                          "ci": _ci_r(r, len(d), alpha), "n": len(d)}
    except Exception:
        out["kendall"] = None

    # 差异说明：Pearson 和 Spearman 差得多，说明"关系是单调的但不是线性的"，
    # 或者**被极端值拽歪了**——这两种情况的处理方式完全不同，必须点出来。
    note = ""
    try:
        rp, rs = out["pearson"]["r"], out["spearman"]["r"]
        gap = abs(rs - abs(rp))
        if gap >= 0.15:
            note = ("Pearson 与 Spearman 差了 %.3f —— 说明这段关系**是单调的、但不线性**，"
                    "或者被少数极端值拽歪了。**不要拿 r² 当「解释了多少变异」**："
                    "秩相关的 r² 根本不是方差解释比例。" % gap)
        else:
            note = "三个系数接近（最大差 %.3f），说明线性/单调这两种读法结论一致，可以放心报。" % gap
    except Exception:
        note = ""
    return out, note


def _posthoc(groups, levels, use, alpha):
    """事后两两比较：参数方法用 Tukey，非参数用 Mann-Whitney + Bonferroni。

    ⚠ 每一对都**带上效应量 rank-biserial r 和它的可信区间**（2026-09-26 加）。
      为什么必须加：主检验用秩方法时，它的 ε² 给不出可靠区间（见 `_ci_eta2` 那条注释），
      于是"差异到底有多大"就只能靠这张表回答。只有 U 和 p 的话，
      "p 校正后 = 1.0000" 会被读成"没有差异"，其实可能只是**样本不够大**。
    """
    k = len(levels)
    pairs = [(i, j) for i in range(k) for j in range(i + 1, k)]
    n_cmp = len(pairs)
    head = ["组 A", "组 B", "统计量", "p（校正后）", "效应量 r", "95% CI", "结论"]
    rows = []

    def _rb_row(i, j, stat, pc):
        """rank-biserial r + CI + 它自己的 p（好让读者分清"效应小"和"没测出来"）。"""
        a, b = groups[i], groups[j]
        try:
            U, _ = stats.mannwhitneyu(a, b, alternative="two-sided")
            rb = 1 - 2 * U / (len(a) * len(b))
        except Exception:
            return [str(levels[i]), str(levels[j]), stat, _p(pc), "—", "—", _sig(pc, alpha)]
        rb_p, _z = _rank_biserial_p(rb, len(a), len(b))
        return [str(levels[i]), str(levels[j]), stat, _p(pc),
                _f(rb), _ci_rb(rb, len(a), len(b), alpha),
                "%s（效应量本身 p=%s）" % (_sig(pc, alpha), _p(rb_p))]

    if use in ("anova", "anova_welch"):
        try:
            res = stats.tukey_hsd(*groups)
            for i, j in pairs:
                p = float(res.pvalue[i, j])
                rows.append(_rb_row(i, j, "Tukey", p))
            return [head] + rows
        except Exception:
            pass
    for i, j in pairs:
        try:
            U, p = stats.mannwhitneyu(groups[i], groups[j], alternative="two-sided")
        except Exception:
            continue
        pc = min(1.0, p * n_cmp)
        rows.append(_rb_row(i, j, "U=%.0f" % U, pc))
    return [head] + rows


def _sps_code_var(df, col, levels):
    """把字符串分组变量编成数字（1..k），并挂上值标签。

    ⚠ SPSS 的 `T-TEST GROUPS=` / `NPAR TESTS ... BY` / `ONEWAY ... BY` 都**只吃数字分组变量**。
    我们的分组常常是「无/有」「每周 1 次及以上」这种字符串，直接写进去 SPSS 会报
    「在仅允许变量列表中仅允许使用数字变量的位置使用了字符串变量」然后整个命令停掉（踩过）。
    编号顺序**跟 Python 的分组顺序一致**，值标签保证输出里还是显示原文。
    """
    sname = _spss_name(col)
    if not pd.api.types.is_string_dtype(df[col]) and not df[col].dtype == object:
        return sname, []                      # 本来就是数字，直接用
    lv = [str(x) for x in (levels or sorted(str(v) for v in df[col].dropna().unique()))]
    if len(lv) < 2:
        return sname, []
    cname = sname + "_码"
    rec = " ".join("('%s'=%d)" % (x.replace("'", "''"), i) for i, x in enumerate(lv, 1))
    lines = ["RECODE %s %s INTO %s." % (sname, rec, cname),
             "VALUE LABELS %s %s." % (cname, " ".join(
                 "%d '%s'" % (i, x.replace("'", "''")) for i, x in enumerate(lv, 1))),
             "EXECUTE."]
    return cname, lines


def _sps_cat_prelude(df, cols, kinds):
    """给 SPSS 语法补上「分类自变量 → 哑变量」那一步。

    ⚠ 踩过：Python 那边把分类变量拆成哑变量再进回归，而生成的 SPSS 语法直接把**字符串变量**
      丢给 `REGRESSION`。SPSS 报「在变量列表中仅允许使用数字变量的位置使用了字符串变量，
      此命令的执行停止」，导出的 HTML 里只有一句报错、没有任何结果表。

    这里按**和 Python 完全一样的规则**生成：类别按名字排序，**去掉第一个当参照**，
    所以两边算的是同一个模型。变量名用 `<变量>_<序号>`，并挂上变量标签说明它代表哪一类。
    """
    lines, names = [], []
    for c in cols:
        sname = _spss_name(c)
        if kinds.get(c) != "categorical" or _is_ordinal_scale(df[c]):
            names.append(sname)                      # 连续 / 有序量表：直接当数字用
            continue
        levels = sorted(str(v) for v in df[c].dropna().unique())
        if len(levels) < 2:
            names.append(sname)
            continue
        for i, lv in enumerate(levels[1:], start=2):   # 第 1 类是参照，不生成
            dn = "%s_%d" % (sname, i)
            lit = lv.replace("'", "''")
            lines.append("COMPUTE %s = (%s = '%s')." % (dn, sname, lit))
            lines.append("VARIABLE LABELS %s '%s = %s'." % (dn, c, lit))
            names.append(dn)
        lines.append("EXECUTE.")
    return lines, names


def _build_sps(df, csv_abs, cmds, how, alpha, prelude=None):
    """生成能在 SPSS 里直接跑的语法：先把 CSV 读进来，再执行分析命令。"""
    L = []
    # 别把整份语法回显到输出里（不然导出的 HTML 前半页全是日志，看不到结果）
    L.append("SET PRINTBACK=OFF.")
    L.append("SET MPRINT=OFF.")

    L.append("* " + "=" * 68)
    L.append("* 用户研究工作台 · 自动生成的 SPSS 语法（复核用）")
    L.append("* 生成时间：" + time.strftime("%Y-%m-%d %H:%M"))
    L.append("* 数据文件：" + csv_abs)
    L.append("* 说明：Python 已经算过一遍，这里让 SPSS 算同一件事，两边对得上才敢用。")
    L.append("* " + "=" * 68)
    L.append("")
    L.append("GET DATA /TYPE=TXT")
    L.append("  /FILE='%s'" % csv_abs.replace("'", "''"))
    L.append("  /ENCODING='UTF8'")
    L.append('  /DELIMITERS=","')
    L.append("  /QUALIFIER='\"'")
    L.append("  /ARRANGEMENT=DELIMITED")
    L.append("  /FIRSTCASE=2")
    L.append("  /VARIABLES=")
    decls = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            decls.append("    %s F8.2" % _spss_name(c))
        else:
            mx = int(s.astype(str).str.len().max() or 8)
            decls.append("    %s A%d" % (_spss_name(c), min(max(mx, 8), 255)))
    L.append("\n".join(decls))
    L.append("  /MAP.")
    L.append("DATASET NAME 研究数据 WINDOW=FRONT.")
    L.append("")
    L.append("* ---- 变量标签（中文名对照） ----")
    for c in df.columns:
        nm = _spss_name(c)
        if nm != str(c):
            L.append("VARIABLE LABELS %s '%s'." % (nm, str(c).replace("'", "''")))
    L.append("")
    L.append("* ---- 分析 ----")
    if prelude:
        L.append("* 先把字符串变量转成 SPSS 要的数字形式："
                 "REGRESSION 只吃数字自变量（分类的要拆成哑变量）；"
                 "T-TEST / NPAR TESTS / ONEWAY 的分组变量也必须数字化。"
                 "规则和 Python 那边完全一样，两边算的是同一个模型。")
        for c in prelude:
            L.append(c)
        L.append("")
    for c in cmds:
        L.append("* " + "-" * 60)
        L.append(c)
    L.append("")
    L.append("* ---- 完 ----")
    return "\n".join(L)
