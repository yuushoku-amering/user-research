# -*- coding: utf-8 -*-
"""工作台 · 知识库

`knowledge/*.md` 里放的是**规则**（研究该怎么做），不是代码逻辑。
放外面的理由：规则要能被研究员看见、改掉、追问出处 —— 埋在 engine.py 里就只有作者知道了。

文件格式（见 knowledge/README.md）：人读的解释 + ```json 代码块里的 `rules` + 出处。
**一份文件里的多个 ```json 块会合并**（一个块写一条规则更好读），后面的同名键覆盖前面的。
但每个块必须是**完整的 JSON 对象** —— 解析不了就是文件写坏了，`load()` 会把错误一起带回来，
调用方必须把它变成提醒显示出来，**不能静默跳过判定**（静默失效正是这套东西最该避免的毛病）。

⚠ 一个刻意的设计：这里的判定**只产出「提醒」，绝不改研究员的文字**。
程序可以指出「这个目的写法没法回答做完没有」，但替不替它改，是研究员的事。
"""
import json
import os
import re

from . import paths

KNOWLEDGE_DIR = os.path.join(paths.WORKBENCH, "knowledge")

_JSON_BLOCK = re.compile(r"```json\s*\n(.*?)```", re.S)
_cache = {}          # {路径: (mtime, rules, error)}  —— 文件改了要能立刻生效


def dir_path():
    return KNOWLEDGE_DIR


def list_files():
    """知识库里的规则文件（不含 README）。"""
    if not os.path.isdir(KNOWLEDGE_DIR):
        return []
    out = []
    for name in sorted(os.listdir(KNOWLEDGE_DIR)):
        if name.lower().endswith(".md") and name.lower() != "readme.md":
            out.append({"name": name, "path": os.path.join(KNOWLEDGE_DIR, name)})
    return out


def load(name, with_error=False):
    """读一个知识文件。

    默认返回合并后的 rules（dict）；`with_error=True` 时返回 (rules, error)，
    error 是「哪个 json 块坏了」的说明 —— 调用方该把它显示出来，而不是当规则不存在。
    读不出来（文件不在/没 json 块）返回 None（或 (None, 原因)）。
    """
    path = name if os.path.isabs(name) else os.path.join(KNOWLEDGE_DIR, name)
    if not os.path.exists(path):
        res = (None, "知识文件不存在：%s" % name)
        return res if with_error else None
    try:
        mt = os.path.getmtime(path)
    except OSError:
        res = (None, "读不到知识文件的时间戳：%s" % name)
        return res if with_error else None
    hit = _cache.get(path)
    if not hit or hit[0] != mt:
        rules, err = None, ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read()
        except OSError as e:
            rules, err = None, "知识文件打不开：%s（%s）" % (name, e)
        else:
            blocks = _JSON_BLOCK.findall(txt)
            if not blocks:
                err = "知识文件里没有 ```json 规则块：%s" % name
            else:
                merged, bad = {}, []
                for i, b in enumerate(blocks, 1):
                    try:
                        obj = json.loads(b)
                    except ValueError as e:
                        bad.append("第 %d 个 json 块解析失败（%s）" % (i, e))
                        continue
                    if isinstance(obj, dict):
                        merged.update(obj)
                    else:
                        bad.append("第 %d 个 json 块不是对象" % i)
                rules = merged or None
                if bad:
                    err = "知识文件 %s 有问题：%s" % (name, "；".join(bad))
        hit = (mt, rules, err)
        _cache[path] = hit
    rules, err = hit[1], hit[2]
    return (rules, err) if with_error else rules


# --------------------------------------------------------------------------- #
# 判定：研究目的写没写成能被检验的样子
# --------------------------------------------------------------------------- #

def _ns(rules, prefix):
    """把带前缀的扁平键收成一条规则：{"purpose_verbs.advice": "…"} → {"advice": "…"}。

    为什么用前缀：一份知识文件里可能有好几条规则，而多个 ```json 块是合并成一个字典的，
    直接平铺会让两条规则的键互相覆盖（踩过：样本量那条把研究目的那条整个盖掉了）。
    """
    if not isinstance(rules, dict):
        return {}
    pre = prefix + "."
    return {k[len(pre):]: v for k, v in rules.items() if k.startswith(pre)}


