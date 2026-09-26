# -*- coding: utf-8 -*-
"""组块 ① 访谈提纲设计 · 引擎

读研究简报 → 把研究问题摊成提纲。

**这里刻意不做「自动写问题」**：访谈提纲的问题措辞是研究员的功夫，
程序能做的是把结构摆好——每个 RQ 给一组**提问角度**（经历/原因/感受/对比/期望），
把变量表转成可问的探测句，再附一份「哪些问法会把答案带偏」的备忘。
研究员照着填，比让模型编十个漂亮问题有用得多。
"""
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WB = os.path.dirname(os.path.dirname(_HERE))
if _WB not in sys.path:
    sys.path.insert(0, _WB)
from core import kit          # noqa: E402


# --------------------------------------------------------------------------- #
# 解析研究简报
# --------------------------------------------------------------------------- #

def _is_placeholder(v):
    """模板里的占位说明（整句被括号包起来的提示）不算内容。"""
    v = (v or "").strip()
    return (v.startswith("（") and v.endswith("）")) or (v.startswith("(") and v.endswith(")"))


def _parse_brief(text):
    """解析研究简报 —— **直接用 `core/kit.parse_brief`，不在这儿另写一份**。

    ⚠ 这里曾经有一份私有副本，是踩过的坑：
      它只取了变量表的**前三列**（变量名 / 角色 / 测量层次），把第 4 列
      「怎么测」整列丢掉了 —— 而那一列才是最有用的东西。
      后果实测：契约写着 `单选：陪伴/情感支持/新鲜感/身边人都谈/其他`，
      提纲却只会说「把选项念出来让受访者选」—— **让你念选项，可选项根本没进提纲**。
      更糟的是两份解析器会各自漂移（`kit.py` 里那句注释正是警告这件事）。
      ⇒ 结论：**一份解析器**，全工作台共用。③ 就是直接调 kit 的。
    """
    d = kit.parse_brief(text or "")
    if not isinstance(d, dict):
        d = {}
    d.setdefault("purpose", "")
    d.setdefault("rqs", [])
    d.setdefault("hyps", [])
    d.setdefault("variables", [])
    d.setdefault("population", "")
    d.setdefault("background", "")
    # 变量统一成 4 列 [名, 角色, 测量层次, 怎么测]，短了就补空 —— 调用方按 4 列取
    d["variables"] = [(list(v) + ["", "", "", ""])[:4] for v in (d.get("variables") or [])]
    return d


ANGLE_TEMPLATES = [
    ("经历", "能具体说说最近一次的经过吗？从什么时候开始的、当时在做什么？"),
    ("原因", "你觉得主要是哪些原因？其中哪一个影响最大？"),
    ("感受", "这件事当时让你有什么感觉？后来有变化吗？"),
    ("对比", "和以前比，有什么不一样？"),
    ("期望", "如果要改善，你希望先动哪一块？"),
]

PROBE_BY_MEASURE = {
    "定类": "「{name}」属于哪一类？（把选项念出来让受访者选，别让他猜）",
    "定序": "如果给「{name}」排个档，你会排在哪一档？为什么不是更高一档？",
    "定距": "如果给「{name}」打 1 到 5 分，你打几分？为什么不是更高一分？",
    "定比": "「{name}」大概是多少？（先让他自己说数字，别急着给区间）",
}

# 测量层次可能写成别的说法 → 归到四类里
_MEASURE_ALIAS = {
    "定类": "定类", "类别": "定类", "分类": "定类", "名义": "定类", "nominal": "定类",
    "定序": "定序", "顺序": "定序", "等级": "定序", "等级": "定序", "ordinal": "定序",
    "定距": "定距", "等距": "定距", "interval": "定距",
    "定比": "定比", "等比": "定比", "比率": "定比", "连续": "定比", "ratio": "定比",
}


