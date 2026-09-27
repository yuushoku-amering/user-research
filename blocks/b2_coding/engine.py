# -*- coding: utf-8 -*-
"""组块 ② 访谈记录编码整理 · 引擎

把转写稿拆成「发言单元」，产出两样东西：

    编码工作表.csv   —— 开放编码 / 范畴 / 主题 三列**留白等你填**
    访谈_初步分析.md —— 关键词、候选主题线索、引语候选

**刻意不做自动编码。** 编码是研究者对材料的理解，让机器代劳就失去了意义。
程序只干三件体力活：把材料切整齐、把高频线索指出来、把适合当引语的好句子挑出来。
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

# 转写稿头部的元信息行，不算发言
META_KEYS = {"访谈对象", "访谈时间", "访谈方式", "访谈者", "采访者", "记者", "记录", "记录人",
             "地点", "访谈地点", "时间", "日期", "时长", "备注", "受访者", "被访者", "受访对象",
             "主持人", "方式", "录音", "整理", "转写", "样本", "编号", "出席", "参与人"}

# 元信息行的识别不能只靠"整行等于某个词" —— 实测踩过：
#   稿子开头是 `访谈时间：… / 访谈地点：线上语音 / 采访者：李明 / 受访者：周然，男，21岁…`，
#   而 `META_KEYS` 里没有「访谈地点」「采访者」→ 它把「访谈地点」**当成了说话人**，
#   于是"认定访谈者：访谈地点"，后面的发言人判定整条都歪了。
#
# ⚠ 但**子串匹配不能太宽**，这是第二个坑（更严重，会静默丢数据）：
#   「受访」这个词加进去之后，说话人写成 `[受访者1]` 的稿子**整段被当成元信息丢掉**
#   —— 实测：全用 `[受访者N]` 的稿子切出 0 段；混用的稿子只剩访谈者的提问，
#   受访者一句不剩，**而且不报错**。
#   而 🔒 去标识化的自定义编号刚好允许把前缀设成「受访者」，所以这不是假想。
# ⇒ 规矩：**只对"像元信息标签"的词做子串匹配**（访谈/采访/时间/地点…），
#   「受访者」「被访者」「主持人」这种**本身就是说话人角色**的词，
#   只在**精确等于**时才算元信息。
_META_HINT = ("访谈", "采访", "地点", "日期", "时长", "方式", "录音", "转写", "整理",
              "记录", "备注", "编号", "样本", "参与", "出席", "对象", "会议", "记者")

# 这些词本身是**说话人角色**，可能被用作说话人标签（尤其去标识化之后）。
# 只有整行精确等于它们（`受访者：`）才算元信息；`[受访者1]：…` 是真人在说话。
_SPEAKER_ROLE_WORDS = {"受访者", "被访者", "受访对象", "主持人", "访谈者", "采访者", "记者"}


# 内容本身就长得像元信息的（时长/日期这类）—— 配合"标签是去标识化占位名"用。
# 现场：`[姓名3]：38 分钟` —— 头部那行「记录：某人」被 🔒 换成了 `[姓名3]`，
#      标签不再是「记录」这种能认出来的词，整行就伪装成了一个人说了"38 分钟"。
#      实测它会被切成一个发言单元（多一段，而且"38 分钟"成了受访者说的话）。
_META_CONTENT = re.compile(
    r"^\s*(\d{1,3}\s*(分钟|小时|min|mins?|hours?|h)\b|"
    r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?|"
    r"\d{1,2}\s*[:：]\s*\d{2}\s*[-~—至]?\s*(\d{1,2}\s*[:：]\s*\d{2})?)\s*$", re.I)


def _is_meta_line(label, line, body=""):
    """这行是转写稿的元信息（时间/地点/采访者…），不是某个人在说话。

    ⚠ 判据分三级，别一刀切（三个方向都踩过）：
      · 精确等于 `META_KEYS`（`受访者：周然，男…`）→ 元信息
      · 标签里含"访谈/地点/时间"这类**不可能是人名**的字样（`访谈地点`）→ 元信息
      · 标签是 `[受访者1]`『受访者A』这种**带编号的角色名** → **是说话人**，不能丢
        （丢了就是整段受访者的话凭空消失，而且不报错）
      · 内容本身长得像时长/日期（`[姓名3]：38 分钟`）→ 元信息
        （去标识化会把「记录：张三」换成 `[姓名3]`，标签就认不出来了，只能看内容）
    """
    lab = (label or "").strip().strip("[]()（）【】")
    if lab in META_KEYS:
        return True
    # 带编号/后缀的角色名（受访者1、受访者A、受访者_2）→ 说话人
    if any(lab.startswith(w) and lab != w for w in _SPEAKER_ROLE_WORDS):
        return False
    if any(w in lab for w in _META_HINT):
        return True
    if body and _META_CONTENT.match(str(body)):
        return True
    return False


# 纯附和，没有信息量
FILLER = {"嗯", "对", "是的", "是的。", "好", "好的", "哈哈", "哦", "喔", "哎",
          "对对", "对对对", "嗯嗯", "是", "没有", "还行", "可以", "差不多"}


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


# 说话人：允许带括号的占位名（🔒 去标识化之后会变成「[姓名1]」）
_SPEAKER_RE = re.compile(
    r"^([\[\(（【]?[\u4e00-\u9fa5A-Za-z0-9_\- ]{1,10}[\]\)）】]?)\s*[:：]\s*(.*)$")


def _is_sep(s):
    """场次分隔线（`---` / `===` / `***` 这类）。"""
    t = (s or "").strip()
    return bool(t) and len(t) >= 3 and set(t) <= set("-=*_")


def _strip_header(lines):
    """每一场开头的那一小块元信息（受访者 / 时间 / 地点…）不算发言。

    ⚠ 两个坑，都是实测踩出来的：

    1. **不能只在碰到 `---` 时才切头**。原来是这样：找不到分隔线就直接返回原样，
       于是有些没有 `---` 的稿子，头部元信息整块留在里面 ——
       而只要标签不在 `META_KEYS` 里（比如「访谈地点」），它就会被当成说话人。

    2. **多份访谈拼在一起时，每一场都要各自切头**。原来只切了**整份文件开头**那一段，
       第二场及以后的元信息就留在正文里。实测后果：
       第二场开头 `采访者：李明` 之后，那位受访者的第一句回答被并进上一场的最后一段，
       **整句归属错人**，而且不报警。
       （② 的表单只允许选一个文件，所以"用 --- 拼起来"是唯一的多访谈姿势。）

    判据：**在一场的最前面，连续若干行都长得像元信息**，直到出现一个真正的发言或空行分界。
    """
    out = list(lines)
    n = len(out)
    i = 0
    # 只看开头这一小段（元信息块不会很长）
    while i < n and i < 40:
        s = (out[i] or "").strip()
        if not s:
            # 空行：如果前面已经收过元信息，就在这里结束；否则跳过继续找
            if i > 0 and any(_is_sep(x) for x in []):
                break
            i += 1
            continue
        m = _SPEAKER_RE.match(s)
        if m and m.group(2) and _is_meta_line(m.group(1), s, m.group(2)):
            i += 1
            continue
        if _is_sep(s):
            i += 1
            continue
        break                      # 遇到真正的内容/发言 → 头部结束
    return out[i:]


def _split_sessions(text):
    """按场次分隔线把整份稿子切开（没有分隔线就是一场）。"""
    lines = (text or "").split("\n")
    sessions, cur = [], []
    for ln in lines:
        if _is_sep(ln):
            if cur:
                sessions.append(cur)
            cur = []
            continue
        cur.append(ln)
    if cur:
        sessions.append(cur)
    return [s for s in sessions if any((x or "").strip() for x in s)] or [lines]


def _split_by_speaker(text):
    units, cur = [], None
    # ⚠ 逐场处理：每一场各自切掉头部的元信息块（见 _strip_header 的说明）。
    #   场与场之间要把 `cur` 收掉 —— 不然上一场最后一个人说的会被并到下一场第一句上。
    for sess in _split_sessions(text):
        if cur:
            units.append(cur)
            cur = None
        for raw in _strip_header(sess):
            s = raw.strip()
            if not s or _is_sep(s):
                continue
            m = _SPEAKER_RE.match(s)
            if m and m.group(2):
                spk = m.group(1).strip()
                if _is_meta_line(spk, s, m.group(2)):   # 元信息行，跳过（但它可能终止当前单元）
                    if cur:
                        units.append(cur); cur = None
                    continue
                if cur:
                    units.append(cur)
                cur = {"speaker": spk, "text": m.group(2).strip()}
            else:
                if cur:
                    cur["text"] += " " + s
                else:
                    cur = {"speaker": "", "text": s}
    if cur:
        units.append(cur)
    return units


def _split_by_para(text):
    out = []
    for block in re.split(r"\n\s*\n", text):
        b = _clean(" ".join(x.strip() for x in block.split("\n") if x.strip()))
        if b:
            out.append({"speaker": "", "text": b})
    return out


def _split_by_sentence(text):
    out = []
    flat = _clean(text.replace("\n", " "))
    for part in re.split(r"(?<=[。！？!?；;])", flat):
        p = part.strip()
        if len(p) > 1:
            out.append({"speaker": "", "text": p})
    return out


# 引语里出现这些 = 说话人在**概括**而不是在讲事。概括句不如具体句好用。
_QUOTE_GENERIC = ("一般都是", "通常都", "大多数时候", "大家都", "我们都会", "平时就",
                  "差不多都", "反正是", "都一样")

# 这些"话语动作"说明这句有内容（在讲自己的经历/判断/态度），比空泛的句子更值得引
_QUOTE_SIGNAL = ("我觉得", "我当时", "后来", "因为", "所以", "但是", "其实", "我发现",
                 "我本来", "我不", "我会", "我想", "我得", "我总是", "有一次", "那次",
                 "才会", "才发现", "才知道", "结果")


def _looks_ident(text_, interviewers=()):
    """这一句里有没有直接标识符（手机/学号/邮箱/身份证…）。

    ⚠ 引语候选**绝不能**把带手机号的句子标成"报告里能直接引的句子"——
      那等于在工作台里亲手把标识符送进汇报稿。
    """
    v = str(text_ or "")
    if re.search(r"(?<!\d)1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)", v):
        return True
    if re.search(r"[\w.+-]+@[\w.-]+\.\w{2,}", v):
        return True
    if re.search(r"(?<!\d)\d{17}[\dXx](?!\d)", v):
        return True
    if re.search(r"(学号|工号|电话|手机|微信|QQ|联系)\s*[:：]?\s*[\dA-Za-z_]{5,}", v):
        return True
    return False


def _quote_score(u, kws, interviewers=()):
    """给一段发言打分，用来挑「报告里可以直接引的原话」。

    ⚠ 改过一版，两个错都很实在：

    1. **没看是谁说的** → 把访谈者的提问标成 ★。实测：
       `- **#18**（李明）「最后一个问题，你觉得大学里谈恋爱值不值？」`
       —— 而"引用时写受访者、不要写名字"那句提醒就写在同一节的尾巴上。
       ⇒ 访谈者的提问一律不给 ★（提问是解读线索，不是引语）。

    2. **打分数的是"命中几个关键词"，等于在量句子长度**。
       实测：全篇唯一同时出现双方视角的核心冲突段（"她说我不在乎她 / 我说我在忙正事"）
       得 1 分落选，而"大二在一起、后来分了"只因词典里有 `大二/学期/上学` 就排第一。
       根因是 25 个关键词里 20 个只出现在一段里 —— 拿"命中多少稀有词"当信息量，
       富的是长句，不是有内容的句子。
       ⇒ 改成看**话语动作**（在讲自己的经历/判断/态度）+ 具体性，关键词只当小加分。
    """
    t = u["text"]
    if not (12 <= len(t) <= 100):
        return 0
    if t.strip("。！？!? ") in FILLER:
        return 0
    spk = (u.get("speaker") or "").strip()
    if interviewers and spk in interviewers:
        return 0                              # 访谈者的提问不当引语
    if _looks_ident(t):
        return 0                              # 含直接标识符的句子不能进汇报稿
    score = 0
    # 话语动作：有"我在讲自己的事"的痕迹
    score += sum(1 for w in _QUOTE_SIGNAL if w in t)
    # 概括句扣分（质性引语要的是具体经历，不是"大家都这样"）
    score -= sum(1 for w in _QUOTE_GENERIC if w in t)
    # 关键词加成：只算**跨段出现过的**词（处处出现一次的词没有信息量）
    kk = [w for w, c in kws if c >= 2]
    score += min(2, sum(1 for w in kk if w in t))
    # 长度：太短的说不清一件事
    if len(t) >= 24:
        score += 1
    # 有对照/冲突的更值得引（"以前…现在…"、"她说…我说…"）
    if ("以前" in t and "现在" in t) or ("她说" in t or "他说" in t):
        score += 1
    return score


def _project_words(ctx, units=None):
    """从研究简报里捡出**本项目特有的词**，喂给关键词词表。

    为什么需要：通用词表不可能认识「付费转化」「小鹰扫描」这种行话，
    但这个项目自己的契约里明明写着它们 —— 不喂进去，最该当线索的词一个都进不来。

    ⚠ 只取**变量表第一列（变量名）**，不碰提纲正文。
      第一版从提纲里数 3 字以上窗口，结果喂进去 `不要凑满`『一个影响』这种短语碎片，
      噪声比收益大（"你觉得" 直接顶到关键词第一位）。变量名是研究员亲手写的、
      每个都是有意义的短词，这才是干净的来源。
    ⚠ 最后还要过一遍「材料里真的出现过吗」：契约里写了但这次访谈没提到的词，
      喂进去只是白占位置。
    """
    words = set()
    try:
        p = ctx.path("contracts/research_brief.md")
    except Exception:
        return []
    if not os.path.exists(p):
        return []
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(p, "r", encoding=enc) as f:
                text = f.read()
            break
        except (UnicodeDecodeError, OSError):
            continue
    for ln in (text or "").split("\n"):
        if "|" not in ln:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not cells:
            continue
        name = re.sub(r"[*_`（）()\[\]：:，,。、\s]", "", cells[0])
        # 变量名：2~6 个纯汉字，且不是表头/占位
        if not (2 <= len(name) <= 6 and re.fullmatch(r"[\u4e00-\u9fa5]+", name)):
            continue
        if name in ("变量名", "变量", "名称", "指标", "维度", "备注", "说明"):
            continue
        words.add(name)
    if not words:
        return []
    if units:
        joined = " ".join(u["text"] for u in units)
        words = set(w for w in words if w in joined)
    return sorted(words)


def _carry_over_coding(old_path, rows, cols):
    """重跑时把旧表里**人已经填好的**三列搬回新表。返回搬了几段。

    对齐键用「原文」（不是行号）—— 换切法/改最短字数之后行号会变，
    但同一句话还是同一句话。

    ⚠ 只搬"填过的"，空的原样留白；一段里面的三列要**整组匹配**才搬
      （"原文"要一模一样），对不上就留空让人自己补，绝不猜。
    """
    if not os.path.exists(old_path):
        return 0
    try:
        import csv as _csv
        with open(old_path, "r", encoding="utf-8-sig", newline="") as f:
            rd = _csv.DictReader(f)
            if not rd.fieldnames:
                return 0
            # 三列在旧表里叫什么（容忍别名）
            def _pick(*names):
                for n in names:
                    for c in rd.fieldnames:
                        if n in (c or ""):
                            return c
                return ""
            c_open = _pick("开放编码", "开放式编码", "一级编码", "初始编码")
            c_cat = _pick("范畴", "二级编码", "分类")
            c_theme = _pick("主题", "三级编码", "核心主题")
            if not (c_open or c_cat or c_theme):
                return 0
            old = {}
            for r in rd:
                txt = (r.get("原文") or "").strip()
                if not txt:
                    continue
                vals = ((r.get(c_open) or "").strip() if c_open else "",
                        (r.get(c_cat) or "").strip() if c_cat else "",
                        (r.get(c_theme) or "").strip() if c_theme else "")
                if any(vals):
                    old[txt] = vals
        if not old:
            return 0
        i_open, i_cat, i_theme = cols.index("开放编码"), cols.index("范畴"), cols.index("主题")
        n = 0
        for row in rows:
            txt = str(row[cols.index("原文")]).strip()
            vals = old.get(txt)
            if not vals:
                continue
            row[i_open], row[i_cat], row[i_theme] = vals
            n += 1
        return n
    except Exception:
        return 0


def _coded_progress(csv_path, fallback_total=0):
    """编码工作表填了多少段 —— ② 和 ②b 都用这一套判据。

    为什么要共用：② 说「填了 5 段」而 ②b 说「填了 3 段」，
    是最容易让人不再信任工作台的那种不一致。
    找不到表就返回 (0, fallback_total)。
    """
    if not os.path.exists(csv_path):
        return 0, fallback_total
    try:
        import csv as _csv
        filled = total = 0
        open_col = ""
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            rd = _csv.DictReader(f)
            for c in (rd.fieldnames or []):
                if any(k in (c or "") for k in ("开放编码", "开放式编码", "一级编码", "初始编码")):
                    open_col = c
                    break
            for row in rd:
                if not (row.get("原文") or "").strip():
                    continue
                total += 1
                if open_col and (row.get(open_col) or "").strip():
                    filled += 1
        return filled, (total or fallback_total)
    except Exception:
        return 0, fallback_total


def _looks_like_transcript(path):
    """像不像一份访谈转写稿（用内容判断，不看文件名）。

    转写稿的共同特征：有明显的时间/地点/受访者这类元信息行，
    或者大量「说话人：内容」的行。用内容判断是为了不误吃别的 txt。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read(4000)
    except OSError:
        return False
    if len(txt.strip()) < 60:
        return False
    meta = 0
    for ln in txt.splitlines()[:20]:
        head = ln.split("：")[0].split(":")[0].strip()
        if head in META_KEYS:
            meta += 1
    turn = len(re.findall(r"(?m)^\s*\S{1,12}\s*[:：]\s*\S", txt))
    return meta >= 1 or turn >= 5