def _broken_alert(err):
    """知识文件坏了 → 也要说出来。静默跳过判定，等于告诉研究员「检查过了，没问题」。"""
    if not err:
        return []
    return [{
        "msg": "知识库的规则文件没读成，这次的规则判定被跳过了：%s" % err,
        "fix": "改 knowledge/ 下那份文件，或者把它挪走（挪走就当没这条规则，但别再让它坏着）",
        "source": "工作台 · 知识库加载",
        "kind": "internal",
    }]


# 「为了 / 旨在 / 本研究」这类帽子：剥掉之后再判断真正的动词。
# ⚠ 别用正则从中间截词 —— 试过 `([\u4e00-\u9fa5]{2,4})`，它是贪婪的，
#   「为了探究价格与复购的关系」会截出「探究价格」，跟词表里的「探究」对不上，于是漏判。
_HAT = re.compile(r"^\s*(?:为了|旨在|希望|想要|试图|本研究|本次研究|这个研究|此项研究)\s*")


def _strip_hat(text):
    """剥掉开头的帽子，**循环剥**——「本研究希望了解…」是两层，剥一层还剩一层。"""
    s = (text or "").strip()
    for _ in range(4):
        nxt = _HAT.sub("", s, count=1)
        if nxt == s:
            break
        s = nxt.strip()
    return s


def check_purpose(purpose, rules=None):
    """研究目的里用了「了解/探索」这类没法收尾的动词 → 给一条提醒。

    返回 [] 或 [{"msg":..., "fix":..., "source":..., "kind":...}]
    """
    err = ""
    if rules is None:
        rules, err = load("研究问题与样本量.md", with_error=True)
    r = _ns(rules, "purpose_verbs")
    if not r:
        return _broken_alert(err or "「研究问题与样本量.md」里没有 purpose_verbs.* 那几条规则")
    text = _strip_hat(purpose)
    if not text:
        return []
    vague = r.get("vague_openers") or []
    hit = None
    for w in vague:
        if text.lower().startswith(w.lower()):
            hit = w
            break
    if hit is None:
        return []
    finite = "、".join((r.get("finite_verbs") or [])[:6])
    return [{
        "msg": "研究目的用了「%s」开头 —— 这类词回答不了「怎样算做完」，后面的分析就没有终点。" % hit,
        "fix": (r.get("advice") or "") + "　可选：" + finite,
        "source": r.get("source", ""),
        "kind": r.get("kind", ""),
    }]


# --------------------------------------------------------------------------- #
# 判定：样本量跟研究类型对不对得上
# --------------------------------------------------------------------------- #

def _pick_study_type(text, types):
    """按出现的关键词判断研究类型；命中多个时按 signals 命中数最多的那个。"""
    t = (text or "").lower()
    best, best_n = None, 0
    for st in types:
        n = sum(1 for s in (st.get("signals") or []) if s.lower() in t)
        if n > best_n:
            best, best_n = st, n
    return best


def check_sample(sample, study_text="", rules=None):
    """样本量 vs 研究类型。返回提醒列表（可能为空）。

    `sample` 可以是数字，也可以是「20 人」「两类各 8 人」这种文本——
    文本里能抠出数字就用，抠不出就跳过（宁可不判，也不瞎判）。
    """
    err = ""
    if rules is None:
        rules, err = load("研究问题与样本量.md", with_error=True)
    r = _ns(rules, "sample_size")
    if not r:
        return _broken_alert(err or "「研究问题与样本量.md」里没有 sample_size.* 那几条规则")
    types = r.get("study_types") or []
    txt = str(sample or "").strip()
    if not txt:
        return []
    nums = [int(x) for x in re.findall(r"\d+", txt)]
    if not nums:
        return []                      # 「视情况而定」这种就别判了
    n = max(nums)                      # 「两类各 8 人」→ 8；「共 20 人」→ 20
    st = _pick_study_type(study_text, types)
    if not st:
        return []
    lo, hi = int(st.get("min") or 0), int(st.get("max") or 0)
    out = []
    if lo and n < lo:
        out.append({
            "msg": "%s通常需要 %d 人起（你填的是 %d）——人太少，材料不够支撑结论。"
                   % (st.get("label"), lo, n),
            "fix": (st.get("advice") or "") + "　" + (r.get("note_if_multiple") or ""),
            "source": r.get("source", ""),
            "kind": r.get("kind", ""),
        })
    elif hi and n > hi:
        out.append({
            "msg": "%s超过 %d 人后，新增的信息通常很少了（你填的是 %d）——多出来的人力花得有点冤。"
                   % (st.get("label"), hi, n),
            "fix": (st.get("advice") or "") + "　" + (r.get("note_if_multiple") or ""),
            "source": r.get("source", ""),
            "kind": r.get("kind", ""),
        })
    return out


