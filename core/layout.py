# -*- coding: utf-8 -*-
"""工作台 · 从材料里「看出」记录格式

**为什么要有这一层**：随手记的材料（记事簿里记的受访者名单）没有表头、
没有统一写法，一条一个样。原来的办法只有两条路：
  · 靠一堆正则硬猜 → 猜不到的就静默漏（真名留在稿子里）
  · 让研究员一条条手写「自定义替换」→ 20 条就要写 20 行，低效得没法用

研究员的习惯其实是**有规律的**：用换行/空行把不同对象隔开，每个对象内部字段顺序一致。
所以这里做的事是：**从前面几条里把格式看出来**，写成一份人能看懂的 `脱敏格式.md`，
拿不准的地方标出来问人 —— 人确认（或改一下）之后，后面全按这个格式走。

⚠ 立场不变：**程序只提示它看出了什么，最终以人确认的为准。**
   看错了不要紧，改那份 md 或点「重新识别」即可。
"""
import json
import os
import re

REL = "格式说明.md"
FMT_JSON = "脱敏格式.json"
# ⚠ 文件名叫「格式说明」而不是「脱敏格式」——原来那个名字太像"脱敏后的东西"，
#   研究员以为里面是脱敏稿（他报的："输出产物请输出一个与原文件一样格式的"）。
#   真正那份脱敏稿是 `output/脱敏_<原文件名>`，跟原文格式一致。
#   这里只是**说明程序是怎么理解这份材料的**，给人看、也能改。

# 姓氏表跟脱敏引擎共用一张 —— 「像不像姓名」必须用同一把尺子，
# 不然这里说"位置4 是姓名"、那边又不换，两边打架。
try:
    from . import deident_names as _dn
    SURNAME = _dn.SURNAME
except Exception:                                        # 兜底：读不出来也不至于炸
    SURNAME = ""

# 明显不是姓名的词（状态、字段名、常见词）——位置推断时先排除掉
NOT_NAME_WORDS = set("""
恋爱中 已分手 单身 追求中 暧昧中 未恋爱 求脱单
男 女 男生 女生
姓名 名字 性别 年龄 年级 学院 专业 学号 手机 电话 邮箱 微信 备注 说明 地址 籍贯
学生 同学 老师 本科 硕士 大一 大二 大三 大四 研一 研二 研三
""".split())

# 「不是标识符，但也不需要问人」的词 —— 性别/状态这类，不用往「拿不准」里塞
NOT_IDENT_NOISE = set("""
男 女 男生 女生
恋爱中 已分手 单身 追求中 暧昧中 未恋爱 求脱单
大一 大二 大三 大四 研一 研二 研三 本科 硕士 博士
""".split())

# 地名特征字 —— 出现在「像姓名的 2–4 汉字词」里就当它不是名字。
# ⚠ 为什么需要：有人写「广东湛江」表示生源地，正好 4 个汉字、首字「广」又真的是姓，
#   于是被判成了姓名。这类同形词靠姓氏表分不开，只能靠地名特征字排掉。
PLACE_CHARS = set("省市县区镇乡村街道路东西南北中上下左右新老大小"
                  "广广州深圳珠汕湛茂佛莞惠梅潮揭阳江清远韶关肇庆云浮")
PLACE_TOKENS = set(("广东 广西 广州 湖南 湖北 河南 河北 山东 山西 江苏 江西 浙江 安徽 "
                    "福建 云南 贵州 四川 陕西 甘肃 青海 辽宁 吉林 黑龙 新疆 西藏 内蒙 "
                    "北京 上海 天津 重庆 湛江 汕头 茂名 佛山 东莞 惠州 珠海 中山 江门 "
                    "南宁 海口 衡阳 赣州 湛江 深圳 广州 潮州 揭阳").split())