def _auto_transcript(ctx):
    """材料里只有一份像转写稿的 → 自动选它。

    ⚠ 关键不是「自动」，是**自动之后要说清楚**：选了哪个、凭什么、怎么改。
      静默替用户做决定比让他自己选更糟 —— 他会以为这是自己填的。
    返回 (rel, 界面上的说明)；没有唯一候选时返回 ("", "")。
    """
    cands = []
    seen = set()
    exts = (".txt", ".md", ".srt", ".csv")
    for sc in ["samples", "data", "output", "contracts", ""]:
        d = ctx.path(sc) if sc else ctx.path(".")
        if not os.path.isdir(d):
            continue
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.lower().endswith(exts):
                continue
            if "编码工作表" in n or "编号对照" in n or "脱敏_变更" in n:
                continue                     # 我们自己产出的表，不是素材
            p = os.path.join(d, n)
            key = os.path.normcase(p)
            if key in seen or not os.path.isfile(p):
                continue
            seen.add(key)
            if _looks_like_transcript(p):
                cands.append((sc + "/" + n) if sc else n)
    if len(cands) == 1:
        rel = cands[0]
        return rel, ("**转写稿我替你选了**：`%s`\n\n"
                     "凭据：材料目录里只有这一份像访谈转写稿（有访谈元信息行，"
                     "或有大量「说话人：内容」）。**不对就在上面那一栏换掉、重跑**——"
                     "我不会因为你没选就停下来，但也不会偷偷替你决定。" % rel)
    if len(cands) > 1:
        ctx.log("有 %d 份像转写稿的材料，没有替你挑：%s" % (len(cands), "、".join(cands)), "warn")
        ctx.alert("材料目录里有 %d 份像转写稿的文件（%s）——不知道该用哪份，请你选。"
                  % (len(cands), "、".join(cands[:3])),
                  level="warn", fix="在「访谈转写稿」那一栏里选一份再跑。",
                  kind="internal")
    return "", ""


