# -*- coding: utf-8 -*-
"""🔒 去标识化 · 引擎

分三层处理，不是一刀切：

    直接标识符 → **替换**（手机、邮箱、身份证、学号、账号…同一实体全篇统一编号）
    上下文姓名 → **替换**（「我叫张三」「李老师」这类明确指向人的）
    准标识符   → **只提示**（年龄、单位、城市、精确收入…降不降粒度是研究决策，不该程序替他定）

产出：脱敏文本 + 处理报告（+ 可选的编号对照表）。
"""
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WB = os.path.dirname(os.path.dirname(_HERE))
if _WB not in sys.path:
    sys.path.insert(0, _WB)

TEXT_EXT = (".txt", ".md", ".srt", ".csv", ".log", ".json", ".tsv")

# 常见姓氏 —— 用来认「上下文里的姓名」。
# ⚠ 这张表漏一个字，代价就是**一整类人的真名留在脱敏稿里**，所以它必须尽量全。
#   踩过两次：
#     · 「林」不在表里 → 转写稿「受访者：林小雨」抓到又被丢掉，真名原样留着
#     · 「刘」也不在（全国第 4 大姓！）→ 随手记里「刘洋 13611112222」没被识别
#   而且原来 177 个字符里**有 39 个是重复的**（实际只有 138 个不同的姓）。
#   现在按「全国前 100 大姓 + 百家姓补充」重排、去重。改动后有一道自检
#   （_deidenttest.py 里）会盯着：前 100 大姓一个都不能缺、表里不能有重复。
_SURNAME_TOP = ("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾"
                "肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏"
                "韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴"
                "莫孔向汤")
_SURNAME_EXTRA = ("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
                  "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
                  "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮齐康伍余元卜顾孟平黄"
                  "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
                  "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
                  "虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉钮龚程"
                  "嵇邢滑裴陆荣翁荀羊甄封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车"
                  "侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭历戎祖武符刘景詹束龙叶幸司韶郜黎"
                  "蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳"
                  "逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎"
                  "充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙"
                  "东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须"
                  "丰巢关蒯相查后荆红游竺权逯盖益桓公")
SURNAME = "".join(dict.fromkeys(_SURNAME_TOP + _SURNAME_EXTRA))   # dict.fromkeys 去重又保序

CITIES = ("北京 上海 广州 深圳 杭州 南京 成都 重庆 武汉 西安 苏州 天津 长沙 郑州 青岛 "
          "宁波 东莞 沈阳 合肥 佛山 无锡 济南 大连 福州 厦门 哈尔滨 昆明 南昌 贵阳 "
          "石家庄 太原 南宁 兰州 长春 常州 泉州 温州 徐州 烟台").split()

# (类型, 正则, 占位前缀, 置信度, 取第几个捕获组)  —— 顺序有讲究：长的、特异的排前面，避免被短模式吃掉
# group=1 的意思是「只换捕获到的那段」，保留「工号」「微信号是」这类前后文，读起来才顺
#
# 手机号里可能出现的分隔符：半角/全角空格、各种横线、以及中文文档里常见的点。
# ⚠ 放宽手机号规则时**必须连分隔符一起放宽**：光加 `[\s\-]?` 的话
#   `１５５　００００　２２２２`（全角空格/全角横线）还是漏。
_PHONE_SEP = "\u3000\uff0d\u2010-\u2015\u2212\uff0e\u3002"


# ⚠ 顺序踩过一次：QQ/微信/学号原来排在「手机号」后面，于是
#   `QQ 18900001111`（一个写成 11 位、又以 1 开头的 QQ 号）会**先被手机号规则吃掉**，
#   而 QQ 规则轮到时已经没有那个数字可换了。**谁更特异谁先动手**：
#   带标签的（QQ/微信/学号）比裸的 11 位数字更确定，所以排前面。
DIRECT = [
    ("身份证", r"(?<!\d)\d{17}[\dXx](?!\d)", "身份证", "high", 0),
    ("邮箱", r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "邮箱", "high", 0),
    ("QQ/群号", r"(?i)(?:QQ|扣扣)\s*(?:群|号)?\s*(?:是|为|[:：])?\s*(\d{5,12})", "QQ", "high", 1),
    ("微信号", r"(?i)(?:微信|wechat|vx)\s*(?:号|ID)?\s*(?:是|为|[:：])?\s*([A-Za-z][\w\-]{5,19})",
     "微信", "high", 1),
    ("学号工号", r"(?:学号|工号|员工号|工牌)\s*[:：]?\s*([A-Za-z0-9\-]{4,20})", "编号", "high", 1),
    # ⚠ 「全角」和「半角」必须写成**同一条规则**（用 `|` 分开的两种写法），
    #   不能拆成两条。拆开的话全角那条先跑，它会先拿走最小的编号 ——
    #   实测：全角手机号在第 12 条、却拿到了 `[手机1]`，而它在文档里并不是第一个。
    ("手机号", r"(?<![\d０-９])(?:1[3-9]\d[\s\-%s]?\d{4}[\s\-%s]?\d{4}"
               r"|[１][３-９][０-９]{9})(?![\d０-９])" % (_PHONE_SEP, _PHONE_SEP),
     "手机", "high", 0),
    ("银行卡", r"(?<!\d)\d{16,19}(?!\d)", "卡号", "mid", 0),
    ("座机", r"(?<!\d)0\d{2,3}[- ]?\d{7,8}(?!\d)", "座机", "mid", 0),
    ("车牌", r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼]"
             r"[A-Z][A-Z0-9]{5}", "车牌", "mid", 0),
    ("昵称网名", r"(?:昵称|网名)\s*[:：]\s*([\w\u4e00-\u9fa5\-]{2,20})", "昵称", "mid", 1),
]

# 上下文里能确定是人名的
NAME_PATTERNS = [
    r"^([%s][\u4e00-\u9fa5]{1,2})\s*[:：]" % SURNAME,          # 行首说话人：张伟：
    r"(?:我叫|我是|我姓|姓|名叫|叫)\s*([%s][\u4e00-\u9fa5]{1,2})" % SURNAME,
    r"(?:记录人?|访谈者|访谈对象|受访者|被访者|主持人|记录)\s*[:：]\s*([%s][\u4e00-\u9fa5]{1,2})" % SURNAME,
    r"([%s][\u4e00-\u9fa5]{1,2})\s*(?:老师|同学|先生|女士|小姐|经理|主任|医生|教授|店长|主管|队长)" % SURNAME,
    r"(?:受访者|被访者|被试|访谈对象)\s*[:：]\s*([\u4e00-\u9fa5]{2,4})",
    r"([%s][\u4e00-\u9fa5]{1,2})\s*(?:说|提到|表示|认为)\s*[:：]" % SURNAME,
    # 规则7：登记表里最常见的「姓名：陈嘉怡」——
    # ⚠ 这一条必须**不受姓氏表限制**（下面 CONTEXTUAL_IDX 里点出来），
    #   因为前面明明白白写着「姓名」两个字，比姓氏表可靠得多。
    r"(?:姓名|名字|全名)\s*[:：]\s*([^\s:：,，;；|]{2,5})",
    # 规则8：一行一人的花名册 —— 「R01 陈嘉怡 女 19岁 …」名字在中间，
    # 后面紧跟「女 / 男 / 19岁 / 20岁」这种特征。没有标签，只能靠姓氏表兜。
    r"^(?:[A-Za-z]{0,3}\d{1,4}[\s、.,，-]+)?([%s][\u4e00-\u9fa5]{1,2})\s+(?:男|女|\d{1,2}\s*岁)"
    % SURNAME,
]

# 哪几条规则是「上下文足够明确、不必再过姓氏表」的
# （规则5：「受访者：xxx」；规则7：「姓名：xxx」）
CONTEXTUAL_IDX = (4, 6)

# 准标识符：只提示，不动手
QUASI = [
    ("年龄", r"(?<!\d)(\d{1,2})\s*(?:岁|周岁)"),
    ("具体单位", r"[\u4e00-\u9fa5]{2,12}(?:大学|学院|学校|公司|集团|医院|银行|研究所|研究院|工作室|事业部)"),
    ("精确收入", r"(?<![\d.])\d{1,3}(?:\.\d)?\s*[kK千]\b|(?<![\d.])\d{4,7}\s*(?:元|块|万)"),
    ("具体日期", r"\d{4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?"),
    ("门牌地址", r"[\u4e00-\u9fa5]{2,10}(?:路|街|巷|小区|大厦|公寓|号楼|单元)\s*[\dA-Za-z\-]*号?"),
    ("行政区", r"[\u4e00-\u9fa5]{2,4}(?:区|县|镇|街道)(?!别|域|分|间|块)"),
    ("可识别特征", r"(?:我们(?:部门|组|团队|班)就(?:我)?一(?:个|名)|全公司只有我|我们那届只有)"),
]


class Replacer(object):
    """同一实体全篇用同一个编号，读起来不会乱。

    `start`：从第几号开始发。**必须接着前一步用掉的最大号**——
    两套替换各自从 1 开始，会把两个人发成同一个 `[姓名1]`（踩过，等于合并身份）。
    """

    def __init__(self, prefix, start=0):
        self.prefix = prefix
        self.map = {}
        self.count = int(start or 0)

    def get(self, s):
        if s not in self.map:
            self.count += 1
            self.map[s] = "[%s%d]" % (self.prefix, self.count)
        return self.map[s]


def _repl_fn(rep, group=0, keyfn=None):
    """给 re.sub 用：每次命中都交给同一个 Replacer，保证全篇编号一致。

    group=0 → 整段换掉；group=1 → 只换捕获到的那段，保留前后文。
    `keyfn` → 取号之前先把命中串归一化。

    ⚠ `keyfn` 踩过一次：`rep.map` 里存的键必须**和取号用的键是同一个**。
      手机号放宽到认「带分隔符 / 全角数字」之后，我先在取号那一步归一化了，
      但 `rep.map` 仍按原文（`１５５００００２２２２`）存 —— 于是
      ① 全角那个号和标准写法**没并成一个实体**，② `_max_used` 数的是占位符、
      而占位符发的是 `[手机1]`，后面的步骤接着 `_max_used` 又发了一次 `[手机1]`，
      **两个不同的人共用一个号**（这正是之前花大力气修掉的那个 bug）。
    """
    if not group:
        def f0(m):
            k = keyfn(m.group(0)) if keyfn else m.group(0)
            return rep.get(k)
        return f0

    def f(m):
        s = m.group(group)
        k = keyfn(s) if keyfn else s
        return m.group(0).replace(s, rep.get(k))
    return f


_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _norm_phone_digits(s):
    """把手机号的写法归一化：全角→半角，去掉中间的分隔符。

    只在**确认是手机号**之后才用（`1[3-9]` 开头 + 11 位数字），
    所以不会把别的东西（比如学号、编号）误伤。
    """
    v = (s or "").translate(_FULLWIDTH_DIGITS)
    v = re.sub(r"[\s\-%s]" % _PHONE_SEP, "", v)
    return v


# 表头关键词 → 该列是什么标识符。顺序有意义：先匹配到的先用。
COL_KINDS = [
    ("姓名", ("姓名", "名字", "受访者", "被访者", "联系人", "称呼")),
    ("学号", ("学号", "学籍号", "工号")),
    ("手机", ("手机", "电话", "联系方式", "联系电话")),
    ("邮箱", ("邮箱", "email", "e-mail", "邮件")),
    ("QQ", ("qq",)),
    ("微信", ("微信", "wechat")),
]


