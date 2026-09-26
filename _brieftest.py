# -*- coding: utf-8 -*-
"""⓪ 研究设计 → ③ 问卷设计 的离线回归（不花额度、不动真项目）

守的是这条链：**模型给的 Markdown 变量表** → 填回表单 → ⓪ 写研究简报 → ③ 出题项。

踩过一次：⓪ 不管三七二十一按逗号劈变量表，而 Markdown 单元格里本来就带中文逗号，
整张表被劈成碎片 → 简报第 6 节变成一堆「五量表 / 不需要 / ## 7. 数据条件」，
③ 照着出了 18 道莫名其妙的题。这个必须是自动化能抓住的。

    python _brieftest.py
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import kit, paths          # noqa: E402

JOBS = os.path.join(HERE, "_jobs")
TMP = os.path.join(JOBS, "tmp_brief")

# 模型真实给的那张表（带中文逗号、带括号说明）
VAR_TABLE_MD = """| 变量名 | 角色 | 测量层次 | 操作化定义（怎么测） |
|---|---|---|---|
| 玩具购买意愿 | 因变量 | 定序 | 「若门店上架该玩具，我愿意购买」5 级 Likert（1 完全不愿意～5 非常愿意） |
| 可接受价格 | 因变量 | 定比 | 开放式填写「单件最高可接受价格」（元） |
| 购买动机 | 自变量 | 定类 | 单选：给自家孩子 / 送礼 / 与零食搭配 / 其他 |
| 偏好玩具品类 | 因变量 | 定类 | 多选或排序题：品类选择／第一偏好 |
| 家中是否有 12 岁以下儿童 | 自变量 | 定类 | 单选：有 / 无 |
| 安全与品质顾虑强度 | 自变量 | 定序 | 3～4 项顾虑各 5 级 Likert，取均值或单题 |
| 到店频次 | 自变量 | 定序 | 单选：每周 1 次及以上 / 每月 2～3 次 / 每月 1 次 / 更低 |
| 性别 | 控制变量 | 定类 | 单选：男 / 女 / 其他 |"""

VAR_TABLE_CSV = """玩具购买意愿, 因变量, 定序, 5 级 Likert
可接受价格, 因变量, 定比, 开放式填写（元）
性别, 控制变量, 定类, 单选：男/女"""

RQ_TEXT = ("- RQ1 需求规模：来店用户中有多大比例愿意购买？\n"
           "RQ2：购买动机：主要动机是给自家孩子还是送礼？\n"
           "**RQ3 价格接受度**：可接受的价格区间是多少？")
HY_TEXT = "- H1 有 12 岁以下儿童的用户购买意愿更高\nH2）价格敏感度越高购买意愿越低"

PASS, FAIL = [], []


def ok(cond, label, extra=""):
    (PASS if cond else FAIL).append(label + ("" if cond else "  ← " + str(extra)))
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else "  ← " + str(extra)))


def run_block(block_id, params, project):
    job = dict(params)
    job["project_root"] = project
    job["block_dir"] = os.path.join(HERE, "blocks", block_id)
    job["block_id"] = block_id
    jf = os.path.join(JOBS, "brief_%s.json" % block_id)
    os.makedirs(JOBS, exist_ok=True)
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([paths.engine_python(), os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE, stdin=subprocess.DEVNULL)
    out = p.stdout.decode("utf-8", "replace")
    with open(os.path.join(JOBS, "brief_%s.jsonl" % block_id), "w", encoding="utf-8") as f:
        f.write(out + ("\n--- STDERR ---\n" + p.stderr.decode("utf-8", "replace")
                       if p.stderr.strip() else ""))
    result, error, logs = None, "", []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("t") == "result":
            result = m.get("data")
        elif m.get("t") == "error":
            error = m.get("msg", "")
        elif m.get("t") == "log":
            logs.append("[%s] %s" % (m.get("level"), m.get("msg")))
    return {"result": result or {}, "error": error, "logs": logs}


GOOD_BRIEF_SNIPPET = """# 研究简报

