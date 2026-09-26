# -*- coding: utf-8 -*-
"""组块 ④ 数据预处理 · 引擎

每一步都记进 `output/预处理日志.md`——这是「可复现」的凭据：
拿着原始数据 + 这份日志，别人能重做出一模一样的 clean_data.csv。
"""
import os
import re
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_WB = os.path.dirname(os.path.dirname(_HERE))
if _WB not in sys.path:
    sys.path.insert(0, _WB)
from core import kit          # noqa: E402


def run(ctx):
    file_rel = (ctx.get("file") or "").strip().strip('"')
    if not file_rel:
        raise ValueError("请先选原始数据文件")
    path = file_rel if os.path.isabs(file_rel) else ctx.path(file_rel)
    df, how = kit.read_table(path)
    df = kit.clean_columns(df)
    n0, c0 = df.shape
    ctx.log("读入 %s → %d 行 × %d 列（%s）" % (os.path.basename(path), n0, c0, how))

    L = []          # 日志（markdown）
    tables = []
    figures = []          # ⚠ 这个块目前不画图，但结果结构要一致（有的块会读它）
    L.append("# 数据预处理日志\n")
    L.append("> 源文件：`%s`（%s）" % (file_rel, how))
    L.append("> 起始规模：**%d 行 × %d 列**；缺失单元格 %d\n" % (
        n0, c0, int(df.isna().sum().sum())))

    steps = []
    work = df.copy()

    # ---------------- 0. 先认「跳题」：它不是漏答 ----------------
    # ⚠ 为什么这一步必须排在最前面（2026-09-26 加）：
    #   问卷里的空白有**两种**意思：
    #     · 结构跳题：这道题对这个人不适用（"从未恋爱"的人不答花销题）—— 不是漏答
    #     · 真漏答  ：该答没答 / 拒答
    #   原来两者都是空白，于是「整行删除」把 41 位从未恋爱的人**整群删掉**，
    #   报告里还写成"缺失率 2.9%"——**结构跳题被当成了漏答**。
    #   现在生成侧会写哨兵值（`<不适用>`）和/或 `_跳题` 标记列，这里先认出来、
    #   记下是哪些行哪些列，再交给下面按研究员的设置处理。
    skip_marker_col = None
    skip_row_mask = None
    n_skip_rows = 0
    for _c in ("_跳题", "_skip", "_不适用"):
        if _c in work.columns:
            skip_marker_col = _c
            break
    if skip_marker_col:
        try:
            _mk = work[skip_marker_col].astype(str).str.strip().str.lower()
            _mk = _mk.isin(["true", "1", "是", "y", "yes"])
            n_skip_rows = int(_mk.sum())
            if n_skip_rows:
                # ⚠ 先把掩码存下来（在丢列之前）—— 第 2 步「只删真漏答」要用它。
                skip_row_mask = np.asarray(_mk.values, dtype=bool)
                # 标记列本身不进分析数据（它是给人/给程序看的说明，不是变量）
                steps.append("按 `%s` 认出**结构跳题 %d 人**（他们不是漏答，"
                             "而是那几道题对他们不适用）" % (skip_marker_col, n_skip_rows))
                ctx.log("结构跳题：%d 人（按 %s 列认出来的）" % (n_skip_rows, skip_marker_col))
                work = work.drop(columns=[skip_marker_col])
        except Exception as e:
            ctx.log("跳题标记列读不出来：%s" % e, "warn")
    # 哨兵值（无论有没有标记列都要认）
    SENTINELS = ["<不适用>", "不适用", "N/A", "NA", "无此题", "跳过"]
    sent_hits = {}
    for c in work.columns:
        if work[c].dtype != object:
            continue
        try:
            _s = work[c].astype(str).str.strip()
            _hit = _s.isin(SENTINELS)
            k = int(_hit.sum())
            if k:
                sent_hits[c] = k
                work.loc[_hit, c] = np.nan          # 认成缺失，供下面的步骤统一处理
        except Exception:
            continue
    if sent_hits:
        _sum = "、".join("%s %d 格" % (k, v) for k, v in list(sent_hits.items())[:8])
        steps.append("哨兵值认成缺失（**这些是「不适用」，不是漏答**）：%s" % _sum)
        ctx.log("哨兵值 → 缺失：%s" % _sum)

    # ---------------- 1. 删掉缺失过多的列 ----------------
    method = ctx.get("missing") or "keep"
    # 多重插补的参数（第 5 批加）
    try:
        _m_mice = int(float(ctx.get("mice_m") or 5))
    except Exception:
        _m_mice = 5
    try:
        _m_iter = int(float(ctx.get("mice_iter") or 10))
    except Exception:
        _m_iter = 10
    try:
        _mice_seed = int(float(ctx.get("mice_seed") or 20260926))
    except Exception:
        _mice_seed = 20260926
    _m_mice = max(2, min(_m_mice, 50))
    _m_iter = max(1, min(_m_iter, 50))
    try:
        thr = float(ctx.get("max_missing_col") or 50)
    except Exception:
        thr = 50.0
    if method == "col50":
        miss_pct = work.isna().mean() * 100
        drop = [c for c in work.columns if miss_pct[c] > thr]
        if drop:
            work = work.drop(columns=drop)
            steps.append("删掉缺失率 > %.0f%% 的列：%s" % (thr, "、".join(drop)))
            ctx.log("删列 %d 个：%s" % (len(drop), "、".join(drop)))
        else:
            steps.append("没有缺失率 > %.0f%% 的列，什么都没删" % thr)

    # ---------------- 2. 缺失值 ----------------
    n_before = len(work)
    if method == "skipdiff":
        # **只删真漏答，跳题的人留着**。
        # ⚠ 怎么做才对：结构跳题的人在那几道题上**本来就是空白**，如果按"有空白就删行"
        #   他还是会被删掉。所以判据要窄一点——**只删"既不是跳题、又留了空"的人**。
        #   跳题的人在他该答的题上没留空 → 留下；进分析时那几道跳过的题
        #   会被各分析自己的"按对删除"自然排除（各分析 n 不同是正常的，不是漏做）。
        n_na_rows = work.isna().sum(axis=1)
        if n_skip_rows and skip_row_mask is not None and len(skip_row_mask) == len(work):
            keep_mask = np.asarray(skip_row_mask) | (n_na_rows.values == 0)
            work = work[keep_mask]
            steps.append(
                "只删真漏答：%d → %d 行（删掉 %d 行；**结构跳题 %d 人保留下来**了，"
                "他们在跳过的那几题上仍是空白，各分析会按对自动排除）"
                % (n_before, len(work), n_before - len(work), int(np.sum(skip_row_mask))))
        else:
            work = work[n_na_rows.values == 0]
            steps.append("没认出结构跳题（这批数据里没有跳题标记），按整行删除处理："
                         "%d → %d 行" % (n_before, len(work)))
        ctx.log(steps[-1])
    elif method == "listwise":
        work = work.dropna()
        _extra = (" ⚠ 这里面**包含结构跳题的人**（如果那几题不是「该答没答」"
                  "而是「不适用」，他们不该被整行删掉 —— 换成「只删真漏答」看看）"
                  if n_skip_rows else "")
        steps.append("整行删除：%d → %d 行（删掉 %d 行，占 %.1f%%）%s" % (
            n_before, len(work), n_before - len(work),
            (n_before - len(work)) / n_before * 100 if n_before else 0, _extra))
        ctx.log(steps[-1])
    elif method == "mice":
        # 多重插补（第 5 批加）
        # ⚠ 它和"单值填补"是**两种思路**，不是"更高级的均值填补"：
        #   单值填补把缺失填成一个数 → 方差被压小、相关被稀释、标准误偏小；
        #   多重插补填 m 套带随机扰动的数据 → 保住变异，而且把"填得不确定"算进标准误。
        from core import impute as _im
        num_cols = [c for c in work.columns
                    if pd.to_numeric(work[c], errors="coerce").notna().sum() >= 5]
        cat_cols = [c for c in work.columns
                    if c not in num_cols and work[c].isna().any()]
        sets, used = _im.mice(work, num_cols, m=_m_mice, seed=_mice_seed)
        if not sets:
            steps.append("多重插补：没有可插的数值列，跳过")
            ctx.log(steps[-1])
        else:
            # ⚠ 对照表要在**填进去之前**用原始（还带缺失的）work 算，
            #   所以先把要对照的东西取好，再覆盖 work。
            #   （第一版是"填完再比"→ 缺失数显示 0、三种做法的数字一模一样，等于没比）
            _raw_for_cmp = work[[c for c in used]].copy()
            first = sets[0]
            for c in used:
                work[c] = first[c].values
            # 分类列：按观测到的比例随机抽（不一律填众数 —— 那会把那一类人为抬高）
            rng_c = np.random.default_rng(_mice_seed)
            for c in cat_cols:
                work[c] = _im.complete_categorical(work[c], rng_c).values
            steps.append("多重插补（MICE）：%d 套 × %d 轮、%d 个数值列"
                         "（主数据用第 1 套，另 %d 套也存下来了）"
                         % (_m_mice, _m_iter, len(used), _m_mice - 1))
            ctx.log(steps[-1])
            # 把"三种做法的后果"并排摊开 —— 这是这块最该给人看的东西
            try:
                _cc = _raw_for_cmp.dropna()
                _mf = _raw_for_cmp.copy()
                for c in used:
                    _mf[c] = _mf[c].fillna(_mf[c].mean())
                _mi_mean = {c: float(np.mean([s[c].mean() for s in sets])) for c in used}
                _mi_sd = {c: float(np.mean([s[c].std(ddof=1) for s in sets])) for c in used}
                _rows = []
                _shrunk = []
                for c in used[:10]:
                    _m_cc = float(_cc[c].mean()) if len(_cc) else None
                    _m_mf = float(_mf[c].mean())
                    _sd_cc = float(_cc[c].std(ddof=1)) if len(_cc) > 1 else None
                    _sd_mf = float(_mf[c].std(ddof=1))
                    _rows.append([
                        c, int(_raw_for_cmp[c].isna().sum()),
                        "%.3f" % _m_cc if _m_cc is not None else "—",
                        "%.3f" % _m_mf, "%.3f" % _mi_mean[c],
                        "%.3f" % _sd_cc if _sd_cc is not None else "—",
                        "%.3f" % _sd_mf, "%.3f" % _mi_sd[c],
                    ])
                    if _sd_cc and _sd_cc > 0:
                        _sh = (_sd_cc - _sd_mf) / _sd_cc
                        if _sh > 0.02:
                            _shrunk.append((c, _sh * 100))
                tables.append({
                    "name": "⚠ 三种缺失做法的后果（并排看）",
                    "columns": ["变量", "缺失数", "完整个案均值", "均值填补均值",
                                "多重插补均值", "完整个案SD", "均值填补SD",
                                "多重插补SD"],
                    "rows": _rows,
                    "note": "**均值填补会把标准差压小、把相关稀释** —— 看最右几列："
                            "「均值填补SD」通常明显小于「完整个案SD」，"
                            "而多重插补的 SD 更接近完整个案。\n"
                            "这不是细节：SD 被压小 → 标准误偏小 → p 值偏乐观 → "
                            "**更容易报告出「显著」**。\n"
                            "均值那一列也看得出来：均值填补会把均值往中间拉，"
                            "多重插补更接近完整个案。",
                })
                if _shrunk:
                    _shrunk.sort(key=lambda x: -x[1])
                    ctx.alert("均值填补把这几列的**标准差压小了**：%s —— "
                              "方差被压小会让标准误偏小、p 值偏乐观。"
                              % "、".join("%s（-%.0f%%）" % (c, p) for c, p in _shrunk[:5]),
                              level="warn", kind="internal",
                              fix="用「多重插补（MICE）」代替均值填补，或者只报完整个案"
                                  "（但要说明样本量少了多少）。")
            except Exception as e:
                ctx.log("三种做法对照没做出来（不影响插补本身）：%s" % e, "warn")
    elif method in ("mean", "median", "mode"):
        filled = 0
        detail = []
        for c in work.columns:
            if work[c].isna().sum() == 0:
                continue
            if method in ("mean", "median"):
                s = pd.to_numeric(work[c], errors="coerce")
                if s.notna().sum() == 0:
                    continue
                val = s.mean() if method == "mean" else s.median()
                if pd.isna(val):
                    continue
                work[c] = work[c].fillna(val)
                detail.append("%s←%.3f" % (c, val))
            else:
                m = work[c].mode(dropna=True)
                if len(m) == 0:
                    continue
                work[c] = work[c].fillna(m.iloc[0])
                detail.append("%s←%s" % (c, m.iloc[0]))
            filled += 1
        steps.append("用%s填补了 %d 列：%s" % (
            {"mean": "均值", "median": "中位数", "mode": "众数"}[method], filled,
            "；".join(detail[:12]) + ("…" if len(detail) > 12 else "")))
        ctx.log(steps[-1])
    else:
        steps.append("缺失值不动（只做报告）")

    # ---------------- 3. 反向题 ----------------
    rev_spec = (ctx.get("reverse") or "").strip()
    rev_done = []
    if rev_spec:
        for line in rev_spec.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in re.split(r"[,，\t]+", line) if p.strip()]
            if len(parts) < 2:
                ctx.log("反向题这行看不懂，跳过：%s" % line, "warn")
                continue
            var, mx = parts[0], parts[1]
            if var not in work.columns:
                ctx.log("数据里没有 %s，跳过反向题" % var, "warn")
                continue
            try:
                mx = float(mx)
            except Exception:
                ctx.log("%s 的最大值不是数字，跳过" % var, "warn")
                continue
            s = pd.to_numeric(work[var], errors="coerce")
            work[var + "_原始"] = s
            work[var] = (mx + 1) - s
            rev_done.append("%s（最大值 %.0f）" % (var, mx))
            ctx.log("反向重编码：%s = %.0f - 原值" % (var, mx + 1))
        if rev_done:
            steps.append("反向题重编码：" + "、".join(rev_done))

    # ---------------- 4. 合成变量 + 信度 ----------------
    comp_spec = (ctx.get("composite") or "").strip()
    alpha_rows = []
    if comp_spec:
        for line in comp_spec.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            name, expr = line.split("=", 1)
            name = name.strip()
            expr = expr.strip()
            m = re.match(r"^(mean|avg|sum|平均|求和|总分)\s*\((.*)\)\s*$", expr, re.I)
            if m:
                fn = m.group(1).lower()
                items = [x.strip() for x in re.split(r"[,，+\s]+", m.group(2)) if x.strip()]
                how2 = "mean" if fn in ("mean", "avg", "平均") else "sum"
            else:
                items = [x.strip() for x in re.split(r"[+,，\s]+", expr) if x.strip()]
                how2 = "sum"
            items = [c for c in items if c in work.columns]
            if len(items) < 2:
                ctx.log("合成变量 %s 找不到足够的题项，跳过" % name, "warn")
                continue
            sub = work[items].apply(pd.to_numeric, errors="coerce")
            work[name] = sub.mean(axis=1) if how2 == "mean" else sub.sum(axis=1)
            a, n, k, _ = kit.cronbach_alpha(work, items)
            if a is not None:
                alpha_rows.append([name, "%s(%s)" % ("均值" if how2 == "mean" else "求和",
                                                     "、".join(items)), k, n, a])
            ctx.log("合成 %s = %s(%s)，有效样本 %d" % (
                name, how2, "、".join(items), int(work[name].notna().sum())))
            steps.append("合成变量 **%s** = %s（%s）" % (name, expr, "、".join(items)))

    # ---------------- 5. 异常值标记 ----------------
    out_mode = ctx.get("outlier") or "none"
    out_rows = []
    if out_mode != "none":
        for c in work.columns:
            s = pd.to_numeric(work[c], errors="coerce")
            if s.notna().sum() < 8:
                continue
            if s.nunique() <= 5:
                continue
            if out_mode == "z3":
                z = (s - s.mean()) / s.std(ddof=1)
                n_out = int((z.abs() > 3).sum())
            else:
                q1, q3 = s.quantile(0.25), s.quantile(0.75)
                iqr = q3 - q1
                n_out = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())
            if n_out:
                out_rows.append([c, n_out, round(n_out / s.notna().sum() * 100, 1)])
        out_rows.sort(key=lambda r: -r[1])
        if out_rows:
            steps.append("异常值标记（%s）：%s" % (
                "|z|>3" if out_mode == "z3" else "1.5×IQR",
                "、".join("%s %d 个(%.1f%%)" % (r[0], r[1], r[2]) for r in out_rows[:8])))
            ctx.log("标记出 %d 个变量有异常值（只标记，没删）" % len(out_rows))

    # ---------------- 6. 存盘 ----------------
    out_rel = "output/clean_data.csv"
    out_path = ctx.path(out_rel)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    work.to_csv(out_path, index=False, encoding="utf-8-sig")
    ctx.made(out_path)
    ctx.log("写出 clean_data.csv：%d 行 × %d 列" % work.shape)

    # ---------------- 7. 日志与结果 ----------------
    L.append("## 处理步骤\n")
    for i, s in enumerate(steps, 1):
        L.append("%d. %s" % (i, s))
    if not steps:
        L.append("（没有做任何改动，只是读了一遍并另存）")
    L.append("")
    L.append("## 结果\n")
    L.append("- 处理后规模：**%d 行 × %d 列**（原 %d × %d）" % (
        work.shape[0], work.shape[1], n0, c0))
    L.append("- 剩余缺失单元格：**%d**" % int(work.isna().sum().sum()))
    L.append("- 新增列：%s" % ("、".join([c for c in work.columns if c not in df.columns]) or "无"))
    L.append("")

    tables.append({
        "name": "处理前后对比",
        "columns": ["", "行", "列", "缺失单元格"],
        "rows": [["处理前", n0, c0, int(df.isna().sum().sum())],
                 ["处理后", work.shape[0], work.shape[1], int(work.isna().sum().sum())]],
        "note": "每一步的细节见 output/预处理日志.md",
    })
    for i, s in enumerate(steps, 1):
        tables.append({"name": "步骤 %d" % i, "columns": ["做了什么"], "rows": [[s]]})

    if alpha_rows:
        tables.append({
            "name": "合成变量的信度",
            "columns": ["合成变量", "来自", "题数", "有效 n", "Cronbach α"],
            "rows": alpha_rows,
            "note": "α ≥ 0.7 一般算可接受；太低说明这几题不在测同一个东西，合成要谨慎。",
        })
        L.append("## 合成变量信度\n")
        L.append("| 合成变量 | 题数 | 有效 n | α |")
        L.append("|---|---|---|---|")
        for r in alpha_rows:
            L.append("| %s | %d | %d | %.3f |" % (r[0], r[2], r[3], r[4]))
        L.append("")

    if out_rows:
        tables.append({
            "name": "异常值标记",
            "columns": ["变量", "异常个数", "占比%"],
            "rows": out_rows,
            "note": "只是标出来给你看，**没有删**。要不要处理由你判断。",
        })

    md_text = "\n".join(L)
    ctx.save_text("output/预处理日志.md", md_text)

    summary = "预处理完成：%d×%d → %d×%d；缺失 %d → %d；%d 个步骤" % (
        n0, c0, work.shape[0], work.shape[1],
        int(df.isna().sum().sum()), int(work.isna().sum().sum()), len(steps))

    return {
        "summary": summary,
        "tables": tables,
        "figures": [],
        "markdown": [{"name": "预处理日志.md", "rel": "output/预处理日志.md", "text": md_text}],
        "notes": "clean_data.csv 已经写进项目的 output/，下一步「⑤ 统计分析」会用它。",
    }
