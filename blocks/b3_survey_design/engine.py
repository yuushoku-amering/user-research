# -*- coding: utf-8 -*-
"""组块 ③ 问卷设计 · 引擎

把研究简报里的**变量表**落成可执行的题项：

    变量「满意度」（定距，态度类）  →  满意度_1 ~ 满意度_4，四道 5 点李克特

为什么这一步不能省：④ 问卷统计的变量名、⑤ 统计分析方法的选择，
全都建立在这里定下的**测量层次**和**变量命名**上。命名对不上，后面全白做。

**刻意不替研究员写题干**：给的是题型、量表、题量、句式骨架和使用提醒，
措辞的活儿留给研究员——那是问卷质量的关键，也是研究者的手艺。
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WB = os.path.dirname(os.path.dirname(_HERE))
if _WB not in sys.path:
    sys.path.insert(0, _WB)
from core import kit          # noqa: E402

# 题型 → (显示名, 默认锚点, 单题耗时秒)
KINDS = {
    "single": ("单选", "互斥选项 + 「其他（请注明）」", 8),
    "multi": ("多选", "互斥选项 + 「其他（请注明）」", 12),
    "likert5": ("李克特 5 点", "1=非常不同意 … 5=非常同意", 10),
    "likert7": ("李克特 7 点", "1=非常不同意 … 7=非常同意", 11),
    "freq5": ("频率 5 点", "1=从不 … 5=总是", 10),
    "nps": ("NPS 0-10", "0=完全不会推荐 … 10=一定会推荐", 12),
    "number": ("数字填空", "（给「大概」的余地，别逼精确）", 15),
    "open": ("开放题", "（限 1~2 题，多了没人填）", 45),
}


# 后台拿得到的行为数据——别问用户（问了也只是估计，不如直接取日志）
BEHAVIOR_HINTS = ("曝光", "停留", "点击", "日志", "埋点", "转化率")
# 操作化定义里出现这些词，说明数据来自系统而不是问用户
SYS_HINTS = ("日志", "埋点", "后台", "系统记录", "计数", "字段取值")
# 人口学变量：一律用区间/档位，不能用同意度量表
# ⚠ 「年级」原来漏了 —— 简报把「年级」标成**定序**，于是掉进下面的定序分支，
#   出了 2 道李克特：「我同意我的年级是…」。和当年「年龄」那个笑话是同一个病（踩过）。
DEMO_HINTS = ("年龄", "收入", "学历", "职业", "性别", "婚", "工龄", "年级", "生源", "专业")


def _split_opts(tail):
    """把一串疑似选项切干净；不像选项就返回 []。

    ⚠ 为什么不能"切一刀就返回"：这段文字来自研究员的**操作化定义**，不是结构化的选项列。
      真实简报里的写法很杂：
        「如陪伴、吸引、同伴压力、经济、家庭期待等」        → 选项，末尾多个「等」
        「按 0 次、1 次、2 次及以上分组」                  → **不是**选项（有指令词）
        「按 0–25%、25–50%、50–75%、75–100% 区间归组」     → 前四项是选项，最后一段是指令
      所以逐项体检：**从后往前**丢掉不像选项的零头（「等」「区间归组」），
      但中途一旦撞上指令词就整串不要 —— 免得把「按 0 次」这种碎片摆进问卷。
    """
    raw = [p.strip(" 　。；;，,、") for p in re.split(r"[/／|]", str(tail or ""))]
    # 「、」和「，」也当分隔符 —— 简报里两种写法都有：
    #   「如陪伴、吸引、同伴压力、经济、家庭期待等」   ← 顿号
    #   「按 0–25%，25–50%，50–75% 区间归组」          ← 中文逗号
    out_raw = []
    for seg in raw:
        for p in re.split(r"[、,，]", seg):
            p = p.strip(" 　。；;，,、")
            if not p:
                continue
            # 剥掉括注：「大二 / 大三（若有其他）」→「大三」
            p = re.sub(r"[（(][^（）()]*[）)]\s*$", "", p).strip()
            if p:
                out_raw.append(p)
    raw = out_raw
    # 从后往前剥零头：「等」「等等」「区间归组」「分组」这种收尾说明
    while raw and (raw[-1] in ("等", "等等", "其他等") or len(raw[-1]) > 14):
        raw.pop()
    if not raw:
        return []
    out = []
    for i, p in enumerate(raw):
        if not p:
            continue
        # 太长 → 是句子不是选项
        if len(p) > 14:
            return []
        # 带指令性词语 → 是"怎么算/怎么归类"的说明，不是给受访者看的选项
        if any(k in p for k in ("按 ", "分组", "选择后", "归组", "计算", "得出", "注明",
                                "填写", "允许", "大概", "自报", "由前", "区间归")):
            if i == 0:
                return []          # 第一个就带指令词 → 整串根本不是选项列
            continue               # 只是尾部说明 → 前面那些照用
        # 选项不该带句读或括号
        if any(ch in p for ch in "，。；;（）()：:"):
            return []
        out.append(p)
    return out



def _opt_anchor(op):
    """从操作化定义里把**已经写好的选项**抠出来，直接当锚点用。

    研究员的简报里常常已经写了选项，写法还很不一样 —— 这几种都得认
    （全是真实简报里的原话）：

        「（知道/不知道/不确定）」                    ← 括号包着
        「单选：知道 / 不知道 / 不确定」               ← 「单选：」开头
        「多选：给自家孩子 / 送礼 / 与零食搭配」        ← 「多选：」开头
        「如陪伴、吸引、同伴压力、经济、家庭期待等」     ← 「如…等」清单（顿号分隔）
        「自报当前状态：从未恋爱 / 恋爱中 / 追求中 / 已分手」  ← 全角冒号后的清单
        「编码为 单方承担 / 轮流承担 / AA 均摊 / …」    ← 「编码为」后的清单
        「按 0 次、1 次、2 次及以上分组」               ← ✗ 这个**不是**选项（有指令词）

    ⚠ 踩过的坑：早版本只认前两种，于是恋爱研究那份简报里
      「自报当前状态：从未恋爱 / 恋爱中 / 追求中 / 已分手」被丢成
      「互斥选项 + 「其他（请注明）」」——**把研究员写好的选项白丢了**，
      而且表面看不出来（锚点看着"也挺合理"）。
    """
    o = str(op or "")
    cands = []
    # ① 括号包着的
    m = re.search(r"[（(]([^（）()]{2,80})[）)]", o)
    if m:
        cands.append(m.group(1))
    # ② 「单选：」「多选：」「排序：」开头的
    m2 = re.search(r"(?:单选|多选|排序)[：:]\s*([^（(]+)", o)
    if m2:
        cands.append(m2.group(1))
    # ③ 「编码为 …」「归类为 …」后面的清单
    m3 = re.search(r"(?:编码为|归为|归入|分为|类别为|取值)\s*([^。；;]{2,80})", o)
    if m3:
        cands.append(m3.group(1))
    # ④ 「如 a、b、c 等」这种列举
    m4 = re.search(r"如\s*([^。；;]{2,80}?)\s*(?:等|等等)", o)
    if m4:
        cands.append(m4.group(1))
    # ⑤ 全角/半角冒号后面的清单（"自报当前状态：从未恋爱 / 恋爱中 / …"）
    #    ⚠ 只在**冒号后那截真的像清单**时才用：短、含分隔符、体检过关。
    #      不然「填数字（注明单位，允许估个大概）」这种说明也会被当成选项。
    for seg in re.findall(r"[：:]\s*([^（(。；;]{2,60})", o):
        if re.search(r"[/／|、]", seg):
            cands.append(seg)
    # ⑥ 「按 a、b、c 区间/分组/档位」——**没有冒号也没有括号**的那种
    #    真实原话：「受访者自报本人承担份额，按 0–25%、25–50%、… 区间归组」
    #              「自报累计恋爱段数，按 0 次、1 次、2 次及以上分组」
    #    ⚠ 这一条是补的：上面五条都要求冒号 / 括号 / 「如…等」，
    #      而这种"裸列举"一条都命不中 —— 结果是「花销分担比例」的档位白丢，
    #      被出成「我同意我的花销分担比例…1=非常不同意」（踩到才发现）。
    m5 = re.search(r"按\s*([^。；;]{2,80}?)\s*(?:区间|分组|档位|归组|分档)", o)
    if m5:
        cands.append(m5.group(1))

    for c in cands:
        parts = _split_opts(c)
        if 2 <= len(parts) <= 8:
            # 「如陪伴、吸引、…等」抽出来会带着「如」和「等」——那是行文语气，
            # 摆进问卷锚点里会变成「如陪伴 / 吸引 / … / 家庭期待等」，看着像没做完的句子
            if parts and parts[0].startswith("如"):
                parts[0] = parts[0][1:].strip()
            if parts and parts[-1].endswith("等"):
                parts[-1] = parts[-1][:-1].strip()
            parts = [p for p in parts if p]
            if len(parts) >= 2:
                return " / ".join(parts)
    return ""



def _suggest(name, role, measure, op=""):
    """按「变量名 + 角色 + 测量层次 + 操作化定义」推荐 (题型, 锚点, 题量, 为什么)；
    返回 None = 不该问用户。

    ⚠ 一个容易犯的错：把**定序**当成**定类**处理。定序变量（价格感知 1~5、满意度）
      用互斥单选就降级成无序分类了，后面只能算卡方，算不了均值——测量层次是会被问卷问丢的。

    ⚠ 另一个：**不看操作化定义就自作聪明**。简报里写着「开放式填写最高可接受价格（元）」，
      老版本却因为它挂着「因变量」就给了 3 道李克特——变成让人对着「1=非常不同意」填价格。
    """
    m, r, n, o = measure or "", role or "", name or "", op or ""

    # 0. **简报已经把"怎么测"写死了的，一律照它来 —— 排在"别问用户"前面。**
    #    ⚠ 这一条原来在后面，于是「恋爱经历次数」被"行为次数类建议走后台日志"那条规则
    #      **整个丢掉了**（一道题都不出）。可简报白纸黑字写着
    #      「自报累计恋爱段数，按 0 次、1 次、2 次及以上分组」——
    #      研究员明确要问、还给了档位，程序却自作主张不出题。
    #      规矩：**"别问用户"是默认建议，不能盖过研究员写明的问法。**
    bracket_early = ""
    if "定序" in m and any(k in n for k in ("频率", "频次", "次数", "段数")):
        bracket_early = _opt_anchor(o)
        if bracket_early or any(k in o for k in ("区间", "档位", "分档", "归组", "分组")):
            return "freq5", bracket_early or "1=从不 … 5=总是（档位要等距）", 1, \
                   "简报写明了按档位自报，照它出有序档位（频率量表，档位要等距）"

    # 0.5 行为次数 / 时长 / 曝光这类，用户记不准 → 建议走后台，不出题。
    # ⚠ 早版本只看**变量名**，于是「扫描量」这种名字里没提示、但简报写着「（日志）」的变量
    #   照样出成了让用户自己估的题 —— 简报明说了从系统取，程序却去问人（对照两个案例才发现）。
    #   所以名字和操作化定义**两边都要看**。
    if any(k in n for k in BEHAVIOR_HINTS) or any(k in o for k in SYS_HINTS):
        return None

    # 1 **操作化定义里已经把怎么测写清楚了 —— 那是最权威的，照它来**
    #     ⚠ 注意「自报」**不算**开放式：它只是「自我报告」。
    #       早版本把「自报」也归进来，于是「自报是否知道有付费版（知道/不知道/不确定）」
    #       被出成了「填数字」——对照两个案例才发现（踩过）。
    #     ⚠ 顺序要紧：「区间档位」要排在「金额」前面 ——
    #       简报写「自报每月可自由支配金额，按区间选择后归组」时，要出的是**档位单选**，
    #       不是让人填一个精确数字（他自己也说不准）。金额只是它的单位，不是测法。
    if any(k in o for k in ("开放式", "填空", "填写", "数字", "（元）", "(元)")):
        return "number", "填数字（注明单位，允许估个大概）", 1, "操作化定义里写的就是开放式填写，照它来"
    if any(k in o for k in ("区间", "档位", "分档", "归组")):
        bracket = _opt_anchor(o)
        if bracket:
            return "single", bracket, 1, "操作化定义里写的是**按区间分档**，照它出有序档位单选"
    if "金额" in o:
        return "number", "填数字（注明单位，允许估个大概）", 1, "操作化定义里写的是金额，照它来"
    if any(k in o for k in ("多选", "排序")):
        return "multi", _opt_anchor(o) or "互斥选项 + 「其他（请注明）」", 1, \
               "操作化定义里写的是多选/排序，照它来"
    if "NPS" in o.upper() or "0-10" in o or "0～10" in o:
        return "nps", "0=完全不会 … 10=一定会", 1, "操作化定义里写的是 0-10 量表，照它来"
    if any(k in o for k in ("7 级", "7点", "7 点")):
        return "likert7", "1=非常不同意 … 7=非常同意", 3, "操作化定义里写的是 7 点量表，照它来"
    if any(k in o for k in ("Likert", "likert", "李克特", "5 级", "5级", "5 点", "5点")):
        many = 3 if any(k in n for k in ("意愿", "满意", "态度", "感知", "价值", "体验",
                                         "信任", "认同", "顾虑")) else 1
        return "likert5", "1=非常不同意 … 5=非常同意", many, "操作化定义里写的是 5 点李克特，照它来"
    if "单选" in o:
        # ⚠ 「操作化里写了单选」不等于「就能用通用的互斥选项」：
        #   · 人口学变量要的是**区间/档位**，不是「其他（请注明）」
        #   · 定序变量的单选必须**有序**，否则降级成无序分类，后面只能算卡方、算不了均值
        #   · 操作化里往往已经把选项列出来了（「（知道/不知道/不确定）」）——直接搬过来
        #   （对照两个案例时发现的：年龄段、到店频次都被盖成了通用选项）
        opts = _opt_anchor(o)
        if any(k in n for k in DEMO_HINTS):
            return "single", opts or "区间 / 类别档位（互斥且完备）", 1, \
                   "操作化里写了单选；人口学变量用区间档位，别用同意度量表"
        if "定序" in m:
            return "single", opts or "有序档位（互斥且完备，档位要等距）", 1, \
                   "操作化里写了单选，但它是**定序**的——选项必须有序，别做成无序单选"
        binary = any(k in o for k in ("是 / 否", "是/否", "有 / 无", "有／无"))
        return "single", opts or ("是 / 否 /（不清楚）" if binary else "互斥选项 + 「其他（请注明）」"), 1, \
               "操作化定义里写的是单选，照它来"

    # 0.5 人口学变量：用区间单选。
    #     （踩过：简报把「年龄」标成定序，于是出了 2 道李克特——变成"我同意我的年龄是…"的笑话）
    if any(k in n for k in DEMO_HINTS):
        return "single", "区间 / 类别档位（互斥且完备）", 1, "人口学变量用区间单选，别用同意度量表"

    # 1. **连续量优先**：数量/时长/次数/金额这类，无论简报标的是「定比」还是「定比（或定序）」，
    #    都该是数字填空，不该被后面的定序分支抓去当量表
    if any(k in n for k in ("金额", "份数", "时长", "多少", "次数", "广度", "事件",
                            "扫描量", "使用量", "支出", "客单价")):
        return "number", "（给「大概」的余地；能从后台日志取就别问用户）", 1, "连续量：允许估个大概，别逼精确"
    if ("定比" in m or "定距" in m) and "定序" not in m \
            and any(k in n for k in ("价格", "花费", "预算", "费用")):
        # ⚠ 必须排除「定序」：简报里常写「定序（合成后可视为定距，待确认）」，
        #   早版本只看「含不含定距」，把写着「4 题量表」的价格敏感度抢成了数字填空（踩过）
        return "number", "填数字（注明单位）", 1, "定比的价格类变量用数字填空——用同意度量表问价格是错的"

    # 2. 定序 → 有序量表（不是单选！）
    if "定序" in m:
        # （次数/段数那类已经在开头处理掉了：简报给了档位就照它的档位出题）
        bracket = _opt_anchor(o)
        if bracket:
            return "single", bracket, 1, \
                   "简报里已经写好了有序档位 —— 直接照它出单选，别拿同意度量表替换掉（量表的均值没法解释）"
        if any(k in n for k in ("价格", "定价", "划算", "贵")):
            return "likert5", "1=非常不划算 … 5=非常划算", 2, "价格感知是有序态度，别做成无序单选"
        if any(k in n for k in ("意愿", "推荐", "倾向", "可能")):
            return "nps", "0=完全不会 … 10=一定会", 1, "意愿类用 0-10，分辨率比 5 点高，也便于和行业对标"
        if any(k in n for k in ("满意", "态度", "感知", "价值", "体验", "信任", "认同", "重要")):
            return "likert5", "1=非常不同意 … 5=非常同意", 4, "态度类构念**必须多题项**（3~5 题）——单题测不准，也没法算信度"
        return "likert5", "1=非常不同意 … 5=非常同意", 2, "定序变量默认用有序量表"

    # 3. 定类 → 单选 / 多选
    if "定类" in m:
        opts = _opt_anchor(o)          # 简报里写好的选项，直接搬过来
        if any(k in n for k in ("是否", "有无", "有没有")):
            return "single", opts or "是 / 否 /（不清楚）", 1, "二分类——务必给「不清楚」，否则受访者会被迫瞎选"
        if any(k in n for k in ("原因", "理由", "动机")):
            return "multi", opts or "互斥选项 + 「其他（请注明）」", 1, "原因通常不止一个，用多选"
        return "single", opts or "互斥选项 + 「其他（请注明）」", 1, "分类变量：选项要互斥且完备"

    # 4. 剩下的定距 / 定比，按构念类型分
    if any(k in n for k in ("意愿", "推荐")):
        return "nps", "0=完全不会 … 10=一定会", 1, "意愿类可用 NPS，便于和行业数据对标"
    if any(k in n for k in ("满意", "态度", "感知", "价值", "体验", "信任", "认同")):
        return "likert5", "1=非常不同意 … 5=非常同意", 4, "态度类构念**必须多题项**（3~5 题）"
    if r and "因变量" in r:
        return "likert5", "1=非常不同意 … 5=非常同意", 3, "作为因变量，多题项合成的均值比单题稳得多"
    return "likert5", "1=非常不同意 … 5=非常同意", 1, "默认按 5 点量表；连续量可改成数字填空"


CHECKLIST = [
    ("双筒题", "一题问了两件事",
     "如「功能好不好用、价格合不合理」→ 必须拆成两题，否则答不出到底是什么在影响结论"),
    ("引导性措辞", "措辞暗示了「应该怎么答」",
     "如「你是否也认为定价偏高」→ 改成「你觉得当前定价怎么样」"),
    ("选项不完备", "漏了「其他」「不清楚」「不方便说」",
     "被迫二选一的数据是假数据；宁可多一个「其他」"),
    ("默认选项", "某一行被预选了",
     "会让赶时间的人直接跳过，等于凭空造了一批假答案"),
    ("量表方向", "同一份问卷里混了「1=同意」和「1=不同意」",
     "会让信度计算全错。反向题**必须在变量名或备注里标出来**"),
    ("问卷长度", "超过 10 分钟",
     "完成率断崖式下滑。题多的时候**砍题，不要砍选项**"),
    ("敏感题位置", "收入 / 联系方式放在开头",
     "应放最后，并说明用途；能不问就不问"),
    ("社会赞许性", "直接问「你会不会做违规的事」",
     "敏感行为要中性化措辞 + 强调匿名，否则人人都是道德模范"),
]


def run(ctx):
    brief_rel = (ctx.get("brief") or "").strip() or "contracts/research_brief.md"
    brief = ctx.read_text(brief_rel) if hasattr(ctx, "read_text") else ""
    if not brief:
        p = ctx.path(brief_rel)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                brief = f.read()
    info = kit.parse_brief(brief)
    variables = info.get("variables") or []
    # 界面上那张「这次要出题的变量表」如果研究员动过/补过行，就以它为准
    override = ctx.var_rows("variables", None)
    if override:
        variables = override
        ctx.log("用界面上那张变量表（%d 行）——它优先于简报里的表" % len(variables))

    # 契约体检：简报里「有内容却没读出来」的小节，必须出声。
    # 实测过：简报的第 6 节被写成手写文字时，这里会拿 0 个变量往下跑，
    # 给出「0 个变量 → 0 道题」的摘要并且照样落盘，界面上还看着像成功了。
    diag = kit.brief_section_report(ctx.path(brief_rel)) if brief else {"failed": [], "sections": []}
    if brief and diag.get("failed"):
        names = "、".join(s["label"] for s in diag["failed"])
        ctx.alert("研究简报里有 %d 节我没读出来：%s —— 它们写的是文字，不是程序认得的形式，"
                  "所以这一步是拿着空的往下跑的。" % (len(diag["failed"]), names),
                  level="error", rel=brief_rel,
                  fix="打开简报，把那几节改成 Markdown 表格（变量表四列：变量 | 角色 | 测量层次 | 操作化）")
    if brief and not variables:
        ctx.alert("研究简报里一个变量都没读到 —— 这次出的问卷是空壳（0 道题）。",
                  level="error", rel=brief_rel,
                  fix="回 ⓪ 把「关键变量与操作化定义」补成表格，再跑这一步")

    if brief:
        ctx.log("读研究简报：%d 个变量、%d 个 RQ、%d 条假设"
                % (len(variables), len(info["rqs"]), len(info["hyps"])))
    else:
        ctx.log("没读到研究简报（%s）——没有变量表就只能出个问卷空壳" % brief_rel, "warn")

    audience = (ctx.get("audience") or "").strip()
    if not audience:
        raise ValueError("请填「调研对象」——问卷开头要用来写筛选题")
    mode = ctx.get("mode") or "online"
    mode_cn = {"online": "线上自填（App 内）", "link": "线上自填（外部链接）",
               "paper": "线下纸笔", "phone": "电话 / 访问员代填"}.get(mode, mode)
    try:
        minutes = float(ctx.get("minutes") or 8)
    except Exception:
        minutes = 8.0
    parts = ctx.get("parts") or []
    if isinstance(parts, str):
        parts = [parts]
    focus = [x.strip() for x in (ctx.get("focus") or "").splitlines() if x.strip()]

    # ---------- 步骤：变量表体检 ----------
    ctx.step("vars", "读研究简报的变量表",
             "解析出 %d 个变量（这是出题项的依据）" % len(variables),
             rows=[[v[0], v[1], v[2]] for v in variables],
             columns=["变量", "角色", "测量层次"]) if variables else None

    # ---------- 1. 每个变量 → 题项 ----------
    items = []
    skipped = []
    qno = 0
    for v in variables:
        name = v[0]
        role = v[1] if len(v) > 1 else ""
        measure = v[2] if len(v) > 2 else ""
        op = v[3] if len(v) > 3 else ""
        sug = _suggest(name, role, measure, op)
        if sug is None:
            skipped.append([name, role, measure,
                            "行为次数 / 时长 / 曝光——用户记不准，建议直接从后台日志取，别占问卷篇幅"])
            continue
        kind, anchors, k, why = sug
        for i in range(k):
            qno += 1
            varname = ("%s_%d" % (name, i + 1)) if k > 1 else name
            items.append({
                "no": "Q%d" % qno, "var": varname, "kind": kind,
                "kinds_cn": KINDS[kind][0], "anchors": anchors,
                "measure": measure, "role": role, "why": why,
                "group": name if k > 1 else "",
            })

    if not items:
        ctx.log("变量表是空的，只能给出问卷结构框架", "warn")

    # ---------- 2. 时长估算 ----------
    sec = sum(KINDS[i["kind"]][2] for i in items)
    if "screen" in parts:
        sec += 20
    if "background" in parts:
        sec += 6 * 12
    if "open" in parts:
        sec += 45
    if "attention" in parts:
        sec += 10
    est_min = round(sec / 60.0, 1)
    over = est_min > minutes * 1.15

    # ---------- 3. 题项表 ----------
    rows = []
    for i in items:
        rows.append([i["no"], i["var"], i["kinds_cn"], "", i["anchors"], i["measure"], i["why"]])
    cols = ["题号", "变量名", "题型", "题干（待你定稿）", "选项 / 量表锚点", "测量层次", "为什么这样设计"]
    if rows:
        ctx.save_table("问卷_题项表.csv", rows, cols)
        ctx.log("题项表 → output/问卷_题项表.csv（%d 题；题干留空等你填）" % len(rows))

    # ---------- 4. 设计说明书 ----------
    L = []
    L.append("# 问卷设计 · %s\n" % audience)
    L.append("> 投放方式：**%s** · 预计填答 **%s 分钟**（按题量估算）" % (mode_cn, est_min))
    L.append("> 依据：`%s`（%d 个变量）" % (brief_rel, len(variables)))
    L.append("> 题项表：`output/问卷_题项表.csv`（题干那列留空，等你定稿）\n")
    if info.get("purpose"):
        L.append("**研究目的**：%s\n" % info["purpose"])

    L.append("---\n")
    L.append("## 一、问卷结构\n")
    seg = []
    if "screen" in parts:
        seg.append(("筛选题", "2~3 题", "确认对方属于「%s」；不符合的礼貌结束" % audience))
    seg.append(("主体", "%d 题" % len(items), "测研究简报里的各个变量——问卷的核心，占 70% 篇幅"))
    if "background" in parts:
        seg.append(("背景信息", "5~6 题", "年龄段、使用时长、使用频率等；放最后，题量要克制"))
    if "open" in parts:
        seg.append(("开放题", "1~2 题", "无提示的开放题能捞出你没想到的原因，别超过 2 题"))
    if "attention" in parts:
        seg.append(("注意力检验", "1 题", "如「本题请选第二个选项」；线上样本必配"))
    L.append("| 部分 | 题量 | 作用 |")
    L.append("|---|---|---|")
    for a, b, c in seg:
        L.append("| %s | %s | %s |" % (a, b, c))
    L.append("")

    if focus:
        L.append("## 二、特别想测的点\n")
        for f in focus:
            L.append("- **%s** —— 建议用 1 道单选 + 1 道开放题配合：先让 TA 选，再让 TA 说为什么" % f)
        L.append("")

    L.append("## 三、题项清单（题干留给你定稿）\n")
    if items:
        L.append("| 题号 | 变量名 | 题型 | 量表 / 选项目径 | 为什么这么设计 |")
        L.append("|---|---|---|---|---|")
        for i in items:
            L.append("| %s | `%s` | %s | %s | %s |" % (
                i["no"], i["var"], i["kinds_cn"], i["anchors"], i["why"]))
        L.append("")
        groups = {}
        for i in items:
            if i["group"]:
                groups.setdefault(i["group"], []).append(i["var"])
        if groups:
            L.append("**多题项构念**（这些变量用了几道题，统计时会合成为均值）：\n")
            for g, vs in groups.items():
                L.append("- **%s**：%s —— 信度（Cronbach α）会在 ⑤ 预处理那一步算" % (g, "、".join("`%s`" % v for v in vs)))
            L.append("")
        L.append("> ⚠ **变量名别改**：④ 问卷统计就是靠这些名字认变量的。"
                 "数据导出后列名要和这里对得上（或者用 ④ 的「从项目里挑」功能确认一遍）。\n")
    else:
        L.append("（变量表是空的——先去 ⓪ 把「关键变量与操作化定义」补上，再回来）\n")

    if skipped:
        L.append("## 三之二、**不建议**问用户的变量\n")
        L.append("下面这些别放进问卷——用户记不准自己的行为次数和时长，问出来全是估计值：\n")
        L.append("| 变量 | 角色 | 测量层次 | 建议 |")
        L.append("|---|---|---|---|")
        for s in skipped:
            L.append("| %s | %s | %s | %s |" % tuple(s))
        L.append("")
        L.append("> 从后台日志取这些数据，比问用户准得多，还不占问卷篇幅。"
                 "问卷该问的是**日志拿不到的**东西：态度、动机、感知。\n")

    L.append("## 四、设计检查清单\n")
    L.append("问卷设计的坑基本就这几类，逐条对一遍：\n")
    L.append("| 坑 | 什么表现 | 怎么处理 |")
    L.append("|---|---|---|")
    for a, b, c in CHECKLIST:
        L.append("| **%s** | %s | %s |" % (a, b, c))
    L.append("")

    L.append("## 五、长度与投放\n")
    L.append("- 按题量估算填答时长：**约 %s 分钟**（目标 %s 分钟）" % (est_min, minutes))
    if over:
        L.append("- ⚠ **超了**。要么砍题（优先砍背景信息里的非必需项），"
                 "要么把多选题改成单选。**别靠压缩选项来省时间**——那会把数据搞脏")
    else:
        L.append("- 长度在目标范围内 ✓")
    L.append("- 线上投放务必加**注意力检验题**；样本量目标按「要分析的组数 × 每组 30+」倒推")
    L.append("- 开放题放在靠后但不最后（最后一道通常是「还有什么想说的」）\n")

    L.append("## 六、下一步\n")
    L.append("1. 在 `output/问卷_题项表.csv` 里把**题干**补上（这是你的活）")
    L.append("2. 拿给 3~5 个人**试填**，掐表看实际耗时，听他们念题目时哪里卡壳")
    L.append("3. 定稿后投放；回收的数据丢进 **④ 问卷数据统计**——变量名对得上就能直接跑\n")

    md = "\n".join(L)
    ctx.save_text("contracts/survey_design.md", md)
    ctx.log("设计说明书 → contracts/survey_design.md")

    # ---------- 5. 结果 ----------
    # 知识库判定（`knowledge/研究问题与样本量.md`）：筛选题这块。
    # 勾了「筛选题」却一道都没生成时，这里必须说出来 —— 否则问卷看着完整，门口却是空的。
    # ⚠ 但要把它**认得的"门口题"一起传进去**：前辈实测报到一次误报 ——
    #   题里明明有「恋爱状态（从未恋爱/恋爱中/追求中/已分手）」这种按**纳入标准**设的题，
    #   功能上就是门口的关卡，只是名字里没有「筛」字。老判据只认名字，于是报了
    #   「一道都没生成」——**门口明明有把门的**。
    from core import knowledge as kb
    ctx.alerts_from(kb.check_screener(items, parts=parts,
                                      brief_pop=(info.get("population") or "")))

    tables = []
    if items:
        tables.append({
            "name": "题项清单（%d 题，题干留空等你填）" % len(items),
            "columns": ["题号", "变量名", "题型", "量表 / 锚点", "测量层次", "为什么这么设计"],
            "rows": [[i["no"], i["var"], i["kinds_cn"], i["anchors"], i["measure"], i["why"]]
                     for i in items],
            "note": "变量名是给 ④ 问卷统计用的，别改。题干请自己在 CSV 里补。",
        })
    tables.append({
        "name": "问卷结构",
        "columns": ["部分", "题量", "作用"],
        "rows": seg,
        "note": "主体应占七成篇幅；背景信息越短越好。",
    })
    tables.append({
        "name": "长度估算",
        "columns": ["项目", "值"],
        "rows": [["按题量估算", "%.1f 分钟" % est_min], ["目标", "%s 分钟" % minutes],
                 ["判断", "超了，建议砍题" if over else "在范围内"]],
        "note": "估算是按题型平均耗时算的（单选 8s / 量表 10s / 开放题 45s）。",
    })

    return {
        "summary": "问卷骨架：%d 个变量 → %d 道题，预计 %.1f 分钟%s；题项表已落盘"
                   % (len(variables), len(items), est_min, "（⚠ 超时了）" if over else ""),
        "tables": tables,
        "figures": [],
        "markdown": [{"name": "survey_design.md", "rel": "contracts/survey_design.md", "text": md}],
        "notes": "题出到「题型 + 量表 + 为什么」这一层；**题干措辞留给你**——那是问卷质量的关键。",
    }