# 字段名（材料里可能出现的写法）→ 内部类别
FIELD_WORDS = [
    ("姓名", ("姓名", "名字", "称呼", "全名")),
    ("性别", ("性别",)),
    ("年龄", ("年龄",)),
    ("年级", ("年级",)),
    ("学院", ("学院", "院系", "系别")),
    ("专业", ("专业",)),
    ("学号", ("学号", "学籍号", "工号")),
    ("手机", ("手机", "电话", "联系电话", "联系方式")),
    ("邮箱", ("邮箱", "email", "e-mail", "邮件")),
    ("QQ", ("qq", "扣扣")),
    ("微信", ("微信", "wechat", "wx")),
    ("生源地", ("生源地", "籍贯", "家乡", "省市")),
    ("恋爱状态", ("恋爱", "状态")),
    ("日期", ("日期", "时间", "访谈")),
    ("备注", ("备注", "说明", "其他")),
]

# 哪些类别是「必须换掉」的直接标识符。
#
# 判定顺序：**先看有没有特征标记，再谈位置优先级**。
# 特征标记是最硬的证据 —— 与其"按顺序猜哪个更像"，不如直接看它长什么样：
#
#   · 邮箱：一定有个 `@`。**看到 @ 就是邮箱，不用再犹豫**（研究员提的判据：
#     「邮箱一般会有 @ 的中间符号，可以作为参考区分点」）
#   · 手机：11 位、以 1[3-9] 开头 —— 这个形状本身就足够特异
#   · 微信：字母开头 + 下划线/数字，且**不含 @**（含 @ 的已经在邮箱那一步截住了）
#   · QQ：5–12 位纯数字，且**不是 1[3-9] 开头的 11 位**（那是手机的形状）
#   · 学号：最宽泛的一条，放最后（纯数字要 8 位以上，或带字母的编号）
#
# 踩过的坑就是「顺序」造成的：手机号被认成学号，因为学号那条也接受字母数字，
# 而它排在手机前面。所以这里把**特征**写在判据里，而不是靠排列组合。
IDENT_MARKS = {
    "邮箱": ("@",),
    "手机": ("11 位、1[3-9] 开头",),
    "QQ": ("5–12 位纯数字",),
    "微信": ("字母开头 + 数字/下划线",),
    "姓名": ("2–4 个汉字，首字是常见姓",),
    "学号": ("8 位以上数字，或带字母的编号",),
}

IDENT_KINDS = ("邮箱", "手机", "QQ", "微信", "姓名", "学号")


def _looks_like_name(v):
    """这串汉字像不像人名。

    两道关：2–4 个汉字 + 首字是常见姓。**再排掉地名**：
    「广东湛江」正好 4 个汉字、首字「广」又真的是姓 —— 靠姓氏表分不开。

    ⚠ 地名判断要**看前两个字**，不能"有一个字是地名特征就排除"：
      省份简称里有「云、南、中、东」，而人名里也常带这些字 ——
      「陈云」被"云＝云南"误伤过一次。所以只有**前两字都**是地名特征才当地名。
    """
    if v in NOT_NAME_WORDS or v in PLACE_TOKENS:
        return False
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", v):
        return False
    if v[0] not in SURNAME:
        return False
    if v[0] in PLACE_CHARS and v[1] in PLACE_CHARS:
        return False                 # 广东、湛江、广州、湖南…（前两字都是地名特征）
    if len(v) >= 3 and v[1] in PLACE_CHARS and v[2] in PLACE_CHARS:
        return False                 # 「广东湛江」这类四字地名
    return True


def _kind_of_word(w):
    """「手机：」「QQ 号：」这类**标签词** → 内部类别。"""
    low = (w or "").strip().lower()
    for kind, words in FIELD_WORDS:
        if any(x in low for x in words):
            return kind
    return ""


def marker_kind(v):
    """只看**特征标记**判断这是什么 —— 不用看位置、不用看标签。

    `@` 是最可靠的那个：邮箱必然有、别的类别必然没有。
    返回类别或 ""（看不出来）。
    """
    v = (v or "").strip()
    if not v:
        return ""
    if "@" in v and re.fullmatch(r"[\w.+-]+@[\w.-]+\.\w+", v):
        return "邮箱"
    if re.fullmatch(r"1[3-9]\d{9}", v):
        return "手机"
    if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", v):
        return "姓名" if _looks_like_name(v) else ""
    # 10 位纯数字：**QQ 号和老式学号都长这样**，这里按实际分布取学号
    # （高校学号 10 位是常态；QQ 号多为 9–10 位但 10 位的那批不占多数）。
    # 拿不准的会在「拿不准的地方」里问人，不在这里硬猜到死。
    if re.fullmatch(r"\d{10}", v):
        return "学号"
    if re.fullmatch(r"\d{5,9}", v):
        return "QQ"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{4,19}", v):
        return "微信"
    if re.fullmatch(r"[A-Za-z0-9\-]{8,20}", v) and any(c.isdigit() for c in v):
        return "学号"
    return ""