def _measure_key(measure):
    """把「测量层次」那一格归成四类之一。

    ⚠ 踩过两个坑：
      1. 复合值：契约会写 `定序（意向量表）；定比（最高支付金额）`、
         `定比（或定序）`。旧实现用 `if k in measure` 遍历，**「定类」永远先命中**
         （字典序），于是"定序"的题被出成"归类"题、甚至"定比"的变量被出成 1~5 分。
         ⇒ 先取**主层次**（`；`/`或` 前的第一段、去掉括号内容），再精确匹配。
      2. 层次写成别名（`连续`『类别』）时静默兜底成"定距"，给**定类**变量出 1~5 分题。
         ⇒ 别名表兜住，仍然认不出才退回"定距"，并且这件事会被上层记进日志。
    """
    raw = str(measure or "").strip()
    if not raw:
        return "定距"
    # 主层次：第一个分隔符之前、去括号
    main = re.split(r"[；;，,、/]|或", raw)[0]
    main = re.sub(r"[（(][^）)]*[）)]", "", main).strip()
    if main in _MEASURE_ALIAS:
        return _MEASURE_ALIAS[main]
    for key in ("定类", "定序", "定距", "定比"):
        if key in main:
            return key
    # 退一步：整串里找（长词优先：定比 → 定距 → 定序 → 定类，避免"定类"抢走"定比"）
    for key in ("定比", "定距", "定序", "定类"):
        if key in raw:
            return key
    for alias, key in _MEASURE_ALIAS.items():
        if alias in raw:
            return key
    return "定距"


def _topic_phrase(info):
    """给开场白和暖场用的**话题短语**（别留「关于……的研究」这种省略号）。

    优先从研究目的里取，取不到就从第一个 RQ 里截。截法保守：
    去掉「研究/分析/了解/识别」这类动词开头和括号里的解释，最多留 20 字。
    """
    def _clean_topic(s):
        s = re.sub(r"[（(][^）)]*[）)]", "", str(s or "")).strip()
        s = re.sub(r"^(研究|分析|了解|识别|探究|探讨|考察|评估|测量|描述)", "", s)
        s = s.strip("，。、；：: ").strip()
        # ⚠ 只要**第一个小句**：研究目的常常是「A与B的关键因素」「识别影响X的Y」这种长句，
        #   整句塞进问句会变成"关于影响大学生恋爱动机与消费决策的关，你…"（实测）。
        s = re.split(r"[与和及、，,；;]|的关键|的影响|的因素|相关|之间的关系", s)[0].strip()
        s = s.rstrip("，。、；：: )）")
        return s[:14]

    if info.get("purpose"):
        t = _clean_topic(info["purpose"])
        if len(t) >= 4:
            return t
    for rq in (info.get("rqs") or []):
        # `动机：大学生谈恋爱的动机有哪些` → 取冒号后那段
        t = _clean_topic(str(rq).split("：")[-1] if "：" in str(rq) else rq)
        if len(t) >= 4:
            return t
    return ""


def _ask_opener(rq, topic=""):
    """把研究问题变成**能对受访者念出口**的问句。

    ⚠ 踩过：原来直接把 RQ 原文套壳 ——
      `「关于免费充足度：非付费用户中，有多大比例…你最先想到的是什么？」`（83 字）
      某大学那份 103 字，连「（答完标准：…）」都一起念给受访者听。
      RQ 是**写给研究员看的**（带抽样限定、带研究口径），受访者听不懂也不该听懂。
    """
    s = re.sub(r"[（(][^）)]*[）)]", "", str(rq or "")).strip()
    # 去掉「XX：」这种话题前缀（研究员自己的标记）
    if "：" in s:
        s = s.split("：", 1)[1].strip()
    # 去掉研究口径的尾巴和 RQ 腔（"有哪些""是怎么决定的""有几类"）
    s = re.sub(r"(有多大比例|比例如何|是否显著|相关性如何).*$", "", s).strip()
    s = re.sub(r"(有哪些|有哪几[种类个]|是怎么决定的|是怎样的|如何|怎么理解|是怎么理解).*?$", "", s).strip()
    # ⚠ 开头的人称代词要去掉：`他们怎么理解一段关系里的责任` → 去掉"怎么理解"之后
    #   会剩 `他们怎么理解一段关系里的责任`→`他们` 这种怪问句（实测出现过"关于他们，你…"）。
    s = re.sub(r"^(他们|她们|我们|大家|受访者|用户|学生)[的是]?", "", s).strip()
    s = s.rstrip("？?。；;，,、 ")
    # 仍然太长（念不顺）→ **优先用话题短语**（它是从「研究目的」里提出来的整块短语），
    # 只有话题短语也没有/太短时才截断 RQ。
    # ⚠ 别在这两个里"取更短的"：RQ 截断常常切掉名词，变成"关于影响…的关"这种半截话。
    if len(s) > 18:
        if topic and 4 <= len(topic) <= 22:
            s = topic
        else:
            s = s[:16].rstrip("，,、 的地得")
    if not s or len(s) < 2:
        s = (topic or "这件事")[:16]
    return "关于%s，你最先想到的是什么？" % s