def _iv_explicit(raw):
    """表单里写明「谁是访谈者」时用它。多个名字用 、,，;；/ 空格 分开。

    认错的代价不对称：多排掉一个人 = 丢掉一位受访者的全部证据；
    少排掉一个人 = 覆盖人数虚高。所以**只在研究员明说时才用这一栏**，
    没填就仍然走「第一个开口的人」那条老规则（② 和 ②b 共用同一条）。
    """
    s = str(raw or "").strip()
    if not s:
        return []
    return [x for x in re.split(r"[、,，;；/\s]+", s) if x]


# 「谁是访谈者」跟着编码表走的小文件。② 写，②b 读。
# ⚠ 为什么不做成 CSV 里的注释行：那会改掉「第一行是表头」这个前提，
#   而 Excel、界面上的逐段编码面板、所有读取方都按第一行是表头写。
IV_META_REL = "output/编码工作表_元信息.json"


def _write_meta_sidecar(ctx, data):
    """把「这份表里谁是访谈者」写成一个随表走的小文件。写不了就算了，不影响主流程。"""
    try:
        import json
        p = ctx.path(IV_META_REL)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        ctx.made(p)
    except Exception as e:
        ctx.log("访谈者元信息没写成（不影响下面的步骤）：%s" % e, "warn")