def _looks_like(kind, v):
    """这一格的值，长得像该类别的东西吗。

    ⚠ 这里有**两道关**，先特异后宽泛，顺序就是「谁更确定」：
      第一关：带特征标记的（`@` → 邮箱；1[3-9] 开头 11 位 → 手机）—— 基本不会错
      第二关：只有形状的（5–12 位纯数字 → QQ；字母开头 → 微信；等等）
    踩过两次：手机号被认成学号、`@` 那个特征没被当证据用。
    """
    v = (v or "").strip()
    if not v:
        return False
    # ---- 第一关：有特征标记，直接定 ----
    if "@" in v:
        return kind == "邮箱" and bool(re.fullmatch(r"[\w.+-]+@[\w.-]+\.\w+", v))
    if re.fullmatch(r"1[3-9]\d{9}", v):
        return kind == "手机"
    # ---- 第二关：看形状 ----
    if kind == "手机":
        return False                       # 上面那关已经排除了
    if kind == "邮箱":
        return False                       # 没有 @，不是邮箱
    if kind == "QQ":
        # ⚠ 只认 5–9 位。10 位纯数字**QQ 号和老式学号都长这样**，
        #   在 marker_kind 里按实际分布归给了学号（那边是统一口径）。
        #   踩过一次：10 位学号 2023114501 被认成 QQ。
        return bool(re.fullmatch(r"\d{5,9}", v))
    if kind == "微信":
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{4,19}", v))
    if kind == "姓名":
        return _looks_like_name(v)
    if kind == "学号":
        if re.fullmatch(r"\d{5,7}", v):
            return False        # 这个长度更像 QQ
        return bool(re.fullmatch(r"[A-Za-z0-9\-]{6,20}", v)) and any(c.isdigit() for c in v)
    return True


def split_records(text):
    """把材料切成一条条记录。返回 [(切法, [记录文本])]。

    两种习惯都认（研究员的写法就这两种）：
      · block —— 空行分隔（每段一个人，段内一行一个字段）
      · line  —— 一行一个（每行一个人，行内用空格/制表符分隔）
    """
    lines = (text or "").split("\n")
    # 空行分隔：有 2 段以上、且每段不止一行 → block
    blocks, cur = [], []
    for ln in lines:
        if ln.strip():
            cur.append(ln.rstrip())
        else:
            if cur:
                blocks.append("\n".join(cur))
                cur = []
    if cur:
        blocks.append("\n".join(cur))
    multi = [b for b in blocks if len(b.split("\n")) > 1]
    if len(blocks) >= 2 and len(multi) >= 2:
        return "block", blocks
    # 一行一个：非空行里大部分都含联系方式
    nonempty = [l.strip() for l in lines if l.strip()]
    with_contact = [l for l in nonempty if re.search(r"1[3-9]\d{9}|@|\d{5,12}", l)]
    if len(nonempty) >= 2 and len(with_contact) >= max(2, len(nonempty) * 0.6):
        return "line", nonempty
    return "unknown", nonempty


def _fields_of_block(block):
    """块里每行的「标签：值」。返回 [(行号, 标签, 值)]。"""
    out = []
    for i, ln in enumerate(block.split("\n")):
        m = re.match(r"^\s*([^：:\s]{1,8})\s*[：:]\s*(.*)$", ln)
        if m and m.group(2).strip():
            out.append((i, m.group(1).strip(), m.group(2).strip()))
        else:
            out.append((i, "", ln.strip()))
    return out


def _tokens(ln):
    """一行里的 token（空格 / 制表符 / 逗号分隔）。"""
    parts = re.split(r"[\t,，]|\s{1,}", ln.strip())
    return [p for p in parts if p]


