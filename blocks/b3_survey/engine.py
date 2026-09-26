# -*- coding: utf-8 -*-
"""组块 ③ 问卷数据统计 · 引擎

读一个问卷导出文件，按勾选的项算：样本概况 / 频数 / 描述统计 / 交叉表 / 信度 / 开放题词频。

原则：**所有数字都在这里产生**，模型不碰算术。
产物全部落在项目的 output/ 下，界面只是把它们显示出来。
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

KIND_CN = {"continuous": "连续", "categorical": "分类", "text": "文本", "empty": "空列"}


def _safe(s):
    return re.sub(r"[^\w\u4e00-\u9fa5]+", "_", str(s)).strip("_")[:38] or "x"


def _pct_str(p):
    return kit.fmt_p(p)


def _pick_scale_groups(ctx, df, kit):
    """挑出「一组量表题」。信度（α）和因子分析**共用这一份**。

    ⚠ 不共用的话，同一批题在信度那边算出来是一组、在因子分析那边又是另一组，
      而两份结果会一起写进同一份报告 —— 那就是自相矛盾。
    """
    spec = (ctx.get("scale_vars") or "").strip()
    groups = {}
    if spec:
        cols = [c for c in re.split(r"[,，\s]+", spec) if c]
        cols = [c for c in cols if c in df.columns]
        missing = [c for c in re.split(r"[,，\s]+", spec) if c and c not in df.columns]
        if missing:
            ctx.log("这些变量不在数据里，已忽略：%s" % "、".join(missing), "warn")
        if len(cols) >= 2:
            groups["指定量表"] = cols
    if not groups:
        groups = kit.guess_scale_vars(df)
        if groups:
            ctx.log("自动猜到 %d 组量表：%s" % (
                len(groups), "；".join("%s(%d题)" % (k, len(v)) for k, v in groups.items())))
    return groups


def run(ctx):
    # ---------------- 1. 读数据 ----------------
    file_rel = (ctx.get("file") or "").strip().strip('"')
    if not file_rel:
        raise ValueError("请先选一个问卷数据文件（第一个输入框）")
    path = file_rel if os.path.isabs(file_rel) else ctx.path(file_rel)
    df, how = kit.read_table(path)
    df = kit.clean_columns(df)
    n_rows, n_cols = df.shape
    ctx.log("读入 %s → %d 行 × %d 列（%s）" % (os.path.basename(path), n_rows, n_cols, how))
    if n_rows == 0:
        raise ValueError("这个文件一行数据都没有")

    tasks = ctx.get("tasks") or []
    if not tasks:
        raise ValueError("上面「要算什么」一个都没勾")
    try:
        top_n = int(float(ctx.get("top_n") or 15))
    except Exception:
        top_n = 15

    vars_info = kit.profile_variables(df)
    cont = [v["name"] for v in vars_info if v["kind"] == "continuous"]
    cats = [v["name"] for v in vars_info if v["kind"] == "categorical"]
    txts = [v["name"] for v in vars_info if v["kind"] == "text"]
    ctx.log("变量：连续 %d · 分类 %d · 文本 %d" % (len(cont), len(cats), len(txts)))

    tables, figures = [], []
    md = []
    md.append("# 问卷数据统计 · 概要\n")
    md.append("> 数据文件：`%s`（%s）" % (file_rel, how))
    md.append("> 样本量：**%d 行 × %d 列**" % (n_rows, n_cols))
    md.append("> 变量：连续 %d · 分类 %d · 文本 %d\n" % (len(cont), len(cats), len(txts)))

    miss_cells = int(df.isna().sum().sum())
    total_cells = n_rows * n_cols
    headline = "读入 %d 行 × %d 列；缺失单元格 %d / %d（%.1f%%）" % (
        n_rows, n_cols, miss_cells, total_cells,
        (miss_cells / total_cells * 100) if total_cells else 0)

    # ---------------- 2. 样本概况 ----------------
    if "profile" in tasks:
        ctx.log("算样本概况…")
        rows = [[v["name"], KIND_CN.get(v["kind"], v["kind"]), v["n_valid"],
                 v["n_missing"], v["missing_pct"], v["n_unique"]] for v in vars_info]
        tables.append({
            "name": "变量清单（%d 个）" % len(rows),
            "columns": ["变量", "类型", "有效 n", "缺失", "缺失率%", "取值数"],
            "rows": rows,
            "note": "类型是自动认的：取值少且为整数 → 分类；其余数值 → 连续；长文本 → 文本。",
        })
        ctx.save_table("问卷_变量清单.csv", rows,
                       ["变量", "类型", "有效n", "缺失", "缺失率%", "取值数"])

        # 缺失较多的变量
        worst = sorted(vars_info, key=lambda v: -v["n_missing"])[:10]
        worst = [v for v in worst if v["n_missing"] > 0]
        md.append("## 一、样本概况\n")
        md.append("- 有效样本 **%d**；缺失单元格 %d / %d（**%.1f%%**）" % (
            n_rows, miss_cells, total_cells, (miss_cells / total_cells * 100) if total_cells else 0))
        md.append("- 完整作答（一行都不缺）的样本：**%d**（%.1f%%）" % (
            int(df.dropna().shape[0]), df.dropna().shape[0] / n_rows * 100))
        if worst:
            md.append("\n缺失最多的变量：\n")
            md.append("| 变量 | 缺失 | 缺失率 |")
            md.append("|---|---|---|")
            for v in worst:
                md.append("| %s | %d | %.1f%% |" % (v["name"], v["n_missing"], v["missing_pct"]))
        else:
            md.append("\n没有任何变量有缺失值。")
        md.append("")

    # ---------------- 3. 频数分布 ----------------
    if "freq" in tasks:
        ctx.log("算频数分布…")
        pick = cats[:12]
        if not pick:
            ctx.log("没有认出来的分类变量，频数跳过", "warn")
        for c in pick:
            rows, total, miss = kit.freq_table(df[c], top=top_n)
            if not rows:
                continue
            tables.append({
                "name": "频数 · %s" % c,
                "columns": ["取值", "频数", "百分比%", "累计%"],
                "rows": rows,
                "note": "有效 %d 人，缺失 %d 人" % (total, miss),
            })
            ctx.save_table("问卷_频数_%s.csv" % _safe(c), rows,
                           ["取值", "频数", "百分比%", "累计%"])
        if pick:
            md.append("## 二、频数分布\n")
            md.append("共 %d 个分类变量，逐个体现在「结果」页的频数表里，也已存成 `output/问卷_频数_*.csv`。\n" % len(pick))

    # ---------------- 4. 描述统计 ----------------
    if "desc" in tasks:
        ctx.log("算描述统计…")
        rows = kit.describe_table(df, cont)
        if rows:
            tables.append({
                "name": "描述统计（连续变量）",
                "columns": ["变量", "n", "均值", "标准差", "中位数", "最小", "最大", "偏度", "峰度"],
                "rows": rows,
                "note": "偏度/峰度看分布形状：|偏度|>1 说明明显偏斜，均值可能不代表典型值。",
            })
            ctx.save_table("问卷_描述统计.csv", rows,
                           ["变量", "n", "均值", "标准差", "中位数", "最小", "最大", "偏度", "峰度"])
            md.append("## 三、描述统计\n")
            md.append("| 变量 | n | 均值 | 标准差 | 中位数 |")
            md.append("|---|---|---|---|---|")
            for r in rows[:20]:
                md.append("| %s | %d | %.3f | %s | %.3f |" % (
                    r[0], r[1], r[2], ("%.3f" % r[3]) if r[3] is not None else "—", r[4]))
            md.append("")
        else:
            ctx.log("没有认出连续变量，描述统计跳过", "warn")

    # ---------------- 5. 交叉表 ----------------
    if "cross" in tasks:
        ctx.log("算交叉表…")
        pairs = []
        for line in (ctx.get("cross_vars") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in re.split(r"[,，\t]+", line) if p.strip()]
            if len(parts) >= 2:
                pairs.append((parts[0], parts[1]))
        if not pairs:
            # 自动挑：优先取值 2~6 的分类变量
            good = [v["name"] for v in vars_info
                    if v["kind"] == "categorical" and 2 <= v["n_unique"] <= 6]
            pool = good or cats
            if len(pool) >= 2:
                pairs = [(pool[0], pool[1])]
                ctx.log("没指定，自动选了：%s × %s" % pairs[0])
        for a, b in pairs:
            try:
                rows, cols_out, info = kit.cross_table(df, a, b)
            except ValueError as e:
                ctx.log("跳过 %s × %s：%s" % (a, b, e), "warn")
                continue
            ex = info["extra"]
            note = ""
            if "chi2" in ex:
                note = ("χ²=%.3f, df=%d, p=%s, n=%d；Cramér's V=%.3f（0.1 弱 / 0.3 中 / 0.5 强）"
                        % (ex["chi2"], ex["dof"], _pct_str(ex["p"]), ex["n"],
                           ex["cramers_v"] if ex["cramers_v"] is not None else float("nan")))
                if ex.get("cells_expected_lt5"):
                    note += "；⚠ 有 %d/%d 个格子期望频数<5，卡方结果要谨慎" % (
                        ex["cells_expected_lt5"], ex["n_cells"])
            tables.append({"name": "交叉表 · %s × %s" % (a, b), "columns": cols_out,
                           "rows": rows, "note": note})
            ctx.save_table("问卷_交叉_%s_x_%s.csv" % (_safe(a), _safe(b)), rows, cols_out)

            md.append("## 四、交叉表 · %s × %s\n" % (a, b))
            md.append("| " + " | ".join(str(c) for c in cols_out) + " |")
            md.append("|" + "---|" * len(cols_out))
            for r in rows:
                md.append("| " + " | ".join(str(x) for x in r) + " |")
            if note:
                md.append("\n%s\n" % note)

    # ---------------- 6. 量表信度 ----------------
    alpha_head = False          # 「效度与信度」这个小标题只写一次的标记（信度和因子分析共用）
    if "alpha" in tasks:
        ctx.log("算 Cronbach α…")
        groups = _pick_scale_groups(ctx, df, kit)
        if not groups:
            ctx.log("没找到量表题（列名带序号、取值 1~7 的同一组题）。可以在界面上手填题目名。", "warn")
        alpha_head = False
        for gname, cols in groups.items():
            a, n, k, drop = kit.cronbach_alpha(df, cols)
            if a is None:
                ctx.log("%s 算不了 α（有效样本 %d、题数 %d）" % (gname, n, k), "warn")
                continue
            judge = ("很好" if a >= 0.9 else "可接受" if a >= 0.8 else
                     "勉强" if a >= 0.7 else "偏低" if a >= 0.6 else "不可用")
            tables.append({
                "name": "信度 · %s（%d 题）" % (gname, k),
                "columns": ["题项 / 合计", "α"],
                "rows": [["α（全部 %d 题）" % k, a]] + [[c, v] for c, v in drop],
                "note": "有效样本 %d；α=%.3f（%s）。若删掉某题 α 明显上升，说明那题拖后腿。" % (n, a, judge),
            })
            ctx.save_table("问卷_信度_%s.csv" % _safe(gname),
                           [["题项", "删除后α"]] + [[c, v] for c, v in drop],
                           ["题项", "删除后α"])
            if not alpha_head:
                md.append("## 五、量表信度\n")
                alpha_head = True
            md.append("**%s**（%d 题，有效样本 %d）：α = **%.3f** —— %s" % (gname, k, n, a, judge))
            worse = [c for c, v in drop if v is not None and v > a + 0.01]
            if worse:
                md.append("\n删掉这些题 α 会上升（说明它们和其它题不太一致）：%s" % "、".join(worse))
            md.append("")

    # ---------------- 7. 因子分析 / 效度 ----------------
    # ⚠ 和信度**挨着放**是刻意的：效度和信度本来就该一起报
    #   （"这量表测的是不是同一个东西" + "测的准不准"）。
    if "factor" in tasks:
        ctx.log("做因子分析…")
        from core import factor as _fa
        # ⚠ ④ 这一块**没有**"显著性水平"那个表单栏（那是 ⑥ 的），所以这里自己定。
        #   Bartlett 的判定门槛用它。
        alpha = 0.05
        groups_f = _pick_scale_groups(ctx, df, kit)
        if not groups_f:
            ctx.log("没找到量表题，因子分析跳过（可以在界面上手填题目名）", "warn")
        else:
            # ⚠ 要**每一组都做**，不是只做第一组。
            #   实测踩到：猜到 Q1/Q2 两组（各 5 题），只做第一组 →
            #   报告里只有 Q1 的效度，Q2 那份**看着像"没做"**，
            #   而研究员会把"没输出"读成"没问题"。
            try:
                _nf = int(float(ctx.get("factor_n") or 0))
            except Exception:
                _nf = 0
            if len(groups_f) > 1:
                ctx.log("找到 %d 组量表题，**每一组都做**：%s"
                        % (len(groups_f), "、".join(groups_f.keys())))
        for gname, cols in (groups_f or {}).items():
            res = _fa.factor_analyze(df, cols,
                                     n_factors=(_nf if _nf > 0 else None),
                                     method=(ctx.get("factor_method") or "pca"))
            if res.get("error"):
                ctx.alert("因子分析没做成：%s" % res["error"], level="warn", kind="internal")
            else:
                # 适用性：KMO + Bartlett（两个都要看，读法相反）
                _k = (res["kmo"] or {}).get("kmo")
                _b = res["bartlett"]
                _judge = ("很好" if (_k or 0) >= .9 else "好" if (_k or 0) >= .8 else
                          "还行" if (_k or 0) >= .7 else "一般" if (_k or 0) >= .6 else
                          "勉强" if (_k or 0) >= .5 else "**不可接受**")
                tables.append({
                    "name": "这份数据适不适合做因子分析 · %s" % gname,
                    "columns": ["指标", "值", "怎么读"],
                    "rows": [
                        ["KMO", ("%.3f" % _k if _k is not None else "—"), "%s（惯例：<0.5 不可接受、>0.8 好）" % _judge],
                        ["Bartlett 球形检验 χ²", "%.1f" % _b["chi2"], "df=%d" % _b["df"]],
                        ["  └ p", _pct_str(_b["p"]),
                         "**p 要小才好**（说明题之间有共同变异，值得做因子分析）"
                         if _b["p"] is not None and _b["p"] <= alpha
                         else "⚠ 不显著 → 题目之间本来就没多少共同的东西，做因子分析意义不大"],
                    ],
                    "note": "**这两个是两件事**：Bartlett 说「有没有共同变异」，"
                            "KMO 说「共同变异占多大比例」。两个都要看——"
                            "Bartlett 显著但 KMO 很低的情况是有的。"
                            "⚠ Bartlett 的读法**和一般检验相反**：p 小才好。",
                })
                # 因子数建议
                _pl = res.get("parallel_line")
                tables.append({
                    "name": "抽几个因子 · %s" % gname,
                    "columns": ["依据", "建议因子数", "说明"],
                    "rows": [
                        ["Kaiser 准则（特征值>1）", str(res["kaiser_n"]),
                         "⚠ 题目多的时候会**高估**"],
                        ["平行分析", str(res["parallel_n"]),
                         "和随机数据比，超过基准线的才保留（**更推荐**）"],
                        ["这次实际抽了", str(res["n_factors"]),
                         "自动判断按平行分析来；也可以在上面手填"],
                    ],
                    "note": "特征值（前 8 个）：%s\n平行分析基准线：%s\n"
                            "碎石图看「拐点」也是一个办法，但它是主观的 —— "
                            "所以才给平行分析这种**有明确判据**的。" % (
                                "、".join("%.2f" % v for v in res["eigenvalues"][:8]),
                                "、".join("%.2f" % v for v in (_pl or [])[:8])),
                })
                # 载荷表
                _load_rows = []
                for i, c in enumerate(res["cols"]):
                    row = [c] + ["%.3f" % v for v in res["loadings"][i]] + \
                          ["%.3f" % res["communality"][i]]
                    _load_rows.append(row)
                tables.append({
                    "name": "旋转后因子载荷 · %s（%s）" % (
                        gname, "主成分" if res["method"] == "pca" else "主轴因子"),
                    "columns": ["题项"] + ["因子%d" % (j + 1)
                                           for j in range(res["n_factors"])] + ["共同度"],
                    "rows": _load_rows,
                    "note": "有效 n=%d、%d 道题；共解释 %.1f%% 的方差。\n"
                            "**怎么看**：每道题**最大**的那个载荷就是它归属的因子；"
                            "一般要求 ≥0.40（这里是 %.2f）。\n"
                            "⚠ 旋转**不改变**总解释方差，只把它在因子之间重新分配 —— "
                            "所以别说「旋转后解释率提高了」。"
                            % (res["n"], res["p"], res["explained_total"] * 100,
                               res["min_loading"]),
                })
                # 因子命名线索 + 双重载荷
                _sug = _fa.suggest_names(res)
                if _sug:
                    tables.append({
                        "name": "每个因子由哪几道题撑着 · %s（命名靠你）" % gname,
                        "columns": ["因子", "载荷最高的题项", "标记题数"],
                        "rows": [[("因子%d" % s["factor"]),
                                  "、".join("%s(%.2f)" % (a, b) for a, b in s["items"]) or "（没有题达到阈值）",
                                  str(s["n_marked"])] for s in _sug],
                        "note": "**因子叫什么名字是你的判断**，程序只把「哪几道题落在这个因子上」列出来。"
                                "看这些题在问什么，就能给它起名。",
                    })
                _cross = _fa.cross_loading_table(res)
                if _cross:
                    tables.append({
                        "name": "⚠ 横跨两个因子的题 · %s（双重载荷）" % gname,
                        "columns": ["题项", "主因子", "主载荷", "次因子", "次载荷"],
                        "rows": [[c["item"], "因子%d" % c["primary"], "%.3f" % c["primary_loading"],
                                  "因子%d" % c["secondary"], "%.3f" % c["secondary_loading"]]
                                 for c in _cross],
                        "note": "这些题**两个因子都能解释**，是结构里最不清楚的地方 —— "
                                "通常要考虑删掉它，或者改写它的措辞。",
                    })
                    ctx.alert("有 %d 道题**双重载荷**（横跨两个因子）：%s —— "
                              "它们是结构里最该处理的地方。"
                              % (len(_cross), "、".join(c["item"] for c in _cross[:5])),
                              level="warn", kind="internal",
                              fix="看那张「横跨两个因子的题」的表；删掉或改写措辞，然后重跑。")
                _weak = [c for i, c in enumerate(res["cols"]) if res["communality"][i] < 0.30]
                if _weak:
                    ctx.alert("有 %d 道题的**共同度 < 0.30**（%s）—— 它们跟其它题几乎没有共同变异，"
                              "留在量表里贡献很小。" % (len(_weak), "、".join(_weak[:5])),
                              level="warn", kind="internal")
                # 碎石图
                if "fig" in (ctx.get("tasks") or []) or True:
                    try:
                        plt = kit.setup_matplotlib()
                        fig, ax = plt.subplots(figsize=(6.6, 3.8))
                        ev = res["eigenvalues"]
                        ax.plot(range(1, len(ev) + 1), ev, "o-", color="#2f6fed", lw=1.6)
                        ax.axhline(1.0, color="#e2664f", ls="--", lw=1.2, label="特征值 = 1")
                        if _pl:
                            ax.plot(range(1, len(_pl) + 1), _pl, "s--", color="#9aa3b2",
                                    lw=1.2, ms=4, label="平行分析基准线")
                        ax.set_xlabel("因子序号")
                        ax.set_ylabel("特征值")
                        ax.set_title("碎石图 + 平行分析", fontsize=11)
                        ax.legend(fontsize=8.5, frameon=False)
                        fn = "fig_问卷_碎石图_%s.png" % _safe(gname)
                        fp = ctx.out_path(fn)
                        os.makedirs(os.path.dirname(fp), exist_ok=True)
                        fig.tight_layout(); fig.savefig(fp); plt.close(fig)
                        ctx.made(fp)
                        figures.append({"rel": "output/" + fn,
                                        "name": "碎石图 + 平行分析",
                                        "caption": "实际特征值（蓝）穿过基准线（灰）的位置就是该保留的因子数"})
                    except Exception as e:
                        ctx.log("碎石图没画出来：%s" % e, "warn")
                ctx.save_table("问卷_因子载荷_%s.csv" % _safe(gname),
                               [["题项"] + ["因子%d" % (j + 1) for j in range(res["n_factors"])]
                                + ["共同度"]] +
                               [[c] + ["%.4f" % v for v in res["loadings"][i]]
                                + ["%.4f" % res["communality"][i]]
                                for i, c in enumerate(res["cols"])],
                               None)
                if not alpha_head:
                    md.append("## 五、效度与信度\n")
                    alpha_head = True
                md.append("**因子分析**（%s，%d 题）：KMO=%.3f（%s）、"
                          "Bartlett χ²=%.1f (df=%d, p=%s)；抽 %d 个因子，共解释 %.1f%%。"
                          % ("主成分" if res["method"] == "pca" else "主轴因子",
                             res["p"], _k or 0, _judge, _b["chi2"], _b["df"], _pct_str(_b["p"]),
                             res["n_factors"], res["explained_total"] * 100))
                md.append("")

    # ---------------- 8. 开放题关键词 ----------------
    if "open" in tasks:
        ctx.log("统计开放题关键词…")
        ov = (ctx.get("open_var") or "").strip()
        if ov and ov not in df.columns:
            ctx.log("数据里没有 %s 这一列，改成自动挑一个文本列" % ov, "warn")
            ov = ""
        if not ov:
            ov = txts[0] if txts else ""
        if not ov:
            ctx.log("没有文本列，开放题跳过", "warn")
        else:
            series = df[ov].dropna().astype(str)
            series = series[series.str.strip().str.len() > 1]
            words = kit.keywords(series, top=20)
            if words:
                tables.append({
                    "name": "开放题关键词 · %s" % ov,
                    "columns": ["关键词", "出现次数", "提及人数占比%"],
                    "rows": [[w, c, round(c / len(series) * 100, 1)] for w, c in words],
                    "note": "有效作答 %d 条。这是粗略的词频（按 2 字组合统计，未做精确分词），"
                            "只看高频词的指向，别当正式编码用。" % len(series),
                })
                ctx.save_table("问卷_开放题关键词_%s.csv" % _safe(ov),
                               [[w, c] for w, c in words], ["关键词", "出现次数"])
                md.append("## 六、开放题关键词 · %s\n" % ov)
                md.append("有效作答 %d 条，高频词：" % len(series))
                md.append("、".join("%s(%d)" % (w, c) for w, c in words[:15]))
                md.append("")

    # ---------------- 8. 画图 ----------------
    if cats and ("freq" in tasks or "profile" in tasks):
        try:
            plt = kit.setup_matplotlib()
            for i, c in enumerate(cats[:3]):
                rows, total, miss = kit.freq_table(df[c], top=8)
                if len(rows) < 2:
                    continue
                labels = [r[0][:12] for r in rows]
                vals = [r[1] for r in rows]
                fig, ax = plt.subplots(figsize=(7.2, 3.4))
                bars = ax.bar(range(len(vals)), vals,
                              color=[kit.PALETTE[j % len(kit.PALETTE)] for j in range(len(vals))])
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=9)
                ax.set_ylabel("人数")
                ax.set_title("%s 分布（n=%d）" % (c, total), fontsize=11)
                for b, v, r in zip(bars, vals, rows):
                    ax.text(b.get_x() + b.get_width() / 2, v, "%.0f%%" % r[2],
                            ha="center", va="bottom", fontsize=8.5, color="#6b7280")
                fn = "fig_问卷_%s.png" % _safe(c)
                fp = ctx.out_path(fn)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                fig.tight_layout()
                fig.savefig(fp)
                plt.close(fig)
                ctx.made(fp)
                figures.append({"rel": "output/" + fn, "name": c + " 分布",
                                "caption": "前几类，条上百分比为占比"})
        except Exception as e:
            ctx.log("画图失败（不影响数字）：%s" % e, "warn")

    # ---------------- 9. 收口 ----------------
    md_path = ctx.save_text("output/问卷_概要.md", "\n".join(md))
    ctx.log("概要写入 %s" % md_path)

    result = {
        "summary": headline,
        "tables": tables,
        "figures": figures,
        "markdown": [{"name": "问卷_概要.md", "rel": "output/问卷_概要.md", "text": "\n".join(md)}],
        "notes": "数字全部由 Python 算出；产物已存到项目的 output/ 目录。",
    }
    ctx.log("完成：%d 张表，%d 张图" % (len(tables), len(figures)))
    return result