def read_meta_sidecar(project_root, rel=IV_META_REL):
    """读「谁是访谈者」那个小文件。没有 / 读坏了 → 返回 {}（调用方退回老规则）。"""
    try:
        import json
        p = os.path.join(project_root, *rel.split("/"))
        if not os.path.exists(p):
            return {}
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _looks_merged_transcript(text):
    """这份稿子像不像**多场访谈拼在一起**（有 `---` 分隔线，或好几处时间/受访者表头）。

    只是拿来决定"要不要提醒你去核一下访谈者"，不拿它改判定结果 ——
    猜错了会把受访者的话当提问排掉，而这个数是直接写进报告的。
    """
    if re.search(r"(?m)^\s*-{3,}\s*$", text) or re.search(r"(?m)^\s*={3,}\s*$", text):
        return True
    marks = re.findall(r"(?m)^\s*(?:访谈对象|受访者|访谈时间|采访者|访谈者)\s*[:：]", text)
    return len(marks) >= 4


def _interviewers_from_meta(text):
    """从转写稿开头的元信息里读「谁是访谈者」。

    `采访者：李明` / `访谈者：[姓名1]` —— 稿子本来就写了，
    读它比猜「第一个开口的人」可靠得多。多场拼接时能一次把每场的采访者都读出来。

    ⚠ 三个都踩过的坑，别改回去：
      1. **绝不能把「受访者」算进来**。实测（三份稿拼一起）：
         `受访者：周然` 被当成访谈者 → 周然那 18 段证据**全部消失**、
         苏雨桐那 35 段被当成提问排掉，而报告里 0 条提醒。
      2. 标签要是 `采访者|访谈者|记者|主持人` 这几个**明确的角色词**。
         「记录」不算（记录员一般不说话），所以不放进正则。
      3. 稿子之间用词不统一是常态：实测同一批稿子里
         `访谈对象：` / `受访者：` 指的是同一个人，`访谈者：` / `采访者：` 也是。
         所以判断**只能看标签本身**，不能顺手把「受访者」当成「采访者」的另一半。
    """
    names = []
    pat = re.compile(r"(?m)^\s*(?:采访者|访谈者|记者|主持人)\s*[:：]\s*(.+?)\s*$")
    for m in pat.finditer(text or ""):
        v = re.sub(r"[（(][^）)]*[）)]", "", m.group(1)).strip()
        v = v.strip(" 　\t,，。;；、")
        if v and v not in names:
            names.append(v)
    return names