def _token_rows(rec):
    """把一条记录切成「一行一段的二维表」：[[段, 段], [段, 段], ...]。

    ⚠ 这里踩过一次：`one_per_line` 那种材料（一条记录跨行、每行又是一串），
      原来只取 `rec.split("\\n")[0]` —— **第一条记录的第二行之后整个被忽略**。
      实测后果：`晓晓 女 17676494856 已分手` 那一行完全没进识别，
      于是它被报成"没认出来的词"，而且位置统计少算了几条。
    """
    return [_tokens(x) for x in rec.split("\n") if x.strip()]


def detect(text, sample_n=3):
    """看材料，给出一份「格式说明」。返回 dict。

    sample_n：用前几条来认格式（默认 3，够看出规律又不至于被后面的异常带偏）。
    """
    style, records = split_records(text)
    info = {
        "style": style,
        "records": len(records),
        "sample_n": sample_n,
        "columns": [],       # line 风格：位置 → 类别
        "fields": [],        # block 风格：[{kind, label, line}]
        "uncertain": [],     # 拿不准的地方，要问人
        "note": "",
    }
    if style == "unknown" or not records:
        info["note"] = "看不出记录是怎么分组的（既不是空行分隔，也不是一行一个）。"
        info["uncertain"].append("请确认：这份材料里，**一条记录**是怎么界定的？（空行隔开？还是每行一条？）")
        # ⚠ 切法看不出来时**不能就这么算了**：至少把「一行里的第几段」摊出来。
        #   材料只有两三行、行里没有标签时，`split_records` 会判成 unknown ——
        #   但人打开一看就知道"第 3 段是手机"。一条判断都不给，等于把人堵死。
        #   （`_detect_columns` 自己会带 `_ask_unknown_words`，这里不用再叫一次，否则提醒出两遍）
        _detect_columns(info, records[:sample_n], _tokens, text)
        return info

    sample = records[:sample_n]

    if style == "block":
        # ⚠ 块式里有两种写法，混起来会让说明**自相矛盾**（研究员看到的就是这个）：
        #   A. 标签式：一行一个字段（`姓名：陈云` / `手机：146...`）→ 按「第几行」报
        #   B. 行内一串：`陈云 男 14658167618 恋爱中`（每条可能占好几行，也可能就一行）
        #      → 按「一行里的第几段」报。
        #   B 原来也走 A 那条路：于是"每条记录里，各行字段"里报出 3 行全「未知」，
        #   底下再补一张"行内各段"的表说第 1 段是姓名 —— 两处打架，
        #   而且报出来的「第 N 行」在**一条记录占多行**时根本对不上号。
        first_block = sample[0] if sample else ""
        first_lines = [x for x in first_block.split("\n") if x.strip()]
        first_cells = _tokens(first_lines[0]) if first_lines else []
        row_like = bool(len(first_cells) >= 3
                        and any(_looks_like(k, c) for c in first_cells for k in IDENT_KINDS))
        if row_like:
            info["row_mode"] = True
            info["fields"] = []
            info["note"] = ("按**空行**把材料切成 %d 条记录；%s，"
                            "每行里有 %d 段，用空格隔开（字段顺序按下面「行内各段」那张表）。"
                            % (len(records),
                               "每条记录就是一行" if len(first_lines) == 1
                               else "每条记录占 %d 行" % len(first_lines),
                               len(first_cells)))
            info["note"] += ("\n⚠ 这 %d 段是**靠位置**认的，没有「标签：值」那种写法。"
                             "位置一旦对错，后面全错——请重点看下面「拿不准的地方」。"
                             % len(first_cells))
            # ⚠ 一条记录占好几行时，只拿**第一行**去数段位（`_tokens`）。
            #   用 `_token_rows` 摊平会把"每人 3 行"堆成一列 9 个值，
            #   于是冒出个不存在的"第 5 段"——自相矛盾的第二处来源。
            _detect_columns(info, sample, lambda rec: _tokens(
                [x for x in rec.split("\n") if x.strip()][0]), text)
            _ask_unknown_words(info, sample, _token_rows)
        else:
            # 真·标签式：一行一个字段（`姓名：陈云` / `手机：146...`）。
            # 这种情况按「第几行」报字段名，比按「第几段」自然（人就是这么读的）。
            info["note"] = ("按**空行**把材料切成 %d 条记录；每条记录里一行一个字段，"
                            "字段顺序按上面这张表。" % len(records))
            _detect_block_fields(info, sample)
            _ask_unknown_words(info, sample, None)

    else:  # line 风格
        info["note"] = ("按**一行一条**把材料切成 %d 条记录；行内用空格分隔，"
                        "下面按位置列出前 %d 条里各位置是什么。" % (len(records), len(sample)))
        _detect_columns(info, sample, _tokens, text)
    return info


