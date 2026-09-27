# -*- coding: utf-8 -*-
"""组块 ⓪ 研究设计 · 引擎

把界面上填的东西整理成标准的 `contracts/research_brief.md`。
这一步**不做判断**，只负责把人的话变成后面模块能读的结构——
研究设计本身是研究员的活，模型最多给个初稿。
"""
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WB = os.path.dirname(os.path.dirname(_HERE))
if _WB not in sys.path:
    sys.path.insert(0, _WB)


def _lines(s):
    return [x.strip() for x in (s or "").splitlines() if x.strip()]


def _strip_prefixes(s, kind):
    """把 `- RQ1：xxx` / `RQ1 xxx` / `H3）xxx` 这几种写法都削成光溜溜的正文。

    踩过的坑：模型写「RQ1 需求规模：…」（编号后面是空格不是冒号），
    老的正则只认冒号，于是简报里出现「- RQ1：- RQ1 需求规模：…」这种双份。
    """
    s = str(s or "").strip()
    s = re.sub(r"^[-*•·]\s*", "", s)                       # 列表符号
    s = re.sub(r"^\*{0,2}%s\s*\d+\s*[.、)）:：]?\s*" % kind, "", s, flags=re.I)
    s = re.sub(r"^\*{0,2}%s\s*[.、)）]?\s*[:：]\s*" % kind, "", s, flags=re.I)
    return s.strip()


