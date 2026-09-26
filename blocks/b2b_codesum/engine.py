# -*- coding: utf-8 -*-
"""组块 ②b 编码汇总 · 引擎

研究员在 ② 生成的编码工作表里逐段填了「开放编码 / 范畴 / 主题」三列。
这个引擎只做三件事：

    1. 照他写的码数一遍 —— 主题撑起了几个范畴、覆盖几位受访者、几段证据
    2. 体检 —— 同一个编码被分到两个范畴、主题只有一个人提过、范畴只有一条证据……
    3. 把结果写成能直接放进报告的表，并回填契约文件 contracts/coded_transcript.md

**它不编码，也不改一个字的编码。** 码是研究员的判断，程序只负责数清楚、
把可疑的地方指出来。填得不全也能跑：它会说清楚现在停在「开放编码 → 范畴 →
主题」这条链的哪一环。
"""
import collections
import importlib.util
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WB = os.path.dirname(os.path.dirname(_HERE))
if _WB not in sys.path:
    sys.path.insert(0, _WB)
from core import kit          # noqa: E402


def _load_b2_engine():
    """把 ② 的引擎当模块取回来。

    ⚠ 写两遍是**不行**的：「谁是访谈者」这条规则 ② 和 ②b 必须**逐字一致**——
      两边认的人不一样，就会出现"② 排掉了提问、②b 又把它当受访者算进覆盖人数"，
      而这种不一致从来不报错。所以宁可 import，也不要复制。
    """
    path = os.path.join(_WB, "blocks", "b2_coding", "engine.py")
    spec = importlib.util.spec_from_file_location("_b2_engine_for_codesum", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_B2 = _load_b2_engine()

# 纯附和，当引语没意义
FILLER = {"嗯", "对", "是的", "好", "好的", "哈哈", "哦", "喔", "哎", "对对",
          "嗯嗯", "是", "没有", "还行", "可以", "差不多", "行", "没问题"}

# 列名识别：先精确匹配，再包含匹配
ALIASES = {
    "no":      ["#", "编号", "序号", "段落编号", "段落号"],
    "speaker": ["说话人", "受访者", "被访者", "访谈对象", "姓名", "对象"],
    "text":    ["原文", "文本", "发言内容", "内容", "转写稿", "发言", "原话"],
    "open":    ["开放编码", "开放式编码", "一级编码", "初始编码", "开放码"],
    "cat":     ["范畴", "类别", "二级编码", "类属", "概念"],
    "theme":   ["主题", "三级编码", "主轴编码", "主轴"],
    "star":    ["可作引语", "引语", "标记"],
}

LEVEL_CN = {"must": "❗ 要处理", "warn": "⚠ 注意", "info": "· 提示"}

# 「说话人」列里这些值**不是人**（转写稿的元信息行留下的占位标签）。
# 只做**精确匹配**：真人标签可能是 `[受访者1]`、`受访者A`，前缀匹配会把人排掉。
_NON_SPEAKER_TAGS = {"（元信息）", "(元信息)", "元信息", "—", "-", "", "nan", "none"}


def _s(v):
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def _blank(v):
    s = _s(v)
    return (not s) or s.lower() in ("nan", "none", "null", "-", "—", "（空）")


def _norm_key(s):
    return re.sub(r"[\s（）()【】\[\]：:·、,，.。]", "", str(s))


def _iv_explicit(raw):
    """表单里写明「谁是访谈者」时用它。多个名字用 、,，;；/ 空格 分开。

    多场访谈拼成一张编码表时，「第一个开口的人」只认得第一场的采访者，
    后面几场的采访者会被算成**新的受访者** —— 「覆盖了几位受访者」直接虚高，
    而这个数是要写进报告、用来判断"这算不算普遍现象"的。
    """
    s = str(raw or "").strip()
    if not s:
        return []
    return [x for x in re.split(r"[、,，;；/\s]+", s) if x]


def _meta_rows(text):
    """这份材料里像「转写稿开头元信息」的行有几条。

    `访谈对象：苏雨桐 / 采访者：林晓 / 访谈时间：…` —— 一场访谈开头两三行。
    条数多，说明这张表**是好几个人的稿子拼在一张表里**（② 的合并表会把每场开头都带上）。
    只用来决定"要不要提醒去核访谈者"，不拿它改判定。
    """
    return len(re.findall(r"(?m)^\s*(?:访谈对象|受访者|访谈时间|访谈方式|采访者|访谈者|记录|时长)\s*[:：]", text))


def _cat_base(s):
    """范畴名的"基础名"：去掉括号补充说明和首尾标点。

    `经济压力（花钱）` → `经济压力`；` 经济压力 ` → `经济压力`。
    """
    s = _s(s)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    return re.sub(r"^[\s、,，.。:：;；\-—]+|[\s、,，.。:：;；\-—]+$", "", s).strip()


def _unify_cats(names):
    """把**写法不同、其实是同一个**的范畴名归到一起。返回 {原名: 统一名}。

    ⚠ 只在**保守条件**下归并，因为归并错了会把两个真范畴合成一个（那是改结论）：
      · 去掉空格/括号补充/首尾标点后**完全相同** → 归（`经济压力 ` / ` 经济压力`）
      · 或者"基础名"在**别处也作为完整范畴名出现过** → 归（`经济压力（花钱）` → `经济压力`）
    同义词（`花钱` vs `金钱花费`）**不猜** —— 那要人判断，程序只把它标出来问。
    """
    names = [n for n in dict.fromkeys(names) if _s(n)]
    base = {n: _cat_base(n) for n in names}
    base_set = set(base.values())
    out = {}
    for n in names:
        b = base[n]
        # 基础名本身就是别的范畴名（或和别的去标点形式相同）→ 用基础名
        if b and b != n and (b in base_set or _norm_key(b) in set(_norm_key(x) for x in names)):
            out[n] = b
        else:
            out[n] = b or n
    return out


def _pick_col(cols, names):
    keys = [_norm_key(n) for n in names]
    for c in cols:
        if _norm_key(c) in keys:
            return c
    for c in cols:
        kc = _norm_key(c)
        for k in keys:
            if k and k in kc:
                return c
    return None


# 一格填多个码：只认这些分隔符。中文逗号故意不拆 —— 编码本身常带逗号。
SEPS = "、；;/｜|\n"


def _split_codes(v):
    if _blank(v):
        return []
    s = str(v)
    for ch in SEPS:
        s = s.replace(ch, "\x00")
    out = []
    for p in s.split("\x00"):
        p = p.strip(" \t·-—•*★☆")
        if p and p not in out:
            out.append(p)
    return out


def _quote_score(rec):
    """给「这句能不能当引语」打分。只排序，不改写。"""
    t = rec["text"]
    s = 0
    if rec["star"]:
        s += 3
    n = len(t)
    if 16 <= n <= 90:
        s += 2
    elif n < 14:
        s -= 2
    if t.strip("。！？!? ") in FILLER:
        s -= 6
    return s


def run(ctx):
    # ---------------- 读 ----------------
    rel = _s(ctx.get("coded_file")) or "output/编码工作表.csv"
    path = rel if os.path.isabs(rel) else ctx.path(rel)
    if not os.path.exists(path):
        raise ValueError("找不到编码表：%s（先用 ② 生成一张，填完再来）" % rel)
    df, how = kit.read_table(path)
    cols = list(df.columns)
    ctx.log("读入 %s（%s）：%d 行 × %d 列" % (os.path.basename(path), how, df.shape[0], df.shape[1]))

    col = {k: _pick_col(cols, v) for k, v in ALIASES.items()}
    if not col["text"]:
        raise ValueError("这张表里找不到「原文」列 —— 列名现在有：%s" % "、".join(cols))
    if not (col["open"] or col["cat"] or col["theme"]):
        # 走查发现：学生跑完 ② 直接点 ②b，只会撞到一句话，
        # 不知道自己该干什么、也不知道「填码」这一步在工作台外面。
        # 所以这里要把**表里有多少段、还缺什么、下一步做什么**一次说清。
        raise ValueError(
            "这张表里 %d 段原文，但**三个编码列一个都没有**（开放编码 / 范畴 / 主题）—— "
            "② 刚生成的表就是这样，因为**编码是你要做的活，不是程序的**。\n"
            "现在的列：%s\n"
            "下一步：用 Excel 打开 `output/编码工作表.csv`，给每段填「开放编码」，"
            "再把相关的码归成「范畴」、最后归成「主题」，存成 CSV 回来跑本组块。"
            % (df.shape[0], "、".join(cols)))
    ctx.log("认出的列：原文=%s · 说话人=%s · 开放编码=%s · 范畴=%s · 主题=%s" % (
        col["text"], col["speaker"] or "（没有）", col["open"] or "（没有）",
        col["cat"] or "（没有）", col["theme"] or "（没有）"))

    # ⚠ `or 2` 会把**填进去的 0 吃掉**（0 是假值）——
    #   研究员写 `min_cover=0`（"我不管覆盖度"）却拿到门槛 2，
    #   而且没有任何提示，正是"填了没效果"那一类。所以要区分「没填」和「填了 0」。
    def _num(key, default):
        raw = ctx.get(key)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            return int(float(raw))
        except Exception:
            return default

    min_cover = _num("min_cover", 2)
    max_themes = _num("max_themes", 6)
    quote_n = _num("quote_n", 3)
    opts = ctx.get("opts") or []
    if isinstance(opts, str):
        opts = [opts]

    # ---------------- 拆成一段一条 ----------------
    recs = []
    raw_texts = []          # 原文**不去空白**的版本，只给体检用（认"转写稿开头的元信息行"）
    for i, r in enumerate(df.to_dict("records"), 1):
        text = _s(r.get(col["text"]))
        if not text:
            continue
        raw_texts.append(str(r.get(col["text"]) or ""))
        no = i
        if col["no"]:
            m = re.search(r"\d+", _s(r.get(col["no"])))
            if m:
                no = int(m.group(0))
        recs.append({
            "no": no,
            "speaker": _s(r.get(col["speaker"])) if col["speaker"] else "—",
            "text": text,
            "open": _split_codes(r.get(col["open"])) if col["open"] else [],
            "cat": _split_codes(r.get(col["cat"])) if col["cat"] else [],
            "theme": _split_codes(r.get(col["theme"])) if col["theme"] else [],
            "star": (not _blank(r.get(col["star"]))) if col["star"] else False,
        })
    if not recs:
        raise ValueError("表里一行有内容的原文都没有")

    # 谁算访谈者，优先级：你填的 > ② 留下的元信息 > 表头写的（`采访者：`）> 第一个开口的人
    # —— 与 ② 完全同一条规则（见 `_load_b2_engine` 上面那段注释）
    iv_given = _iv_explicit(ctx.get("iv_names"))
    iv_src = ""
    if iv_given:
        iv_src = "表单里填的"
    else:
        side = _B2.read_meta_sidecar(ctx.project_root)
        if side.get("interviewers"):
            iv_given = [str(x) for x in side["interviewers"]]
            iv_src = "② 留下的元信息"
    if not iv_given:
        iv_given = _B2._interviewers_from_meta("\n".join(raw_texts))
        if iv_given:
            iv_src = "编码表里带的「采访者：」"

    # ⚠ 范畴名/主题名要先**归一同一种写法的不同变体**，否则数字会虚高。
    #   实测（研究员自己提过的真实痛点）：「经济压力」「经济压力 」「 经济压力」
    #   「经济压力（花钱）」在手填的表里会被算成 **4 个范畴**。
    #   归并只做保守那两种（去空格括号标点 / 基础名在别处也出现过），同义词不猜。
    _cat_map = _unify_cats([c for r in recs for c in r["cat"]])
    _th_map = _unify_cats([t for r in recs for t in r["theme"]])
    _merged = {}
    for r in recs:
        if r["cat"]:
            r["cat"] = list(dict.fromkeys(_cat_map.get(c, c) for c in r["cat"]))
        if r["theme"]:
            r["theme"] = list(dict.fromkeys(_th_map.get(t, t) for t in r["theme"]))
    for old, new in list(_cat_map.items()) + list(_th_map.items()):
        if old != new:
            _merged.setdefault(new, []).append(old)
    if _merged:
        _pairs = "；".join("%s ← %s" % (k, "／".join(v[:4])) for k, v in list(_merged.items())[:6])
        ctx.log("把写法不同的同一个名字归到了一起：%s" % _pairs)
        ctx.alert("有 %d 组名字写法不一样、其实是同一个，已经**归并到一起统计**：%s"
                  % (len(_merged), _pairs),
                  level="info", kind="internal",
                  rel="output/编码工作表.csv",
                  fix="如果其中有你**故意分开**的（比如「经济压力（自己）」和「经济压力（家里）」"
                      "确实是两件事），就把表里那两个名字改得**完全不一样**，再跑一次。")

    # 谁算访谈者，优先级：你填的 > 稿子表头写的 > 第一个开口的人
    interviewers = set(iv_given)
    if iv_given:
        ctx.log("访谈者（%s）：%s" % (iv_src, "、".join(iv_given)))
    else:
        for r in recs:
            if r["speaker"] and r["speaker"] != "—":
                interviewers.add(r["speaker"])
                break
    keep_q = "keep_interviewer" in opts

    def is_iv(r):
        return (r["speaker"] in interviewers) and not keep_q

    speakers = []
    for r in recs:
        # ⚠ 转写稿的**元信息行**（`访谈者：…`/`受访者：…`）在合并表里会作为发言单元留着，
        #   而它们的「说话人」列在 ② 生成的表里是「（元信息）」这种**占位标签**。
        #   实测：不排掉，主题矩阵会多出一列「（元信息）」—— 一个不是人的"受访者"，
        #   覆盖人数里也混着它，读表的人根本不知道那是什么。
        #   注意：真正的说话人标签允许带编号（`[受访者1]`），所以这一条按**精确值**判，
        #   不做前缀匹配（前缀匹配会把真人排掉）。
        if _s(r["speaker"]) in _NON_SPEAKER_TAGS:
            continue
        if r["speaker"] not in speakers:
            speakers.append(r["speaker"])
    respondents = [s for s in speakers if s not in interviewers] or [s for s in speakers]

    # ⚠ **统计只算受访者的话**（访谈者的提问不算证据）—— 2026-09-24 修的，这条很要紧：
    #   `is_iv()` 原来只用在一个地方（未编码段落表里标"是谁在说"），
    #   而**段落数 / 覆盖受访者数**是全量算的 —— 一份访谈里提问常占一半（实测 35/70），
    #   于是"这个主题有 N 段证据"直接虚一倍。这个数是要写进报告的，不能虚。
    #   （② 的逐段编码面板早就按角色筛过了，这里是把它对齐过来。）
    #   `recs_all` 留着给"要摆给人看"的地方用（未编码清单要能看出哪段是提问）。
    recs_all = recs
    recs = [r for r in recs if not is_iv(r)]
    n_excluded = len(recs_all) - len(recs)
    if n_excluded:
        ctx.log("统计只算受访者：全表 %d 段，其中访谈者提问 %d 段**不计入证据段数**"
                % (len(recs_all), n_excluded))
        ctx.step("scope", "统计口径：只算受访者的话",
                 "全表 %d 段 → 访谈者提问 %d 段不计入（它们是上下文，不是证据）。"
                 "下面所有「段落数 / 覆盖受访者数」都是按 **%d 段受访者的话** 算的。"
                 % (len(recs_all), n_excluded, len(recs)))

    # ⚠ 下面这几个"填了多少"的计数要在**筛过之后**算 —— 不然进度条的分母还是全量，
    #   跟上面那个口径说明自相矛盾。（第一版就写反了顺序，白算一遍。）
    n_open = sum(1 for r in recs if r["open"])
    n_cat = sum(1 for r in recs if r["cat"])
    n_theme = sum(1 for r in recs if r["theme"])
    if not (n_open or n_cat or n_theme):
        # 走查发现：学生跑完 ② 直接点 ②b，只会撞到一句话，
        # 不知道自己该干什么、也不知道「填码」这一步发生在工作台外面。
        # 所以这里不只是报错，要把**进度和下一步**一起说清楚。
        raise ValueError(
            "表里 **%d 段**原文，但受访者那 %d 段的三个编码列（开放编码 / 范畴 / 主题）"
            "**一格都没填** —— 还没开始编。" % (len(recs_all), len(recs)))

    has_open, has_cat, has_theme = n_open > 0, n_cat > 0, n_theme > 0

    # 受访者顺序按「在材料里第一次出现的先后」来，不按字典序 —— 甲乙丙不该排成丙乙甲
    order_idx = {s: i for i, s in enumerate(speakers)}

    def _ord(names):
        return sorted(names, key=lambda s: order_idx.get(s, 999))

    ctx.step("fill", "编码填到什么程度了",
             "总 %d 段；开放编码填了 %d 段、范畴 %d 段、主题 %d 段。"
             "缺口在哪一环，下面这张表一眼能看出来。" % (len(recs), n_open, n_cat, n_theme),
             rows=[["开放编码", n_open, len(recs), "%.0f%%" % (n_open / len(recs) * 100)],
                   ["范畴", n_cat, len(recs), "%.0f%%" % (n_cat / len(recs) * 100)],
                   ["主题", n_theme, len(recs), "%.0f%%" % (n_theme / len(recs) * 100)]],
             columns=["编码层级", "已填段数", "总段数", "填充率"])

    # ---------------- 编码之间的对应关系 ----------------
    # 一格填了两个码、两个范畴时，谁配谁只有研究员自己知道（我按顺序猜过一次，
    # 结果凭空造出一堆「同一个编码分到不同范畴」的假冲突）。所以：
    #   编码 → 范畴：只从「这一段只有一个范畴」的行里学
    #   范畴 → 主题：只从「这一段只有一个主题」的行里学
    #   其余多对多的格子，只记「同时出现在一段里」这个事实，用于列表展示，不做推断。
    code2cat = collections.defaultdict(set)
    cat2theme = collections.defaultdict(set)
    cat_codes = collections.defaultdict(set)      # 范畴 → 同段出现过的编码（只作展示与覆盖判断）
    for r in recs:
        if len(r["cat"]) == 1:
            for c in r["open"]:
                code2cat[c].add(r["cat"][0])
        if len(r["theme"]) == 1:
            for k in r["cat"]:
                cat2theme[k].add(r["theme"][0])
        for k in r["cat"]:
            cat_codes[k] |= set(r["open"])

    def rec_cats(r):
        """这一段属于哪些范畴。以研究员写的「范畴」列为准，那一格空着才用编码去推。"""
        if r["cat"]:
            return list(r["cat"])
        out = []
        for c in r["open"]:
            for k in code2cat.get(c, ()):
                if k not in out:
                    out.append(k)
        return out or list(r["open"])

    def rec_themes(r):
        """这一段属于哪些主题。以「主题」列为准，那一格空着才顺着范畴往上推。"""
        if r["theme"]:
            return list(r["theme"])
        ks = rec_cats(r)
        if not ks:
            return []
        out = []
        for k in ks:
            for t in cat2theme.get(k, ()):
                if t not in out:
                    out.append(t)
        return out or ["（还没归主题）"]

    # ---------------- 体检：编码冲突 ----------------
    code_conflict = {c: sorted(v) for c, v in code2cat.items() if len(v) > 1}
    cat_conflict = {k: sorted(v) for k, v in cat2theme.items() if len(v) > 1}

    if code_conflict or cat_conflict:
        rows = [["同一个开放编码分到了不同范畴", "%s → %s" % (c, "／".join(v))]
                for c, v in list(code_conflict.items())[:10]]
        rows += [["同一个范畴分到了不同主题", "%s → %s" % (k, "／".join(v))]
                 for k, v in list(cat_conflict.items())[:10]]
        ans = ctx.ask(
            "conflict",
            "编码里有两处对不上：%d 个编码分到了多个范畴、%d 个范畴分到了多个主题" % (
                len(code_conflict), len(cat_conflict)),
            "这未必是错——同一个词在不同语境下确实可以属于不同范畴。"
            "但**汇总表会按你写的全部算一遍**，于是同一段证据会同时挂到两边，数字会虚高。\n"
            "要不要现在回去改表，你自己定。",
            options=[
                {"value": "go", "label": "照我写的原样汇总", "hint": "两边的数都算，汇总表里会标出来"},
                {"value": "stop", "label": "停一下，我先去改表", "hint": "回 Excel 把冲突的格子改清楚，再重跑"},
            ],
            default="go", rows=rows,
            columns=["类型", "具体是哪几处"])
        ctx.log("编码冲突：%d 个编码 / %d 个范畴" % (len(code_conflict), len(cat_conflict)), "warn")
        if ans == "stop":
            return _stopped("编码里有对不上的地方，先去改表", rows)

    if has_cat and not has_theme:
        ans = ctx.ask(
            "no_theme",
            "范畴填了 %d 段，主题列还空着 —— 现在汇总，还是先归主题？" % n_cat,
            "范畴是「同义编码合到一起」，主题是「范畴再往上归一层」。"
            "现在汇总，得到的是范畴级的清单（也能用，只是报告里少一层结构）。",
            options=[
                {"value": "go", "label": "先按范畴汇总给我看看", "hint": "主题就显示成「（还没归主题）」"},
                {"value": "stop", "label": "停一下，我先归主题", "hint": "回 Excel 把主题列补上，再重跑"},
            ],
            default="go",
        )
        if ans == "stop":
            return _stopped("主题列还没填，先回去归主题", [["主题列", "全空"]])

    # ---------------- 聚合 ----------------
    # ⚠ 覆盖度/段落数**只统计真正写了主题名的行**。
    #   踩过（会悄悄改结论的那种）：主题列没填完时，`rec_themes` 会顺着范畴替你推断主题，
    #   而聚合把这些**推断出来的**也计入 segs/resp ——
    #   实测 1 段 / 1 人 → 报 6 段 / 3 人，而同一份产物自己的进度条还诚实地说"主题只填了 1 段"，
    #   两句话打架，还 0 条提醒。覆盖人数是结论强度，**不许拿推断值充数**。
    cat_agg = collections.defaultdict(lambda: {"segs": 0, "resp": set(), "codes": set(), "recs": []})
    theme_agg = collections.defaultdict(lambda: {"segs": 0, "resp": set(), "cats": set(), "recs": []})
    inferred_segs, inferred_resp = 0, set()
    for r in recs:
        ks, ts = rec_cats(r), rec_themes(r)
        for k in ks:
            d = cat_agg[k]
            d["segs"] += 1
            d["resp"].add(r["speaker"])
            d["recs"].append(r)
            d["codes"] |= set(r["open"])
        if not r["theme"]:
            # 主题列空着 → 这一段只能"顺范畴看"，不算进主题的覆盖度
            if ts:
                inferred_segs += 1
                inferred_resp.add(r["speaker"])
            continue
        for t in ts:
            d = theme_agg[t]
            d["segs"] += 1
            d["resp"].add(r["speaker"])
            d["recs"].append(r)
            for k in ks:
                d["cats"].add(k)

    theme_names = sorted(theme_agg.keys(), key=lambda t: (-len(theme_agg[t]["resp"]),
                                                          -theme_agg[t]["segs"], t))
    theme_num = {t: "T%d" % (i + 1) for i, t in enumerate(theme_names)}

    def _tlabel(t):
        """主题名自带编号（有人习惯写「T1 效率痛点」）时不重复加。"""
        return t if re.match(r"^\s*T\s*\d+", str(t), re.I) else "%s %s" % (theme_num[t], t)

    cat_names = sorted(cat_agg.keys(), key=lambda k: (-cat_agg[k]["segs"], k))

    # 归属关系整理
    all_codes = set(c for r in recs for c in r["open"])
    covered_codes = set(c for s in cat_codes.values() for c in s)
    uncat_codes = sorted(all_codes - covered_codes) if has_cat else []
    untheme_cats = sorted(k for k in cat_names if not cat2theme.get(k)) if has_theme else []

    # 主题矩阵
    resp_list = list(respondents)
    matrix = {t: {s: 0 for s in resp_list} for t in theme_names}
    for r in recs:
        for t in rec_themes(r):
            if r["speaker"] in matrix.get(t, {}):
                matrix[t][r["speaker"]] += 1

    # 候选引语
    quotes = {}
    for t in theme_names:
        rs = sorted(theme_agg[t]["recs"], key=lambda r: (-_quote_score(r), -len(r["text"])))
        picks, seen = [], set()
        for r in rs:
            if r["no"] in seen:
                continue
            if _s(r["text"]).strip("。！？!? ") in FILLER:
                continue
            seen.add(r["no"])
            picks.append(r)
            if len(picks) >= quote_n:
                break
        quotes[t] = picks

    ctx.step("map", "怎么归上去的",
             "共 %d 个开放编码、%d 个范畴、%d 个主题。下面是把它们串起来的关系。"
             % (len(set(c for r in recs for c in r["open"])), len(cat_names), len(theme_names)),
             rows=[[code2cat and ("、".join(sorted(code2cat.get(c, ()))) or "（还没归范畴）") or "（没填范畴）",
                    c, sum(1 for r in recs if c in r["open"])]
                   for c in sorted(set(c for r in recs for c in r["open"]))][:40],
             columns=["归入范畴", "开放编码", "出现段数"])

    # ---------------- 体检清单 ----------------
    alerts = []

    def A(level, item, note):
        alerts.append([LEVEL_CN[level], item, note])

    if len(resp_list) <= 1:
        A("must", "整份材料只有 %d 位受访者" % len(resp_list),
          "所有主题都只出自这一位（%s）。结论只能写成「这位受访者认为」，"
          "**不能写成「用户普遍认为」**；要谈普遍性，至少再补 2~3 位。" % "、".join(resp_list))
    if not iv_given and _meta_rows("\n".join(raw_texts)):
        # 表里带着转写稿的开头几行元信息（`访谈对象：/采访者：`）—— 说明这张编码表是
        # **好几场访谈拼起来的**，而"第一个开口的人"只排掉了第一场的采访者。
        # 两个方向都会错，且都改结论：
        #   · 第二场**采访者**没排掉 → 被算成一位受访者，覆盖人数虚高；
        #   · 第二场**受访者**被排掉 → 他的证据整段消失，覆盖人数虚低（更隐蔽）。
        _iv_guess = "、".join(sorted(interviewers)) or "（没认出来）"
        _extra = [s for s in resp_list if s not in interviewers]
        A("warn", "编码表里有好几场访谈的开头，但没指明谁是访谈者",
          "程序只按「第一个开口的人」排掉了 **%s**。多场拼在一起时，后面几场的采访者"
          "会被当受访者（覆盖人数虚高），或者后面几场的受访者被当采访者排掉"
          "（**证据整段消失**，更隐蔽）。现在算出的受访者：%s。"
          "在上面「谁是访谈者」栏把每一场的采访者都写上，再跑一次。"
          % (_iv_guess, "、".join(_extra) if _extra else "—"))
    elif not iv_given and len(resp_list) >= 3:
        _iv_guess = "、".join(sorted(interviewers)) or "（没认出来）"
        A("warn", "表里有 %d 位「受访者」，但没指明谁是访谈者" % len(resp_list),
          "程序只按「第一个开口的人」排掉了 **%s**。如果这张表是好几场访谈拼起来的，"
          "这个数就不对（现在是：%s）。确认无误就忽略这条；"
          "不确定就把每一场的采访者名字填到上面的栏里。" % (_iv_guess, "、".join(resp_list)))
    if not has_theme:
        A("warn", "主题列还空着", "现在这版是「范畴平铺」——报告里缺一层结构，归完主题再跑一次。")
    if not has_cat and has_open:
        A("warn", "范畴列还空着", "现在按开放编码直接汇总，同一件事的不同说法还没合并。")
    for c, v in list(code_conflict.items())[:8]:
        A("warn", "编码「%s」分到了不同范畴" % c, "→ " + "／".join(v))
    for k, v in list(cat_conflict.items())[:8]:
        A("warn", "范畴「%s」分到了不同主题" % k, "→ " + "／".join(v))
    if uncat_codes:
        A("warn", "%d 个开放编码还没归范畴" % len(uncat_codes),
          "、".join(uncat_codes[:10]) + ("…" if len(uncat_codes) > 10 else ""))
    if untheme_cats:
        A("warn", "%d 个范畴还没归主题" % len(untheme_cats),
          "、".join(untheme_cats[:10]) + ("…" if len(untheme_cats) > 10 else ""))

    thin = [t for t in theme_names if len(theme_agg[t]["resp"]) < min_cover]
    if thin:
        A("must" if len(resp_list) > 1 else "info",
          "%d 个主题没达到「至少 %d 位受访者」" % (len(thin), min_cover),
          "、".join("%s（%d 人）" % (_tlabel(t), len(theme_agg[t]["resp"])) for t in thin[:6]) +
          " —— 这些是**个人经历，不是共同模式**，报告里要么单列成个案，要么补访。")

    one_seg = [k for k in cat_names if cat_agg[k]["segs"] == 1]
    if one_seg:
        A("warn", "%d 个范畴只有 1 条证据" % len(one_seg),
          "、".join(one_seg[:10]) + ("…" if len(one_seg) > 10 else "") +
          " —— 回到原文确认一下，是材料里真的只有一处，还是漏编了。")

    # ---------------- 统计口径：把"排除了谁"摆出来 ----------------
    # ⚠ "第一个开口的是访谈者"是**推断**，会有认错的时候，而认错的一种方式是把
    #   **受访者的话**当提问排除掉 —— 数字会悄悄偏少、还不报错。所以**把事实摆出来让人一眼核**。
    #   ⚠ 试过更"聪明"的判据（"被当成访谈者的人不该是说得最多的人"）→ **判不准**：
    #     正规访谈里提问也可能比任何一位受访者都多（一场问 40 次、三位各答 12 次），
    #     而且"说得最多"跟"谁是访谈者"没有必然关系。与其给个会误报的聪明判据，
    #     不如老实摆事实。（第一版写了那个聪明判据，自己造用例时当场发现它判反了。）
    if n_excluded:
        iv_detail = "、".join("%s（%d 段）" % (s, sum(1 for r in recs_all if r["speaker"] == s))
                             for s in sorted(interviewers))
        turns = collections.Counter(r["speaker"] for r in recs)
        top_resp = max(turns.values()) if turns else 0
        risky = (len(recs_all) - len(recs)) > max(1, top_resp)
        A("warn" if risky else "info",
          "统计口径：把 **%s** 当访谈者排除了，不计入证据段数" % iv_detail,
          ("证据段数按 **%d 段受访者的话**算（全表 %d 段）。\n" % (len(recs), len(recs_all)))
          + ("⚠ 这位「访谈者」比任何一位受访者说得都多 —— 材料如果是**多场访谈拼在一起**"
             "（`---` 分隔、第二场开头是受访者在说话），这条推断可能**认反**了，"
             "那就会把受访者的话当成提问排掉、数字悄悄偏少。请对着原稿核一下。"
             if risky else
             "推断依据：**同一个说话人在材料里第一个开口**就是访谈者。"
             "材料如果是多场访谈拼在一起（`---` 分隔），只认了第一场那一次 —— "
             "第二场开头若正好是受访者在说话，会被误认。"))

    if len(theme_names) > max_themes:
        A("warn", "主题有 %d 个，超过你设的上限 %d" % (len(theme_names), max_themes),
          "主题多了等于没归。试着把讲同一件事的范畴合起来，3~6 个最好用。")

    for t in theme_names:
        d = theme_agg[t]
        if len(d["resp"]) >= 2:
            top = max(matrix[t].items(), key=lambda x: x[1])
            if top[1] >= d["segs"] * 0.8:
                A("info", "主题「%s」主要来自 %s" % (t, top[0]),
                  "%d 段里有 %d 段是这个人说的 —— 写的时候别当成全体的声音。" % (d["segs"], top[1]))

    # ⚠ 未编码清单要用 **recs_all**（含访谈者的提问）：那张表有一列「是谁在说」，
    #   要能看出哪一段是提问 —— 只列受访者的话就白留那一列了。（提醒里只数受访者的。）
    uncoded = [r for r in recs_all if not rec_cats(r)]
    uncoded_resp = [r for r in uncoded if not is_iv(r)]
    if uncoded_resp:
        A("warn", "%d 段受访者的话还没编码" % len(uncoded_resp),
          "段落 #" + "、#".join(str(r["no"]) for r in uncoded_resp[:15]) +
          ("…" if len(uncoded_resp) > 15 else "") + " —— 要么补编，要么在报告里说明为什么跳过。")
    if "list_uncoded" in opts and uncoded:
        pass

    ctx.step("check", "体检：这版编码能不能直接用",
             "共 %d 条提醒。红色的是**会直接影响结论表述**的，黄色的是要回去看一眼的。" % len(alerts),
             rows=alerts, columns=["级别", "问题", "怎么处理"])

    # ---------------- 写产物 ----------------
    # 1) 主题汇总表
    t_rows = []
    for t in theme_names:
        d = theme_agg[t]
        t_rows.append([theme_num[t], t,
                       len(d["cats"]), "、".join(sorted(d["cats"])),
                       d["segs"], len(d["resp"]), "、".join(_ord(d["resp"])),
                       (quotes[t][0]["text"][:40] + "…") if quotes[t] and len(quotes[t][0]["text"]) > 40
                       else (quotes[t][0]["text"] if quotes[t] else "")])
    t_cols = ["编号", "主题", "范畴数", "包含范畴", "段落数", "覆盖受访者数", "覆盖受访者", "代表引语"]
    ctx.save_table("编码汇总_主题.csv", t_rows, t_cols)

    # 2) 范畴明细表
    c_rows = []
    for k in cat_names:
        d = cat_agg[k]
        ts = sorted(cat2theme.get(k, ())) or ["（还没归主题）"]
        c_rows.append([k, "、".join(ts), len(d["codes"]), "、".join(sorted(d["codes"])),
                       d["segs"], len(d["resp"]), "、".join(_ord(d["resp"])),
                       "只有 1 条证据" if d["segs"] == 1 else ""])
    c_cols = ["范畴", "归属主题", "编码数", "包含开放编码", "段落数", "覆盖受访者数", "覆盖受访者", "备注"]
    ctx.save_table("编码汇总_范畴.csv", c_rows, c_cols)

    # 3) 主题 × 受访者矩阵
    m_rows = []
    for t in theme_names:
        row = [theme_num[t], t] + [matrix[t].get(s, 0) for s in resp_list]
        m_rows.append(row + [theme_agg[t]["segs"]])
    m_cols = ["编号", "主题"] + resp_list + ["合计"]
    ctx.save_table("编码_主题矩阵.csv", m_rows, m_cols)

    # 4) 未编码段落
    if uncoded:
        u_rows = [[r["no"], r["speaker"], len(r["text"]), r["text"],
                   "访谈者提问" if is_iv(r) else "受访者的话"] for r in uncoded]
        ctx.save_table("编码_未编码段落.csv", u_rows, ["#", "说话人", "字数", "原文", "是谁在说"])

    # 5) 图
    # ⚠ **一个主题都还没归出来时，一张图都不画**。实测（主题列一段没填）：
    #   图一画出一张空轴的白图（标题、坐标轴都在，里面什么都没有，看着像程序坏了），
    #   图二直接 `Invalid shape (0,) for image data`（0 行的矩阵 imshow 不了）。
    #   界面上的「图」是给人看结论的，空图只会让人以为出了故障——
    #   真正该看的是上面那张体检表和「主题列还空着」那条提醒。
    figures = []
    if theme_names:
        try:
            plt = kit.setup_matplotlib()
            import numpy as np

            # 图一：主题 × 范畴 堆叠条
            n = len(theme_names)
            cats_per_theme = {t: collections.Counter() for t in theme_names}
            for r in recs:
                for t in rec_themes(r):
                    # ⚠ `rec_themes()` 在「主题列空着」时会返回占位符 `（还没归主题）`——
                    #   那是**给界面显示**用的，不是主题名。实测：主题列一段没填时，
                    #   这一行直接 `KeyError: '（还没归主题）'`，整块图**静默不出**，
                    #   日志里只有一句「画图失败」（走查实测报的）。
                    #   顺便对齐聚合那边的口径：没填主题的段落**不算进主题覆盖度**。
                    if t not in cats_per_theme:
                        continue
                    for k in rec_cats(r):
                        if k in cat_agg:
                            cats_per_theme[t][k] += 1
            shown = []
            for t in theme_names:
                for k in cats_per_theme[t]:
                    if k not in shown:
                        shown.append(k)
            fig, ax = plt.subplots(figsize=(8.2, max(3.2, 0.66 * n + 1.5)))
            ypos = list(range(n))
            left = [0.0] * n
            for j, k in enumerate(shown):
                vals = [cats_per_theme[t].get(k, 0) for t in theme_names]
                ax.barh(ypos, vals, left=left, height=0.6, label=k,
                        color=kit.PALETTE[j % len(kit.PALETTE)], edgecolor="white", linewidth=0.7)
                left = [a + b for a, b in zip(left, vals)]
            for i, t in enumerate(theme_names):
                ax.text(left[i] + 0.15, i, "%d 人 / %d 段" % (len(theme_agg[t]["resp"]), theme_agg[t]["segs"]),
                        va="center", fontsize=8.5, color="#475569")
            ax.set_yticks(ypos)
            ax.set_yticklabels([_tlabel(t) for t in theme_names], fontsize=9.5)
            ax.invert_yaxis()
            ax.set_xlabel("段落数")
            ax.set_title("主题由哪些范畴撑起来", fontsize=11)
            ax.legend(fontsize=8, frameon=False, loc="lower right", ncol=1)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            fig.tight_layout()
            fp = ctx.out_path("fig_编码_主题结构.png")
            fig.savefig(fp)
            plt.close(fig)
            ctx.made(fp)
            figures.append({"rel": "output/fig_编码_主题结构.png", "name": "主题 × 范畴 结构图",
                            "caption": "条越长说明这个主题的证据越多；右边标的是覆盖人数 / 段落数"})

            # 图二：主题 × 受访者 覆盖矩阵（只有一位受访者时没意义，跳过）
            if len(resp_list) >= 2:
                M = np.array([[matrix[t].get(s, 0) for s in resp_list] for t in theme_names], dtype=float)
                fig, ax = plt.subplots(figsize=(max(4.6, 1.0 * len(resp_list) + 2.4),
                                                max(3.0, 0.5 * n + 1.6)))
                im = ax.imshow(M, cmap="Blues", aspect="auto", vmin=0)
                for i in range(M.shape[0]):
                    for j in range(M.shape[1]):
                        v = int(M[i, j])
                        ax.text(j, i, str(v) if v else "·", ha="center", va="center",
                                fontsize=9, color=("#ffffff" if v > M.max() * 0.6 else "#334155"))
                ax.set_xticks(range(len(resp_list)))
                ax.set_xticklabels(resp_list, rotation=30, ha="right", fontsize=9)
                ax.set_yticks(range(n))
                ax.set_yticklabels([_tlabel(t) for t in theme_names], fontsize=9)
                ax.set_title("谁提到了哪个主题（格子里的数是段数）", fontsize=11)
                fig.colorbar(im, ax=ax, shrink=0.75, label="段落数")
                fig.tight_layout()
                fp = ctx.out_path("fig_编码_主题覆盖矩阵.png")
                fig.savefig(fp)
                plt.close(fig)
                ctx.made(fp)
                figures.append({"rel": "output/fig_编码_主题覆盖矩阵.png", "name": "主题 × 受访者 覆盖矩阵",
                                "caption": "一整行只有一格有数 → 这个主题只有一个人提过"})
        except Exception as e:
            ctx.log("画图失败：%s" % e, "warn")

    # 6) 报告
    CN = "一二三四五六七八九十"
    sec = [0]

    def _h(title):
        sec[0] += 1
        return "## %s、%s\n" % (CN[sec[0] - 1], title)

    L = []
    L.append("# 访谈编码汇总 · 范畴 → 主题\n")
    L.append("> 编码表：`%s`（%s），共 **%d 段**" % (rel, how, len(recs)))
    L.append("> 受访者：%s" % ("、".join(resp_list) if resp_list else "（没认出来）"))
    L.append("> 填充率：开放编码 %d 段 / 范畴 %d 段 / 主题 %d 段" % (n_open, n_cat, n_theme))
    L.append("> 汇总出的结构：**%d 个开放编码 → %d 个范畴 → %d 个主题**" % (
        len(set(c for r in recs for c in r["open"])), len(cat_names), len(theme_names)))
    L.append("> 生成时间：%s\n" % time.strftime("%Y-%m-%d %H:%M"))

    L.append(_h("主题汇总"))
    L.append("| 编号 | 主题 | 范畴数 | 包含范畴 | 段落数 | 覆盖受访者 | 覆盖人数 |")
    L.append("|---|---|---|---|---|---|---|")
    for t in theme_names:
        d = theme_agg[t]
        L.append("| %s | **%s** | %d | %s | %d | %s | %d |" % (
            theme_num[t], t, len(d["cats"]), "、".join(sorted(d["cats"])),
            d["segs"], "、".join(_ord(d["resp"])), len(d["resp"])))
    L.append("")

    L.append(_h("范畴明细"))
    L.append("| 范畴 | 归属主题 | 包含开放编码 | 段落数 | 覆盖人数 | 备注 |")
    L.append("|---|---|---|---|---|---|")
    for k in cat_names:
        d = cat_agg[k]
        L.append("| %s | %s | %s | %d | %d | %s |" % (
            k, "、".join(sorted(cat2theme.get(k, ()))) or "（还没归主题）",
            "、".join(sorted(d["codes"])) or "—", d["segs"], len(d["resp"]),
            "只有 1 条证据" if d["segs"] == 1 else ""))
    L.append("")

    if len(resp_list) >= 2:
        L.append(_h("谁提到了哪个主题"))
        L.append("| 主题 | " + " | ".join(resp_list) + " | 合计 |")
        L.append("|---" * (len(resp_list) + 2) + "|")
        for t in theme_names:
            L.append("| %s | " % _tlabel(t) +
                     " | ".join(str(matrix[t].get(s, 0)) for s in resp_list) +
                     " | %d |" % theme_agg[t]["segs"])
        L.append("")
        L.append("> 一整行只有一格有数 → 这个主题只有一个人提过。**普遍性看的是行，不是合计。**\n")

    L.append(_h("候选引语"))
    for t in theme_names:
        L.append("### %s\n" % _tlabel(t))
        for r in quotes[t]:
            tag = "（你标了★）" if r["star"] else ""
            L.append("- **#%d**（%s）「%s」%s" % (r["no"], r["speaker"], r["text"], tag))
        if not quotes[t]:
            L.append("（这个主题下没挑到合适的句子）")
        L.append("")
    L.append("> 引语要**原样**，不要顺手改通顺；报告里写「受访者 N」，不要写名字。")
    L.append("> 上面是我按「长度合适 + 有信息量 + 你标过★」挑的候选，**用不用你定**。\n")

    L.append(_h("体检"))
    if alerts:
        L.append("| 级别 | 问题 | 怎么处理 |")
        L.append("|---|---|---|")
        for a in alerts:
            L.append("| %s | %s | %s |" % (a[0], a[1], a[2]))
    else:
        L.append("这版编码没查出问题。")
    L.append("")

    L.append(_h("写报告时的几条硬规矩"))
    L.append("1. 主题的**普遍性**看「覆盖了几位受访者」，不是看「有多少段」——"
             "一个人说十遍，也还是一个人")
    L.append("2. 只被一个人提到的，写成个案（「有位受访者提到…」），别写「用户普遍认为」")
    L.append("3. 每个主题至少要能挂回一句原话；挂不回去的，说明是你想出来的，不是材料里的")
    L.append("4. 数字（几个人、几段）由程序出；**主题叫什么名字、算不算一个主题，是你的判断**\n")

    md = "\n".join(L)
    ctx.save_text("output/编码汇总.md", md)

    # 7) 回填契约文件
    C = []
    C.append("# 契约 2 · 访谈编码表（coded_transcript）\n")
    C.append("> 源自 `%s`，共 %d 个发言单元；受访者：%s。" % (rel, len(recs), "、".join(resp_list)))
    C.append("> 本表由 ②b 编码汇总从研究员填写的编码表自动生成（%s）。" % time.strftime("%Y-%m-%d %H:%M"))
    C.append("> 主题名与归类是研究员的判断，程序只做了统计。\n")
    C.append("## 主题汇总\n")
    C.append("| 主题 | 包含范畴 | 覆盖受访者数 | 代表性引语（段落 #） |")
    C.append("|---|---|---|---|")
    for t in theme_names:
        d = theme_agg[t]
        qs = "、".join("#%d" % r["no"] for r in quotes[t][:2])
        C.append("| %s | %s | %d | %s |" % (_tlabel(t), "、".join(sorted(d["cats"])),
                                           len(d["resp"]), qs))
    C.append("")
    C.append("## 引语候选\n")
    for t in theme_names:
        C.append("**%s**" % _tlabel(t))
        for r in quotes[t]:
            C.append("- #%d（%s）「%s」" % (r["no"], r["speaker"], r["text"]))
        C.append("")
    C.append("## 体检提醒\n")
    for a in alerts:
        C.append("- %s **%s** —— %s" % (a[0], a[1], a[2]))
    C.append("")
    ctx.save_text("contracts/coded_transcript.md", "\n".join(C))

    # ---------------- 返回 ----------------
    tables = [
        {"name": "主题汇总", "columns": t_cols, "rows": t_rows,
         "note": "「覆盖受访者数」才是普遍性的依据；段落数只说明证据多不多。"},
        {"name": "范畴明细", "columns": c_cols, "rows": c_rows[:40],
         "note": "完整 %d 个范畴在 output/编码汇总_范畴.csv。" % len(c_rows)},
        {"name": "体检", "columns": ["级别", "问题", "怎么处理"], "rows": alerts,
         "note": "红色是会直接影响结论表述的，黄色是回去看一眼的。"},
    ]

    concl = "%d 个范畴 → %d 个主题；%d 条提醒" % (len(cat_names), len(theme_names), len(alerts))
    if len(resp_list) <= 1:
        concl += "（只有 1 位受访者，普遍性下不了结论）"
    ctx.log("完成：%d 个主题 / %d 个范畴 / %d 条提醒" % (len(theme_names), len(cat_names), len(alerts)))

    # ---------- 下一步 / 还剩多少没填 ----------
    # 走查发现：②→②b 之间「去 Excel 填码」这一段在工作台外面，
    # 没有任何地方告诉研究员「填到哪了、还差多少」。这里补上。
    left_open = len(recs) - n_open
    next_card = None
    if left_open > 0:
        next_card = {
            "title": "还有 %d 段没填开放编码（占 %.0f%%）" % (
                left_open, left_open / float(len(recs)) * 100),
            "body": ("这次汇总只统计了填了码的 %d 段。**没填的段不会被算进去，"
                     "也不会被当成「没人提到」**——别让它们悄悄消失。\n\n"
                     "建议：先把剩下的填完再定稿；或者就按现在这批先看结构，"
                     "但报告里要写明「共 %d 段，已编码 %d 段」。"
                     % (n_open, len(recs), n_open)),
            "rel": "output/编码工作表.csv",
            "btns": [{"label": "打开编码工作表", "action": "open", "rel": "output/编码工作表.csv"}],
        }
    elif not has_theme:
        next_card = {
            "title": "开放编码填全了，但还没归主题",
            "body": "现在得到的是范畴级的清单。把范畴再往上归一层（3~6 个主题），"
                    "报告里才有结构。回 Excel 填「主题」列，再跑一次。",
            "rel": "output/编码工作表.csv",
            "btns": [{"label": "打开编码工作表", "action": "open", "rel": "output/编码工作表.csv"}],
        }

    return {
        "summary": concl,
        "tables": tables,
        "figures": figures,
        "markdown": [{"name": "编码汇总.md", "rel": "output/编码汇总.md", "text": md}],
        "notes": "程序只统计你写的码；主题叫什么、算不算一个主题，是你的判断。",
        "next": next_card,
        "coded_progress": {"filled": n_open, "total": len(recs),
                           "open": n_open, "cat": n_cat, "theme": n_theme},
    }


def _stopped(why, rows):
    return {
        "summary": "按你的要求停在这里 —— %s，本次没有产出汇总表。" % why,
        "stopped": True,
        "tables": [{"name": "需要先处理的编码问题", "columns": ["类型", "具体是哪几处"], "rows": rows,
                    "note": "改完编码表再跑一次就行。"}],
        "figures": [], "markdown": [],
        "notes": "编码表在 output/编码工作表.csv；改完直接重跑本组块。",
    }