def _abs_line(whole, value):
    """`value` 在整份材料里的绝对行号（1 起）。给「看原文第 N 行」用。

    ⚠ 必须按**绝对行号**算，不能按"第几条记录的第几行" —— 界面那边打开的是整份原文。
    """
    if not value or whole is None:
        return 0
    i = str(whole).find(str(value))
    if i < 0:
        return 0
    return str(whole).count("\n", 0, i) + 1


def _detect_columns(info, sample, splitter, raw_text=None):
    """按「一行里的第几段」认字段（line 风格，以及块式里"一行一串"的那种）。

    `splitter(record)` 可以给两种东西：
      · `[段, 段, ...]`            —— 一条记录就是一行
      · `[[段, 段], [段, 段], ...]` —— 一条记录跨多行，每行一串（`_token_rows`）
    两种都会摊平成一串段来看，所以"她那种记事簿"和"一行一条"用的是同一套判据。
    """
    rows = []
    for r in sample:
        cells = splitter(r)
        if cells and isinstance(cells[0], (list, tuple)):
            for c in cells:
                if c:
                    rows.append(list(c))
        elif cells:
            rows.append(list(cells))
    n = max((len(r) for r in rows), default=0)
    for i in range(n):
        got = []
        vals = []
        for r in rows:
            if i >= len(r):
                continue
            t = r[i]
            kk = ""
            for cand in IDENT_KINDS:
                if _looks_like(cand, t):
                    kk = cand
                    break
            got.append(kk)
            vals.append(t)
        uniq = [x for x in dict.fromkeys(got) if x]
        kind = uniq[0] if len(uniq) == 1 else ""
        info["columns"].append({
            "pos": i + 1, "kind": kind, "agree": len(uniq) <= 1,
            "seen": "、".join(x or "（非标识符）" for x in got),
            # 这一段的**真实样子**（前几条），以及第一条落在原文第几行。
            # 两个用途：① 提醒里能把样子摆出来（研究员说"这里很杂"，看不到样子没法判断）
            #           ② 「看原文」能直接落到这一段的第一个例子那一行
            "samples": [x for x in dict.fromkeys(vals) if x][:6],
            "at": _abs_line(raw_text, vals[0] if vals else ""),
        })
        if len(uniq) > 1:
            # ⚠ 一定要把**实际写的样子**摆出来。研究员报过：「这个问题只有自定义，但是这里很杂」——
            #   光说"出现过 手机、学号"他没法判断；看到「14658167618、2023114501」才知道该怎么定。
            info["uncertain"].append(
                "**一行里第 %d 段**（把一行按空格切开数的）拿不准：前 %d 条里这里出现过 %s。"
                "实际写的是「%s」。**告诉我一次就行**，整份材料都按你的判断走。"
                % (i + 1, len(rows), "、".join(uniq),
                   "、".join([x for x in dict.fromkeys(vals) if x][:4])))
        elif not uniq:
            # ⚠ 只在"这一段的实际值不是公认的字段值"时才问。
            #   原来不分青红皂白就问，于是 `男`（性别）、`恋爱中`（状态）这两段也被问
            #   "不是标识符，如果它其实是请指出来" —— 研究员看到的就是这种
            #   **题目本身看着像错**的提醒（他说的"问题表述配合操作有点复杂"）。
            #   真值原样报出来（"实际是「男、女」"），别写「空」，看得懂才有用。
            real = [x for x in dict.fromkeys(vals) if x]
            if real and all(x in NOT_IDENT_NOISE for x in real):
                continue
            info["uncertain"].append(
                "**一行里第 %d 段**：这一格在前 %d 条里都不是标识符（实际是「%s」）。"
                "如果它其实是——比如这一格写的是微信号、昵称——请点下面的选项告诉我。"
                % (i + 1, len(rows), "、".join(real[:6]) if real else "空"))
    # 一行里数字串的歧义：既要提醒，也让人确认
    for j, r in enumerate(rows):
        for t in r:
            if re.fullmatch(r"1[3-9]\d{9}", t):
                # 同一行里还有别的 5-12 位数字 → 可能一个是手机一个是 QQ
                others = [x for x in r if re.fullmatch(r"\d{5,12}", x) and x != t]
                if others:
                    info["uncertain"].append(
                        "第 %d 条里有两个数字串（`%s` 和 `%s`）—— 哪个是手机、哪个是 QQ？"
                        "（11 位 1 开头的通常是手机，但写成 QQ 也很常见）"
                        % (j + 1, t, others[0]))
                    break
    _ask_unknown_words(info, sample, splitter)


