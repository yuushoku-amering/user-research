# -*- coding: utf-8 -*-
"""模型输出 → 填回表单 的自测

  python _llmfilltest.py          # 只跑离线部分（不花额度）：拿写死的模型输出喂切分器
  python _llmfilltest.py --api    # 再加一次真调用（会消耗少量额度）

**为什么要离线跑**：踩过一次——⓪ 的提示词正文让模型写 `## 1. 背景与业务问题`，
而切分器按无编号的精确标题找，一个小节都没切出来，界面上「⤵ 填回表单」按钮直接消失。
这个错必须能在不花钱的情况下被抓住。

结果写 _jobs/llmfilltest.txt
"""
import json
import os
import shutil
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import llm          # noqa: E402

BASE = "http://127.0.0.1:8765"
OUT = os.path.join(HERE, "_jobs", "llmfilltest.txt")
LOG = []
PASS, FAIL = [], []


def _pick_project():
    """要一个**存在**的项目当靶子（模型只拿它的路径，不读它的内容）。

    原来写死成某个真实案例项目的绝对路径 —— 别人 clone 下来没有那个项目，
    这一段会莫名其妙地失败。现在：命令行给 > 案例项目在 > 用自带素材临时拼一个。
    """
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        return os.path.abspath(sys.argv[1])
    real = os.path.abspath(os.path.join(HERE, "..", "projects", "小鹰扫描_付费转化研究"))
    if os.path.isdir(real):
        return real
    tmp = os.path.join(HERE, "_jobs", "tmp_llmfill_proj")
    src = os.path.join(HERE, "_fixtures")
    os.makedirs(os.path.join(tmp, "samples"), exist_ok=True)
    for name in ("research_brief.md",
                 "访谈转写稿_小周.txt", "访谈转写稿_小林.txt"):
        f = os.path.join(src, name)
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(tmp, "samples", os.path.basename(f)))
    return tmp


PROJ = _pick_project()


def say(*a):
    line = " ".join(str(x) for x in a)
    LOG.append(line)
    print(line)


def ok(cond, label, extra=""):
    (PASS if cond else FAIL).append(label + ("" if cond else "  ← " + str(extra)))
    say(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else "  ← " + str(extra)))


# ⓪ 声明了哪 7 个小节
FIELDS = [
    ("background", "背景与业务问题"), ("purpose", "研究目的"), ("rqs", "研究问题"),
    ("hypotheses", "假设"), ("population", "目标人群与抽样"),
    ("variables", "关键变量与操作化定义"), ("constraints", "约束与伦理"),
]
OFIELDS = [{"key": k, "title": t} for k, t in FIELDS]

# 模型真实输出长这样：**带编号**的二级标题（这就是当初切不出来的样子）
SAMPLE_NUMBERED = """# 研究简报

## 1. 背景与业务问题
我们是一家零食零售企业，主营业务为零食零售。本次业务决策问题是：
**是否引入轻量化儿童玩具作为新的零售产品**。

（待确认：本次考察的是全部门店试点还是个别门店/城市试点？）
（待确认：轻量化儿童玩具的具体品类与价格带是什么？）

## 2. 研究目的
从「用户端（未消费）」评估引入轻量化儿童玩具的可行性。

### 研究问题（RQ）
需求基线：（待确认：给出两个比例的估计值、置信区间与样本量）

## 3. 假设
- H1 有 3~12 岁儿童的家庭购买意愿显著高于无孩家庭
- H2 价格带在 10~30 元时购买意愿最高

## 4. 目标人群与抽样
纳入标准：（待确认）
排除标准：近三个月买过同类玩具

## 5. 关键变量与操作化定义
| 变量 | 角色 | 操作化 | 测量层次 |
|---|---|---|---|
| 购买意愿 | 因变量 | 5 点量表 | 定距 |

## 6. 约束与伦理
时间：两周内完成。
"""

SAMPLE_PLAIN = """## 背景与业务问题
背景正文。

## 研究目的
目的一段。

## 研究问题
- RQ1 一条

## 假设
- H1 一条

## 目标人群与抽样
人群一段。

## 关键变量与操作化定义
变量一段。

## 约束与伦理
约束一段。
"""

SAMPLE_BOLD = """**背景与业务问题**
背景正文。

**研究目的**
目的正文。

**研究问题**
RQ 正文。

**假设**
假设正文。

**目标人群与抽样**
人群。

**关键变量与操作化定义**
变量。

**约束与伦理**
伦理。
"""

SAMPLE_FENCED = """## 1. 背景与业务问题
```markdown
背景在最外层包了个代码块围栏
```

## 2. 研究目的
目的。
"""

SAMPLE_SHORT = """## 1. 背景与业务问题
只有这一节。
"""