def _cells_of(line):
    """把一行切成单元格（CSV / TSV / Markdown 表格 / 竖线分隔都认）。"""
    s = line.rstrip("\n")
    if not s.strip():
        return []
    if "|" in s and s.strip().startswith("|"):
        parts = [c.strip() for c in s.strip().strip("|").split("|")]
    elif "\t" in s:
        parts = [c.strip() for c in s.split("\t")]
    elif "," in s:
        parts = [c.strip().strip('"') for c in s.split(",")]
    else:
        return []
    return parts


def _kind_of_header(cells):
    """这一行是表头吗？是的话返回 [列序号 → 标识符类别]。"""
    if not cells or len(cells) < 2:
        return None
    found = {}
    for i, c in enumerate(cells):
        low = (c or "").strip().lower()
        if not low:
            continue
        for kind, words in COL_KINDS:
            if any(w in low for w in words):
                found[i] = kind
                break
    # 至少要认出「2 个标识符列」才当成表头，避免把普通数据行误判成表头
    return found if len(found) >= 2 else None




def _find_table_cells(text):
    """认表头列，**找出**该换的单元格。返回 [(行号, 列号, 类别, 原值)]，不改文本。

    为什么只找不换：编号要跟全文统一（`[姓名1]`、`[编号1]` 用一个计数器），
    由主流程拿着已有的 Replacer 统一发号，不然同一个人的编号会打架。
    """
    lines = text.split("\n")
    header, header_at = None, -1
    for i, ln in enumerate(lines[:20]):                 # 表头总在前面
        cells = _cells_of(ln)
        k = _kind_of_header(cells) if cells else None
        if k:
            header, header_at = k, i
            break
    if header is None:
        return lines, []
    out = []
    for i in range(header_at + 1, len(lines)):
        cells = _cells_of(lines[i])
        if not cells:
            continue
        for ci, kind in header.items():
            if ci >= len(cells):
                continue
            v = (cells[ci] or "").strip()
            if not v or v.startswith("[") or "待确认" in v:
                continue                                # 已经换过 / 是占位符
            if _looks_like(kind, v):
                out.append((i, ci, kind, v))
    return lines, out