## 6. 关键变量与操作化定义

| 变量 | 角色 | 测量层次 | 操作化定义 |
|---|---|---|---|
| 付费意愿 | 因变量 | 定序 | 5 级 Likert |
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if os.path.isdir(TMP):
        shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(os.path.join(TMP, "contracts"), exist_ok=True)
    os.makedirs(os.path.join(TMP, "output"), exist_ok=True)

    print("=" * 70)
    print("一、变量表解析（这是当初烂掉的地方）")
    print("=" * 70)
    rows = kit.parse_var_table(VAR_TABLE_MD)
    ok(len(rows) == 8, "Markdown 表解析出 8 个变量", len(rows))
    ok(rows[0][0] == "玩具购买意愿", "第一个变量名没被劈碎", rows[0][0])
    ok(rows[0][1] == "因变量" and rows[0][2] == "定序", "角色 / 测量层次归位了", rows[0])
    ok("我愿意购买" in rows[0][3] and "完全不愿意" in rows[0][3],
       "操作化定义里的中文逗号没有被当成列分隔符", rows[0][3])
    ok(all("|" not in r[0] for r in rows), "变量名里没有残留的竖线")
    ok(len(kit.parse_var_table(VAR_TABLE_CSV)) == 3, "逗号分隔的老格式照样认")
    ok(kit.parse_var_table("## 7. 数据条件\n- 数据类型：问卷\n不需要") == [],
       "漏进来的正文/标题不会被当成变量", kit.parse_var_table("## 7. 数据条件\n不需要"))

    print("")
    print("=" * 70)
    print("二、⓪ 写简报（喂的就是模型那张表）")
    print("=" * 70)
    r1 = run_block("b0_brief", {
        "background": "某零食零售企业正在评估是否引入轻量化儿童玩具。",
        "purpose": "从来店用户出发，评估新品类可行性",
        "rqs": RQ_TEXT,
        "hypotheses": HY_TEXT,
        "population": "来店用户；现场随机拦截",
        "variables": VAR_TABLE_MD,
        "data_types": ["survey"],
        "constraints": "两周，预算 3k",
    }, TMP)
    ok(not r1["error"], "⓪ 能跑通", r1["error"])
    brief = open(os.path.join(TMP, "contracts", "research_brief.md"),
                 encoding="utf-8").read()

    body = brief.split("## 6.")[1].split("## 7.")[0]
    bad = [w for w in ("五量表", "不需要", "数据条件", "分析思路", "能打通") if w in body]
    ok(not bad, "第 6 节里没有混进别的章节/半截话", bad)
    ok(body.count("| 玩具购买意愿 |") == 1, "变量行写进去了")

    rq_line = [l for l in brief.splitlines() if l.startswith("- RQ1")][0]
    ok(rq_line.count("RQ1") == 1, "RQ 没被重复加一份编号", rq_line)
    ok("需求规模" in rq_line, "RQ 正文保住了", rq_line)
    ok(len([l for l in brief.splitlines() if l.startswith("- RQ")]) == 3, "3 个 RQ 都写进去了")
    ok(len([l for l in brief.splitlines() if l.startswith("- H")]) == 2, "2 条假设都写进去了")
    ok("H2）价格敏感度" not in brief, "假设编号的「）」写法也削掉了",
       [l for l in brief.splitlines() if l.startswith("- H2")])

    print("")
    print("=" * 70)
    print("三、解析回来的简报 → ③ 问卷设计")
    print("=" * 70)
    info = kit.parse_brief(brief)
    names = [v[0] for v in info["variables"]]
    ok(len(info["variables"]) == 8, "从简报里读回 8 个变量", names)
    ok(names[0] == "玩具购买意愿", "变量名对得上", names)
    ok(len(info["rqs"]) == 3, "读到 3 个 RQ", info["rqs"])
    ok(all("|" not in n and len(n) <= 16 for n in names), "没有垃圾变量名", names)
    ok(any("因变量" in v[1] for v in info["variables"]), "角色列读到了")

    r3 = run_block("b3_survey_design", {
        "brief": "contracts/research_brief.md",
        "audience": "来店顾客（18 岁以上）",
        "mode": "paper", "minutes": 6, "parts": ["screen", "main", "demo"],
    }, TMP)
    ok(not r3["error"], "③ 能跑通", r3["error"])
    n_items = len(r3["result"].get("tables", [{}])[0].get("rows", []))
    ok(4 <= n_items <= 25, "③ 出的题项数量合理（%d 道，不是 18 道垃圾）" % n_items, n_items)
    items = r3["result"].get("tables", [{}])[0].get("rows", [])
    ok(all(len(str(r[1])) <= 16 for r in items), "题项表里的变量名都是正常变量名",
       [r[1] for r in items][:8])

    # 题型必须跟着「操作化定义」走，而不是自作聪明
    # （多题项构念会被拆成 满意度_1/_2/_3，所以比对时去掉后缀）
    kinds = {}
    for r in items:
        base = re.sub(r"_\d+$", "", str(r[1]))
        kinds.setdefault(base, str(r[2]))
    ok(kinds.get("玩具购买意愿") == "李克特 5 点",
       "「5 级 Likert」的意愿变量出成李克特 5 点，不是 NPS 0-10", kinds.get("玩具购买意愿"))
    ok(kinds.get("可接受价格") == "数字填空",
       "「开放式填写价格（元）」出成数字填空，不是李克特", kinds.get("可接受价格"))
    ok(kinds.get("性别") == "单选", "性别出成单选", kinds.get("性别"))
    ok(kinds.get("购买动机") == "单选",
       "购买动机在简报里写的是单选，就不该被改成多选（操作化定义优先）", kinds.get("购买动机"))
    ok(kinds.get("安全与品质顾虑强度") == "李克特 5 点",
       "「3～4 项顾虑各 5 级 Likert」也认", kinds.get("安全与品质顾虑强度"))
    ok(kinds.get("偏好玩具品类") == "多选",
       "「多选或排序题」出成多选", kinds.get("偏好玩具品类"))

    # 简报里已经写好的选项要直接搬进锚点（以前一律吐「互斥选项 + 其他」，
    # 等于把研究员写好的东西丢了）
    anchors = {}
    for r in items:
        anchors.setdefault(re.sub(r"_\d+$", "", str(r[1])), str(r[3]))
    ok("给自家孩子" in anchors.get("购买动机", ""),
       "购买动机的锚点带上了简报里写好的选项", anchors.get("购买动机"))
    ok("每周 1 次及以上" in anchors.get("到店频次", ""),
       "定序单选的锚点带上了有序档位", anchors.get("到店频次"))
    ok("男" in anchors.get("性别", "") and "同意" not in anchors.get("性别", ""),
       "性别用的是简报里写好的选项，没被出成同意度量表", anchors.get("性别"))

    print("")
    print("=" * 70)
    print("四、界面上那张变量表格：结构化那份要优先于文本")
    print("=" * 70)
    # 界面把表格既序列化成文本、也传一份逐行数据。这里故意让两者打架，
    # 看引擎听谁的 —— 以后谁改了序列化规则，这条会先叫。
    r4 = run_block("b0_brief", {
        "background": "验证变量表结构化输入优先。",
        "purpose": "验证变量表结构化输入优先",
        "rqs": "- RQ1 验证：结构化变量表有没有被用上",
        "hypotheses": "",
        "population": "无",
        "variables": "文本里那个变量, 自变量, 定类, 应该被忽略",
        "variables_rows": [["界面来的变量", "因变量", "定距", "5 点量表"],
                           ["界面来的变量2", "自变量", "定类", "单选"]],
        "data_types": ["survey"],
    }, TMP)
    ok(not r4["error"], "⓪ 带着结构化变量表能跑通", r4["error"])
    brief4 = open(os.path.join(TMP, "contracts", "research_brief.md"),
                  encoding="utf-8").read()
    sec6 = brief4.split("## 6.")[1].split("## 7.")[0]
    ok("界面来的变量" in sec6, "简报第 6 节用的是结构化那份")
    ok("文本里那个变量" not in sec6, "文本那份没有插进来")
    ok(kit.parse_brief(brief4)["variables"][0][0] == "界面来的变量",
       "解析回来第一个变量是界面那份")

    r5 = run_block("b3_survey_design", {
        "brief": "contracts/research_brief.md",
        "audience": "任何人", "mode": "paper", "minutes": 5,
        "parts": ["main"],
        "variables_rows": [["只测这个", "因变量", "定距", "5 点量表"]],
    }, TMP)
    ok(not r5["error"], "③ 能跑通（带界面覆盖的变量表）", r5["error"])
    rows5 = r5["result"].get("tables", [{}])[0].get("rows", [])
    names5 = set(re.sub(r"_\d+$", "", str(r[1])) for r in rows5)
    ok(names5 == set(["只测这个"]),
       "③ 只给界面那张表里的变量出题，没把简报里那 8 个也塞进来", sorted(names5))

    print("")
    print("=" * 70)
    print("五、契约解析失败要出声（不能只写日志）")
    print("=" * 70)
    # 实测过的现场：简报第 6 节被写成手写文字而不是表格 → ③ 拿 0 个变量
    # 跑出「0 道题」、照样落盘、照样给绿色摘要。那条 warn 在日志页，没人会翻。
    BAD = (u"# 研究简报\n\n"
           u"## 1. 背景与业务问题\n付费转化在下滑。\n\n"
           u"## 2. 研究目的\n搞清楚为什么没人升级付费版。\n\n"
           u"## 3. 研究问题（RQ）\n- RQ1 认知：用户知不知道有付费版\n\n"
           u"## 6. 关键变量与操作化定义\n（这一段我用手写，没做成表格）\n"
           u"满意度：问用户满不满意\n付费意愿：问用户愿不愿意付费\n")
    rep = kit.brief_section_report_text(BAD, "contracts/research_brief.md")
    labels = [s["label"] for s in rep["failed"]]
    ok("关键变量与操作化定义" in labels, "体检认出了「有内容却没读出来」的那一节", labels)
    ok(rep["variables"] == 0, "变量表确实是 0", rep["variables"])
    ok(bool(kit.brief_section_report_text(GOOD_BRIEF_SNIPPET, "x").get("failed")) is False,
       "写对了的简报不会被误报")

    bad_dir = os.path.join(TMP, "契约体检")
    os.makedirs(os.path.join(bad_dir, "contracts"), exist_ok=True)
    with open(os.path.join(bad_dir, "contracts", "research_brief.md"), "w", encoding="utf-8") as f:
        f.write(BAD)
    r6 = run_block("b3_survey_design", {
        "brief": "contracts/research_brief.md", "audience": "全部用户",
        "mode": "online", "minutes": 8, "parts": ["main"],
    }, bad_dir)
    alerts = (r6.get("result") or {}).get("alerts") or []
    ok(any(a.get("level") == "error" for a in alerts),
       "③ 拿「读不出变量表」的简报跑 → 结果里带 error 级提醒（界面上红条）", alerts)
    ok(any("一个变量都没读到" in a.get("msg", "") for a in alerts),
       "提醒直说了「一个变量都没读到」", [a.get("msg") for a in alerts])
    ok(any(a.get("fix") for a in alerts), "提醒里带了「怎么办」")
    ok(any("research_brief.md" in (a.get("rel") or "") for a in alerts),
       "提醒指向那份契约文件", [a.get("rel") for a in alerts])

    # ------------------------------------------------------------------ #
    # 字段自带的说明：人不会一上来把每个模块读完，所以「这个表是干什么的」
    # 必须写在产品里（字段的 note），而不是只写在聊天或文档里。
    # ------------------------------------------------------------------ #
    print("")
    print("=" * 70)
    print("字段说明（note）")
    print("=" * 70)
    sys.path.insert(0, HERE)
    from core import registry
    bl = {b["id"]: b for b in registry.load_blocks()}
    for bid, key, must in (("b0_brief", "variables", ["源头", "③", "测量层次"]),
                           ("b3_survey_design", "variables", ["⓪", "读回", "不会写回 ⓪"])):
        fld = None
        for f in (bl.get(bid, {}).get("form") or []):
            if f.get("key") == key:
                fld = f
        ok(bool(fld), "%s 有 %s 字段" % (bid, key))
        note = (fld or {}).get("note") or {}
        ok(bool(note.get("title")), "%s 的 %s 带说明标题：%s" % (bid, key, note.get("title")))
        body = note.get("body") or ""
        whole = (note.get("title") or "") + body      # 断言看整体：标题里说清也算说清
        ok(len(body) > 80, "%s 的说明有实质内容（%d 字）" % (bid, len(body)))
        for m in must:
            ok(m in whole, "%s 的说明里讲到了「%s」" % (key, m))
    # 说明是给人看的，别把 HTML 写进去（前端会转义）
    for bid in ("b0_brief", "b3_survey_design"):
        for f in (bl.get(bid, {}).get("form") or []):
            note = f.get("note") or {}
            ok("<" not in (note.get("body") or ""), "%s/%s 的说明里没有 HTML 标签" % (bid, f.get("key")))

    # ---------------- ③ 选项抽取：简报里"写好的选项"别白丢 ----------------
    # 现场（2026-09-24，拿「恋爱研究」那份真实简报跑 ③ 才暴露）：
    #   简报的写法五花八门，`_opt_anchor` 原来只认「（括号包着）」和「单选：」两种，
    #   于是**研究员已经写好的选项白白丢掉**，换成「互斥选项 + 「其他（请注明）」」——
    #   而且表面看不出来（锚点看着"也挺合理"）。比丢选项更糟的是**题型判错**：
    #     · 「年级」标着定序 → 出了 2 道李克特（「我同意我的年级是…」）
    #     · 「花销分担比例」的 4 个区间档 → 被换成同意度量表（均值没法解释）
    #     · 「恋爱经历次数」→ 被"行为次数别问用户"那条规则**整个丢掉**，一道题都不出
    print("\n【③ 简报里写好的选项 / 档位：六种写法都要认】")
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "b3d_probe", os.path.join(HERE, "blocks", "b3_survey_design", "engine.py"))
    _b3d = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_b3d)

    anchor_cases = [
        ("自报当前状态：从未恋爱 / 恋爱中 / 追求中 / 已分手", "从未恋爱", "冒号后的清单"),
        ("受访者描述的花销决定机制，编码为单方承担 / 轮流承担 / AA 均摊 / 视场景混合 / 未讨论",
         "AA 均摊", "「编码为」后的清单"),
        ("受访者自报本人承担份额，按 0–25%、25–50%、50–75%、75–100% 区间归组",
         "50–75%", "「按 a、b 区间归组」的**裸列举**（没冒号没括号）"),
        ("自报累计恋爱段数，按 0 次、1 次、2 次及以上分组", "2 次及以上", "「按…分组」的裸列举"),
        ("如陪伴、吸引、同伴压力、经济、家庭期待等", "同伴压力", "「如…等」列举"),
        ("自报主要经济来源：家庭给 / 奖助学金 / 兼职 / 混合", "奖助学金", "冒号后的清单（第二种）"),
    ]
    for op, must, label in anchor_cases:
        got = _b3d._opt_anchor(op)
        ok(must in got, "认得出%s（抽到：%s）" % (label, got or "（空）"), got)

    # 不能误抽：这些是"怎么算"的说明，不是给受访者看的选项
    for op, label in [("受访者自报需与对方商量或会犹豫的金额临界值", "金额临界值（没有选项）"),
                      ("月均恋爱支出 ÷ 月可支配生活费，由前两项计算得出", "计算式（不是选项）"),
                      ("受访者自报的每月恋爱相关开销金额", "纯金额说明（不是选项）")]:
        got = _b3d._opt_anchor(op)
        ok(got == "", "别把%s当选项（抽到 %r）" % (label, got), got)

    # 题型判定：这三条都是"判错但看着合理"，只有对照真实简报才发现
    kind_of = {}
    for name, role, measure, op in [
        ("年级", "控制变量", "定序", "自报年级：大一 / 大二 / 大三（若有其他）"),
        ("花销分担比例", "因变量", "定序", "受访者自报本人承担份额，按 0–25%、25–50%、50–75%、75–100% 区间归组"),
        ("恋爱经历次数", "自变量", "定序", "自报累计恋爱段数，按 0 次、1 次、2 次及以上分组"),
        ("月可支配生活费", "自变量", "定序", "自报每月可自由支配金额，按区间选择后归组"),
        ("性别", "控制变量", "定类", "自报性别"),
    ]:
        sug = _b3d._suggest(name, role, measure, op)
        ok(sug is not None, "「%s」要出题（不能整条被丢掉）" % name)
        if sug:
            kind_of[name] = (sug[0], sug[1], sug[2])
    ok(kind_of.get("年级", ("",))[0] == "single",
       "年级出单选 —— 不是「我同意我的年级是…」的李克特", kind_of.get("年级"))
    ok(kind_of.get("花销分担比例", ("",))[0] == "single"
       and "50–75%" in kind_of.get("花销分担比例", ("", ""))[1],
       "花销分担比例照简报的区间档出单选，档位搬进锚点", kind_of.get("花销分担比例"))
    ok(kind_of.get("恋爱经历次数", ("",))[0] == "freq5",
       "恋爱经历次数出频率档位（简报写明了要自报档位），不是被「别问用户」那条规则丢掉",
       kind_of.get("恋爱经历次数"))
    ok(kind_of.get("月可支配生活费", ("",))[0] == "number",
       "月可支配生活费是填金额（它没有具体档位可搬）", kind_of.get("月可支配生活费"))

    # ---------------- ③ 的提醒里**不该**出现「替换类填写」 ----------------
    # 前辈实测报的：弹出一条「你勾了筛选题，但一道都没生成」的提醒，
    #   底下却跟着 `原文 = 换成什么（空 = 删掉）` + 「加进自定义替换」——
    #   那是 🔒 去标识化的填法，跟"筛选题怎么写"完全无关，看着莫名其妙。
    #   ⇒ 规矩：**那套"替换"输入框只有当这条提醒确实要"写替换规则"时才给**。
    print("\n【③ 的提醒不该带替换框】")
    projA = os.path.join(HERE, "_jobs", "alert_probe")
    shutil.rmtree(projA, ignore_errors=True)
    for d in ("contracts", "output"):
        os.makedirs(os.path.join(projA, d), exist_ok=True)
    # ⚠ 简报里**写明纳入标准**：这样"筛选题"那条提醒才会出现（见下一条）
    with open(os.path.join(projA, "contracts", "research_brief.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("# 契约 0 · 研究简报\n\n## 5. 目标人群与抽样\n\n"
                "- 目标总体：本校**有恋爱经验**的大一到大三学生\n"
                "- 纳入标准：有恋爱经验\n\n"
                "## 6. 关键变量与操作化定义\n\n"
                "| 变量名 | 角色 | 测量层次 | 操作化定义（怎么测） |\n"
                "|---|---|---|---|\n"
                "| 恋爱状态 | 自变量 | 定类 | 自报当前状态：从未恋爱 / 恋爱中 / 追求中 / 已分手 |\n"
                "| 月可支配生活费 | 自变量 | 定序 | 自报每月可自由支配金额，按区间选择后归组 |\n")
    rA = run_block("b3_survey_design", {
        "brief": "contracts/research_brief.md",
        "audience": "本校有恋爱经验的大一到大三学生",
        "mode": "link", "minutes": 8,
        "parts": ["screen", "main", "background"],
    }, projA)
    ok(not rA["error"], "③ 能跑通（带纳入标准的简报）", rA["error"])
    alertsA = (rA["result"] or {}).get("alerts") or []
    ok(bool(alertsA), "③ 这条简报确实会出提醒（否则下面几条断言是空转）",
       len(alertsA))
    boxy = [a for a in alertsA if a.get("rules_field") or a.get("options")]
    ok(not boxy, "③ 的提醒里**没有一条**带「替换框 / 替换选项」",
       [(a.get("msg") or "")[:40] for a in boxy])
    # 「筛选题」那条：要么不出，要么出得**说对**
    scr = [a for a in alertsA if "筛选题" in str(a.get("msg") or "")]
    for a in scr:
        ok("一道都没生成" not in str(a.get("msg") or ""),
           "**不再误报「一道都没生成」**（表里明明有「恋爱状态」这种门口的题）",
           str(a.get("msg"))[:80])
    shutil.rmtree(projA, ignore_errors=True)

    # ---------------- ① 提问组的三种形式要**真的不一样** ----------------
    # 现场：选「焦点小组」只改了标题一行字（实测 semi→focus 的差异只有 1 行），
    #   拿到手的还是一对一的开场白和主问题结构 —— 等于这个选项挂在那儿没用。
    print("\n【① 访谈形式：三种要真的不同】")
    proj = os.path.join(HERE, "_jobs", "style_probe")
    shutil.rmtree(proj, ignore_errors=True)
    for d in ("contracts", "output"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    src_brief = os.path.join(HERE, "_jobs", "brief_fixture.md")
    if os.path.exists(src_brief):
        shutil.copy2(src_brief, os.path.join(proj, "contracts", "research_brief.md"))
    outs = {}
    for tag, style, dur in (("semi45", "semi", 45), ("deep45", "deep", 45),
                            ("focus0", "focus", ""), ("focus60", "focus", 60)):
        r = run_block("b1_guide", {"audience": "某类受访者", "duration": dur, "style": style,
                                   "focus": "", "channels": ""}, proj)
        g = ""
        gp = os.path.join(proj, "contracts", "interview_guide.md")
        if os.path.exists(gp):
            g = open(gp, encoding="utf-8").read()
        outs[tag] = g
    if all(outs.values()):
        ok("焦点小组的主持要点" in outs["focus0"],
           "焦点小组有自己的一节（不是只改标题）")
        for k in ("人数组场", "轮次怎么走", "抓住分歧"):
            ok(k in outs["focus0"], "焦点小组讲到了「%s」" % k)
        ok("预计 **90 分钟**" in outs["focus0"],
           "焦点小组没填时长时按 90 分钟起算（6~8 人轮流说，45 分钟走不完）")
        ok("预计 **60 分钟**" in outs["focus60"],
           "**填了**时长就尊重填的值（不能拿默认值顶掉人写的）")
        ok("焦点小组的主持要点" not in outs["semi45"],
           "半结构式不该混进焦点小组那一节")
        ok(outs["semi45"] != outs["deep45"], "深度访谈和半结构式也要有差别")
        # 小节编号连号（条件小节缺席时原来会断号 0,1,2,4,6）
        for tag, g in outs.items():
            nums = [int(x[3:].split(".")[0]) for x in g.split("\n")
                    if x.startswith("## ") and x[3:4].isdigit()]
            ok(nums == list(range(len(nums))),
               "%s 的小节编号连号（%s）" % (tag, nums))
    else:
        ok(False, "① 的四种形式都跑出了提纲", [k for k, v in outs.items() if not v])
    shutil.rmtree(proj, ignore_errors=True)

    print("")
    print("=" * 70)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for x in FAIL:
        print("  ❌ " + x)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