def run(ctx):
    # ---------------- 读 ----------------
    rel = (ctx.get("transcript") or "").strip().strip('"')
    auto_note = ""
    if not rel:
        rel, auto_note = _auto_transcript(ctx)
        if rel:
            ctx.log("转写稿没选；材料里只有这一份像转写稿，自动用它：%s" % rel)
    if not rel:
        raise ValueError("请先选访谈转写稿（材料目录里没找到、或有好几份不知道该用哪份；"
                         "把转写稿放进 samples/ 或 data/，或在上面的栏里直接选）")
    path = rel if os.path.isabs(rel) else ctx.path(rel)
    if not os.path.exists(path):
        raise ValueError("找不到文件：%s" % path)
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
    if not text:
        raise ValueError("文件读不出内容（编码不认识）")
    ctx.log("读入 %s：%d 字" % (os.path.basename(path), len(text)))

    split = ctx.get("split") or "speaker"
    opts = ctx.get("keep_interviewer") or []
    if isinstance(opts, str):
        opts = [opts]
    kind = "保留访谈者提问" if "keep_q" in opts else "只留受访者的话"
    try:
        min_len = int(float(ctx.get("min_len") or 6))
        top_kw = int(float(ctx.get("top_kw") or 25))
    except Exception:
        min_len, top_kw = 6, 25

    # ---------------- 切 ----------------
    if split == "speaker":
        raw_units = _split_by_speaker(text)
    elif split == "sentence":
        raw_units = _split_by_sentence(text)
    else:
        raw_units = _split_by_para(text)
    ctx.log("切成 %d 个发言单元（%s）" % (len(raw_units), {
        "speaker": "按说话人", "para": "按段落", "sentence": "按句子"}[split]))

    # 谁算访谈者，优先级：你填的 > 稿子表头写的（`采访者：`）> 第一个开口的人
    iv_given = _iv_explicit(ctx.get("iv_names"))
    iv_src = ""
    if iv_given:
        iv_src = "表单里填的"
    else:
        iv_given = _interviewers_from_meta(text)
        if iv_given:
            iv_src = "稿子开头的「采访者：」"
    interviewers = set(iv_given)
    if iv_given:
        ctx.log("访谈者（%s）：%s" % (iv_src, "、".join(iv_given)))
    else:
        for u in raw_units:
            if u["speaker"]:
                interviewers.add(u["speaker"])
                break
    seen_shape = [(u["speaker"] or "—") for u in raw_units]
    ctx.log("认定访谈者：%s" % ("、".join(interviewers) or "（没认出来，全部保留）"))

    # ⚠ 多场访谈拼在一份稿里时，「第一个开口的人」这条规则会把**第二场的采访者**
    #   当成一位新受访者 —— 于是"覆盖了 3 位受访者"里有一位根本是提问的人。
    #   实测（小周 + 小林 + 苏雨桐 三份拼一张表）：受访者被算成 3 位（实际 2 位）。
    #   不改判定（猜错就是**静默丢掉一位受访者的全部证据**，比虚高更糟），
    #   但把事实摆到脸上，并给一个能直接照着填的名字。
    if not iv_given and _looks_merged_transcript(text):
        ctx.alert("这份稿子像是**好几场访谈拼在一起的**，但「谁是访谈者」那一栏是空的 —— "
                  "「第一个开口的人」这条规则只认得**第一场**的采访者，"
                  "后面几场的采访者会被当成新的受访者，覆盖人数会虚高。",
                  level="warn", kind="internal",
                  fix="先看下面「认定访谈者」是哪个名字。如果是 `[姓名1]` 这种占位符，"
                      "就在「谁是访谈者」那一栏把每一场的采访者都写上（多个用「、」分开）再跑。")

    units = []
    dropped_filler = dropped_short = dropped_q = 0
    for u in raw_units:
        t = _clean(u["text"])
        if not t:
            continue
        if u["speaker"] in interviewers and "keep_q" not in opts:
            dropped_q += 1
            continue
        if "drop_short" in opts and t.strip("。！？!? ") in FILLER:
            dropped_filler += 1
            continue
        if len(t) < min_len:
            dropped_short += 1
            continue
        units.append({"speaker": u["speaker"] or "—", "text": t, "n": len(t)})

    for i, u in enumerate(units, 1):
        u["no"] = i
    ctx.log("保留 %d 段（丢掉：太短 %d、纯附和 %d、访谈者提问 %d）" % (
        len(units), dropped_short, dropped_filler, dropped_q))
    if not units:
        raise ValueError("过滤之后一段都没剩下——把「最短保留多少字」调小一点试试")

    # ---------------- 关键词 ----------------
    # ⚠ 把**本项目特有的词**喂进词表（研究简报的变量名 + 提纲里的关注点）：
    #   通用词表不可能认识「付费转化」「小鹰扫描」这种行话，而这个项目自己的契约里
    #   明明写着它们。不喂的话，最该被当成线索的词一个都进不来。
    project_words = _project_words(ctx, units)
    if project_words:
        ctx.log("从研究简报的变量表里认出 %d 个本项目专有词，一并当线索：%s"
                % (len(project_words), "、".join(project_words[:8])))
    kws = kit.keywords([u["text"] for u in units], top=top_kw, extra=project_words)
    if kws:
        ctx.log("高频关键词：" + "、".join("%s(%d)" % (w, c) for w, c in kws[:10]))

    # ---------------- 候选主题线索 ----------------
    clusters = []
    for w, c in kws[:18]:
        idxs = [u["no"] for u in units if w in u["text"]]
        if len(idxs) >= 2:
            clusters.append([w, len(idxs), idxs])

    # ---------------- 引语候选 ----------------
    scored = sorted(units, key=lambda u: -_quote_score(u, kws, interviewers))
    picks = [u for u in scored if _quote_score(u, kws, interviewers) >= 2][:12]
    ctx.log("挑出 %d 条引语候选" % len(picks))

    # ---------------- 编码工作表 ----------------
    rows = []
    for u in units:
        local_kw = [w for w, _ in kws[:30] if w in u["text"]][:6]
        rows.append([u["no"], u["speaker"], u["n"], u["text"], "、".join(local_kw), "", "", "",
                     "★" if u in picks else ""])
    cols = ["#", "说话人", "字数", "原文", "关键词（线索）", "开放编码", "范畴", "主题", "可作引语"]
    # ⚠ 重跑**不能把人填的编码冲掉**。这是这一整轮最实在的一条：
    #   研究员会反复回来调参数（换切法、改最短字数），而每一次重跑都会重写这张表。
    #   原来写出来的是一张**全空**的新表 → 手工填的编码全没，界面也不问一声。
    #   （实测：1284 字节 / 9 段编码 → 189 字节 / 0 段，`_history` 里连备份都没有。）
    #   现在：新表和旧表按「原文」对齐，**把已经填过的三列搬回来**，并明确告诉研究员搬了几段。
    kept = _carry_over_coding(ctx.path("output/编码工作表.csv"), rows, cols)
    if kept:
        ctx.log("把旧表里已经填好的编码搬回来了：%d 段（按「原文」对齐；改过原文的段落对不上就留空）"
                % kept)
    ctx.save_table("编码工作表.csv", rows, cols)
    ctx.log("编码工作表 → output/编码工作表.csv（%d 行，后三列留白等你填）" % len(rows))

    # ⚠ 「谁是访谈者」这件事实**必须跟着表走**。
    #   实测（三份稿拼一张表）：② 按表头认出了两位采访者 `[姓名2]、[姓名4]`，
    #   但**表里根本没留下这件事** —— 表头那几行元信息在切分时就被丢掉了，
    #   于是 ②b 拿到表只能按"第一个开口的人"猜，把第 2 位采访者算成了**第 4 位受访者**。
    #   为什么不写进 CSV 当注释行：那会改掉「第一行是表头」这个前提 ——
    #   Excel、界面上的逐段编码面板、各个读取方全都按第一行是表头写。
    #   为了一行元信息去动那个前提，风险远大于收益。所以另存一张小文件。
    _write_meta_sidecar(ctx, {
        "interviewers": sorted(interviewers),
        "interviewer_source": iv_src or "第一个开口的人",
        "transcript": rel,
        "speakers": seen_shape,
        "segments": len(units),
        "note": "② 认出的「谁是访谈者」。②b 读它，免得再把采访者算成一位受访者；"
                "这份文件可以删，删了就退回「第一个开口的人」那条规则。",
    })
    if kept:
        ctx.alert("这张编码表里**你之前填过的 %d 段编码已经保留下来了**"
                  "（换切法/改参数重跑也不会丢）。" % kept,
                  level="info", kind="internal",
                  rel="output/编码工作表.csv",
                  fix="如果某些段落这次对不上（比如原文被改过），那几行的编码会留空，"
                      "对着旧版补一下就行 —— 旧版一直在 `_history/` 里。")

    # ---------------- 报告 ----------------
    L = []
    L.append("# 访谈编码 · 初步分析\n")
    L.append("> 转写稿：`%s`（%d 字）" % (rel, len(text)))
    L.append("> 切成 **%d 个发言单元**（丢掉太短 %d、纯附和 %d、访谈者提问 %d）" % (
        len(units), dropped_short, dropped_filler, dropped_q))
    L.append("> 设置：%s · 最短 %d 字 · 访谈者%s" % (
        {"speaker": "按说话人切", "para": "按段落切", "sentence": "按句子切"}[split],
        min_len, "保留" if "keep_q" in opts else "不保留"))
    L.append("> 生成时间：%s\n" % time.strftime("%Y-%m-%d %H:%M"))

    L.append("## 一、这堆材料长什么样\n")
    if len(interviewers) and split == "speaker":
        by_spk = {}
        for u in units:
            by_spk[u["speaker"]] = by_spk.get(u["speaker"], 0) + u["n"]
        L.append("| 说话人 | 字数 | 占比 |")
        L.append("|---|---|---|")
        total = sum(by_spk.values()) or 1
        for k, v in sorted(by_spk.items(), key=lambda x: -x[1]):
            L.append("| %s | %d | %.1f%% |" % (k, v, v / total * 100))
        L.append("")
        L.append("> 如果某个受访者明显说得比别人少，先想想是**他不爱说**还是**你没问进去**。\n")

    L.append("## 二、高频关键词（只是线索，不是主题）\n")
    if kws:
        L.append("| 关键词 | 提及段落数 | 提及率 |")
        L.append("|---|---|---|")
        for w, c in kws[:20]:
            L.append("| %s | %d | %.0f%% |" % (w, c, c / len(units) * 100))
        L.append("")
        L.append("> ⚠ 这是**词表驱动的词频线索**（不是 2-gram 碎块），"
                 "**别直接当主题用**——它只能告诉你「往哪看」。"
                 "要给这个项目加专有词，改 `workbench/core/lexicon.txt`。\n")
    else:
        L.append("（没提取到高频词）\n")

    L.append("## 三、候选主题线索\n")
    if clusters:
        L.append("下面每个词后面跟的是**提到它的段落编号**，顺着编号回去读原文，"
                 "把讲同一件事的段落圈到一起，就是一个范畴的雏形：\n")
        L.append("| 线索词 | 段落数 | 相关段落 |")
        L.append("|---|---|---|")
        for w, c, idxs in clusters:
            L.append("| %s | %d | %s |" % (w, c, "、".join("#%d" % i for i in idxs[:15])))
        L.append("")
    else:
        L.append("（没有出现两次以上的线索词）\n")

    L.append("## 四、引语候选（报告里能直接引的句子）\n")
    if picks:
        for u in picks:
            L.append("- **#%d**（%s）「%s」" % (u["no"], u["speaker"], u["text"]))
        L.append("")
        L.append("> 引用时写「受访者 N」不要写名字；引语要**原样**，别顺手改通顺。\n")
    else:
        L.append("（没挑出合适的引语句子）\n")

    L.append("## 五、接下来怎么编码\n")
    L.append("1. 打开 `output/编码工作表.csv`，**逐段读**，在「开放编码」列写下这段话在讲什么"
             "（用受访者自己的词，别急着归纳）")
    L.append("2. 全部编完再回头合并同义编码，升成「范畴」")
    L.append("3. 范畴再往上归，就是「主题」——主题数量控制在 3~6 个，多了等于没归")
    L.append("4. 每个主题都要能**挂回原文引语**；挂不回去的，说明是你想出来的，不是材料里的")
    L.append("5. 统计每个主题覆盖了几个受访者——**只被一个人提到的，别写成普遍现象**\n")

    md = "\n".join(L)
    ctx.save_text("output/访谈_初步分析.md", md)

    # 契约文件（编码表）也放一份骨架，方便后续步骤引用
    coded = ["# 契约 2 · 访谈编码表（coded_transcript）\n",
             "> 源自 `%s`，共 %d 个发言单元。" % (rel, len(units)),
             "> **待填**：开放编码 → 范畴 → 主题。逐段填在 `output/编码工作表.csv` 里。\n",
             "## 主题汇总（编完再填）\n",
             "| 主题 | 包含范畴 | 覆盖受访者数 | 代表性引语（段落 #） |",
             "|---|---|---|---|",
             "|  |  |  |  |\n",
             "## 引语候选\n"]
    for u in picks:
        coded.append("- #%d（%s）「%s」" % (u["no"], u["speaker"], u["text"]))
    coded.append("")
    ctx.save_text("contracts/coded_transcript.md", "\n".join(coded))

    # ---------------- 结果 ----------------
    tables = [{
        "name": "发言单元一览（前 40 段）",
        "columns": cols,
        "rows": rows[:40],
        "note": "完整 %d 行在 output/编码工作表.csv —— 后三列留白，那是你要填的。" % len(rows),
    }]
    if kws:
        tables.append({
            "name": "高频关键词",
            "columns": ["关键词", "段落数", "提及率%"],
            "rows": [[w, c, round(c / len(units) * 100)] for w, c in kws[:20]],
            "note": "粗略 2 字词频，只用来指方向，不能当主题。",
        })
    if clusters:
        tables.append({
            "name": "候选主题线索",
            "columns": ["线索词", "段落数", "相关段落"],
            "rows": [[w, c, "、".join("#%d" % i for i in idxs[:15])] for w, c, idxs in clusters],
            "note": "顺着编号回原文，把讲同一件事的圈到一起，就是范畴雏形。",
        })

    # ---------- 下一步：填码这件事发生在工作台外面，得说清楚 ----------
    # 走查发现：② 跑完给的是一张**空码表**，学生点 ②b 只会撞一句报错，
    # 中间「去 Excel 填码」这一段界面上完全没有痕迹。
    filled, total = _coded_progress(ctx.path("output/编码工作表.csv"), len(units))
    next_card = None
    if filled == 0:
        next_card = {
            "title": "接下来这一步在工作台外面，但我会盯着",
            "body": ("我出了 **%d 段**发言单元，编码三列是空的——**填码这件事只有你能做**"
                     "（程序替你理解材料，等于替你下结论）。\n\n"
                     "1. 用 Excel 打开 `output/编码工作表.csv`\n"
                     "2. 给每段填「开放编码」，再把相关的码归成「范畴」，最后归成「主题」\n"
                     "3. 存成 CSV（UTF-8）回到这里，跑 **②b 编码汇总**\n\n"
                     "回来的时候我会告诉你填了多少、还差多少，不会让你自己数。" % total),
            "rel": "output/编码工作表.csv",
            "btns": [{"label": "打开编码工作表", "action": "open", "rel": "output/编码工作表.csv"}],
        }
    else:
        next_card = {
            "title": "编码表填了 %d/%d 段" % (filled, total),
            "body": ("还差 %d 段没填。填完（或先填一部分）就可以跑 **②b 编码汇总**——"
                     "它会先告诉你填了多少、哪些还没填，再汇总主题。"
                     % max(0, total - filled)),
            "rel": "output/编码工作表.csv",
            "btns": [{"label": "打开编码工作表", "action": "open", "rel": "output/编码工作表.csv"}],
        }

    notes = "后三列（开放编码/范畴/主题）留给你——程序不替你理解材料。"
    if auto_note:
        notes = auto_note + "\n\n" + notes
    return {
        "summary": "%d 段发言单元 / %d 个关键词 / %d 条引语候选 → output/编码工作表.csv" % (
            len(units), len(kws), len(picks)),
        "tables": tables,
        "figures": [],
        "markdown": [{"name": "访谈_初步分析.md", "rel": "output/访谈_初步分析.md", "text": md}],
        "notes": notes,
        "next": next_card,
        "coded_progress": {"filled": filled, "total": total},
    }