def _looks_like(kind, v):
    """这一列的某个值，长得像这种标识符吗。**宁可漏，不可误伤**（数据列不能乱换）。"""
    if kind == "姓名":
        # 没有上下文可依，只能靠姓氏表。2–4 个汉字 + 首字是常见姓。
        return bool(re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", v)) and v[0] in SURNAME
    if kind == "学号":
        return bool(re.fullmatch(r"\d{6,20}", v))
    if kind == "手机":
        return bool(re.fullmatch(r"1[3-9]\d{9}", v))
    if kind == "邮箱":
        return bool(re.fullmatch(r"[\w.+-]+@[\w.-]+\.\w+", v))
    if kind == "QQ":
        return bool(re.fullmatch(r"\d{5,12}", v))
    if kind == "微信":
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{4,19}", v))
    return False


def _put_cell(lines, row, col, newval):
    """把某一格换掉，按原分隔符拼回去，别把表格格式改坏。"""
    raw = lines[row]
    cells = _cells_of(raw)
    if col >= len(cells):
        return
    cells[col] = newval
    if raw.strip().startswith("|"):
        lines[row] = "| " + " | ".join(cells) + " |"
    elif "\t" in raw:
        lines[row] = "\t".join(cells)
    else:
        lines[row] = ",".join(('"' + c + '"') if ("," in c) else c for c in cells)


# 「像姓名」的候选里要直接排除的词（字段名/状态/性别这类）。
# ⚠ 单独列一张，是因为它比 core/layout.py 那张表更宽 —— 这里是**替换**，
#   误伤一个词就等于把资料改坏；那边只是"报一句提醒"，宁可多报。
NOT_NAME_VALUES = set("""
姓名 名字 称呼 全名 电话 手机 手机号 微信 微信号 邮箱 邮件 备注 联系 联系方式
学生 同学 老师 女生 男生 编号 学号 学籍号 工号 年级 学院 专业 系别 宿舍 地址 年龄
恋爱中 已分手 单身 追求中 暧昧中 未恋爱 求脱单
大一 大二 大三 大四 研一 研二 研三 本科 硕士 博士
男 女
""".split())

# ⚠ 姓氏表里有**一大堆同时也是常用字的字** —— 时、都、基、本、长、常、方、于、段、成、白、
#   明、全、车、门、计、双、文、关、后、相、查、红、山、谷、车、水……（写表的人没做区分）。
#   于是「一个两字词的**前半截**」只要以这些字开头，就会被当成姓名候选。实测两次误伤：
#       `时长：41 分钟`      → 抽出「时长」→ 变成 `[姓名4]：41 分钟`
#       `他爸妈都是老师`      → 抽出「都是」→ 变成 `他爸妈[姓名5]老师`
#       `这种基本都是他`      → 抽出「基本」→ 变成 `这种基本[姓名5]他`
#   **把正文改坏比漏掉一个名字严重得多**（漏了他能自己补，改坏了他未必发现）。
#   所以这里列一张「以姓氏字开头、但绝不是人名」的常用词表，命中就否决。
NOT_NAME_WORDS = set("""
时长 时间 日期 时候 时机 时刻 时段 时期
都是 都在 都不 都有 都能 都会 也要 也是 也不 都没
基本 基于 基础 基地 基金 基因
长期 长处 长度 长方形
方式 方法 方面 方向 方案 方才 方圆
于是 用于 在于 对于 关于 由于 至于 等于 位于 属于 善用 适用 便于
段落 阶段 成本 成为 成人 成语 成员 成长 成熟
白色 白天 白酒 明白 全部 全家 全校 全面 全国 全程
同学 同时 同意 同样 同期 同事 同名 共同
文档 文件 文学 文章 文明 中文 英文 语文 论文
关系 关注 关于 后面 后来 后悔 后来
相信 相关 相同 相似 相互
查询 查看 开会 会面
红色 红酒 网名
水平 水果 山水
""".split())


def _is_sentence_word(w, line, start):
    """w 是不是**一个更大中文词里的碎片**（而不是一个独立姓名）。

    判据：这个候选的**紧邻左右**只要还是汉字，它就不是一个独立的词 ——
    「都是」在「他爸妈都是老师」里前后都是汉字，那是句子的一部分，不是名字；
    而「王芳 15912345678」里「王芳」两边是空白/行首，才是那个独立的人名。
    """
    if start > 0 and re.match(r"[\u4e00-\u9fa5]", line[start - 1]):
        return True
    end = start + len(w)
    if end < len(line) and re.match(r"[\u4e00-\u9fa5]", line[end]):
        return True
    return False



def find_names_in_contact_lines(text):
    """在「带联系方式的那些行」里找候选姓名。返回 [名字]，按出场顺序。

    为什么需要这一条：没有表头、也没有「姓名：」标签的随手记录，长这样 ——

        王芳 15912345678 微信 wangfang_88
        刘洋 13611112222

    名字后面接的是手机号，不是「男/女/N岁」，所以原来那条规则整行都够不着。
    这里的判据是：**这一行有联系方式 + 行里唯一那个"像姓名"的词**。
    两个条件缺一不可 —— 只看"像姓名"会把普通句子里随便一个姓氏开头的词也抓进来。

    ⚠ 仍然用姓氏表兜底（宁可漏，不能误伤）。「刘」这种漏在姓氏表外的字，
      是姓氏表本身要补的问题，不在这里硬猜。
    """
    out, seen = [], set()
    for ln in (text or "").split("\n"):
        if not ln.strip():
            continue
        line_replaced = ln
        # 这一行里有没有直接标识符？没有就跳过（普通句子不该被当成联系人）
        has_contact = False
        for label, pat, _p, _c, _g in DIRECT:
            if re.search(pat, line_replaced):
                has_contact = True
                break
        if not has_contact:
            continue
        # 找「字母数字串」以外的中文词串，看哪个像姓名
        cands = []
        for m in re.finditer(r"[\u4e00-\u9fa5]{2,4}", ln):
            w = m.group(0)
            if len(w) < 2 or len(w) > 4:
                continue
            if w in NOT_NAME_VALUES or w in NOT_NAME_WORDS:
                continue
            # ⚠ 「像姓名」还不够，得是**一个独立的词**：
            #   姓氏表里有一堆常用字（时/都/基/本/长…），两字词的**前半截**会被误当成名字。
            #   实测：「时长：41 分钟」→`[姓名4]：41 分钟`、「他爸妈都是老师」→`他爸妈[姓名5]老师`。
            #   把正文改坏比漏一个名字严重得多，所以这里再卡一道边界。
            if _is_sentence_word(w, ln, m.start()):
                continue
            # ⚠ 判据是「像姓名」，不是「以姓氏表里的姓开头」。
            #   原来只放行姓氏开头的，于是 `晓晓`『红红』这类**叠字昵称**全漏
            #   （研究员压测名单里就有，而且他自己说过"昵称不在姓氏表里"这种要抓）。
            #   放行的两类：
            #     ① 姓氏表开头 —— 常规姓名
            #     ② 叠字昵称（晓晓/红红/婷婷）—— 不是姓氏也几乎一定是称呼
            #   风险仍然被"这一行有联系方式 + 行里唯一一个中文候选"这两个条件压着。
            _surname_like = w[0] in SURNAME
            _nick_like = bool(re.fullmatch(r"([\u4e00-\u9fa5])\1", w))
            if not (_surname_like or _nick_like):
                continue
            cands.append(w)
        # 一行里只有一个候选才算 —— 多个候选说明这行信息复杂，交给别的规则
        uniq = []
        for c in cands:
            if c not in uniq:
                uniq.append(c)
        if len(uniq) == 1 and uniq[0] not in seen:
            seen.add(uniq[0])
            out.append(uniq[0])
    return out


def ambiguous_numbers(text):
    """找出「数字串有歧义」的地方：像手机号、但也被写成了 QQ/微信号。

    典型现场：`李娜 女 18900001111 QQ 33445566` —— 这里 18900001111 是手机没错。
    但如果有人写成 `QQ 18900001111`（QQ 号恰好 11 位、又以 1 开头），
    光看数字分不清是手机还是 QQ。**工作台不猜，但必须告诉你去核。**

    返回 [(数字, 说明, 第几行)]。说明只讲**为什么可疑**，不带"去哪儿看"——
    因为这句话会被抄进报告表格里，而"去哪儿看"取决于这次有没有生成对照表。

    ⚠ 带行号是因为踩过：同一个号在两行里各触发一次，提醒里两条**一字不差**，
      看着像程序坏了；而且没有行号，研究员也不知道说的是哪一个（他最怕的就是这个）。
    """
    out = []
    seen_pairs = set()          # (数字, 行号)：同一行里同一个号出现两次只报一次
    lines = (text or "").split("\n")
    for li, ln in enumerate(lines, 1):
        for m in re.finditer(r"(?<!\d)(1[3-9]\d{9})(?!\d)", ln):
            num = m.group(1)
            # ⚠ 只在**同一行**里找 QQ/微信 字眼。
            #   第一版用 ±30 字符，会跨到隔壁行 —— 于是 `13812345678` 上面一行写着
            #   「QQ 33445566」，它也报"这个手机号可能是 QQ"，误报一大片。
            for w in ("QQ", "qq", "扣扣", "微信", "群号"):
                if w in ln:
                    key = (num, li)
                    if key in seen_pairs:
                        break
                    seen_pairs.add(key)
                    out.append((num, "这一行里同时出现了「%s」和这个 11 位数字 —— "
                                     "它可能是 QQ 号/微信号，不一定是手机号。" % w, li))
                    break
    return out


def _max_used(text, prefix):
    """文本里已经用掉的「[前缀N]」最大编号。

    ⚠ 为什么要这个：**两套替换各自从 1 开始编号会撞车**。
      踩过一次很严重的：上下文规则把「陈云」发成 `[姓名1]`，
      按格式那步又另起一个计数器，把「晓晓」也发成 `[姓名1]` ——
      **两个不同的人被编成同一个号**，读稿子的人会以为只有 3 个受访者，
      而且把两个人当成一个人。这类错比漏名字严重，因为它**悄悄篡改了身份**。
    """
    top = 0
    for m in re.finditer(r"\[%s(\d+)\]" % re.escape(prefix), text or ""):
        try:
            top = max(top, int(m.group(1)))
        except ValueError:
            pass
    return top


def _apply_layout(text, lay, raw, hits, all_map, ctx=None):
    """按「看出来的格式」去换：位置对上了就直接换，比正则可靠。

    · line 风格 或 block 里「每条就是一行」：**按「一行里的第几段」换**
    · block 里标签式：按行号换

    ⚠ 编号必须**接着已经用掉的最大号往下发**（见 _max_used），
      不然会跟前面几步撞号 —— 撞号等于把两个人合并成一个人。
    返回换过的文本；一处都没换就返回 ""（让调用方保持原样）。
    """
    # 「研究员确认过的段」优先于自动推断：`!第3段是手机` 这种。
    # 他要的就是这个 —— 段落语义在整份材料里是统一的，不该让他逐行填一遍。
    # ⚠ 值为空串 = 他说「这一段不用管」：那**自动推断也不能再动它**，
    #   否则就成了"我让你别管，你偏按自己认出来的换了"（测试撞出来的）。
    confirmed = {}
    plain_cols = set()
    for k, v in (lay.get("col_kinds") or {}).items():
        if not str(k).strip().isdigit():
            continue
        if v in _PREFIX:
            confirmed[int(k)] = v
        elif v == "":
            plain_cols.add(int(k))
    KINDS_OK = ("姓名", "学号", "手机", "邮箱", "QQ", "微信")

    if lay.get("style") == "block" and not lay.get("row_mode"):
        kinds = {f["line"]: f["kind"] for f in (lay.get("fields") or [])
                 if f.get("kind") in KINDS_OK and f.get("agree")}
        if kinds:
            return _apply_labeled_block(text, kinds, hits, all_map)
        return ""

    if lay.get("style") in ("line", "block", "unknown"):
        # ⚠ 连 `unknown` 也要试一次：材料只有两三行时 `split_records` 会判成"看不出切法"，
        #   但只要你确认过段位（`!第3段是手机`），就能按"一行里的第几段"处理。
        #   不试的话，人确认了也没用 —— 他就是为此来问的。
        cols = {}
        for c in (lay.get("columns") or []):
            if c.get("kind") in KINDS_OK and c.get("agree"):
                cols[c["pos"]] = c["kind"]
        # ⚠ 反馈：**你的确认和程序的自动判断一样时，要明说**。
        #   研究员报的「我勾选手机也无效」：他选了「第 3 段是手机号」，
        #   而程序本来就把第 3 段认成手机 —— 两边结论相同，输出当然一模一样，
        #   于是他以为选项坏了。这类"没效果"最难查，所以要主动说出来。
        for _p, _k in confirmed.items():
            _auto = dict((c["pos"], c["kind"]) for c in (lay.get("columns") or []))
            if _auto.get(_p) == _k and ctx is not None:
                ctx.log("第 %d 段本来就是%s —— 你的确认和程序一致，所以输出不会有变化"
                        "（选项没坏，是没东西可改）" % (_p, _KIND_CN.get(_k, _k)), "info")
        cols.update(confirmed)                # 人确认的盖过自动推断
        for p in plain_cols:
            cols.pop(p, None)                 # 人说"别管"的段，谁都不许动
        if not cols:
            return ""
        reps = {}
        n = 0
        out = []
        for ln in text.split("\n"):
            if not ln.strip():
                out.append(ln)
                continue
            toks = re.split(r"(\s{1,}|\t)", ln)          # 保留分隔符，拼回去不改格式
            idx = -1
            for i, t in enumerate(toks):
                if not t.strip():
                    continue
                idx += 1
                kind = cols.get(idx + 1)
                if not kind or not t.strip():
                    continue
                val = t.strip()
                if val.startswith("[") or "待确认" in val:
                    continue
                if not _looks_like_ident(kind, val, loose=(idx + 1) in confirmed):
                    continue
                if kind not in reps:
                    # 接着已经用掉的最大号往下发，别从 1 重来（会跟前面的撞号）
                    reps[kind] = Replacer(_PREFIX[kind], start=_max_used(text, _PREFIX[kind]))
                r = reps[kind]
                ph = r.get(val)
                toks[i] = t.replace(val, ph)
                hits.append(["%s（按格式·第%d段）" % (kind, idx + 1), val, ph, 1, "直接标识符", "mid"])
                all_map[val] = ph
                n += 1
            out.append("".join(toks))
        return "\n".join(out) if n else ""

    if lay.get("style") == "block":
        pass                                    # 标签式在上面那个分支里处理掉了
    return ""


def _apply_labeled_block(text, kinds, hits, all_map):
    """标签式块（`姓名：陈云` / `手机：146...`）：按「第几行」换。"""
    reps = {}
    n = 0
    out = []
    for blk in text.split("\n\n"):
        lines = blk.split("\n")
        for li, ln in enumerate(lines):
            kind = kinds.get(li)
            if not kind:
                continue
            m = re.match(r"^(\s*[^：:\s]{1,8}\s*[：:]\s*)(\S.*)$", ln)
            if not m:
                continue
            val = m.group(2).strip()
            if val.startswith("[") or not _looks_like_ident(kind, val):
                continue
            if kind not in reps:
                reps[kind] = Replacer(_PREFIX[kind], start=_max_used(text, _PREFIX[kind]))
            r = reps[kind]
            ph = r.get(val)
            lines[li] = m.group(1) + ph
            hits.append(["%s（按格式·第%d行）" % (kind, li + 1), val, ph, 1, "直接标识符", "mid"])
            all_map[val] = ph
            n += 1
        out.append("\n".join(lines))
    return "\n\n".join(out) if n else ""


_PREFIX = {"姓名": "姓名", "学号": "编号", "手机": "手机", "邮箱": "邮箱", "QQ": "QQ", "微信": "微信"}


def _looks_like_ident(kind, v, loose=False):
    """按格式替换时的「这一格像不像这种东西」。

    ⚠ 判据**跟 core/layout.py 共用一套** —— 格式识别说某位置是邮箱、
      脱敏这边却因为尺子不同不换它，两边就打架了。
      特征标记优先：`@` 一定是邮箱；11 位 1[3-9] 开头一定是手机。

    `loose=True`：**研究员已经明确确认过这个位置是什么**的时候用。
    ⚠ 踩过：确认了「第 1 段是姓名」，可 `_looks_like_ident("姓名", "晓晓")` 还是 False
      （姓名判据要求以姓氏表开头）—— 于是"我确认了、它还是不换"。人既然已经指明，
      这一格就该按他说的处理，只剩"是不是空/是不是占位符"这种最低限度的检查。
    """
    v = (v or "").strip()
    if not v:
        return False
    if re.fullmatch(r"\[\S+\]", v):          # 已经是占位符了
        return False
    if loose:
        if kind == "手机":
            return bool(re.fullmatch(r"[\d\s\-%s]{7,20}" % _PHONE_SEP, v))
        if kind == "邮箱":
            return "@" in v
        return bool(re.fullmatch(r"[^\s]{2,30}", v))
    if "@" in v:
        return kind == "邮箱" and bool(re.fullmatch(r"[\w.+-]+@[\w.-]+\.\w+", v))
    if re.fullmatch(r"1[3-9]\d{9}", v):
        return kind == "手机"
    if kind in ("手机", "邮箱"):
        return False
    if kind == "姓名":
        return bool(re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", v))
    if kind == "QQ":
        # 5–9 位（10 位纯数字归学号，见 core/layout.py 的统一口径）
        return bool(re.fullmatch(r"\d{5,9}", v))
    if kind == "微信":
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{4,19}", v))
    if kind == "学号":
        return bool(re.fullmatch(r"[A-Za-z0-9\-]{4,20}", v))
    return False


_SUGGEST_CODES = {}          # 值 → 已经发过的占位。同一个值永远同一个号（跑一次内有效）
_SUGGEST_MAX = [0]           # 已经发到第几号


def _suggest_code(value):
    """给一个值配一个 `[代号N]` 占位。

    ⚠ **必须整个 run 共用一个号池**：
      第一版是每条提醒各自从 `[代号1]` 开始发，于是「点两条选项」会让两个不同的东西
      共用 `[代号1]` —— 跟之前那个「两个人被编成同一个号」是同一类错，只是藏在选项里。
      同一个值反复出现（比如同一个 QQ 号在两行里）也给同一个号。
    """
    v = str(value or "")
    if v in _SUGGEST_CODES:
        return _SUGGEST_CODES[v]
    _SUGGEST_MAX[0] += 1
    ph = "[代号%d]" % _SUGGEST_MAX[0]
    _SUGGEST_CODES[v] = ph
    return ph


def suggest_for(kind, value, code_used=None):
    """给一条提醒配「可以直接点的选项」。

    研究员的原话：「在提示处增加选项与自定义填写（要求用户按规定格式输出，必须带有 =），
    然后把用户的填写或选择直接转到自定义替换」。

    ⚠ 更重要的是他后来的那句：「选项和我想的不一样，比如她疑惑于是 qq 还是电话，
      但是选项却是【直接替换为代号 x】，有点割裂」——
      **选项必须是「对那个问题的回答」，不是"换个代号"这种答非所问。**
      所以他问"是手机还是 QQ"，选项就该是「是手机」「是 QQ」。
      选了之后程序按他的判断处理（`!这是手机 131...` 这种指令行会存进 脱敏格式.json）。
    """
    out = []

    if kind == "数字歧义":
        out.append({"label": "这是手机号 → 按手机处理", "src": value, "dst": "",
                    "line": "!这是手机 %s = " % value,
                    "hint": "按你的判断把它当手机号换成 [手机N]"})
        out.append({"label": "这是 QQ/微信号 → 按那个处理", "src": value, "dst": "",
                    "line": "!这是QQ %s = " % value,
                    "hint": "它会换成 [QQN] 而不是 [手机N]"})
        out.append({"label": "两边都不是 → 不用管它（别再问我）", "src": value, "dst": "",
                    "line": "!不用管 %s = " % value,
                    "hint": "原样留着，也不再拿它来提醒你。"
                            "但程序自己的规则要是认得它（比如 11 位 1 开头的手机号），它照旧会被换掉 —— "
                            "要**连换都不换**就得手动改产物"})
        return out

    if kind == "写法变体":
        line = _norm_hint(value)               # 例如 `130-1234-5678 = 13012345678`
        if line:
            out.append({"label": "换成标准写法", "src": value,
                        "dst": line.split("=", 1)[1].strip(), "line": line,
                        "hint": "以后这个写法就认得出来"})
        ph = _suggest_code(value)
        out.append({"label": "不换写法，直接换成 %s" % ph, "src": value, "dst": ph,
                    "line": "%s = %s" % (value, ph),
                    "hint": "当标识符处理掉"})
        return out

    if kind in ("没认出来", "地名同形"):
        ph = _suggest_code(value)
        out.append({"label": "换成 %s" % ph, "src": value, "dst": ph,
                    "line": "%s = %s" % (value, ph),
                    "hint": "把它当标识符处理掉"})
        if kind == "地名同形":
            out.append({"label": "这是人名，不是地名", "src": value, "dst": ph,
                        "line": "%s = %s" % (value, ph),
                        "hint": "程序按地名判成不处理，这里改成人名"})
            out.append({"label": "确实是地名，不用管", "src": "", "dst": "",
                        "line": "", "hint": "不用加规则，程序本来就没换它"})
    return out


def _pick_unknown_words(phrase, cap=8):
    """把「这些词没被认出来」那句话里的**词**挑出来 —— 只挑像名字/账号的那些。

    ⚠ 这里踩过两个坑：
      1. 格式说明按"整段"报没认出来的东西，一段可能是一整条记录
         （`陈云 男 14658167618 恋爱中`）。原来直接把整段当成一个"词"给选项，
         点一下就会把**整条记录**换成一个代号 —— 把资料毁了。
         （研究员看到的正是这个：「他提醒的部分和他已经处理了的部分有重合」，
          因为那条记录里的手机号早就被换掉了，剩下这个"词"已经不存在了。）
      2. 把整段按空格切开之后，`恋爱中`『已分手』这种**字段值**也会混进来当候选。
         判据收紧成：中文词必须**以姓氏表里的姓开头**才算像人名（`晓晓`『广东莞』过，
         `恋爱中`『已分手』不过）；账号只认字母数字下划线那种。
    """
    import core.layout as _L
    cands = []
    for w in re.split(r"[、,，;；\s]+", phrase or ""):
        w = w.strip().strip("「」`\"'（）()。：:")
        if not w or len(w) < 2 or len(w) > 30:
            continue
        if re.search(r"\s", w):                       # 带空格 = 不是词，是整条记录
            continue
        if re.fullmatch(r"\[\S+\]", w):               # 已经是占位符了
            continue
        if any(_looks_like_ident(k, w) for k in ("手机", "邮箱", "QQ", "微信", "学号")):
            continue
        if re.fullmatch(r"\d+", w):                   # 纯数字让数字规则自己管
            continue
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", w):
            # ⚠ 这里**必须**严格：只要是"绝不是人名"的字段值就排除掉，否则选项里会出现
            #   『单身 = [代号3]』这种荒唐东西（把字段值换成代号 = 毁数据）。
            #   在**格式说明**那边可以宽（漏报一句不致命），在**给选项**这边必须严防误伤。
            if w in _L.NOT_NAME_WORDS or w in _L.NOT_IDENT_NOISE:
                continue
            cands.append(w)
        elif re.fullmatch(r"[A-Za-z0-9_\-\.]{4,30}", w):
            cands.append(w)
    return list(dict.fromkeys(cands))[:cap]


def _norm_hint(v):
    """给「写法变体」配一条归一化规则：全角→半角、去掉手机号里的分隔符。"""
    v = (v or "").strip()
    fixed = v
    # 全角数字 → 半角
    fixed = fixed.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    # 手机号里的 空格 / 横线 去掉
    m = re.fullmatch(r"(1[3-9]\d)[\s\-]?(\d{4})[\s\-]?(\d{4})", fixed)
    if m:
        fixed = m.group(1) + m.group(2) + m.group(3)
    if fixed != v:
        return "%s = %s" % (v, fixed)
    return ""


_KIND_CN = {"手机": "手机号", "学号": "学号", "姓名": "姓名", "QQ": "QQ 号",
            "微信": "微信号", "邮箱": "邮箱", "编号": "学号/工号"}


def _segment_confirm_options(msg):
    """给「一行里第 N 段拿不准 / 不是标识符」这种提醒配**能点的选项**。

    研究员的原话：「我想要告诉她是手机，但是每一行原文都不一样我怎么填呢，
    同时也没有选项给我直接告诉她是手机」——
    这句提醒以前只说了现象，一个能点的东西都没有，等于把活全推回给人。

    做法：确认的是**段位**，不是某一个值 —— 段落语义在整份材料里是统一的。
    点一下写下 `!第3段是手机`，整份材料的第 3 段都按手机处理（不用逐行填）。
    `seen` 里出现过的类别就是候选；一个都没认出来的段，给"这几类都不是"。
    """
    m = re.search(r"第\s*(\d+)\s*段", msg or "")
    if not m:
        return []
    pos = m.group(1)
    out = []
    seen = re.search(r"这里出现过\s*([^。（]+)", msg or "")
    cands = []
    for w in re.split(r"[、,，\s]+", seen.group(1) if seen else ""):
        w = w.strip()
        if w in _KIND_CN:
            cands.append(w)
    if not cands:
        # ⚠ 「这一段一个标识符都没认出来」时**不能只给"不用管"** ——
        #   研究员要的正是这种时候能说一句"它其实是手机/微信号"。
        #   踩过：只给"这几类都不是"，等于把人堵死（「我想要告诉她是手机…也没有选项」）。
        cands = ["手机", "微信", "学号", "QQ"]
    for k in dict.fromkeys(cands):
        out.append({"label": "第 %s 段是%s" % (pos, _KIND_CN[k]),
                    "src": "", "dst": "", "pos": int(pos), "kind": k,
                    "line": "!第%s段是%s" % (pos, k),
                    "hint": "整份材料的第 %s 段都按%s处理（只说一次，不用逐行填）"
                            % (pos, _KIND_CN[k])})
    out.append({"label": "第 %s 段不是标识符，别管它" % pos,
                "src": "", "dst": "", "pos": int(pos), "kind": "",
                "line": "!第%s段不用管" % pos,
                "hint": "这一段是性别、状态这类东西，整份材料都不用处理它"})
    # ⚠ 「一列里只有一部分是标识符」的出路（研究员问的：
    #   「如果有些行中是有用信息，有些不是标识符又怎么办呢」）——
    #   段位判断只管整列，行级的零头用普通自定义替换点掉，这里把用法写清楚，
    #   不然人只能猜（他这次就是卡在这儿来找我的）。
    out.append({"label": "只有一部分行要处理 → 用「原文 = 替换为」逐行点",
                "src": "", "dst": "", "line": "",
                "hint": "第 %s 段里是标识符的那几行，把那个值本身写进「自定义替换」"
                        "（`具体那个值 = [代号N]`）；不是标识符的行保持原样，程序不会动它"
                        % pos})
    return out


def looks_like_but_missed(raw, already=()):
    """找「一眼看着像标识符、但规则没处理」的东西。

    这是压测抓出来的四类漏网（都跑在 raw 上，替换之后就找不到了）：
      1. 手机带分隔符：`130-1234-5678`、`130 1234 5678`
      2. 全角数字手机号：`１５５００００２２２２`（从输入法粘出来就这样）
      3. 微信号不是字母开头：`1234567890`、`_yujia_88`
      4. 11 位里混了全角/分隔符的其它形态

    ⚠ `already`：**这次已经被处理掉的**原文（比如手机号规则已经放宽、能认带分隔符的了）。
      不排除掉的话，程序会一边说"这个我换了"，一边又说"这个我看着像但没处理" ——
      研究员看到的正是这种自相矛盾（他报的第 3 条）。

    返回 [{"kind": 类别, "value": 原文, "norm": 标准写法}]。
    """
    out = []
    seen = set()
    done = set()
    for v in (already or ()):
        done.add(_norm_phone_digits(v))
        done.add(str(v))

    def add(kind, val, norm=""):
        if not val or val in seen:
            return
        if _norm_phone_digits(val) in done or val in done:
            return
        seen.add(val)
        out.append({"kind": kind, "value": val, "norm": norm})

    # 1. 手机带分隔符
    for m in re.finditer(r"(?<!\d)(1[3-9]\d)[\s\-](\d{4})[\s\-](\d{4})(?!\d)", raw or ""):
        v = m.group(0)
        add("手机带分隔符", v, m.group(1) + m.group(2) + m.group(3))
    # 2. 全角数字（连着 8 位以上就值得看一眼）
    for m in re.finditer(r"[０-９]{8,}", raw or ""):
        v = m.group(0)
        add("全角数字", v, v.translate(_FULLWIDTH_DIGITS))
    # 3. 微信号/QQ 那一栏写的不是字母开头
    for m in re.finditer(r"(?i)(?:微信|wechat|wx)\s*(?:号|ID)?\s*(?:是|为|[:：])?\s*([^\s,，;；、]{5,20})",
                         raw or ""):
        v = m.group(1).strip()
        if v and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{4,19}", v):
            add("微信/QQ 号写法", v, "")
    return out


def _read(path):
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(), enc
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(), "utf-8(容错)"


def _doc_pos(raw, value):
    """一个值在原文里第一次出现的位置（找不到给一个很大的数，排在最后）。

    用来实现研究员拍板的那条：「**编号要按文档出现顺序发**」。
    他原话：「我就是很担心顺序这个东西，怕用户需要自己改的时候不知道这是几号，
    又担心遗漏或者多编了一行什么的导致顺序大乱」——
    所以编号必须是**一眼看着就对的那一版**：从文档头往下数，1、2、3…
    """
    i = (raw or "").find(value)
    return i if i >= 0 else 10 ** 9


def _row_of(raw, value):
    """这个值在原文的第几行（1 起），找不到返回 0。

    ⚠ 这**不是** `_doc_pos`（那是字符位置，用来排序）。「按序号编码」这一档用的就是它：
    研究员要的第二套编码方式 ——「如果没有序号，我们就按行数来默认添加一个前置的序号」。
    """
    i = (raw or "").find(value)
    return 0 if i < 0 else raw.count("\n", 0, i) + 1


def _line_of(raw, value):
    """这个值在原文的第几行（1 起）。给对照表、跳转定位用。"""
    return _row_of(raw, value)


def _first_line_in(msg, raw):
    """一条提醒里说到了原文的哪些内容？拿**第一个能在原文里找到的**内容的行号。

    用来给「看原文」按钮定位 —— 研究员提的：「自己翻原文档一行行找太要命了」。
    找不着就返回 0（界面那边就当"打开原文、不定位"，而不是跳到一个瞎猜的行）。
    """
    # 提醒里被引号/括号包起来的东西最可能是原文片段
    for m in re.finditer(r"[「`『]([^」`』]{2,40})[」`』]|（([^）]{2,40})）", msg or ""):
        cand = (m.group(1) or m.group(2) or "").strip()
        if not cand or "第几" in cand or "段" == cand:
            continue
        ln = _row_of(raw, cand)
        if ln:
            return ln
    return 0


def _user_seqs(raw, col_ref):
    """从原文里把**用户自己的序号**读出来（他材料里本来就有的那一列编号）。

    研究员要的第二套编码方式：「如果用户提供了序号，就把电话和 QQ 都按前面的序号匹配」——
    他自己的材料里往往已经有一列编号（`R07`、`01`、`受访者3`），
    脱敏后如果占位符还能对上那个号，他回头查原始记录就一步到位。
    """
    out = {}
    if not col_ref:
        return out
    ref = str(col_ref).strip()
    lines = (raw or "").split("\n")
    # 「第 N 段 / 第 N 列」：按位置取那一格
    m = re.match(r"^第\s*(\d+)\s*(?:段|列|格|栏)?$", ref)
    if m:
        want = int(m.group(1))
        for ln in lines:
            if not ln.strip():
                continue
            cells = re.split(r"[\t,，|]|\s{1,}", ln.strip())
            cells = [c for c in cells if c]
            if len(cells) >= want and cells[want - 1].strip():
                seq = cells[want - 1].strip().strip("：:")
                if seq and not _looks_like_ident("手机", seq):
                    out[seq] = seq
        # 上面只是把候选收进来；真正"哪个值配哪个号"在调用处按行算，
        # 所以这里返回的是**整行 → 序号**的映射，交给 _seq_for_value 用。
        return {"__by_col__": want}
    # 否则当**表头名**：认「序号/编号/ID/受访者编号…」那一列
    head_words = ("序号", "编号", "id", "ID", "序", "no", "No", "NO")
    hit_col = 0
    for ln in lines[:5]:
        cells = [c.strip() for c in re.split(r"[\t,，|]", ln) if c.strip()]
        if len(cells) < 2:
            continue
        for i, c in enumerate(cells):
            if any(w in c for w in head_words) or c.lower() in ("id", "no"):
                hit_col = i + 1
                break
        if hit_col:
            break
    return {"__by_col__": hit_col} if hit_col else out


def _seq_by_col(raw, value, col):
    """值所在的**那一行**的第 `col` 格 —— 就是它的序号（用户提供的那种写法）。"""
    if not col:
        return ""
    for ln in (raw or "").split("\n"):
        if not ln.strip() or value not in ln:
            continue
        cells = [c for c in re.split(r"[\t,，|]|\s{1,}", ln.strip()) if c]
        if len(cells) >= col:
            return cells[col - 1].strip().strip("：:")
    return ""


# 会被重新编号的占位符前缀。`代号`『保留』是自定义/确认走的号，也一起排进去，
# 免得它们看起来像另一套体系。
_RENUM_RE = r"\[(%s)(\d+)\]" % "|".join(
    re.escape(p) for p in sorted(set(_PREFIX.values()) | {"代号", "保留"}, key=len, reverse=True))


def _renumber(text, hits, all_map, raw, numbering="order", seq_col_ref=""):
    """把所有 `[前缀N]` **按它们在原文里第一次出现的位置**重新编号。

    为什么不在一开始就按顺序发：发号是分好几轮的（直接标识符 → 姓名 → 表格 → 按格式），
    每一轮只看得到自己那一轮的文本状态 —— 「认出来就发号」必然跨通道乱序
    （实测：`晓晓` 拿到 `[姓名18]`，可它在文档里排第 2）。
    所以做法是：**先照旧发号，全部处理完之后统一重排一次**。
    这样每一轮的判据（谁更特异谁先换）完全不受影响，只有编号变成人读的那种。

    `numbering`（研究员拍板的第二套编码方式）：
      · `"order"`（默认）—— 按出现顺序发 `[姓名1] [姓名2]`…
      · `"seq"`  —— **按序号**：有用户提供的序号列就用它（`[姓名R07]`），
                    没有就用**行号**（`[姓名#5]`，原文第 5 行）。
                    「如果用户提供了序号，就把电话和 QQ 都按前面的序号匹配；
                     如果没有序号，我们就按行数来默认添加一个前置的序号」——他的原话。
    """
    if not text:
        return text, hits, all_map, ""
    pat = re.compile(_RENUM_RE)
    seen = {}                       # (前缀, 旧号) → (那个值的原文, 它在原文里第一次出现的位置)
    for h in hits:
        m = re.fullmatch(_RENUM_RE, h[2] or "")
        if not m:
            continue
        seen[(m.group(1), m.group(2))] = (h[1], _doc_pos(raw, h[1]))
    if not seen:
        return text, hits, all_map, ""

    if numbering == "seq":
        # 用户提供序号列 → 用它；没提供 → 用行号（他说的"默认添加一个前置的序号"）
        col = 0
        if seq_col_ref:
            info = _user_seqs(raw, seq_col_ref)
            col = int(info.get("__by_col__") or 0)
        seq_of, used = {}, {}
        for (prefix, old), (orig, _pos) in sorted(
                seen.items(), key=lambda kv: (kv[1][1], kv[0][0], int(kv[0][1]))):
            seq = _seq_by_col(raw, orig, col) if col else ""
            if not seq:
                # 没序号列 → 用**行号**当序号，并且加 `#` 前缀。
                # ⚠ 加 `#` 是为了和"按出现顺序"的 `[姓名1]` 一眼分得开 ——
                #   不加的话 `[姓名1]` 到底是"第 1 个"还是"第 1 行"，人得回去猜。
                seq = "#" + str(_row_of(raw, orig))
            seq = "".join(ch for ch in str(seq) if ch not in "[]")
            key = (prefix, seq)
            used[key] = used.get(key, 0) + 1
            # 同一条记录里同一种东西出现两次（比如"备用号"那一格）→ 加 a/b 后缀，别撞号
            suffix = "" if used[key] == 1 else chr(ord("a") + used[key] - 2)
            seq_of[(prefix, old)] = "[%s%s%s]" % (prefix, seq, suffix)
        mapping = dict((("[%s%s]" % (p, o)), v) for (p, o), v in seq_of.items())
        note = ("按你的设置：编号用%s（%s）"
                % ("原文里的序号列「%s」" % seq_col_ref if col else "原文行号",
                   "例如 [姓名%s]" % (seq_of.get(next(iter(seq_of))) if seq_of else "#5")))
        text = pat.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)
        for h in hits:
            h[2] = mapping.get(h[2], h[2])
        all_map = dict((k, mapping.get(v, v)) for k, v in all_map.items())
        return text, hits, all_map, note

    order = sorted(seen.items(), key=lambda kv: (kv[1][1], kv[0][0], int(kv[0][1])))
    counter, mapping = {}, {}
    for (prefix, old), _v in order:
        counter[prefix] = counter.get(prefix, 0) + 1
        mapping["[%s%s]" % (prefix, old)] = "[%s%d]" % (prefix, counter[prefix])

    # ⚠ 必须**一次性扫全文替换**（re.sub + 查表）。逐个 replace 会在交换时踩踏：
    #   `[手机1]→[手机2]` 之后，再把 `[手机2]→[手机1]` 就把刚改好的又改回去了。
    text = pat.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)
    for h in hits:
        h[2] = mapping.get(h[2], h[2])
    all_map = dict((k, mapping.get(v, v)) for k, v in all_map.items())
    return text, hits, all_map, ""