def _consent_lines(info, raw_brief=""):
    """契约 §9（研究伦理）里写了什么，就在知情同意里逐条展开。

    ⚠ 踩过：契约里明明写着「纸质签字」「化名」「敏感话题风险」，而提纲的知情同意只有固定一行。
    ⚠ 而且**必须看契约原文**，不能只看 `parse_brief` 的结果：解析器只收
      背景/目的/RQ/假设/变量/对象这六节，**§9 整节不在里面** ——
      实测那条「招募偏差：不用滚雪球」就在 §9，靠解析结果永远搜不到。
      而提纲的知情同意只有固定一行 —— 该说的话一句没说。
    """
    txt = info.get("background", "") or ""
    pop = info.get("population", "") or ""
    whole = txt + "\n" + pop + "\n" + (raw_brief or "")
    out = []
    for kw, line in (
        ("纸质", "需要**纸质签字**的，提前把知情同意书打印好，现场签完再开始。"),
        ("签字", "知情同意要**签字**确认（不是口头说说）。"),
        ("化名", "材料里一律用**化名**，别写真实姓名。"),
        ("匿名", "结果**匿名**呈现，引用时用「受访者 N」。"),
        ("敏感", "涉及敏感话题：先声明「可以跳过任何问题」，并准备中止访谈的信号。"),
        ("录音", "录音要单独征得同意，并说明录音只用于转写、转写完如何处理。"),
        ("未成年人", "有未成年受访者时，需要**监护人同意**。"),
    ):
        if kw in whole:
            out.append(line)
    return out


def _probe_for(v):
    """一条变量的「可以这样问」—— **提纲正文和结果页表格共用这一个函数**。

    ⚠ 必须共用：这两处原来是两份各写各的逻辑，于是同一次跑出来的提纲和结果页
      给的追问句**不一样**。研究员对不上就会开始不信任产物。
    """
    name, _role, measure, how = (list(v) + ["", "", "", ""])[:4]
    if str(how or "").strip():
        return "按契约里的测法问：**%s**" % str(how).strip()
    key = _measure_key(measure)
    return PROBE_BY_MEASURE[key].replace("{name}", name)


_FALLBACK_TIPS = {
    "probe_dig": {
        "script": "能说一次你具体这么做的时候吗？带我走一遍当时发生了什么。",
        "advice": "听到「一般/通常/平时」就往回推一次：要一次具体经历，不要概括。",
    },
    "probe_resp": {
        "advice": "提问是换方向的信号；他还没说完时，用语气接（「嗯」「我懂」「然后呢」），别急着问下一个。",
        "signals": ["（停顿）", "（笑）", "（叹气）"],
    },
    "probe_con": {
        "script": "「具体是指什么？」「能举个例子吗？」「那之后呢？」",
        "advice": "含糊的词别放过——他说的「压力」和你想的「压力」常常不是一件事。",
    },
    "probe_arc": {
        "opening_rule": "开场先聊具体经历，别一上来就问观点——观点是后面才敢说的。",
        "steps": ["一般（暖场 + 体验近端的开放问题）", "具体（一次经历的完整经过）",
                  "一般（回看：对你意味着什么）"],
    },
}