def _ask_unknown_words(info, sample, splitter):
    """问一句「这些词里有没有没认出来的名字」。

    ⚠ 原来这里报的是**整条记录**（比如 `陈云 男 14658167618 恋爱中`），
      于是引擎那边直接把它当成一个"词"给选项 —— 点一下会把整条记录换掉。
      （研究员看到的：「他提醒的部分和他已经处理了的部分有重合」，
       因为那条记录里的手机号早就被换成了占位符，这个"整条"已经不存在了。）
      现在：按段切开，逐段问；切不开（真·块式一行一字段）就逐字段问。
    """
    unknown = []
    for rec in sample:
        if splitter:
            cells = splitter(rec)
            if cells and isinstance(cells[0], (list, tuple)):
                vals = [t for row in cells for t in row]
            else:
                vals = list(cells)
        else:
            # 标签式：一行一个字段，**逐词**看，别把整行当一个词
            vals = []
            for x in rec.split("\n"):
                vals += _tokens(x)
        for t in vals:
            t = (t or "").strip()
            if not t or not re.search(r"[\u4e00-\u9fa5]", t):
                continue
            if t in NOT_NAME_WORDS or t in NOT_IDENT_NOISE:
                continue
            if any(_looks_like(k, t) for k in IDENT_KINDS):
                continue
            # ⚠ 不要在这里按"以姓开头"过滤中文词。想过这么干，但**会漏掉真昵称**：
            #   `晓晓`『红红』这些正是研究员要抓的（他自己就举过这个例子），
            #   而"恋爱中""单身"这种字段值已经由 NOT_NAME_WORDS / NOT_IDENT_NOISE 挡住了。
            #   过滤放在**引擎给选项**那一步（`_pick_unknown_words`），那里才需要保守。
            if t not in unknown:
                unknown.append(t)
    if unknown:
        info["uncertain"].append(
            "这些词**没被认出来**：%s。如果其中有需要脱敏的名字（比如不是姓氏开头的昵称），"
            "请把它们写进 🔒 表单的「自定义替换」里（一行一条：`晓晓 = [受访者A]`）。"
            % "、".join(unknown[:8]))


def _detect_block_fields(info, sample):
    """真·块式：一条记录里一行一个字段。"""
    first = _fields_of_block(sample[0]) if sample else []
    for k in range(len(first)):
        kinds = []
        for rec in sample:
            fs = _fields_of_block(rec)
            if k < len(fs):
                label = fs[k][1]
                kind = _kind_of_word(label)
                if not kind and fs[k][2]:
                    for cand in IDENT_KINDS:
                        if _looks_like(cand, fs[k][2]):
                            kind = cand
                            break
                kinds.append((label, kind or "未知"))
        label = kinds[0][0] if kinds else ""
        kind = kinds[0][1] if kinds else "未知"
        agree = len(set(x[1] for x in kinds)) == 1 if kinds else False
        info["fields"].append({"line": k, "label": label, "kind": kind, "agree": agree})
        if not agree and len(kinds) > 1:
            info["uncertain"].append(
                "第 %d 行：前 %d 条里这一行的字段对不上（%s）—— 请确认这一行是什么。"
                % (k + 1, len(kinds), "、".join("%s=%s" % (a, b) for a, b in kinds)))
        elif kind == "未知":
            info["uncertain"].append(
                "第 %d 行（`%s`）：看不出是哪种字段 —— 如果是标识符，请在这里写清楚。"
                % (k + 1, label or "没有标签"))