def offline():
    say("=" * 70)
    say("一、离线：拿写死的模型输出喂切分器")
    say("=" * 70)

    cases = [
        ("带编号的二级标题（当初坏掉的就是这种）", SAMPLE_NUMBERED, 7),
        ("不带编号的二级标题", SAMPLE_PLAIN, 7),
        ("**加粗** 当标题", SAMPLE_BOLD, 7),
    ]
    for name, text, expect in cases:
        got = llm._split_fields(text, OFIELDS)
        say("  【%s】解析出 %d / %d" % (name, len(got), len(OFIELDS)))
        for k, t in FIELDS:
            v = got.get(k)
            say("      %-12s %-22s %s" % (k, t, ("OK %d 字" % len(v)) if v else "❌ 没解析到"))
        ok(len(got) == expect, "%s → 7 个小节全切出来" % name, sorted(got.keys()))
        ok(not got.get("background", "").startswith("1."),
           "%s → 正文里没有把编号吃进去" % name, got.get("background", "")[:20])

    # 编号里带着「1. 」的那节，值不能把后面的节也吞了
    a = llm._split_fields(SAMPLE_NUMBERED, OFIELDS)
    ok("研究目的" not in a.get("background", ""), "编号版：背景那节没吞掉下一节")
    ok("需求基线" in a.get("rqs", ""), "编号版：### 子标题「研究问题（RQ）」也认出来了",
       a.get("rqs", "")[:40])
    ok("H1" in a.get("hypotheses", ""), "编号版：假设那节切对了")
    ok("5 点量表" in a.get("variables", ""), "编号版：变量表切对了")

    # 代码块围栏要剥掉
    f = llm._split_fields(SAMPLE_FENCED, OFIELDS)
    ok("```" not in f.get("background", ""), "代码块围栏被剥掉了", f.get("background"))
    ok("背景在最外层" in f.get("background", ""), "围栏里的正文留下了")

    # 缺小节要能报出来（前端据此提示「这几项没解析出来」）
    s = llm._split_fields(SAMPLE_SHORT, OFIELDS)
    missing = [t for k, t in FIELDS if k not in s]
    ok(len(s) == 1 and len(missing) == 6, "只写了一节时报出 6 个缺的", missing)

    # 别把普通句子当标题
    noise = llm._split_fields("研究目的是什么？这个问题很复杂。\n还有第二行。", OFIELDS)
    ok(len(noise) == 0, "正文里的普通句子不会被当成标题", list(noise.keys()))

    # 待确认标记：切回来的值里要原样带着，前端侧栏才扫得到
    marks = llm._split_fields(SAMPLE_NUMBERED, OFIELDS)
    n = sum(len(llm.re.findall(r"（待确认", v)) for v in marks.values())
    ok(n >= 3, "切回来的字段里带着 %d 处「（待确认：…）」" % n)


def online():
    say("")
    say("=" * 70)
    say("二、真调一次模型（--api）")
    say("=" * 70)

    def post(path, data, timeout=400):
        req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    post("/api/config/save", {"config": {"llm": {"enabled": True}}})
    r = post("/api/llm", {
        "block_id": "b0_brief", "project": PROJ,
        "params": {
            "background": "小鹰扫描是免费文档扫描 App，MAU 180 万、商店 4.7 分，付费率只有 1.1%"
                          "（同量级产品 2.5%~3%）。团队试过挪按钮、双十一六折、启动页推会员，效果都一般。"
                          "内部有三种说法：①用户不知道有付费版 ②知道了但觉得免费够用 ③觉得定价不值。"
                          "要判断哪条是主因，因为三种原因对应完全不同的动作。",
        },
    })
    say("ok = %s" % r.get("ok"))
    if r.get("ok"):
        fs = r.get("fields") or {}
        meta = r.get("fields_meta") or []
        say("模型耗时 %ss；声明 %d 个，解析出 %d 个" % (r.get("seconds"), len(meta), len(fs)))
        for m in meta:
            v = fs.get(m["key"])
            say("   %-12s %-22s %s" % (m["key"], m["title"],
                                       ("OK %d 字" % len(v)) if v else "❌ 没解析到"))
        ok(len(fs) >= len(meta) - 1, "真调用：至少切出 %d 个小节" % (len(meta) - 1),
           r.get("missing_fields"))
        ok(bool(fs.get("background")), "真调用：背景那节切到了")
    else:
        ok(False, "真调用成功", r.get("error"))
    post("/api/config/save", {"config": {"llm": {"enabled": False}}})
    say("（已把模型通道关回去）")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    offline()
    if "--api" in sys.argv:
        try:
            online()
        except Exception as e:
            ok(False, "真调用", e)

    say("")
    say("=" * 70)
    say("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for x in FAIL:
        say("  ❌ " + x)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
