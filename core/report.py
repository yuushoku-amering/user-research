# -*- coding: utf-8 -*-
"""工作台 · 报告汇总

`output/` 一多就变成灾难：跑两次分析能攒出十几个文件，
真正进报告的只有十几张表，剩下的（中间件、对照图、SPSS 原文）没人看。
**使用者关心的是"我要的那几个数"，不是"你生成了什么"。**

所以这里做两件事：

1. **产物分层** —— 核心产出（默认摆前面）/ 过程产物（折叠，但不删）。
   分两层而且**分两种来路**：
     · **按约定自动归**（`key_reason()`）：契约文件、报告正文、以及
       "要打开来编辑或逐条过目"的那几类（编码工作表、题项表、提纲、初步分析…）
       —— 这些天生就在流程主干上，不该让人每次去"过程产物"里翻。
     · **研究员自己标 ⭐**：规则没命中的也能自己提上来。存 `output/关键结果.json`。
   ⚠ 原来的注释写的是"**不是程序猜的**" —— 那句现在已经不准确了（有规则在自动归）。
     准确定的说法是：**自动归的部分只用路径/文件名约定**（本项目自己定的约定，可靠），
     **不去猜内容**；拿不准的一律留在过程产物里。
2. **按固定骨架串一份汇总** —— 把各步骤的产物按「背景 → 方法 → 发现 → 局限」串起来，
   **每个数字后面标它出自哪个文件**，并且明说"这是串起来的，不是新写的"。

⚠ 一条硬线：**这份汇总不产生任何新结论**。
它只做搬运和标注来源。谁想让它"帮你写结论"，那是另一件事，不在这个模块里。
"""
import json
import os
import re
import time

FLAGS_REL = "output/关键结果.json"
REPORT_REL = "output/研究报告_汇总.md"

# 骨架：每一节 -> (标题, 找哪些产物, 说明)
SECTIONS = [
    ("研究设计", "背景与研究问题",
     ["contracts/research_brief.md"],
     "研究目的、RQ、变量与操作化定义都在这里。**下游每一步都读它**，所以它错了后面全错。"),
    ("数据采集", "方法、提纲与问卷",
     ["contracts/interview_guide.md", "contracts/survey_design.md", "output/问卷_题项表.csv"],
     "访谈提纲和问卷设计。这一节回答「你是怎么拿到数据的」。"),
    ("分析过程", "数据与预处理",
     ["output/问卷_概要.md", "output/预处理日志.md"],
     "数据长什么样、预处理做了什么。**可复现的关键在这一节**。"),
    ("发现", "分析结果",
     [],       # 这一节自动收所有「分析报告_*.md」+ 研究员标过的结果
     "每个数字后面标了它出自哪个文件。数字全部由程序算出，模型不参与。"),
    ("局限", "这份研究哪里不硬",
     [],       # 自动收诊断类产物
     "把诊断结果和已知局限集中到一处——**答辩时最先被问的就是这里**。"),
]


def _read(path):
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def load_flags(proj):
    """读「关键结果」标记：{rel: {at, note}}。"""
    p = proj.safe(FLAGS_REL)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return (d.get("files") or {}) if isinstance(d, dict) else {}
    except Exception:
        return {}


def toggle_flag(proj, rel, on=True, note=""):
    """标 / 取消标一个产物为「关键结果」。"""
    rel = str(rel or "").replace("\\", "/").lstrip("./")
    if not rel:
        return {"ok": False, "error": "没说是哪个产物"}
    if not os.path.exists(proj.safe(rel)):
        return {"ok": False, "error": "项目里没有这个产物：%s" % rel}
    data = {"files": load_flags(proj)}
    if on:
        old = data["files"].get(rel) or {}
        # ⚠ 不填备注时不要覆盖已有的备注 —— 那等于静默丢掉研究员写过的字。
        #   踩过：重新标一次（只想改个标记）把上次写的「主结论」抹没了。
        note = str(note or "").strip()
        data["files"][rel] = {"at": time.strftime("%Y-%m-%d %H:%M"),
                              "note": note if note else (old.get("note") or "")}
    else:
        data["files"].pop(rel, None)
    data["note"] = ("研究员自己标出来的「这个结果我要用」。程序不猜——"
                    "报告汇总只读这份清单，所以标错了自己改这个文件即可。")
    p = proj.safe(FLAGS_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "rel": rel, "flagged": bool(on), "count": len(data["files"])}