def _is_screener(var):
    """这条题项是不是筛选题？——**按名字**认（变量名里带「筛」字）。"""
    return "筛" in str(var or "")


# 「门口题」：不叫"筛选"，但功能上就是把不合条件的人挡在门外。
# ⚠ 为什么需要它（前辈 2026-09-24 实测报的误报）：
#   他的问卷 Q1 是「恋爱状态：从未恋爱 / 恋爱中 / 追求中 / 已分手」，
#   而这份研究的样本框就是「**有恋爱经验**的大学生」——
#   选"从未恋爱"的人本来就该被礼貌结束，这题**就是门口的关卡**。
#   可老判据只认名字里带「筛」字的，于是报了「一道都没生成、样本合不合要求就没把门的」,
#   **而门口明明有人把门** —— 这种误报比不报更坏：他会去怀疑一份其实没问题的问卷。
# 判据（两条同时满足才算，宁可漏也不误报）：
#   ① 名字属于"身份/经历/状态"这一类
#   ② 选项里能看到**成对的互斥边界**（有/没有、用过/没用过、从未/已有…）
_GATE_NAME_HINT = ("状态", "经历", "经验", "身份", "是否", "有无", "使用过", "接触过")
_GATE_BOUNDARY_HINT = ("从未", "没有", "无", "从不", "使用过", "用过", "接触过", "不确定")


def _looks_like_gate(it):
    """这条题项**功能上**像不像门口的关卡（按纳入标准设的题）。"""
    var = str(it.get("var") or it.get("变量名") or "")
    if not any(k in var for k in _GATE_NAME_HINT):
        return False
    anchors = str(it.get("anchors") or it.get("选项 / 量表锚点") or "")
    if not anchors:
        return False
    # 选项得像"一串档位"（互斥且不完备就是门口题的样子），而不是一句说明
    if not any(ch in anchors for ch in "/／、"):
        return False
    return any(k in anchors for k in _GATE_BOUNDARY_HINT)


def _gate_boundary_of(it):
    """把那道门口题里"能挡掉人"的那一档挑出来，好在提醒里点名。"""
    anchors = str(it.get("anchors") or it.get("选项 / 量表锚点") or "")
    for k in _GATE_BOUNDARY_HINT:
        if k in anchors:
            for seg in re.split(r"[/／、]", anchors):
                if k in seg:
                    return seg.strip()
            return k
    return "（没认出来）"


def check_recruit(pop, study_text="", rules=None):
    """目标人群写成了人口学口径（年龄/性别/学历/收入…）→ 提醒换成行为口径。

    只在**同时**看到人口学词、却没看到行为词的时候报——
    研究问题本身就在问人群差异时，人口学是自变量，不该被当成毛病。
    """
    err = ""
    if rules is None:
        rules, err = load("研究问题与样本量.md", with_error=True)
    r = _ns(rules, "recruit")
    if not r:
        return _broken_alert(err or "「研究问题与样本量.md」里没有 recruit.* 那几条规则")
    txt = str(pop or "").strip()
    if not txt:
        return []
    demo = [w for w in (r.get("demo_signals") or []) if w in txt]
    beh = [w for w in (r.get("behavior_signals") or []) if w in txt]
    if not demo or beh:
        return []
    return [{
        "msg": "目标人群写的是人口学口径（%s）——招到的是「符合标签的人」，"
               "不一定是真的在做这件事的人。" % "、".join(demo[:4]),
        "fix": r.get("advice", ""),
        "source": r.get("source", ""),
        "kind": r.get("kind", ""),
    }]