def to_markdown(info, source_name=""):
    """把识别结果写成一份**人能看懂、也能改**的说明。"""
    L = []
    L.append("# 脱敏格式（程序看出来的，请你确认）\n")
    L.append("> 源文件：`%s`" % (source_name or "（未记）"))
    L.append("> 这文件是**给人看的**：程序按它去认字段。看错了就改这里，或者点「重新识别」。")
    L.append("> 改完再跑一次 🔒，就按你确认的来。\n")
    L.append("## 一句话\n")
    L.append(info.get("note") or "（没看出规律）")
    L.append("")
    style = info.get("style")
    L.append("## 记录怎么分组\n")
    L.append("- 切法：**%s**（%s）" % (
        {"block": "空行分隔", "line": "一行一条", "unknown": "没看出来"}.get(style, style),
        "共 %d 条记录" % info.get("records", 0)))
    L.append("- 用在识别上的前几条：%d 条\n" % info.get("sample_n", 3))

    if info.get("fields"):
        L.append("## 每条记录里，各行的字段（按顺序）\n")
        L.append("| 第几行 | 标签 | 认成什么 | 前几条一致吗 |")
        L.append("|---|---|---|---|")
        for f in info["fields"]:
            L.append("| %d | %s | %s | %s |" % (
                f["line"] + 1, f["label"] or "（没有标签）", f["kind"],
                "一致" if f.get("agree") else "**不一致**"))
        L.append("")
    if info.get("columns"):
        L.append("## 行内各段是什么（把一行按空格切开，从左往右数）\n")
        L.append("| 第几段 | 认成什么 | 前几条实际看到 | 一致吗 |")
        L.append("|---|---|---|---|")
        for c in info["columns"]:
            L.append("| %d | %s | %s | %s |" % (
                c["pos"], c["kind"] or "（不是标识符）", c["seen"],
                "一致" if c.get("agree") else "**不一致**"))
        L.append("")

    L.append("## 拿不准的地方（要你拍板）\n")
    un = info.get("uncertain") or []
    if un:
        for i, u in enumerate(un, 1):
            L.append("%d. %s" % (i, u))
    else:
        L.append("没有。前几条里字段是对得上的，直接跑就行。")
    L.append("")

    L.append("## 你能改的地方\n")
    L.append("1. **改这份文件**：把上面「认成什么」改成对的，再跑一次 🔒（程序按你改的来）")
    L.append("2. **改材料里的写法**：写成 `姓名：王芳` `手机：159...` 这种带标签的，程序就不靠猜了")
    L.append("3. **改不了、也不想改的**：在 🔒 表单的「自定义替换」里一条条写（比如 `王芳 = [受访者A]`）\n")
    return "\n".join(L)


def save(proj, info, source_name=""):
    """把识别结果落盘到项目里（md 给人看，json 给程序读）。"""
    md = to_markdown(info, source_name)
    proj.write_text(REL, md)
    try:
        proj.write_text(FMT_JSON, json.dumps(info, ensure_ascii=False, indent=2))
    except Exception:
        pass
    return REL


def save_root(root, info, source_name=""):
    """把识别结果落盘到项目根目录（`脱敏格式.json`，给程序读）。

    md 那份由引擎用 ctx.save_text 写成产物（`output/脱敏格式.md`，给人看）。
    """
    try:
        p = os.path.join(root, FMT_JSON)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        return p
    except OSError:
        return ""


def load_confirmed(proj):
    """读回人确认/改过的那份 json（有就用它，没有就 None）。"""
    p = proj.safe(FMT_JSON)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("style") else None
    except Exception:
        return None