def classify(proj):
    """产物分两层：**核心产出**（默认在前）/ 过程产物（折叠）。

    为什么要**按规则自动分**（2026-09-24 提的）：
      原来只有"研究员点过 ⭐"的才算关键结果 —— 于是一份**必须打开来编辑或分析**的产物
      （最典型：`output/编码工作表.csv`，逐段填编码用的）默认沉在"过程产物"里，
      每次都要先展开、再找。这不是"重要不重要"的问题，是**它天生就在流程的主干上**。
      ⇒ 立几条**按约定**的规则（工具生成的产物，路径/文件名是本项目自己定的，
        所以可以可靠地按约定判），规则写在 `key_reason()` 里，**每条都给一句理由**。

    ⭐ 手动标记仍然算数，而且**优先级更高**：
      · 规则命中的 → 进 key，`why` 写清是哪条规则
      · 研究员点过 ⭐ 的 → 也进 key（规则没命中也能标）
      · 研究员**取消**过某个自动项？目前不做"取消"——取消标记就是把它从 key 挪走，
        规则会在下一次重新把它放回来。这一条**如实写在这里**，不装作支持。
    """
    arts = proj.artifacts()
    flags = load_flags(proj)
    key, other = [], []
    for a in arts:
        rec = flags.get(a["rel"])
        item = dict(a)
        item["note"] = (rec or {}).get("note", "")
        item["flagged_at"] = (rec or {}).get("at", "")
        item["manual"] = bool(rec)
        auto_why = key_reason(a["rel"])
        item["auto_why"] = auto_why
        # `why` 是给界面显示的那一句（手动标的优先说"你标的"）
        item["why"] = ("你标的：%s" % (item["note"] or "关键结果")) if rec else (auto_why or "")
        (key if (rec or auto_why) else other).append(item)
    return {"key": key, "other": other,
            "flagged": len([1 for a in arts if flags.get(a["rel"])]),
            "auto": len([1 for a in key if not a["manual"]]),
            "total": len(arts)}


# 「天生在主干上、必须打开来看/改」的产物 —— 按约定自动进核心产出。
# 每一条都写清**为什么**，好让人知道它凭什么排前面（也方便哪天不认同就来改这张表）。
CORE_NAME_HINTS = ("报告", "编码工作表", "编码汇总", "题项表", "提纲", "设计",
                   "清单", "对照表", "样例", "初步分析")
# 这些虽然也叫"报告/分析"，但是**过程或诊断**件，进核心产出只会把眼睛弄花
NOT_CORE_HINTS = ("预处理日志", "去标识化报告", "格式说明", "脱敏", "变更说明",
                  "结果汇总", "日志", "缓存", "临时", "埋雷", "markDown")


def key_reason(rel):
    """这个产物"天生在主干上"吗？是 → 返回一句理由；否 → 返回空串。

    ⚠ 判据只依赖**本项目自己生成的路径与文件名约定**（`contracts/`、`output/分析报告_*.md`…），
      不去猜内容 —— 猜内容就会像"论文章节骨架"那样，同一个文件名在不同项目里含义不同。
    """
    r = str(rel or "").replace("\\", "/")
    base = os.path.basename(r)
    if not r or r.startswith("_") or "/_" in r:
        return ""
    if any(k in base for k in NOT_CORE_HINTS):
        return ""
    # ① 契约：这一层的文件是**下游每一步的输入**，也都是要人来定稿的
    if r.startswith("contracts/"):
        return "契约文件：下游每一步都读它，也是你要定稿的东西"
    # ② 明确的分析报告 / 汇总：这是交付物的正文
    if re.match(r"^(分析报告|研究报告|编码汇总|问卷_概要|分析_结果)", base):
        return "报告正文：写结论时直接引用"
    # ③ 名字里带"要编辑/要看"的那几个（编码工作表、题项表、提纲、初步分析…）
    if any(k in base for k in CORE_NAME_HINTS):
        return "流程主干的产物：要打开来编辑或逐条过目"
    # ⚠ 配图**不进**核心产出（实测调过一版）：
    #   判据是"**需要编辑或分析时必须看的信息**"。图是报告里嵌的，
    #   要看图的时候你是在读那份报告，不是在翻文件列表 —— 放进核心产出只占地方。
    return ""