def check_screener(items, parts=None, rules=None, planned=None, brief_pop=""):
    """筛选题的写法检查。

    `items` 是 ③ 出的题项（[{"var":…, "kinds_cn":…}, …]）；
    `parts` 是表单里勾了哪些部分（含 "screen" 表示要做筛选题）；
    `planned` 是研究员自己写的筛选题草稿（可选，有就查写法）；
    `brief_pop` 是简报里「目标人群与抽样」那段（用来判断**有没有门口题**）。
    """
    err = ""
    if rules is None:
        rules, err = load("研究问题与样本量.md", with_error=True)
    r = _ns(rules, "screener")
    if not r:
        return _broken_alert(err or "「研究问题与样本量.md」里没有 screener.* 那几条规则")
    out = []
    parts = parts or []
    screeners = [it for it in (items or []) if _is_screener(it.get("var"))]
    # ⚠ 「门口题」**不能算进 screeners 去数上限**（它不是独立的一道筛选题，
    #   而是主体里本来就要问的那道身份题），只用来判断"门口到底有没有人把门"。
    gates = [it for it in (items or []) if _looks_like_gate(it)]

    if "screen" in parts and not screeners and not planned and not gates:
        # ⚠ 注意 `not planned`：研究员自己写了筛选题草稿时，不能说「一道都没生成」——
        #   那是他的草稿，程序只是来查写法的（第一版漏了这个条件，报了一次误报）。
        # ⚠ `not gates`：题里已经有按纳入标准设的"门口题"时也不能说这句（前辈实测报的第二次误报）。
        out.append({
            "msg": "你勾了「筛选题」，但这次一道都没生成 —— 问卷直接从主体开始，"
                   "样本合不合要求就没把门的。",
            "fix": "把筛选题当**招人条件**来写，不是了解人的题：%d–%d 题就够，"
                   "先放能筛掉人的（同行/竞品/不符合角色），再放一道行为确认。%s"
                   % (int(r.get("recommended_min") or 2), int(r.get("max_questions") or 4),
                      r.get("advice", "")),
            "source": r.get("source", ""),
            "kind": r.get("kind", ""),
            "level": "warn",
        })
    elif "screen" in parts and not screeners and not planned and gates:
        # 门口有人把门，但**不是专门设的筛选题**。说清楚事实，不当成毛病报。
        names = "、".join(str(g.get("var")) for g in gates[:3])
        out.append({
            "msg": "没有单独的「筛选题」，但题里的「%s」**功能上就是门口那道关卡** "
                   "（选项里有「%s」这类，按你的纳入标准能挡掉不合条件的人）。"
                   % (names, _gate_boundary_of(gates[0])),
            "fix": "这样是可以的 —— 别为了「有筛选题」再堆一道重复的题。"
                   "只要在报告里写清**哪一题承担了筛选职责、不符合的人怎么结束**就行。"
                   "如果当初是勾错了（本来就不打算单独设筛选题），把那个勾去掉更干净。",
            "source": r.get("source", ""), "kind": r.get("kind", ""), "level": "info",
        })

    n = len(screeners)
    if n > int(r.get("max_questions") or 4):
        out.append({
            "msg": "筛选题有 %d 道，超过通用上限 %d 道 —— 每多一道就多一批人在门口流失。"
                   % (n, int(r.get("max_questions") or 4)),
            "fix": "只留「能筛掉一批人」的那些；筛不掉人的题是白占位置。",
            "source": r.get("source", ""), "kind": r.get("kind", ""), "level": "warn",
        })

    # 筛除题应该在最前面：筛选题里出现「竞品/同行/本行业」这些词，却在中间或后面
    so = r.get("screenout_signals") or []
    for i, it in enumerate(screeners):
        blob = "%s %s" % (it.get("var", ""), it.get("why", ""))
        if any(w in blob for w in so) and i > 0:
            out.append({
                "msg": "「筛除题」（同行 / 竞品 / 不相关行业）排在第 %d 道筛选题上，"
                       "通常应该放在最前面 —— 不合格的人早退出，别浪费双方时间。" % (i + 1),
                "fix": "把筛除题提到筛选题的第一道。",
                "source": r.get("source", ""), "kind": r.get("kind", ""), "level": "warn",
            })
            break

    # 写法检查：是否题、以及「以上都不是」当唯一出路
    txt = ""
    if planned:
        txt = planned if isinstance(planned, str) else "\n".join(
            str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in planned)
    else:
        txt = "\n".join("%s %s" % (it.get("var", ""), it.get("why", "")) for it in screeners)
    if txt.strip():
        binw = [w for w in (r.get("binary_signals") or []) if w in txt]
        if binw:
            out.append({
                "msg": "筛选题里出现了「%s」这种是非问法 —— 受访者为了拿到报酬会倾向答「是」，"
                       "筛不准。" % "、".join(binw[:3]),
                "fix": "换成有具体选项 / 数量 / 时间范围的问法（最近 30 天用过哪几个、最近一次是什么时候）。",
                "source": r.get("source", ""), "kind": r.get("kind", ""), "level": "warn",
            })
        nonew = [w for w in (r.get("none_answer_signals") or []) if w in txt]
        if nonew and ("其他" not in txt and "请注明" not in txt):
            out.append({
                "msg": "选项里有「%s」，但没给别的出路 —— 真人会卡在这里，流失率上去还拿不到信息。"
                       % "、".join(nonew[:2]),
                "fix": "给「以上都不是」配上「其他（请注明）」，或者把选项补全。",
                "source": r.get("source", ""), "kind": r.get("kind", ""), "level": "warn",
            })
    return out