def run(ctx):
    brief_rel = (ctx.get("brief") or "").strip() or "contracts/research_brief.md"
    brief = ""
    try:
        brief = ctx.read_text(brief_rel) if hasattr(ctx, "read_text") else ""
    except Exception:
        brief = ""
    if not brief:
        p = ctx.path(brief_rel)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                brief = f.read()
    info = _parse_brief(brief)
    if brief:
        ctx.log("读研究简报：%d 个 RQ，%d 条假设，%d 个变量" % (
            len(info["rqs"]), len(info["hyps"]), len(info["variables"])))
    else:
        ctx.log("没读到研究简报（%s），提纲只会有通用骨架" % brief_rel, "warn")

    # ⚠ 契约读不到 / 解析不出东西时**必须出声**。这一段是踩出来的：
    #   原来契约文件根本不存在时，程序照样写出 1600 多字的提纲、头部还写着
    #   「> 依据：contracts/research_brief.md」—— 一份看着很正规、实际上
    #   和研究毫无关系的提纲。而 `ctx.alert` 在 ① 里一次都没被调用过（隔壁 ③ 有）。
    #   规矩：**解析不出来但看起来成功**，是最危险的一类失败，必须摆到人会看到的地方。
    if not brief.strip():
        ctx.alert("没读到研究简报（`%s`）——**这份提纲只有通用骨架，和你的研究没关系**。"
                  % brief_rel,
                  level="error", kind="internal",
                  fix="先去 ⓪ 把研究设计跑出来（产出 contracts/research_brief.md），"
                      "再回来跑这一步。")
    elif not info["rqs"] and not info["variables"]:
        ctx.alert("研究简报读到了，但**一个研究问题、一个变量都没解析出来**——"
                  "这份提纲只有通用骨架。",
                  level="error", kind="internal",
                  rel="contracts/research_brief.md",
                  fix="打开简报看一眼：研究问题要写成 `- RQ1：…`（放在「研究问题」那一节），"
                      "变量要写成带表头的表格（变量名 / 角色 / 测量层次 / 怎么测）。")
    else:
        if not info["rqs"]:
            ctx.alert("研究简报里**没解析到研究问题**（RQ）——提纲的骨架会缺一块。",
                      level="warn", kind="internal", rel="contracts/research_brief.md",
                      fix="把研究问题写成 `- RQ1：…` 这种一行一条的形式。")
        if not info["variables"]:
            ctx.alert("研究简报里**没解析到变量表**——提纲里不会有「变量探测」那一节，"
                      "后面的问卷和统计也就继承不到东西。",
                      level="warn", kind="internal", rel="contracts/research_brief.md",
                      fix="变量要写成带表头的表格：`| 变量名 | 角色 | 测量层次 | 怎么测 |`。")

    audience = (ctx.get("audience") or "").strip()
    if not audience:
        raise ValueError("请填「受访者是谁」——提纲是写给特定人群的")
    # ⚠ style 必须在时长之前定：焦点小组的默认时长和一对一不一样
    style = ctx.get("style") or "semi"
    # ⚠ 焦点小组默认时长不一样：6~8 个人轮流说，45 分钟连一圈都走不完。
    #   而「没填」和"填了 45 但想跑小组"是两回事，要分开处理。
    _dur_raw = ctx.get("duration")
    _dur_given = _dur_raw is not None and str(_dur_raw).strip() != ""
    try:
        duration = int(float(_dur_raw or 45))
    except Exception:
        duration = 45
        ctx.log("「预计时长」填的不是数字（%r），按 45 分钟算" % _dur_raw, "warn")
    if style == "focus" and not _dur_given:
        duration = 90
        ctx.log("焦点小组没填时长，按 **90 分钟** 起算（6~8 个人轮流说，短了走不完一圈）")
    focus = [x.strip() for x in (ctx.get("focus") or "").splitlines() if x.strip()]
    channels = (ctx.get("channels") or "").strip()

    style_cn = {"semi": "半结构式访谈", "deep": "深度访谈", "focus": "焦点小组"}.get(style, "半结构式访谈")
    warm = max(3, round(duration * 0.1))
    close = max(3, round(duration * 0.1))
    body = max(10, duration - warm - close)

    # ⚠ 时间表要**自己加得起来**。原来只扣了一次 warm，但开场和暖场两节都用它，
    #   于是 45 分钟那张表相加 = 49、5 分钟那张相加 = 19 而合计写着 5 —— 一眼假。
    #   现在按实际环节扣，并且**合计就用实际相加的值**（不写名义时长，免得自相矛盾）。
    opening = max(2, round(duration * 0.05))
    body = max(8, duration - opening - warm - close)
    total_shown = opening + warm + body + close
    if total_shown != duration:
        ctx.log("时间表按环节拆是 %d 分钟（你填的是 %d）—— 环节有下限，短访谈塞不下更多。"
                % (total_shown, duration), "warn")
    # 焦点小组：人一多，主问题就得少，时间是花在互相回应上的
    n_angles = len(ANGLE_TEMPLATES)
    if style == "focus":
        n_angles = max(2, len(ANGLE_TEMPLATES) - 2)
    elif style == "deep":
        n_angles = max(3, len(ANGLE_TEMPLATES) - 1)

    # 话题名：从研究目的里取一个短语，用来填开场白和暖场（别留「关于……的研究」这种省略号）
    topic = _topic_phrase(info)
    # 每个 RQ 有一段'时间预算'，据此算每个 RQ 该留几个追问角度
    n_rq = max(1, len(info["rqs"]))

    L = []
    L.append("# 访谈提纲 · %s\n" % audience)
    L.append("> 形式：**%s** · 预计 **%d 分钟**" % (style_cn, total_shown))
    if channels:
        L.append("> 招募渠道：%s" % channels)
    if brief_rel and info.get("rqs"):
        L.append("> 依据：`%s`" % brief_rel)
    else:
        L.append("> 依据：**没读到研究简报** —— 这份提纲只有通用骨架")
    L.append("> 生成时间：%s（用户研究工作台）\n" % time.strftime("%Y-%m-%d %H:%M"))

    if info["purpose"]:
        L.append("**研究目的**：%s\n" % info["purpose"])

    L.append("---\n")
    L.append("## 0. 开场（约 %d 分钟）\n" % opening)
    L.append("1. 自我介绍 + 说明来意：「我们在做一项关于**%s**的研究，想听听你的真实体验。」" % topic)
    # 契约 §9 里写了伦理要求就逐条展开，别只留一句固定话
    L.append("2. **知情同意**：说明会录音、结果匿名处理、随时可以退出或跳过任何问题。")
    for _c in _consent_lines(info, brief):
        L.append("   - %s" % _c)
    L.append("3. 定调：「没有标准答案，你的真实感受比正确答案更有用。」")
    L.append("4. 确认设备与舒适度（要不要喝水、需不需要休息）\n")

    L.append("## 1. 暖场（约 %d 分钟）\n" % warm)
    L.append("- 先聊聊你平时怎么安排一天？")
    if topic:
        L.append("- 说到**%s**，你最先想到的是什么？" % topic)
        L.append("- 这方面你印象最深的一次是什么时候？当时在做什么？\n")
    else:
        L.append("- 这方面你印象最深的一次是什么时候？当时在做什么？\n")

    L.append("## 2. 主问题（约 %d 分钟）\n" % body)
    if info["rqs"]:
        for i, rq in enumerate(info["rqs"], 1):
            L.append("### 2.%d ← RQ%d：%s\n" % (i, i, rq))
            L.append("**开场问法**（把话题引出来就好，别急着问细节）")
            # ⚠ 别把 RQ 原文当问题念给受访者。实测过的产物：
            #   「关于免费充足度：非付费用户中，有多大比例…你最先想到的是什么？」（83 字）
            #   某大学那份 103 字，连「（答完标准：…）」都一起念了。
            #   RQ 是给研究员看的，问句要短、要人话。
            L.append("> 「%s」\n" % _ask_opener(rq, topic))
            # 时间预算 → 每个 RQ 该挑几个角度（时间不够就先砍题，别硬塞）
            per_rq = body / n_rq
            take = 2 if per_rq < 6 else (3 if per_rq < 10 else n_angles)
            take = max(2, min(take, n_angles))
            L.append("**追问角度**（约 %.0f 分钟给这个 RQ，现场挑 %d 个就够，不要凑满）"
                     % (per_rq, take))
            for tag, tpl in ANGLE_TEMPLATES[:n_angles]:
                L.append("- 【%s】%s" % (tag, tpl))
            L.append("")
        if n_rq > 1 and body / n_rq < 8:
            L.append("> ⚠ **时间不够**：%d 个研究问题分 %d 分钟，平均每个只有 %.0f 分钟。"
                     "建议现场优先保证 2.1 和 2.2，后面几个问到什么算什么——"
                     "**宁可少问两个，也别把每个都匆匆带过**。\n" % (n_rq, body, body / n_rq))
    else:
        L.append("（研究简报里没有研究问题——建议先去 ⓪ 把 RQ 定下来，再回来生成提纲）\n")
        L.append("### 通用主问题骨架\n")
        for tag, tpl in ANGLE_TEMPLATES:
            L.append("- 【%s】%s" % (tag, tpl))
        L.append("")

    # ⚠ 小节编号要**按实际出现的顺序连号**。原来编号是写死的（0/1/2/3/4/5/6），
    #   但「特别想挖的点」「假设的证伪机会」是条件出现的 —— 于是产物里出现
    #   0,1,2,4,6 这种断号，读的人会以为漏了内容。
    _sec = [2]          # 已经用到 2（主问题）；下一个从 3 起

    def _next_sec():
        _sec[0] += 1
        return _sec[0]

    if focus:
        L.append("## %d. 特别想挖的点\n" % _next_sec())
        for f in focus:
            L.append("### %s\n" % f)
            L.append("- 切入：「能说说%s是怎么回事吗？」" % f)
            L.append("- 追问：具体例子 → 当时的感受 → 对你的影响 → 你后来怎么做的")
            L.append("")

    if info["variables"]:
        L.append("## %d. 变量探测（可以嵌在上面任何一处，别单独列成大题）\n" % _next_sec())
        L.append("| 变量 | 角色 | 测量层次 | 可以这样问 |")
        L.append("|---|---|---|---|")
        for v in info["variables"]:
            L.append("| %s | %s | %s | %s |" % ((list(v) + ["", "", "", ""])[0],
                                               (list(v) + ["", "", "", ""])[1],
                                               (list(v) + ["", "", "", ""])[2],
                                               _probe_for(v)))
        L.append("")

    if info["hyps"]:
        L.append("## %d. 假设的「证伪机会」（**别直接问假设**）\n" % _next_sec())
        L.append("访谈不能用来验证假设，但可以留意反例。下面这些假设，注意听有没有**对不上的说法**：\n")
        for i, h in enumerate(info["hyps"], 1):
            L.append("- H%d：%s → 留意：有没有受访者的说法和它相反？" % (i, h))
        L.append("")

    # ⚠ 焦点小组**不是"一对多的一对一"** —— 主持方式和一对一完全不同。
    #   原来选「焦点小组」只改了标题一行字（实测 `semi→focus` 的差异只有 1 行），
    #   拿到手的还是一对一的开场白和主问题结构。这一节补上小组该有的东西。
    if style == "focus":
        L.append("## %d. 焦点小组的主持要点（**和一对一完全不同，别照着问**）\n"
                 % _next_sec())
        L.append("**人数组场**：6~8 人最合适（少于 4 人退化成小组访谈、多于 10 人有人整场说不上话）。"
                 "人少了就在备注里写明你实际几个人。\n")
        L.append("**开场必须额外做两件事**：")
        L.append("- 立规矩：「今天想听**互相**聊，不同意别人的说法尽管说 —— 我要的是不同的看法，"
                 "不是一致的答案。」")
        L.append("- 提醒保密：「大家说的都会匿名，也请各位别把今天听到的带到外面去。」\n")
        L.append("**轮次怎么走**（别用「挨个回答」的方式，那是把小组当成一串一对一）：")
        L.append("- 先给每个人 30 秒**表态**（一圈），然后放开讨论 —— 一圈表态能保证内向的人也说上话")
        L.append("- 之后**只抛问题、不点名**，谁接都行；冷场超过 5 秒再点名")
        L.append("- 每换一个话题，重开一圈表态\n")
        L.append("**主持人的四个动作**：")
        L.append("- **拉回**：有人跑题 → 「这个我们待会儿说，先回到刚才那个」")
        L.append("- **邀请沉默者**：别问「你怎么看」（他会说「我同意」）→ 「你刚才点了个头，是想到了什么？」")
        L.append("- **压住话多的人**：别打断，用视线移开 + 转向别人：「我们先听听 XX 的」")
        L.append("- **抓住分歧**（这是小组最值钱的东西）：出现不同说法时**别急着调和** → "
                 "「你俩说的不太一样，能各自再讲讲为什么吗？」")
        L.append("")
        L.append("> ⚠ 你填的时长是 %d 分钟 —— 这是**一群人**的时长："
                 "每个话题至少留 %.0f 分钟，问题数量要比一对一**少一半**。\n"
                 % (total_shown, max(8.0, body / max(1, len(info["rqs"]) or 1))))

    L.append("## %d. 收尾（约 %d 分钟）\n" % (_next_sec(), close))
    L.append("- 「今天聊的这些，有没有什么我没问到、但你觉得重要的？」")
    L.append("- 「如果让你给**做这个研究的人**带一句话，会是什么？」")
    L.append("- 致谢 + 说明后续（结果怎么用、会不会反馈给他们）\n")

    L.append("---\n")
    L.append("## 附：访谈者备忘\n")

    # 技巧从知识库读（knowledge/访谈技巧.md）—— 研究员能看、能改、能追问出处。
    # 读不到就退回内置的那套，别因为知识库坏了就让提纲缺内容。
    from core import knowledge as kb
    _kr, _kerr = kb.load("访谈技巧.md", with_error=True)
    dig = kb._ns(_kr, "probe_dig") or dict(_FALLBACK_TIPS["probe_dig"])
    resp = kb._ns(_kr, "probe_resp") or dict(_FALLBACK_TIPS["probe_resp"])
    con = kb._ns(_kr, "probe_con") or dict(_FALLBACK_TIPS["probe_con"])
    arc = kb._ns(_kr, "probe_arc") or dict(_FALLBACK_TIPS["probe_arc"])
    if _kerr:
        # ⚠ 这句话原来在骗人：它说"下面用的是内置的简版"，但实际上根本没有简版 ——
        #   知识库读不到时，故事挖掘/语气回应/具体化追问/沙漏/收尾三件套**整节消失**
        #   （实测 2642 字 → 2041 字），只留一句 ⚠ 就完了。
        #   现在真的写了兜底（`_FALLBACK_TIPS`），所以这句话是实话了。
        L.append("> ⚠ 访谈技巧那份知识文件没读成（%s）。**下面是内置的简版**——"
                 "该说的都还在，但不如知识库那份细。修好 `workbench/knowledge/访谈技巧.md` "
                 "再跑一次就能拿回完整版。" % _kerr)
        L.append("")

    L.append("**会带偏答案的问法（别用）**")
    L.append("- ❌「你是不是因为XX才那样的？」→ ✅「当时发生了什么？」"
             "（把结论塞进问句 = 得到你想听的答案）")
    L.append("- ❌「你觉得这个好不好用？」→ ✅「你上次用它是什么时候？当时怎么样？」"
             "（要评价 = 逼他表态；要经历 = 拿到事实）")
    L.append("- ❌ 一次问两个问题（「你觉得怎么样，哪里不好？」）→ 分开问")
    L.append("")

    if dig.get("script"):
        L.append("**故事挖掘（今天最该记住的一条）**")
        L.append("- 他要是说「%s」这种概括，**别顺着问下去**，把他拉回某一次："
                 % "／".join((dig.get("generalize_signals") or ["一般", "通常"])[:3]))
        L.append("  > 「%s」" % dig["script"])
        if dig.get("advice"):
            L.append("- %s" % dig["advice"])
        L.append("- 判断拉到具体了没有：回答里有**时间、地点、先后顺序、原话**就算拉到了；"
                 "还是「一般」「通常」就再推一次。")
        L.append("")

    if resp.get("how"):
        L.append("**语气回应（不要用问题去接）**")
        L.append("- %s" % resp.get("advice", "提问是换方向的信号；他还没说完时，用语气接。"))
        for h in resp["how"]:
            L.append("  - %s" % h)
        L.append("")

    if con.get("script"):
        L.append("**具体化追问**")
        L.append("- %s" % con["script"])
        if con.get("advice"):
            L.append("- %s" % con["advice"])
        L.append("")

    arc = kb._ns(_kr, "probe_arc")
    if arc.get("shape"):
        L.append("**整场的形状：沙漏（一般 → 具体 → 一般）**")
        for x in arc["shape"]:
            L.append("  - %s" % x)
        if arc.get("opening_rule"):
            L.append("- 开场那条最要紧：%s" % arc["opening_rule"])
        L.append("")

    if arc.get("closing"):
        L.append("**收尾三件套（几乎每场都值得问）**")
        # ⚠ 收尾里有一条是「转介绍（你认识谁也有类似情况吗）」= 滚雪球的起点。
        #   而**抽样方式是你定的**：某份契约明写「招募偏差：不用滚雪球」，
        #   提纲却照样让你去问转介绍 —— 产物和自己的研究设计打架。
        #   契约里写了抽样偏好，就照它来。
        _no_snow = re.search(r"不用滚雪球|不滚雪球|不做滚雪球|避免滚雪球|不用转介绍|随机抽",
                             (info.get("population", "") or "") + (info.get("background", "") or "")
                             + "\n" + (brief or ""))
        for x in arc["closing"]:
            if _no_snow and ("转介绍" in str(x) or "认识谁" in str(x) or "滚雪球" in str(x)):
                L.append("  - ~~%s~~ → **你的抽样设计说了不用滚雪球**，这条跳过；"
                         "需要更多样本就按契约里写的方式找。" % x)
            else:
                L.append("  - %s" % x)
        if _no_snow:
            L.append("  > ⚠ 检测到契约里的抽样偏好是「不用滚雪球」，所以转介绍那条已按你的设计改掉。")
        L.append("")

    L.append("**记录要点**")
    L.append("- 原话比概括值钱：觉得关键就**逐字记**，标上时间码")
    L.append("- 记情绪：犹豫、笑、语气变化，这些是编码时的线索")
    L.append("- 访谈结束 30 分钟内写下**印象笔记**（印象会随时间快速衰减）\n")
    L.append("**伦理提醒**")
    L.append("- 录音前必须明确同意；转写稿进任何分析前，先过 🔒 去标识化")
    L.append("- 受访者提到的第三方（同事、朋友）也要匿名\n")

    md = "\n".join(L)
    ctx.save_text("contracts/interview_guide.md", md)
    ctx.log("提纲写入 contracts/interview_guide.md（%d 字）" % len(md))

    tables = []
    if info["rqs"]:
        tables.append({
            "name": "研究问题 → 提纲结构",
            "columns": ["#", "研究问题", "对应提纲小节", "给的提问角度"],
            "rows": [[i, rq, "2.%d" % i, "经历 / 原因 / 感受 / 对比 / 期望（挑 2~3）"]
                     for i, rq in enumerate(info["rqs"], 1)],
            "note": "提纲是骨架不是剧本：每个 RQ 下挑 2~3 个角度问就够了。",
        })
    if info["variables"]:
        def _probe_of(v):
            """结果页那张表里的「可以这样问」——和写进提纲的必须是**同一句**。

            ⚠ 踩过：这里原来是另一套逻辑（`next(k for k in PROBE_BY_MEASURE if k in measure)`），
              和正文那份不一致 —— 同一次跑，提纲里写 A、结果页显示 B。
              现在统一走 `_probe_for()`。
            """
            return _probe_for(v)

        tables.append({
            "name": "变量探测表",
            "columns": ["变量", "角色", "测量层次", "可以这样问"],
            "rows": [[(list(v) + ["", "", "", ""])[0], (list(v) + ["", "", "", ""])[1],
                      (list(v) + ["", "", "", ""])[2], _probe_of(v)]
                     for v in info["variables"]],
            "note": "把操作化定义翻译成受访者听得懂的话——这一步做不好，后面的量化就对不上。",
        })
    tables.append({
        "name": "时间分配",
        "columns": ["环节", "分钟"],
        "rows": [["开场与知情同意", warm], ["暖场", warm],
                 ["主问题", body], ["收尾", close], ["合计", duration]],
        "note": "实际访谈里主问题常常吃掉全部时间——准备 2 个「时间不够就砍」的备用问题。",
    })

    return {
        "summary": "提纲已写入 contracts/interview_guide.md（%d 个 RQ · %d 个变量 · 约 %d 分钟）"
                   % (len(info["rqs"]), len(info["variables"]), duration),
        "tables": tables,
        "figures": [],
        "markdown": [{"name": "interview_guide.md", "rel": "contracts/interview_guide.md",
                      "text": md}],
        "notes": "问题措辞留给你自己写——程序给的是结构和提醒，不是替你思考。",
    }