def _auto_sections(proj):
    """自动收：分析报告类（发现）、诊断/局限类（局限）。"""
    arts = [a["rel"] for a in proj.artifacts()]
    found = [r for r in arts if os.path.basename(r).startswith("分析报告")]
    limits = [r for r in arts if any(k in os.path.basename(r)
                                     for k in ("预处理日志", "去标识化报告", "问卷_概要"))]
    return sorted(found), sorted(limits)


def build(proj, title=""):
    """生成汇总 markdown。返回 (markdown, 统计)。

    ⚠ 只搬运 + 标来源，不写新结论。
    """
    flags = load_flags(proj)
    cls = classify(proj)
    found, limits = _auto_sections(proj)

    L = []
    L.append("# 研究报告 · 汇总\n")
    L.append("> 这份东西是**程序按固定骨架串起来的**，内容都来自项目里已有的产物。")
    L.append("> **它不会替你写结论，也不会新增任何数字** —— 每个数字后面都标了它出自哪个文件，")
    L.append("> 你可以顺着去核。写结论是你的事。\n")
    # ⚠ 落款故意写「用户研究工作台」，**不是**界面上的品牌名「岚苔 Vesper」——
    #   这份报告是拿去交作业/给导师看的，工具名保持中性（2026-09-27 拍板）。
    #   改品牌名时别顺手改这一行。
    L.append("> 生成时间：%s（用户研究工作台）\n" % time.strftime("%Y-%m-%d %H:%M"))
    if title:
        L.append("**%s**\n" % title)
    L.append("---\n")

    used = []
    for _, sec_title, rels, why in SECTIONS:
        picked = [r for r in rels if os.path.exists(proj.safe(r))]
        if sec_title == "分析结果":
            picked = found + [r for r in flags if r not in found]
        elif sec_title == "这份研究哪里不硬":
            picked = limits
        L.append("## %s\n" % sec_title)
        if why:
            L.append("%s\n" % why)
        if not picked:
            L.append("- （这一步还没有产物）\n")
            continue
        for rel in picked:
            txt = _read(proj.safe(rel))
            mark = "⭐ " if rel in flags else ""
            L.append("### %s`%s`\n" % (mark, rel))
            if rel in flags and flags[rel].get("note"):
                L.append("> 你标的备注：%s\n" % flags[rel]["note"])
            if not txt.strip():
                L.append("（空文件）\n")
                continue
            # 摘录而不是整篇塞进来：报告要能读，不是又一个文件堆
            lines = [x for x in txt.splitlines() if x.strip()]
            keep = lines[:40]
            L.append("\n".join(keep))
            if len(lines) > 40:
                L.append("\n> …（后面还有 %d 行，全文见 `%s`）\n" % (len(lines) - 40, rel))
            L.append("")
            used.append(rel)

    L.append("---\n")
    L.append("## 这一节是给答辩/评审看的\n")
    L.append("- 上面每一条都能顺着文件名回到原始产物；`_history/` 里还留着每次改动前的版本")
    L.append("- 标了 ⭐ 的是你自己标为「关键结果」的产物")
    L.append("- 数字全部由程序计算（Python），模型不参与算数")
    L.append("- **没写进来的**：你的解释、判断、下一步建议 —— 那些该由你写\n")

    md = "\n".join(L)
    stat = {"sections": len([1 for _, t, r, _ in SECTIONS]),
            "used": len(set(used)), "flagged": cls["flagged"], "total": cls["total"]}
    return md, stat


def write(proj, title=""):
    md, stat = build(proj, title)
    proj.write_text(REPORT_REL, md)
    return {"ok": True, "rel": REPORT_REL, "bytes": len(md), "stat": stat}