def run(ctx):
    bg = (ctx.get("background") or "").strip()
    purpose = (ctx.get("purpose") or "").strip()
    rqs = _lines(ctx.get("rqs"))
    hyps = _lines(ctx.get("hypotheses"))
    pop = (ctx.get("population") or "").strip()
    variables = _lines(ctx.get("variables"))          # 原始行（用来做「有没有因变量」的判断）
    dtypes = ctx.get("data_types") or []
    constraints = (ctx.get("constraints") or "").strip()

    if not (bg or purpose or rqs):
        raise ValueError("至少把「背景」或「研究目的」或「研究问题」填一个吧")

    # 变量表：模型很可能给的是 Markdown 表格，别按逗号劈（单元格里本来就有逗号）。
    # 界面上那张表格会直接把逐行数据传过来，优先用它。
    from core import kit
    var_rows = ctx.var_rows("variables", kit.parse_var_table(ctx.get("variables")))
    var_roles = " ".join(r[1] for r in var_rows) if var_rows else " ".join(variables)

    ctx.log("整理研究简报：%d 个 RQ，%d 条假设，%d 个变量" % (len(rqs), len(hyps), len(var_rows)))
    if variables and not var_rows:
        ctx.log("「关键变量与操作化定义」那栏没能解析出变量——检查一下格式，"
                "它应该是一张表或每行「变量名, 角色, 测量层次, 怎么测」", "warn")

    # ---------- 知识库判定 ----------
    # 规则不在这里写死，读 knowledge/*.md（研究员能看、能改、能追问出处）。
    # 命中就挂到结果页上；**只提醒，不改文字，也不拦着不让跑**。
    from core import knowledge as kb
    study_text = " ".join(list(rqs) + list(hyps) + list(dtypes) + [bg])
    kb_hits = kb.check_brief_inputs(purpose=purpose, sample=pop, study_text=study_text,
                                    population=pop)
    ctx.alerts_from(kb_hits)

    L = []
    L.append("# 契约 0 · 研究简报（research_brief）\n")
    L.append("> 组块 0 的产物，**全流程的源头**。提纲、编码、预处理、统计都读它。")
    # ⚠ 落款故意保持「用户研究工作台」（不是界面上的「岚苔 Vesper」）——2026-09-27 前辈拍的板，
    #   报告/契约是给导师看的东西，工具名要中性。别顺手改。
    L.append("> 生成时间：%s（用户研究工作台）\n" % time.strftime("%Y-%m-%d %H:%M"))
    L.append("---\n")

    L.append("## 1. 背景与业务问题\n")
    L.append(bg or "（未填）")
    L.append("")

    L.append("## 2. 研究目的\n")
    L.append("- 一句话目的：%s" % (purpose or "（未填）"))
    L.append("")

    L.append("## 3. 研究问题（RQ）\n")
    if rqs:
        for i, r in enumerate(rqs, 1):
            L.append("- RQ%d：%s" % (i, _strip_prefixes(r, "RQ")))
    else:
        L.append("（未填）")
    L.append("")

    L.append("## 4. 假设\n")
    if hyps:
        for i, h in enumerate(hyps, 1):
            L.append("- H%d：%s" % (i, _strip_prefixes(h, "H")))
    else:
        L.append("（未填。质性研究可以没有假设；量化研究里假设能把后面的统计方法定下来。）")
    L.append("")

    L.append("## 5. 目标人群与抽样\n")
    L.append(pop or "（未填）")
    L.append("")

    L.append("## 6. 关键变量与操作化定义 ⭐\n")
    if var_rows:
        L.append("| 变量名 | 角色 | 测量层次 | 操作化定义（怎么测） |")
        L.append("|---|---|---|---|")
        for name, role, lvl, op in var_rows:
            L.append("| %s | %s | %s | %s |" % (name, role, lvl,
                                                op.replace("|", "／")))
    else:
        L.append("（未填）")
    L.append("")

    L.append("## 7. 数据类型与来源\n")
    name_map = {"interview": "访谈（质性）", "survey": "问卷（量化）", "log": "行为/后台数据"}
    picked = [name_map.get(d, d) for d in dtypes]
    L.append("- 类型：%s" % ("、".join(picked) if picked else "（未选）"))
    L.append("")

    L.append("## 8. 初步分析思路\n")
    if "interview" in dtypes and "survey" not in dtypes:
        L.append("以质性为主 → 走 ② 访谈编码，必要时再做频次化的量化补充。")
    elif "survey" in dtypes:
        L.append("以量化为主 → 走 ④ 预处理，再由 ⑤ 按变量类型走决策树选统计方法。")
    else:
        L.append("（待定）")
    L.append("")

    L.append("## 9. 约束与伦理\n")
    L.append(constraints or "（未填）")
    L.append("- 提醒：直接标识符（姓名/学号/手机/邮箱）在进入任何分析前必须去掉，见 🔒 去标识化模块。")
    L.append("")

    # 提醒：变量表里有没有因变量，直接影响 ⑤ 能不能自动选方法
    roles = var_roles
    warns = []
    if var_rows and "因变量" not in roles and "dependent" not in roles.lower():
        warns.append("变量表里没看到「因变量」——⑤ 统计分析可能选不出方法。")
    if variables and not var_rows:
        # 这不是一条日志能了事的：简报照样会写出去，而下游 ③ 会拿着**空变量表**跑出个空壳问卷
        ctx.alert("「关键变量与操作化定义」填了内容，但一个变量都没解析出来 —— "
                  "写出去的简报里变量表是空的，③ 问卷设计会因此出不了题。",
                  level="error", fix="改成 Markdown 表格（列：变量 | 角色 | 测量层次 | 操作化），"
                                     "或者每行「变量名, 角色, 测量层次, 怎么测」。")
        warns.append("「关键变量与操作化定义」那栏没解析出变量，简报里的变量表是空的 —— "
                     "③ 问卷设计和 ⑤ 统计分析都要靠它，回去把格式改对（Markdown 表格，"
                     "或者每行「变量名, 角色, 测量层次, 怎么测」）。")
    if not rqs:
        warns.append("没有研究问题，后面很难判断分析做到哪算够。")
    if warns:
        L.append("---\n")
        L.append("## ⚠ 给后面几步的提醒\n")
        for w in warns:
            L.append("- " + w)
        L.append("")

    # 设计上的提醒也写进简报 —— 这些是「研究员看过的建议」。
    # 理由：提醒只活在界面上，一刷新就没了；而「我知道这条建议、但我仍然这么设计」
    # 本身就是研究记录的一部分（答辩、伦理审查、后来接手的人都需要看到）。
    # ⚠ 写的是「提醒」不是「问题」：研究人员不采纳，这里也只是留个记录，不做任何阻拦。
    if kb_hits:
        L.append("## 📌 设计提醒（只是提醒，采不采纳由研究员定）\n")
        L.append("> 下面是工作台按 `knowledge/` 里的规则提出的建议，**不是错误**。")
        L.append("> 研究员有权不采纳——这里留一条记录，是为了让设计依据可追溯。\n")
        for h in kb_hits:
            L.append("- **%s**" % h.get("msg", ""))
            if h.get("fix"):
                L.append("  - 建议：%s" % h["fix"])
            if h.get("source"):
                L.append("  - 依据（%s）：%s" % (
                    {"convention": "行业惯例", "opinion": "某家观点",
                     "heuristic": "经验法则"}.get(h.get("kind"), h.get("kind") or "未标注"),
                    h["source"]))
        L.append("")

    md = "\n".join(L)
    ctx.save_text("contracts/research_brief.md", md)

    tables = []

    # 「我写出去的这份简报，后面几步到底读不读得懂」—— 用和下游同一套解析规则回读一遍。
    # 只在有东西没认出来的时候才摆这张表：顺利的时候不该拿一张全绿的诊断表占地方。
    diag = kit.brief_section_report_text(md, "contracts/research_brief.md")
    if diag["failed"]:
        rows = []
        for s in diag["sections"]:
            got = "没认出" if s["failed"] else (
                ("认出 %d 条" % s["parsed"]) if s["present"] else "没有这一节")
            rows.append([s["label"], "有 %d 行内容" % s["body_lines"] if s["present"] else "—", got,
                         "⚠ 格式不对，下游读不出来" if s["failed"] else ""])
        tables.append({
            "name": "简报体检：有 %d 节我没读出来" % len(diag["failed"]),
            "columns": ["小节", "简报里", "我读到的", "要不要紧"],
            "rows": rows,
            "note": "契约文件是流程之间的事实接口。有内容却读不出来，下游会拿着空的东西照样跑 —— "
                    "所以这里明着告诉你，别到 ③ 出空问卷时才发现。",
        })

    if var_rows:
        tables.append({"name": "变量与操作化（%d 个）" % len(var_rows),
                       "columns": ["变量名", "角色", "测量层次", "操作化定义"],
                       "rows": [list(r) for r in var_rows],
                       "note": "这张表决定了 ⑤ 能自动选哪些统计方法——因变量、自变量、测量层次缺一不可。"})
    if rqs:
        tables.append({"name": "研究问题", "columns": ["#", "问题"],
                       "rows": [[i, _strip_prefixes(r, "RQ")] for i, r in enumerate(rqs, 1)]})
    if hyps:
        tables.append({"name": "假设", "columns": ["#", "假设"],
                       "rows": [[i, _strip_prefixes(h, "H")] for i, h in enumerate(hyps, 1)]})

    return {
        "summary": "研究简报已写入 contracts/research_brief.md（%d 个 RQ / %d 条假设 / %d 个变量）"
                   % (len(rqs), len(hyps), len(var_rows)),
        "tables": tables,
        "figures": [],
        "markdown": [{"name": "research_brief.md", "rel": "contracts/research_brief.md", "text": md}],
        "notes": "后续 ① 访谈提纲、④ 预处理、⑤ 统计分析都会读这份简报。",
    }