def stats_rules():
    """⑤ 统计分析的判定阈值（`knowledge/统计分析判定.md`）。

    ⚠ **读不到就用代码里的原值兜底，并且把这件事报出来**：
      统计判定读不到规则时静默用默认值，等于"检查过了没问题"——那是我们最不想要的毛病。
    返回 (rules_dict, error_str)，rules 里的键都带 `stats.` 前缀（用 _ns 取子块）。
    """
    r, err = load("统计分析判定.md", with_error=True)
    return (r or {}), (err or "")


def check_stats_rules(rules=None, err=""):
    """统计规则的自我体检：缺了就给一条提醒（不是拦住计算，是让人知道判定走了默认值）。"""
    if rules is None:
        rules, err = stats_rules()
    r = _ns(rules, "stats")
    if not r:
        return _broken_alert(err or "「统计分析判定.md」里没有 stats.* 那几条规则")
    return []


def data_bounds():
    """「数据能支持什么」的条目（`knowledge/数据能支持什么.md`）。

    和 `stats_rules` 一样的规矩：**读不到要说出来**，不能静默当没这条规则。
    返回 (entries_list, error_str)。
    """
    r, err = load("数据能支持什么.md", with_error=True)
    ns = _ns(r or {}, "data")
    ents = ns.get("entries")
    if not isinstance(ents, list):
        return [], (err or "「数据能支持什么.md」里没有 data.entries")
    good = []
    for i, e in enumerate(ents, 1):
        if not isinstance(e, dict):
            continue
        miss = [k for k in ("id", "触发词", "要求", "现在给你什么", "降级路径", "为什么")
                if not e.get(k)]
        if miss:
            # 字段缺了不能猜 —— 猜出来的规则比没有规则更糟（它会以"规则"的名义误导人）
            err = (err + "；" if err else "") + \
                "第 %d 条（%s）缺字段：%s" % (i, e.get("id") or "没写 id", "、".join(miss))
            continue
        good.append(e)
    return good, (err or "")