def run(ctx):
    file_rel = (ctx.get("file") or "").strip().strip('"')
    if not file_rel:
        raise ValueError("请先选一个要脱敏的文件")
    path = file_rel if os.path.isabs(file_rel) else ctx.path(file_rel)
    if not os.path.exists(path):
        raise ValueError("找不到文件：%s" % path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in TEXT_EXT:
        ctx.log("提醒：%s 不在常见文本格式里，还是按文本读（二进制文件别用这个）" % ext, "warn")

    raw, enc = _read(path)
    ctx.log("读入 %s（%d 字，编码 %s）" % (os.path.basename(path), len(raw), enc))
    # 歧义检查要在原文上做：替换之后上下文就没了
    ambig = ambiguous_numbers(raw)
    # 「编号对照表」是要研究员自己勾的（它本身敏感，默认不生成）。
    # ⚠ 提醒里说"打开对照表"之前必须先知道它这次到底有没有 —— 否则就是让人去找不存在的文件。
    _want_mapping = ctx.get("keep_mapping") or []
    if isinstance(_want_mapping, str):
        _want_mapping = [_want_mapping]
    _want_mapping = "mapping" in _want_mapping

    # ⚠ 二进制文件（.xlsx / .docx / .pdf）按文本读会变成一堆乱码，
    #   而脱敏"成功"了、替换 0 处、输出一个更大的乱码文件 —— **界面看不出哪里不对**。
    #   实测过：一份 12 人的 xlsx 信息表丢进来，「替换 0 处」，然后你拿着那个文件
    #   以为已经脱敏了。所以这里要**拒绝**，并告诉他怎么转。
    IMG = (".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".bmp", ".gif", ".tif", ".tiff")
    n_nul = raw.count("\x00")
    if ext in IMG:
        raise ValueError(
            "这是一张**图片**（%s）。图片里没有文字层，工作台也**故意不接 OCR** ——\n"
            "一是那要装几百 MB 的东西（工作台现在是零依赖、拷走就能跑）；\n"
            "二是**更重要的**：手机截图里就是受访者的姓名手机号，为了读它把整张图"
            "发给云端，跟「先过 🔒 再分析」是矛盾的。\n"
            "怎么办（一步）：在手机上打开这张截图 → 长按选中文字 → 「提取文字」/「识屏」\n"
            "→ 全选复制 → 粘进记事本或 Word → 另存为 .txt 或 .csv → 再把那个文件丢进来。\n"
            "手机自带的识别对中文截屏通常最准，而且全程在本机，图不用上传。" % (ext,))
    if ext in (".xlsx", ".xlsm", ".docx", ".pptx", ".pdf", ".sav", ".zip") or n_nul > 0:
        raise ValueError(
            "这个文件是**二进制格式**（%s），不能直接脱敏 —— 按文本读出来只会是一堆乱码，"
            "替换 0 处，而你还以为处理好了。\n"
            "怎么办：用 Excel 打开，另存为 **CSV UTF-8（逗号分隔）** 或直接另存为 .txt，"
            "再把那个文件丢进来。\n"
            "（④ 预处理和 ⑤ 统计那两步是可以直接读 .xlsx 的，但 🔒 只处理文本。）" % (ext or "没有扩展名"))

    text = raw
    hits = []          # [类型, 原文, 替换为, 次数]
    all_map = {}       # 原文 → 替换为

    # ---------- 0. 自定义替换：**必须第一个跑** ----------
    # ⚠ 这条顺序踩过一次（研究员报的"我自定义填写之后输出没效果"）：
    #   自定义规则原来排在最后，等它跑的时候，那个数字**已经被前面的步骤换成 `[手机1]` 了**，
    #   它去找原文自然找不到，于是"填了没反应"。
    #   自定义是研究员**明确指定**的，优先级最高 —— 它说换什么就换什么，再轮到自动规则。
    #
    #   两种写法：
    #     `原文 = 替换为`        → 直接换（比如 `晓晓 = [受访者A]`）
    #     `原文 = `（右边空）      → **把那段原文删掉**（用来清掉碍事的前缀，
    #                              比如 `QQ 13177778888` 去掉 `QQ `，让数字自己暴露出来被当手机识别）
    rules = (ctx.get("extra_rules") or "").strip()
    custom_n = 0
    # 「确认判断」类指令：`!这是手机 131...` / `!这是QQ 131...` / `!不用管 131...`
    # 它们是**研究员对"是手机还是QQ"这个问题的回答**，不是替换规则。
    # 存下来，在下一步按他的判断处理 —— 光记一笔不给效果，就是"选项答非所问"的另一种表现。
    _confirm_kind = {}
    _confirm_plain = set()
    _col_kinds = {}          # 段位 → 类别（`!第3段是手机`），整份材料照办
    _bad_rules = []          # 看不懂的 `!` 指令 —— **必须报出来**，不能默默跳过
    # 自定义发的号要跟后面的自动规则共用号池，不然会撞号
    custom_rep = Replacer("代号", start=0)
    if rules:
        for line in rules.splitlines():
            line = line.strip()
            if not line:
                continue
            # ⚠ **`!` 指令行没有 `=` 也是合法的**（`!第3段是手机`）。
            #   原来第一句就是 `if "=" not in line: continue` —— 把这类指令整个扔掉，
            #   于是界面允许你加、后端当没看见（"我确认了它不动"的又一个来源）。
            if line.startswith("!"):
                src, dst = line, ""
            elif "=" in line:
                src, dst = line.split("=", 1)
                src, dst = src.strip(), dst.strip()
            else:
                continue
            if src.startswith("!"):
                body = src[1:].strip()
                # ⚠ 带上 `dst`：界面上手改过的指令可能长成 `!这是QQ X = `。这里把它拼回来当整体识别。
                if dst:
                    body = (body + " " + dst).strip()
                # `!第3段是手机` / `!第3段不用管`：**段位判断**，一次确认整篇照办。
                # 研究员要的正是这个 —— 「每一行原文都不一样我怎么填呢」。
                mseg = re.match(r"^第\s*(\d+)\s*段\s*(?:是|为)\s*([^\s=]+)$", body)
                if mseg and mseg.group(2) in _PREFIX:
                    _col_kinds[mseg.group(1)] = mseg.group(2)
                    ctx.log("按你的确认：整份材料的第 %s 段是%s" % (mseg.group(1), mseg.group(2)))
                    continue
                mseg2 = re.match(r"^第\s*(\d+)\s*段\s*(?:不用管|不是标识符|别管)$", body)
                if mseg2:
                    _col_kinds[mseg2.group(1)] = ""
                    ctx.log("按你的确认：第 %s 段不是标识符，跳过" % mseg2.group(1))
                    continue
                if body.startswith(("保留", "不用管", "不管")):
                    v = re.sub(r"^(保留|不用管|不管)", "", body).strip().rstrip("=").strip()
                    if v:
                        _confirm_plain.add(v)
                        ctx.log("按你的确认：`%s` 两边都不是，原样保留、不再提醒" % v)
                        continue
                elif body.startswith("这是"):
                    kindword = body[2:].strip()
                    idx = kindword.find(" ")
                    v = kindword[idx + 1:].strip() if idx > 0 else ""
                    kindword = kindword[:idx].strip() if idx > 0 else kindword
                    kmap = {"手机": "手机", "手机号": "手机", "QQ": "QQ", "qq": "QQ",
                            "微信号": "微信", "微信": "微信", "邮箱": "邮箱", "学号": "学号"}
                    k = kmap.get(kindword)
                    v = v.rstrip("=").strip()
                    if v and k:
                        _confirm_kind[v] = k
                        ctx.log("按你的确认：`%s` 是%s" % (v, k))
                        continue
                # ⚠ 走到这里 = **以 `!` 开头、但谁都认不出来**。
                #   原来这里是"默默 continue"，于是界面上那条规则看着好好的、引擎当它不存在，
                #   研究员看到的现象就是"我选了，没效果"（他真踩了这个坑：旧页面把指令
                #   存成了 `!这是QQ X = `，匹配不上，一声不吭）。
                #   现在：**说出来**，别装没看见。
                ctx.log("⚠ 看不懂这条指令：「%s」—— 它被跳过了（没生效）。"
                        "正确写法：`!这是手机 13800001111`、`!这是QQ 13800001111`、"
                        "`!不用管 13800001111`、`!第3段是手机`、`!第3段不用管`" % line, "warn")
                _bad_rules.append(line)
                continue
            if not src:
                continue
            cnt = text.count(src)
            if cnt == 0:
                ctx.log("自定义规则「%s」在文本里没找到（是不是已经被自动规则换掉了？）" % src, "warn")
                continue
            if dst:
                text = text.replace(src, dst)
                hits.append(["自定义", src, dst, cnt, "直接标识符", "high"])
                all_map[src] = dst
            else:
                # 右边空 = 删掉这段原文（清前缀用）
                text = text.replace(src, "")
                hits.append(["自定义（清掉）", src, "（删掉）", cnt, "直接标识符", "high"])
                ctx.log("按自定义规则清掉 %d 处：%s" % (cnt, src))
            custom_n += cnt
        if custom_n:
            ctx.log("按自定义规则处理：%d 处（研究员指定的，优先于自动规则）" % custom_n)

    # 看不懂的 `!` 指令**必须变成提醒**，不能只躺在日志里 —— 研究员遇到的正是这个：
    # 界面上那条规则看着好好的、引擎当它不存在，他只能得出"我选了，没效果"（他真踩了）。
    if _bad_rules:
        ctx.alert("有 %d 条 `!` 指令看不懂，**被跳过了（没生效）**：%s"
                  % (len(_bad_rules), " ／ ".join(_bad_rules[:3])),
                  level="warn", kind="internal",
                  fix="`!` 开头的指令只有这几种写法：`!这是手机 13800001111`、"
                      "`!这是QQ 13800001111`、`!不用管 13800001111`、"
                      "`!第3段是手机`、`!第3段不用管`。不是这几种就改成 `原文 = 替换为`，"
                      "或者把它删掉。")

    # 「两边都不是，不用管它」：**什么都不做，而且不再拿它来烦人**。    #   ⚠ 原来这个选项是把值换成 `[保留1]` —— 那就等于"我让你别动，你偏给它编了个号"，
    #     反而在脱敏件里凭空造出一个占位符（研究员看到的输出就是这样）。
    #     它的意思其实是「这不是标识符，你不用报」，所以：文本不动 + 该值的提醒不再发。
    _confirm_plain = set(_confirm_plain)
    if _confirm_plain:
        ctx.log("按你的确认：%d 个值「两边都不是」—— 原样保留，也不再提醒" % len(_confirm_plain))
    if _confirm_kind:
        kind_rep = {}
        for v, k in _confirm_kind.items():
            if v and v in text:
                if k not in kind_rep:
                    kind_rep[k] = Replacer(_PREFIX.get(k, k), start=_max_used(text, _PREFIX.get(k, k)))
                ph = kind_rep[k].get(v)
                text = text.replace(v, ph)
                hits.append(["按你确认的（%s）" % k, v, ph, 1, "直接标识符", "high"])
                all_map[v] = ph
        if kind_rep:
            ctx.log("按你的确认，%d 个值按指定类别换掉了" % sum(r.count for r in kind_rep.values()))

    # ---------- 1. 直接标识符 ----------
    # ⚠ `_raw_handled` 收的是**命中的原文片段**（`130-1234-5678` 这种），
    #   不是归一化之后的写法 —— 后面判「哪些漏网其实已经处理过了」要用原文比。
    #   踩过：rep.map 的键已经归一化成 `13012345678`，拿它去比原文永远比不中，
    #   于是程序一边换了它、一边又说"我看着像但没处理"。
    _raw_handled = []
    for label, pat, prefix, conf, grp in DIRECT:
        before = _max_used(text, prefix)
        rep = Replacer(prefix, start=before)
        keyfn = _norm_phone_digits if prefix == "手机" else None

        def _collect(m, _k=keyfn, _g=grp, _out=_raw_handled):
            _out.append(m.group(_g) if _g else m.group(0))
        # 先扫一遍收原文，再正式替换（两次都用同一个 pattern，结果一致）
        for m in re.finditer(pat, text):
            _collect(m)
        text = re.sub(pat, _repl_fn(rep, grp, keyfn), text)
        for original, placeholder in rep.map.items():
            n = len(re.findall(re.escape(placeholder), text))
            hits.append([label, original, placeholder, n, "直接标识符", conf])
            all_map[original] = placeholder
        made = rep.count - before          # 这一轮**新发**了几个号（rep.count 是从 before 起算的）
        if made:
            ctx.log("替换 %s：%d 处" % (label, made))

    # ---------- 2. 上下文姓名 ----------
    name_rep = Replacer("姓名")
    # 第一遍：从上下文里「认出」这是人名；第二遍：全篇统一替换。
    # 分两步是因为人名一旦认出，后面那些不带上下文的写法（「张伟你好」）也该一起换掉。
    candidates = {}
    for idx, pat in enumerate(NAME_PATTERNS):
        contextual = (idx in CONTEXTUAL_IDX)   # 规则5/7：带「受访者/姓名」这种明确标记
        for m in re.finditer(pat, text, flags=re.M):
            nm = m.group(1)
            if len(nm) < 2:
                continue
            # ⚠ **先过这张否决表**：姓氏表里混着大量常用字（时/都/基/本/长/方/于/明/全…），
            #   所以「行首 + 冒号」这条规则会把**元信息标签**也当成说话人 ——
            #   实测：`时长：41 分钟` 抓出「时长」→ 脱敏稿变成 `[姓名4]：41 分钟`，
            #   而这一行本来是"访谈时长"的登记项，一个真名都没有。
            #   元信息标签被换成占位名，等于把资料改坏（比漏一个名字严重）。
            if nm in NOT_NAME_WORDS or nm in NOT_NAME_VALUES:
                continue
            # ⚠ 「有明确角色标记」时直接采信，**不要再用姓氏表二次否决** ——
            #   踩过一次严重的：转写稿写着「受访者：林小雨，女，…」，规则抓到了「林小雨」，
            #   却因为「林」不在姓氏表里被丢掉，脱敏稿里受访者的真名原样留着。
            #   姓氏表只能用来兜「没有标记」的场合（比如「张伟你好」）。
            if not contextual and nm[0] not in SURNAME:
                continue
            if nm[0] in SURNAME or contextual:
                candidates[nm] = candidates.get(nm, 0) + 1
    # 再加上「带联系方式的行里那个唯一的像姓名的词」——
    # 现场：`王芳 15912345678 微信 xxx`（名字后面接的是手机号，不是「男/女」），
    # 原来那条规则整行都够不着，20 个名字漏了 16 个。
    # ⚠ 必须传 **raw**（原文）而不是 text —— text 里手机号已经变成 `[手机1]`，
    #   这条规则的判据「这一行有联系方式」就再也认不出来了（踩过一次，白改）。
    #   同样再筛一道否决表：这条规则是"猜"出来的，最容易被常用字带偏。
    for nm in find_names_in_contact_lines(raw):
        if nm in NOT_NAME_WORDS or nm in NOT_NAME_VALUES:
            continue
        candidates[nm] = candidates.get(nm, 0) + 1
    for nm in sorted(candidates, key=lambda n: text.find(n)):   # 先按出场顺序定编号，读起来符合直觉
        name_rep.get(nm)
    for nm in sorted(candidates, key=len, reverse=True):        # 再长的先换，免得把短名切坏
        text = text.replace(nm, name_rep.get(nm))
    for original, placeholder in name_rep.map.items():
        n = len(re.findall(re.escape(placeholder), text))
        hits.append(["姓名（上下文）", original, placeholder, n, "直接标识符", "mid"])
        all_map[original] = placeholder
    if name_rep.count:
        ctx.log("替换上下文里的姓名：%d 个" % name_rep.count)

    # ---------- 2b. 表格式（认表头列，按列替换）----------
    # 实测踩到的：一份「受访者信息表」，姓名是**独立单元格** —— 那一列前面没有
    # 「姓名：」这种上下文，6 条姓名规则一条都不命中，于是 **12 个真名原样留着**；
    # 学号也一样（那些规则要「学号」这个词紧挨着数字）。
    # 表格是最常见的素材形态（招募名单 / 登记表 / 花名册），所以这里认表头、按列处理。
    lines, cells_todo = _find_table_cells(text)
    if cells_todo:
        # 同样要接着已用掉的最大号往下发（不然会跟上下文姓名撞号 → 合并身份）
        reps = {k: Replacer(p, start=_max_used(text, p))
                for k, p in (("姓名", "姓名"), ("学号", "编号"), ("手机", "手机"),
                             ("邮箱", "邮箱"), ("QQ", "QQ"), ("微信", "微信"))}
        by_kind = {}
        for row, col, kind, val in cells_todo:
            ph = reps[kind].get(val)
            _put_cell(lines, row, col, ph)
            by_kind.setdefault(kind, []).append((val, ph))
        text = "\n".join(lines)
        for kind, pairs in by_kind.items():
            for val, ph in pairs:
                hits.append(["%s（表格式·按列）" % kind, val, ph, 1, "直接标识符", "mid"])
                all_map[val] = ph
        ctx.log("按表头列替换：%d 处（姓名/学号这类独立成列的标识符）" % len(cells_todo))

    # ---------- 2c. JSON 里的 "姓名": "陈嘉怡" 这种 ----------
    # 结构化数据（自己写脚本导出的那份）也是独立取值，没有上下文标记。
    # 只在文件看起来像 JSON 的时候做（首字符是 { 或 [），别去猜别的文本。
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        jreps = {k: Replacer(p, start=_max_used(text, p))
                 for k, p in (("姓名", "姓名"), ("学号", "编号"), ("手机", "手机"),
                              ("邮箱", "邮箱"), ("QQ", "QQ"), ("微信", "微信"))}
        jhit = 0

        def _json_sub(m):
            nonlocal jhit
            key, val = m.group(1).strip(), m.group(3).strip()
            quote = m.group(2) or ""
            if not val:
                return m.group(0)
            kind = None
            for k, words in COL_KINDS:
                if any(w in key.lower() for w in words):
                    kind = k
                    break
            if not kind or not _looks_like(kind, val):
                return m.group(0)
            ph = jreps[kind].get(val)
            hits.append(["%s（JSON·按字段）" % kind, val, ph, 1, "直接标识符", "mid"])
            all_map[val] = ph
            jhit += 1
            return '%s: %s%s%s' % (m.group(1), quote, ph, quote)

        text = re.sub(r'"([^"\n]{1,14})"\s*:\s*("?)([^",}\n]{2,60})\2', _json_sub, text)
        if jhit:
            ctx.log("按 JSON 字段替换：%d 处" % jhit)

    # ---------- 2d. 「先看格式，再按格式换」----------
    # 这是研究员提的办法，比我原来那套硬猜好一个量级：
    #   「记事簿里我会习惯性用换行隔开不同对象，能不能先识别出格式，拿不准再问我，最后我确认？」
    # 做法：从前面几条里看出「一条记录怎么切、行内各位置是什么」，写成 脱敏格式.md 给人看，
    #      拿不准的地方作为提醒弹出来；能确定的位置直接按位置换（比正则可靠）。
    from core import layout as _layout
    lay = _layout.detect(raw, sample_n=3)
    # 你在表单里拍板的段位判断（`!第3段是手机`）要**盖过**自动识别 ——
    # 这正是研究员要的：「每一行原文都不一样我怎么填呢」，所以确认的是段位、不是值。
    if _col_kinds:
        # ⚠ 顺序别写反：`dict(a, **b)` 是 **b 覆盖 a**。
        #   原来写成 `dict(_col_kinds, **已有的)` —— 已有的（通常是空）把我的确认盖掉了，
        #   于是"我确认了、它当没看见"。必须让**研究员确认的赢**。
        _merged_cols = dict(lay.get("col_kinds") or {})
        _merged_cols.update(_col_kinds)
        lay["col_kinds"] = _merged_cols
    if lay.get("style") in ("line", "block", "unknown"):
        # ⚠ 连 `unknown` 也要试一次：材料只有两三行时 `split_records` 会判成"看不出切法"，
        #   但只要你确认过段位（`!第3段是手机`），就能按"一行里的第几段"处理。
        #   不试的话，人确认了也没用 —— 他就是为此来问的。
        lhit = _apply_layout(text, lay, raw, hits, all_map, ctx)
        if lhit:
            text = lhit
        try:
            # ⚠ 路径必须**带 output/** —— ctx.save_text 是按给的相对路径直接写，
            #   不是自动放进 output/。漏了前缀的话，md 落在项目根目录、
            #   而提醒里写的是 output/脱敏格式.md，人一点就"文件不存在"（踩过）。
            #   给人看的那份写进 output/（跟别的产物一样，界面能直接打开）。
            lay_rel = "output/" + _layout.REL
            ctx.save_text(lay_rel, _layout.to_markdown(lay, os.path.basename(path)))
            # ⚠ 这份说明原来叫 `output/脱敏格式.md`，改名成 `格式说明.md` 了
            #   （旧名字看着像"脱敏产物本身"，研究员说"输出产物请输出一个与原文件一样格式的"）。
            #   老的机器上会留着旧名字那份，两份说明并排摆着最容易被当成两个东西 —— 顺手清掉。
            stale = ctx.path("output/脱敏格式.md")
            try:
                if os.path.exists(stale):
                    os.remove(stale)
                    ctx.log("清掉了改名前的旧说明：output/脱敏格式.md（现在是 output/%s）"
                            % _layout.REL, "info")
            except OSError:
                pass
            # 给程序读的那份放项目根目录（它是个中间状态，不该混进「产物」里）
            root = os.path.dirname(os.path.dirname(ctx.path("output/x")))
            if root and os.path.isdir(root):
                _layout.save_root(root, lay)
        except Exception as e:
            ctx.log("格式说明没写出去：%s" % e, "warn")
        ctx.log("看格式：%s（%d 条记录）%s" % (
            {"line": "一行一条", "block": "空行分隔"}.get(lay["style"]),
            lay.get("records", 0),
            "；有 %d 处要你拍板" % len(lay.get("uncertain") or [])
            if lay.get("uncertain") else "；没看出问题"))
        # ⚠ 你说过「第 N 段不用管」的段，别再列进「拿不准」问第二遍 ——
        #   点了选项、跑完还在问，看着就像程序没记住（这一轮踩的全是这类"没效果"）。
        #   **确认过"是什么"的段也一样**：都拍过板了，还问就是没完没了。
        _skip_cols = set()
        for _k, _v in (lay.get("col_kinds") or {}).items():
            if str(_k).strip().isdigit():
                _skip_cols.add(int(_k))
        for u in (lay.get("uncertain") or [])[:8]:
            _sm = re.search(r"第\s*(\d+)\s*段", u)
            if _sm and int(_sm.group(1)) in _skip_cols:
                continue
            # 这条提醒说的是原文的哪一行？—— 有具体值就拿它的行号，
            # 段位类的拿"第一段落在哪一行"（`_apply_layout` 记在 columns[].at 里）。
            _u_ln = _first_line_in(u, raw)
            # 段位类的提醒：拿「这一段的第一个例子在哪一行」（layout 记在 columns[].at 里），
            # 比在提醒文本里瞎找可靠。
            if not _u_ln and _sm:
                for _c in (lay.get("columns") or []):
                    if _c.get("pos") == int(_sm.group(1)) and _c.get("at"):
                        _u_ln = int(_c["at"])
                        break
            opts = []
            # 从这句话里把「没被认出来的词」挑出来，一个词一个选项
            m = re.search(r"没被认出来\*\*：([^。]+)", u)
            if m:
                for w in _pick_unknown_words(m.group(1)):
                    opts += suggest_for("没认出来", w)
                    if not _u_ln:
                        _u_ln = _line_of(raw, w)
            opts += _segment_confirm_options(u)
            ctx.alert(u, level="warn", kind="internal", options=opts,
                      line=_u_ln, locate={"file": file_rel, "line": _u_ln},
                      fix="点下面的选项（**段位判断只说一次**，整份材料都照办），"
                          "或者在框里按 `原文 = 替换为` 自己写一条。"
                          "看完整说明：output/格式说明.md",
                      rel="output/" + _layout.REL)
    elif lay.get("note"):
        ctx.log("格式识别：%s" % lay["note"], "info")

    # ---------- 3. （自定义替换已提到最前面，见第 0 段）----------
    # ⚠ 这一段原来在这儿。挪走的原因：自定义规则排最后时，等它跑的时候，
    #   原文已经被自动规则换成了 `[手机1]`，它找不到 → 研究员"填了没效果"（他报的）。
    #   自定义是研究员**明确指定**的，必须优先于自动规则。

    # ---------- 4. 准标识符：只提示 ----------
    quasi_rows = []
    for label, pat in QUASI:
        found = re.findall(pat, text)
        found = [f if isinstance(f, str) else next((x for x in f if x), "") for f in found]
        found = [f for f in found if f]
        if not found:
            continue
        uniq = list(dict.fromkeys(found))
        quasi_rows.append([label, len(found), "、".join(uniq[:8]) + ("…" if len(uniq) > 8 else "")])
    for c in CITIES:
        if c in text:
            quasi_rows.append(["提到城市", text.count(c), c])
    if quasi_rows:
        ctx.log("提示：有 %d 类准标识符需要你判断（已列在报告里，**没有自动改**）" % len(quasi_rows))

    # ---------- 4b. 数字串有歧义：必须告诉人来核 ----------
    # 现场：`QQ 18900001111` —— 一个 11 位、以 1 开头的 QQ 号，
    # 光看数字跟手机号长得一模一样。程序**两边都占了号**（QQ 规则先跑、
    # 但如果那个位置没被 QQ 抓到，手机号规则就会把它当手机），
    # 所以这里不猜，直接把可疑的地方摆出来让研究员对一遍。
    if ambig:
        # ⚠ 提醒里原来直接写「打开 output/编号对照表.csv」—— 而对照表是**要勾「编号对照表」才生成**的，
        #   没勾的时候那句就是让人去找一个不存在的文件（研究员正好撞上这个）。
        #   对照表本身是敏感文件，默认不生成是对的；错的是提醒没看它到底有没有。
        for num, why, ln_no in ambig:
            # ⚠ 你**确认过的值**就别再问了 —— 包括"这是手机"「这是 QQ」这种已拍板的。
            #   踩过：点了「这是手机号 → 按手机处理」，输出确实变了（日志有"按你的确认"），
            #   但这条提醒照旧弹出来 —— 研究员看到的现象就是"我按了，它没反应"。
            if num in _confirm_plain or num in _confirm_kind:
                continue
            ctx.alert("「%s」可能有歧义（原文第 %d 行）：%s" % (num, ln_no, why),
                      level="warn", kind="internal",
                      options=suggest_for("数字歧义", num),
                      line=ln_no, locate={"file": file_rel, "line": ln_no},
                      fix=("想核对的话：`output/编号对照表.csv` 里写了这个号被归到哪一类；"
                           if _want_mapping else
                           "这次没生成 `output/编号对照表.csv`（🔒 表单里「编号对照表」没勾）—— "
                           "勾上再跑一次就能看到它归到哪一类；")
                          + "归错了就点下面的选项告诉我它到底是什么，或者在原文里写清楚"
                            "（比如写成「QQ：18900001111」）。")
        ctx.log("提示：%d 处数字串有歧义（可能是手机也可能是 QQ/微信号），已列在提醒里" % len(ambig))

    # ---------- 4c. 看着像标识符、却没被处理的 ----------
    # 压测抓出来的四类漏网（详见 looks_like_but_missed 的说明）。
    # 这类**不该只是提醒**：研究员看一眼就知道该不该换，所以配上「换成标准写法」的选项，
    # 点一下就并进「自定义替换」，下次按标准写法认得出来。
    # ⚠ 要告诉它「哪些原文这次已经处理过了」，否则会出现
    #   「我换了它」和「我看着像但没处理」两条互相打脸的提醒（研究员报的第 3 条）。
    _handled = list(_raw_handled) + [k for k in all_map if k]
    missed = [it for it in looks_like_but_missed(raw, _handled) if it["value"] not in _confirm_plain]
    for it in missed[:8]:
        opts = []
        if it["norm"]:
            opts.append({"label": "换成标准写法：%s" % it["norm"],
                         "line": "%s = %s" % (it["value"], it["norm"]),
                         "hint": "规则里加这一条，下次它就按标准写法处理（然后再被手机号规则换掉）"})
        opts.append({"label": "直接换成 %s" % _suggest_code(it["value"]),
                     "line": "%s = %s" % (it["value"], _suggest_code(it["value"])),
                     "hint": "不换写法，直接当标识符处理掉"})
        if it["kind"] == "微信/QQ 号写法":
            opts.append({"label": "这栏确实是微信号/QQ 号",
                         "line": "%s = %s" % (it["value"], _suggest_code(it["value"])),
                         "hint": "微信号不一定字母开头，程序不敢自己认；你说它是，就按标识符处理"})
        _ln = _line_of(raw, it["value"])
        ctx.alert("「%s」看着像标识符（%s），但**这次没被处理**（原文第 %s 行）"
                  % (it["value"], it["kind"], _ln or "?"),
                  level="warn", kind="internal", options=opts,
                  line=_ln, locate={"file": file_rel, "line": _ln},
                  fix="选一个（点了会并进「自定义替换」，再跑一次就生效），或者手动改产物。"
                      "同一件事的不同写法规则很难穷尽 —— 所以程序把「像但拿不准」的摆出来让你拍板，"
                      "而不是自己猜。")
    if missed:
        ctx.log("提示：%d 处「像标识符但没处理」，已给出选项" % len(missed))

    # ---------- 5. 写产物 ----------
    # ⚠ 先给 hits **去重**：规则是按「哪条规则命中」追加的，同一条规则里同一个值
    #   命中两次会留两行一模一样的（实测：`刘洋 男 13177778888 QQ 13177778888`
    #   的报告里出现两行 `手机号 | 13177778888 | [手机2]`，看着像程序自己重复劳动）。
    #   占位符不同 = 确实是两次不同的替换，不能合并。
    _merged = []
    _idx = {}
    for h in hits:
        key = (h[0], h[1], h[2], h[4])
        if key in _idx:
            _merged[_idx[key]][3] += h[3]
        else:
            _idx[key] = len(_merged)
            _merged.append(list(h))
    hits = _merged

    # ⚠ 编号统一重排，**按原文出现顺序**（研究员拍板的第 1 条）。
    #   必须在写产物之前、在报告之前 —— 后面所有地方都引用 hits 里的占位符。
    #   他后来补了第二套编码方式（按序号），也在这里分岔。
    text, hits, all_map, _num_note = _renumber(
        text, hits, all_map, raw,
        numbering=(ctx.get("numbering") or "order"),
        seq_col_ref=(ctx.get("seq_col") or ""))
    if _num_note:
        ctx.log(_num_note)

    # 对照表按**编号**排（而不是按规则先后），并从 1 连号 ——
    # 研究员担心的正是"顺序乱了、人自己改的时候不知道这是几号"。
    def _hit_sort_key(h):
        m = re.match(r"\[(\D+?)(\d+)\]$", h[2] or "")
        return (m.group(1), int(m.group(2))) if m else ("\uffff", 0)
    hits.sort(key=_hit_sort_key)

    base = os.path.splitext(os.path.basename(path))[0]
    out_name = (ctx.get("out_name") or "").strip() or ("脱敏_" + base + os.path.splitext(path)[1])
    if not out_name.lower().endswith(ext) and "." not in os.path.basename(out_name):
        out_name += os.path.splitext(path)[1]
    out_rel = "output/" + out_name
    ctx.save_text(out_rel, text)

    if _want_mapping and all_map:
        # 带上「原文第几行」：研究员担心"人自己改的时候不知道这是几号、怕顺序乱"——
        # 有了行号就能拿产物和原文逐行对，一眼看出有没有漏、有没有多编。
        rows = [["替换为", "原文", "类型", "原文第几行", "出现次数"]]
        for h in hits:
            rows.append([h[2], h[1], h[0], _line_of(raw, h[1]), h[3]])
        ctx.save_table("编号对照表.csv", rows[1:], rows[0])
        ctx.log("编号对照表 → output/编号对照表.csv（⚠ 这张表本身是敏感的）")

    # ---------- 6. 报告 ----------
    L = []
    L.append("# 去标识化报告\n")
    L.append("> 源文件：`%s`（%d 字，编码 %s）" % (file_rel, len(raw), enc))
    L.append("> 脱敏文件：`%s`" % out_rel)
    L.append("> 处理时间：%s\n" % time.strftime("%Y-%m-%d %H:%M"))

    total = sum(h[3] for h in hits)
    L.append("## 一、处理结果\n")
    L.append("- 共替换 **%d 处**，涉及 **%d 个不同的实体**" % (total, len(hits)))
    L.append("- 脱敏后文本 %d 字（原 %d 字）\n" % (len(text), len(raw)))

    if hits:
        L.append("| 类型 | 原文 | 替换为 | 出现次数 | 置信度 |")
        L.append("|---|---|---|---|---|")
        for h in hits:
            L.append("| %s | %s | %s | %d | %s |" % (h[0], h[1], h[2], h[3],
                                                      {"high": "高（确定）", "mid": "中（建议人工过一眼）"}.get(h[4], h[4])))
        L.append("")
        mid = [h for h in hits if h[4] == "mid"]
        if mid:
            L.append("⚠ 有 %d 处是**中等置信度**的替换，建议人工确认一下有没有误伤：%s\n" % (
                len(mid), "、".join(h[1] for h in mid[:10])))
    else:
        L.append("没有命中任何直接标识符。**但别就此放心**——见下面第三节的人工检查清单。\n")

    L.append("## 二、准标识符提示（**没有自动改**）\n")
    if quasi_rows:
        L.append("下面这些单独看不致命，但组合起来可能把一个人认出来。降不降粒度是研究决策：\n")
        L.append("| 类型 | 出现次数 | 内容 |")
        L.append("|---|---|---|")
        for r in quasi_rows:
            L.append("| %s | %d | %s |" % (r[0], r[1], r[2]))
        L.append("")
    else:
        L.append("没有发现明显的准标识符。\n")

    # ⚠ 报告里的表也要**滤掉你已经确认过的**：你按了「这是手机」，报告里还挂着
    #   "这个号可能是 QQ，请人工核一遍" —— 等于白按了（提醒列表那边已经修过一次，这是同一件事的第二个出口）。
    _ambig_left = [(n, w, li) for n, w, li in ambig
                   if n not in _confirm_plain and n not in _confirm_kind]
    if _ambig_left:
        L.append("## 二·补、数字串有歧义（**请人工核一遍**）\n")
        L.append("下面这些数字**只有一串数**，光看数字分不出是手机号还是 QQ 号/微信号。"
                 "程序按自己的规则归了类，**但可能归错**：\n")
        L.append("| 原文第几行 | 数字 | 为什么可疑 |")
        L.append("|---|---|---|")
        for num, why, li in _ambig_left:
            L.append("| %d | `%s` | %s |" % (li, num, why))
        L.append("\n怎么消掉它：把原文里的写法写清楚（`QQ：18900001111` 而不是 `QQ 18900001111`），"
                 "或者干脆分开两栏写；也可以在提醒里点一下选项，告诉我它到底是什么。再跑一次就不会有这条了。\n")
    elif ambig:
        L.append("## 二·补、数字串有歧义\n")
        L.append("原本有 %d 处数字看着可疑，**你已经逐个确认过了**，这里不再提示。\n"
                 % len(ambig))

    L.append("## 三、人工检查清单（程序做不到的部分）\n")
    L.append("1. **罕见特征组合**：「我们部门就我一个女生」+「在杭州」+「做游戏」——这三条凑起来可能就定位到人了")
    L.append("2. **上下文指代**：前面替换成 `[姓名1]`，后面又出现「我那个同事」——语义上还是能追到")
    L.append("3. **引语里的自曝**：受访者自己说出的产品名、项目名、时间点")
    L.append("4. **音频原声**：录音本身是直接标识符，转写稿脱敏了不代表音频能用")
    L.append("5. **图片/截图**：聊天记录截图、工牌照片——程序不管这些\n")

    L.append("## 四、存档提醒\n")
    L.append("- 编号对照表如果生成了，它是**敏感文件**：单独保管或按伦理要求销毁，**别和脱敏数据放一起**")
    L.append("- 脱敏文件已经放进 `output/`，要当正式分析输入的话记得再挪进 `data/`")
    L.append("- 建议在报告里留一句「已脱敏」的说明，作品展示时是加分项\n")

    md = "\n".join(L)
    ctx.save_text("output/去标识化报告.md", md)

    if "clean_log" in (ctx.get("keep_mapping") or []):
        ctx.save_text("output/脱敏_变更说明.md",
                      "# 变更说明\n\n本次共替换 %d 处：\n\n" % total +
                      "\n".join("- `%s` → `%s`（%s，%d 次）" % (h[1], h[2], h[0], h[3]) for h in hits) + "\n")

    # ---------- 7. 登记：告诉工作台「这份源文件处理过了，脱敏件在这里」----------
    #    没有这条记录，入口守卫每次都会把同一份素材再摆一次（它只认证据，不认「应该做过了」）
    reg_rel = ""
    try:
        from core import guard as guard_mod
        reg_rel = guard_mod.register(ctx.project_root, file_rel, out_rel, hits)
        ctx.log("已登记进 %s —— 入口守卫拿它当「这份处理过了」的证据" % reg_rel)
    except Exception as e:
        ctx.log("登记没写成（不影响脱敏结果）：%s" % e, "warn")

    # ---------- 8. 结果 ----------
    tables = []
    if hits:
        tables.append({
            "name": "替换明细（%d 处）" % total,
            "columns": ["类型", "原文", "替换为", "次数", "置信度"],
            "rows": [[h[0], h[1], h[2], h[3],
                      {"high": "高", "mid": "中·需复核"}.get(h[4], h[4])] for h in hits],
            "note": "同一实体全篇统一编号，读起来不会乱。中等置信度的建议人工过一眼。",
        })
    if quasi_rows:
        tables.append({
            "name": "准标识符（只提示，没改）",
            "columns": ["类型", "次数", "内容"],
            "rows": quasi_rows,
            "note": "单独看不致命，组合起来可能定位到人。降粒度与否是研究决策。",
        })

    return {
        "summary": "替换 %d 处 / %d 个实体；%d 类准标识符待你判断 → %s" % (
            total, len(hits), len(quasi_rows), out_rel),
        "tables": tables,
        "figures": [],
        "markdown": [{"name": "去标识化报告.md", "rel": "output/去标识化报告.md", "text": md}],
        "notes": "程序只管能模式化的部分；罕见特征组合、上下文指代、音频原声这些必须人来看。",
    }
