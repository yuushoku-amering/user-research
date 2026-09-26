# -*- coding: utf-8 -*-
"""中文关键词线索 · 词表驱动的切词

## 为什么不用 n-gram（踩过的坑）

第一版是纯 2-gram 频次（`P(ab)` 直接数）。在真实访谈稿上跑出来是这样：

    个月(6) 一段(4) 时间(4) 电话(3) 一起(3) 恋爱(3) 不太(3) 异地(3) 一次(3) 天天(3)
    么情(2) 情况(2) 期在(2) 分了(2) 谈恋(2) 得花(2)

`期在`（"那阵子**在**准备"跨词边界）、`么情`（"什**么情**况"）、`谈恋`（"**谈恋**爱"被切断）
——这些**不是词**，研究员拿去当编码线索没有意义，反而占掉了前 25 个位置里的好几位。

后来试过**无监督词发现**（凝固度 + 左右邻字熵）。结论：**语料太小用不了**。
一份访谈稿只有一千来字，无监督方法能稳定找出来的只有 `觉得/什么/就是` 这种虚词
（它们频次高、邻字丰富），真正的领域实词一次都不出现。

所以走**词表驱动**：词表 + 停用词 + 最长匹配。

    `谈恋爱` 在词表里 → 整体命中，不会再切成 `谈恋`+`恋爱`
    `期在` 不在词表里 → 直接忽略，没有碎词
    `觉得/就是/什么` 在停用词里 → 不算线索

## 词表是可以加的（重要）

`lexicon.txt` 跟这份代码放在一起，**一行一个词，`#` 开头是注释**。
遇到本行业/本项目的专有词（比如"付费转化""小鹰扫描"），**直接加到那个文件里**，
下次跑就认。这比改代码现实得多。

`keywords(texts, extra=[...])` 还能临时再传一批项目特有的词
（引擎就是这么干的：把研究简报里的变量名、提纲里的关键词喂进来）。
"""
import os
import re
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
LEXICON_FILE = os.path.join(_HERE, "lexicon.txt")

# 停用词：高频虚词 / 功能词。宁可多列 —— 多列只是少几个线索，漏列就会混进一堆废话。
STOPWORDS = set("""
的 了 是 在 我 你 他 她 它 我们 你们 他们 她们 咱们 这 那 这个 那个 这些 那些 这样 那样
什么 怎么 怎样 为啥 为什么 哪些 哪个 多少 几个
就是 觉得 认为 感觉 可能 应该 可以 不会 不是 没有 有点 比较 特别 真的 其实 反正 干脆
然后 但是 而且 因为 所以 如果 虽然 还是 或者 已经 一直 一下 一些 一个 一样 这么 那么
时候 现在 以前 以后 后来 起来 出来 过来 下来 上去 里面 外面 上面 下面 这边 那边
大家 自己 别人 人家 有点 一点 不太 不能 不用 不要 不会 没 有 会 能 要 想 说 问 做 去 来
好 对 嗯 啊 吧 呢 吗 嘛 哦 哎 唉 哈哈 都 也 还 就 才 再 又 很 太 更 最 挺
个月 一段 一次 天天 每天 每次 那天 那天 一般 通常 平时 大多数 都是
""".split())


def load_lexicon(extra=None):
    """词表 = 内置文件 + 调用方临时给的词（项目特有的）。

    ⚠ 词表文件是**一行多个词、用空格分开**（方便人读和分组），所以要 split 开。
      踩过：第一版整行当一个词，于是词表里躺着一条
      `"恋爱 谈恋爱 早恋 暗恋 异地 …"` 的超长"词"，切词时一个都命中不了 ——
      关键词直接变成空的（而且不报错，最坑的那种）。
    """
    words = set()
    try:
        with open(LEXICON_FILE, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.split("#", 1)[0]          # 行尾注释也允许
                for w in ln.split():
                    w = w.strip()
                    if len(w) >= 2:
                        words.add(w)
    except OSError:
        pass
    for w in (extra or []):
        for part in str(w).split():
            part = part.strip()
            if len(part) >= 2:
                words.add(part)
    return words


def cut(text, words):
    """最长匹配切词（4→3→2）。命中的整词吃掉，不命中就跳过那个字。

    ⚠ 不命中的字**直接跳过**，不做"补一个 2-gram"的兜底 ——
      兜底就把 `期在` 这种碎块又放回来了，那正是要避免的。
    """
    out, i, n = [], 0, len(text)
    while i < n:
        hit = None
        for L in (4, 3, 2):
            if i + L <= n and text[i:i + L] in words:
                hit = text[i:i + L]
                break
        if hit:
            out.append(hit)
            i += len(hit)
        else:
            i += 1
    return out


def keyword_hits(texts, top=25, min_count=1, extra=None, min_len=2):
    """返回 [(词, 提到的段数, 总出现次数)]，按段数降序。

    用「提到的**段数**」排序而不是总次数：一个词在同一个人嘴里说十遍，不该比
    十个人各说一遍更重要 —— 质性研究看的是**覆盖面**，不是词频。

    ⚠ 判据是「**这个词在词表里**」，不是「分词切到了它」。
      这是试了四版才定下来的：
        · 纯 2-gram 频次 → `期在`『么情』『谈恋』这种跨词边界的碎块（不能用）
        · 无监督词发现（凝固度+邻字熵）→ 一份访谈才一千来字，只能找出 `觉得/就是` 虚词
        · 最长匹配切词 → 切得干净，但**词表里没有的词就完全消失了**
          （实测 `花销` 出现 3 次却没进词表，结果一个线索都没提）
        · **数词表里有的词**（现在这版）→ 既没有碎块，又不会漏掉词表覆盖到的词；
          想让它认更多词，就加 `lexicon.txt`，这是给研究员的入口

    ⚠ `min_count` 默认 **1**，不是 2：一份访谈稿只有一千来字，
      按"至少出现两次"筛，`异地恋`『简历』这种只说过一次的领域词全被丢掉。
      宁可从宽进候选，靠 `top` 卡数量。
    """
    words = load_lexicon(extra)
    segs, occ = Counter(), Counter()
    for t in texts:
        t = str(t)
        seen_here = set()
        for chunk in re.findall(r"[\u4e00-\u9fa5]+", t):
            n = len(chunk)
            for L in range(4, min_len - 1, -1):     # 长的先数，避免子串重复计数
                for i in range(n - L + 1):
                    w = chunk[i:i + L]
                    if w not in words or w in STOPWORDS:
                        continue
                    # 已经被更长的命中覆盖过的位置不再计入短词（`谈恋爱` 命中后不再数 `恋爱`）
                    if any(w in longer for longer in seen_here if len(longer) > L):
                        continue
                    occ[w] += 1
                    if w not in seen_here:
                        seen_here.add(w)
                        segs[w] += 1
    items = [(w, c, occ[w]) for w, c in segs.items() if c >= min_count]
    items.sort(key=lambda x: (-x[1], -len(x[0]), -x[2]))
    return items[:top]