def check_data_bounds(intent_text="", entries=None, err=""):
    """用户说的研究意图里，有没有**数据答不了**的那种问法。

    只看措辞命中（"更容易""每多""最主要"这类）；**结构性的要求**
    （有没有两次测量、变量是连续还是分档）由调用方用 `known` 传进来，
    因为只有它知道数据长什么样。
    """
    if entries is None:
        entries, err = data_bounds()
    out = []
    txt = str(intent_text or "").strip()
    if txt:
        for e in entries or []:
            hit = [w for w in (e.get("触发词") or []) if w and w in txt]
            if not hit:
                continue
            out.append({
                "id": e.get("id"),
                "命中词": hit,
                "要求": e.get("要求") or [],
                "现在给你什么": e.get("现在给你什么"),
                "降级路径": e.get("降级路径"),
                "为什么": e.get("为什么"),
            })
    if err:
        out.extend(_broken_alert(err))
    return out


def check_method_fit(study_text="", rules=None):
    """方法有没有选错（"想知道实际怎么做"却选了深访，是最容易踩的一个）。"""
    err = ""
    if rules is None:
        rules, err = load("研究策略.md", with_error=True)
    r = _ns(rules, "strategy")
    if not r:
        return _broken_alert(err or "「研究策略.md」里没有 strategy.* 那几条规则")
    txt = str(study_text or "").lower()
    if not txt.strip():
        return []
    methods = r.get("methods") or []
    chosen = [m for m in methods
              if any(s.lower() in txt for s in (m.get("signals") or []))]
    if not chosen:
        return []
    out = []
    for m in chosen:
        bad = [w for w in (m.get("not_for") or []) if w.lower() in txt]
        if not bad:
            continue
        # ⚠ 只有当**没有任何别的、更合适的方法**被提到时才报。
        #   踩过：「想看用户实际操作流程，做情境访谈和实地观察」里同时出现了「访谈」，
        #   先匹配到深访就报了误报 —— 可他明明选对了方法。
        better = []
        for x in methods:
            if x is m:
                continue
            good = [w for w in (x.get("good_for") or []) if w.lower() in txt]
            named = any(s.lower() in txt for s in (x.get("signals") or []))
            if good and named:
                better.append(x.get("label"))
        if better:
            continue
        out.append({
            "msg": "用「%s」来问「%s」这类问题不太对路 —— 得到的是他自己的叙述，不是那件事本身。"
                   % (m.get("label"), "、".join(bad[:2])),
            "fix": "这类问题更该用：情境访谈 / 实地观察（看他做，而不是问他怎么做）。",
            "source": r.get("source", ""), "kind": r.get("kind", ""), "level": "warn",
        })
        break
    return out


def check_priority_framework(study_text="", rules=None):
    """研究目标 → 有没有对应上「按什么排优先级」。分析之前就该定，不然后面排序没标准。"""
    err = ""
    if rules is None:
        rules, err = load("研究策略.md", with_error=True)
    r = _ns(rules, "strategy")
    if not r:
        return _broken_alert(err or "「研究策略.md」里没有 strategy.* 那几条规则")
    txt = str(study_text or "").lower()
    sig = r.get("goal_signals") or {}
    hit = None
    for goal, words in sig.items():
        if any(w.lower() in txt for w in words):
            hit = goal
            break
    if not hit:
        return []
    fw = [f.get("framework") for f in (r.get("priority_frameworks") or [])]
    return [{
        "msg": "这批结论打算按什么排序？现在还看不出来。",
        "fix": "常见对应：%s。**分析之前**先定标准，不然后面重要的和花边会并列。"
               % "；".join(fw[:3]),
        "source": r.get("source", ""), "kind": r.get("kind", ""), "level": "warn",
    }]


def check_brief_inputs(purpose="", sample="", study_text="", population=""):
    """⓪ 的一站式体检：把这一步所有知识库判定过一遍。"""
    return (check_purpose(purpose)
            + check_sample(sample, study_text)
            + check_recruit(population, study_text)
            + check_method_fit(study_text))


def summarize():
    """给界面/自检用：现在装了几份知识、几条规则。"""
    out = []
    for f in list_files():
        r = load(f["name"])
        n = len(r) if isinstance(r, dict) else 0
        out.append({"file": f["name"], "rules": n, "ok": isinstance(r, dict)})
    return out
