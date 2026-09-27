# -*- coding: utf-8 -*-
"""知识库规则 · 专项自检

守三件事：
  1. 规则文件能被读懂（读不懂要**说出来**，不能静默跳过判定）
  2. 该报的报（不漏），不该报的不报（不误报）
  3. 判定带得出「依据」——研究员要能知道这条规则从哪来

跑法：  python _knowledgetest.py
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import knowledge as kb                       # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, label, extra=None):
    if cond:
        PASS[0] += 1
        print("  [OK] " + label)
    else:
        FAIL[0] += 1
        print("  [!!] " + label + ("" if extra is None else "  —— %s" % (extra,)))


def eq(a, b, label):
    same = a == b
    ok(same, label, None if same else "实际 %r，期望 %r" % (a, b))


def run_block(block_id, params, project_root):
    job = dict(params)
    job["project_root"] = project_root
    job["block_dir"] = os.path.join(HERE, "blocks", block_id)
    job["block_id"] = block_id
    jf = os.path.join(project_root, "_job.json")
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    import subprocess
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE, stdin=subprocess.DEVNULL)
    out = p.stdout.decode("utf-8", "replace")
    result, error = None, ""
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
    return {"result": result or {}, "error": error}


def main():
    print("\n【1】规则文件读得懂吗")
    files = kb.list_files()
    ok(len(files) >= 1, "知识库里有规则文件（%d 份）" % len(files), [f["name"] for f in files])
    summ = kb.summarize()
    for s in summ:
        ok(s["ok"], "%s 解析正常（%d 条键）" % (s["file"], s["rules"]), s)

    rules, err = kb.load("研究问题与样本量.md", with_error=True)
    eq(err, "", "这份规则文件没有解析错误")
    pv = kb._ns(rules, "purpose_verbs")
    ss = kb._ns(rules, "sample_size")
    ok(len(pv) >= 5, "研究目的那条规则读全了", sorted(pv.keys()))
    ok(len(ss) >= 5, "样本量那条规则读全了", sorted(ss.keys()))
    ok(bool(pv.get("source")) and bool(ss.get("source")), "两条规则都带出处")
    ok(pv.get("kind") in ("convention", "opinion", "heuristic"), "研究目的那条标了类型：%s" % pv.get("kind"))
    ok(ss.get("kind") == "heuristic", "样本量那条标成经验法则（数字是经验值，不是推导值）")

    print("\n【2】该报的要报（不漏）")
    for p, want in [("了解用户对会员体系的感受", "了解"),
                    ("探索新用户流失的原因", "探索"),
                    ("为了探究价格与复购的关系", "探究"),
                    ("旨在探索新用户流失", "探索"),
                    ("本研究希望了解用户的真实感受", "了解"),
                    ("研究一下大家对定价的看法", "研究一下"),
                    ("understand how users feel about X", "understand")]:
        res = kb.check_purpose(p)
        got = (res[0]["msg"].split("「")[1].split("」")[0]) if res else ""
        eq(got, want, "「%s」→ 报出「%s」" % (p[:16], want))

    print("\n【3】不该报的别报（不误报）")
    for p in ["识别影响用户续费意愿的关键因素", "描述用户的开箱流程",
              "比较流失用户与留存用户的行为差异", "评估三档定价方案的接受度",
              "evaluate three pricing options", "刻画高活跃用户的典型一天"]:
        eq(kb.check_purpose(p), [], "「%s」→ 安静" % p[:20])
    eq(kb.check_purpose(""), [], "空的目的不报")

    print("\n【4】样本量：按研究类型判，多个数字取最大的那个")
    cases = [
        ("5", "访谈", True, "低于访谈下限"),
        ("10", "访谈", False, "访谈正常区间"),
        ("30", "访谈", True, "超过访谈上限"),
        ("3", "可用性测试", True, "低于可用性下限"),
        ("6", "可用性测试", False, "可用性正常"),
        ("50", "问卷", True, "低于问卷下限"),
        ("200", "问卷", False, "问卷正常"),
        ("两类各 8 人", "深访", False, "「两类各 8 人」抠出 8，落在区间内"),
        ("", "访谈", False, "没填就不判"),
        ("视情况而定", "访谈", False, "抠不出数字就不判（宁可不判，不瞎判）"),
        ("20", "", False, "判断不出研究类型就不判"),
    ]
    for n, st, want_hit, label in cases:
        res = kb.check_sample(n, st)
        eq(bool(res), want_hit, label)
    res = kb.check_sample("5", "访谈")
    ok(res and "8 人起" in res[0]["msg"], "提醒里写清了该是多少人", res[0]["msg"] if res else None)
    ok(res and "按人群分别适用" in res[0]["fix"], "提醒里带上了「按人群分别算」这句")
    ok(res and res[0]["source"], "样本量的提醒也带出处")

    print("\n【5】规则文件坏了要说出来，不能静默跳过判定")
    # 这是这套东西最该避免的毛病：规则没读成，却表现成「检查过了，没问题」
    tmp = os.path.join(kb.KNOWLEDGE_DIR, "_坏文件测试.md")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("# 故意写坏的规则\n\n```json\n{\"purpose_verbs.id\": \"x\", 这不是合法 JSON}\n```\n")
        r, e = kb.load("_坏文件测试.md", with_error=True)
        ok("解析失败" in e, "load 把解析错误带回来了", e)
        # 规则整条缺失（文件被挪走 / 键名写错）时，判定必须报「没读成」，不能静默通过。
        # 注意别用 {"purpose_verbs.id": "x"} 这种假输入去测 —— 那在 _ns 看来是「存在」，
        # 会走正常流程（踩过：我自己就被这个假输入骗了一次）。
        res = kb.check_purpose("了解用户想法", rules={})
        ok(any("没读成" in x.get("msg", "") for x in res), "规则缺了 → 判定报「没读成」而不是静默通过", res)
        ok(any(x.get("kind") == "internal" for x in res), "这种提醒标成「工作台自身」的问题")
        res2 = kb.check_sample("5", "访谈", rules={})
        ok(any("没读成" in x.get("msg", "") for x in res2), "样本量那条规则缺了也一样会报", res2)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
        kb._cache.pop(tmp, None)

    print("\n【6】⓪ 跑起来：命中会挂到结果页上（而不是只写日志）")
    root = tempfile.mkdtemp(prefix="urw_kb_")
    try:
        os.makedirs(os.path.join(root, "contracts"), exist_ok=True)
        os.makedirs(os.path.join(root, "output"), exist_ok=True)
        r = run_block("b0_brief", {
            "background": "一个免费工具 App 的付费转化在下滑。",
            "purpose": "了解用户为什么不愿意升级付费版",       # 该报：用了「了解」
            "rqs": "- RQ1 认知：用户知不知道有付费版",
            "hypotheses": "",
            "population": "招募 3 位受访者，做半结构访谈",       # 该报：访谈 3 人 < 8
            "variables": "付费意愿, 因变量, 定序, 5 级 Likert",
            "variables_rows": [["付费意愿", "因变量", "定序", "5 级 Likert"]],
            "data_types": ["interview"],
        }, root)
        ok(not r["error"], "⓪ 能跑通", r["error"])
        alerts = r["result"].get("alerts") or []
        msgs = " | ".join(a.get("msg", "") for a in alerts)
        ok(any("了解" in a.get("msg", "") for a in alerts), "研究目的的提醒出来了：%s" % msgs[:80])
        ok(any("人太少" in a.get("msg", "") for a in alerts), "样本量的提醒出来了")
        ok(all(a.get("source") for a in alerts), "每条提醒都带依据")
        ok(any("行业惯例" in json.dumps(a, ensure_ascii=False) or a.get("kind") == "convention"
               for a in alerts), "带出了「行业惯例」这个类型标记")
        # 简报照样要写出来——提醒不等于拦住
        brief = open(os.path.join(root, "contracts", "research_brief.md"), encoding="utf-8").read()
        ok("了解用户为什么不愿意升级" in brief, "提醒归提醒，简报照写（不拦人）")

        r2 = run_block("b0_brief", {
            "background": "验证写对了就不啰嗦。",
            "purpose": "识别影响用户续费意愿的关键因素",
            "rqs": "- RQ1 因素：哪些因素影响续费",
            "hypotheses": "",
            "population": "招募 10 位受访者做深访",
            "variables_rows": [["付费意愿", "因变量", "定序", "5 级 Likert"]],
            "data_types": ["interview"],
        }, root)
        a2 = r2["result"].get("alerts") or []
        kb2 = [a for a in a2 if a.get("kind") in ("convention", "heuristic", "opinion")]
        eq(kb2, [], "写对了就不该有知识库提醒（只留真正的问题）")

        # 空小节（占位）不该被当成「解析失败」—— 这里守的是误报，
        # 而且注意占位可能写成长句（`（未填。质性研究可以没有假设；……）`），别用长度去认
        r3 = run_block("b0_brief", {
            "background": "验证空小节不误报。",
            "purpose": "识别影响续费的关键因素",
            "rqs": "- RQ1 因素：哪些因素",
            "hypotheses": "",                      # 空：简报里会写成一句带解释的占位
            "population": "10 位深访",
            "variables_rows": [["付费意愿", "因变量", "定序", "5 级 Likert"]],
            "data_types": ["interview"],
        }, root)
        tables3 = [t.get("name", "") for t in (r3["result"].get("tables") or [])]
        ok(not [t for t in tables3 if "体检" in t],
           "假设留空不会触发「简报体检」（占位文字不算内容）", tables3)
        eq([a for a in (r3["result"].get("alerts") or []) if a.get("kind") == "convention"], [],
           "而且也不会因此冒出别的提醒")

        # 但真有内容却读不出来时，体检必须报（不能因为修误报把功能修没了）
        bad_dir = os.path.join(root, "故意写坏")
        os.makedirs(os.path.join(bad_dir, "contracts"), exist_ok=True)
        with open(os.path.join(bad_dir, "contracts", "research_brief.md"), "w", encoding="utf-8") as f:
            f.write("# 研究简报\n\n## 6. 关键变量与操作化定义\n"
                    "（这段我用手写，没做成表格）\n满意度：问用户满不满意\n付费意愿：问用户愿不愿意付费\n")
        r4 = run_block("b0_brief", {
            "background": "验证真坏了还是能报出来。",
            "purpose": "识别影响因素",
            "rqs": "- RQ1 因素：哪些因素",
            "variables": "这里写一段没法解析的文字",
            "variables_rows": [],
            "data_types": ["interview"],
        }, bad_dir)
        # 补一个真·解析失败的：手写简报 + 变量表那栏是纯文本
        r5 = run_block("b3_survey_design", {
            "brief": "contracts/research_brief.md", "audience": "全部用户",
            "mode": "online", "minutes": 8, "parts": ["main"],
        }, bad_dir)
        errs5 = [a for a in ((r5["result"] or {}).get("alerts") or []) if a.get("level") == "error"]
        ok(bool(errs5), "手写变量表 → ③ 仍然报得出「一个变量都没读到」", errs5)

        print("\n【7】原则：提醒绝不能变成拦路 —— 不认同也照样跑完全程")
        # 定下的规矩：研究怎么设计是研究者的选择，提醒只是提醒。
        # 这里故意用一个「三条都踩」的设计：目的没法收尾 + 样本量太小 + 人群不合规范，
        # 断言它照样跑完、产物齐全、下游还能继续用。
        root2 = tempfile.mkdtemp(prefix="urw_noblock_")
        try:
            os.makedirs(os.path.join(root2, "contracts"), exist_ok=True)
            os.makedirs(os.path.join(root2, "output"), exist_ok=True)
            rr = run_block("b0_brief", {
                "background": "故意做一个不合格的设计，验证不会被拦住。",
                "purpose": "了解用户的感受",                       # 提醒 1：没法收尾
                "rqs": "- RQ1 感受：用户感受如何",
                "hypotheses": "",
                "population": "只招我们自己的同事，2 人，做深访",      # 提醒 2：样本太小
                "variables_rows": [["满意度", "因变量", "定距", "5 点量表"]],
                "data_types": ["interview"],
            }, root2)
            ok(not rr["error"], "顶着两条提醒，⓪ 照样跑完（没被拦住）", rr["error"])
            brief_p = os.path.join(root2, "contracts", "research_brief.md")
            ok(os.path.exists(brief_p), "简报照样写出来了（产物没被扣下）")
            brief = open(brief_p, encoding="utf-8").read()
            ok("了解用户的感受" in brief, "研究员写的目的原样保留（程序不改他的字）")
            ok("只招我们自己的同事" in brief, "不合规范的人群也原样保留")
            ok(len(rr["result"].get("alerts") or []) >= 2, "提醒该给的都给了")
            # 提醒还要落进简报：一刷新界面就没了，可「我知道这条建议」是研究记录的一部分
            ok("设计提醒" in brief, "提醒写进了简报（不只在界面上闪一下）")
            ok("不是错误" in brief and "有权不采纳" in brief,
               "简报里写明「只是提醒、研究员有权不采纳」——别让留痕变成施压")
            ok("行业惯例" in brief or "经验法则" in brief, "连依据的类型一起留下来了")
            # 下游照旧能读 —— 「不拦」不能只是「不报错」，得真的能用
            r3b = run_block("b3_survey_design", {
                "brief": "contracts/research_brief.md", "audience": "同事",
                "mode": "online", "minutes": 8, "parts": ["main"],
            }, root2)
            ok(not r3b["error"], "③ 照样能读这份简报、照样跑", r3b["error"])
            rows = (r3b["result"].get("tables") or [{}])[0].get("rows") or []
            ok(len(rows) >= 1, "而且真出题了（%d 道），不是空壳" % len(rows))
        finally:
            shutil.rmtree(root2, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【8】招募画像：看行为，不看人口学")
    for p, want_hit in [
        ("25-40 岁，男女各半，本科学历", True),
        ("过去 6 个月内换过项目管理工具的人", False),
        ("过去一年里在网上订过酒店的人", False),
        ("大学生", False),                                   # 没人人口学词，不判
        ("过去一个月用过分期付款的大学生，男女各半", False),      # 有行为词 → 人口学是补充，不报
        ("", False),
    ]:
        res = kb.check_recruit(p)
        eq(bool(res), want_hit, "「%s」→ %s" % (p[:20] or "(空)", "提醒" if want_hit else "安静"))
    r = kb.check_recruit("25-40 岁，男女各半，本科学历")
    ok(r and "行为" in r[0]["fix"], "提醒里给了「换成行为口径」的改法", r[0]["fix"][:40] if r else None)
    ok(r and r[0]["source"], "招募画像这条也带出处")

    print("\n【9】筛选题写法")
    base_items = [{"var": "玩具购买意愿_1"}, {"var": "性别"}]
    res = kb.check_screener(base_items, parts=["screen", "main"])
    ok(any("一道都没生成" in x["msg"] for x in res), "勾了筛选题却没生成 → 报出来", res)
    eq(kb.check_screener(base_items, parts=["main"]), [], "没勾筛选题 → 不啰嗦")
    many = [{"var": "筛%d" % i} for i in range(6)]
    ok(any("超过通用上限" in x["msg"] for x in kb.check_screener(many, parts=["screen"])),
       "筛选题超过 4 道 → 报出来")
    scr = [{"var": "筛选-行为"}, {"var": "筛除-同行", "why": "筛掉竞品和同业从业者"}]
    ok(any("放在最前面" in x["msg"] for x in kb.check_screener(scr, parts=["screen"])),
       "筛除题没排在最前 → 报出来")
    ok(any("是非问法" in x["msg"] for x in
           kb.check_screener([], parts=["screen"], planned="你是否用过记账 App？")),
       "筛选题用了是否问法 → 报出来")
    ok(any("没给别的出路" in x["msg"] for x in
           kb.check_screener([], parts=["screen"], planned="你用过哪些？A 记账 B 预算 C 以上都不是")),
       "「以上都不是」是唯一出路 → 报出来")
    # 给了草稿就不该说「一道都没生成」——那是研究员自己写的
    res2 = kb.check_screener([], parts=["screen"], planned="你是否用过记账 App？")
    ok(not any("一道都没生成" in x["msg"] for x in res2),
       "给了筛选题草稿时，不说「没生成」（防误报）", res2)
    ok(any("其他" in x["fix"] or "补全" in x["fix"] for x in
           kb.check_screener([], parts=["screen"], planned="你用过哪些？A 记账 B 预算 C 以上都不是")),
       "「以上都不是」那条给了具体改法")

    print("\n【10】③ 真跑一遍：勾了筛选题就得说出来")
    root3 = tempfile.mkdtemp(prefix="urw_scr_")
    try:
        os.makedirs(os.path.join(root3, "contracts"), exist_ok=True)
        os.makedirs(os.path.join(root3, "output"), exist_ok=True)
        with open(os.path.join(root3, "contracts", "research_brief.md"), "w", encoding="utf-8") as f:
            f.write("# 研究简报\n\n## 6. 关键变量与操作化定义\n\n"
                    "| 变量 | 角色 | 测量层次 | 操作化定义 |\n|---|---|---|---|\n"
                    "| 付费意愿 | 因变量 | 定序 | 5 级 Likert |\n")
        r6 = run_block("b3_survey_design", {
            "brief": "contracts/research_brief.md", "audience": "近 90 天活跃、未开通会员的用户",
            "mode": "online", "minutes": 8, "parts": ["screen", "main"],
        }, root3)
        ok(not r6["error"], "③ 能跑通", r6["error"])
        al = [a for a in ((r6["result"] or {}).get("alerts") or []) if a.get("kind") == "convention"]
        ok(any("筛选题" in a.get("msg", "") for a in al),
           "结果里带出了「勾了筛选题却没生成」的提醒", [a.get("msg", "")[:36] for a in al])
        # 提醒归提醒：题项还是照出
        rows6 = (r6["result"].get("tables") or [{}])[0].get("rows") or []
        ok(len(rows6) >= 1, "题项照样出（不因为提醒就不干活）", len(rows6))
    finally:
        shutil.rmtree(root3, ignore_errors=True)

    print("\n【11】访谈技巧：采纳的进来了、没采纳的别混进来")
    tr, terr = kb.load("访谈技巧.md", with_error=True)
    eq(terr, "", "访谈技巧那份知识文件解析正常")
    dig = kb._ns(tr, "probe_dig")
    resp = kb._ns(tr, "probe_resp")
    con = kb._ns(tr, "probe_con")
    ok(bool(dig.get("script")), "故事挖掘有可照读的脚本")
    ok(len(resp.get("how") or []) >= 3, "语气回应给了具体动作", resp.get("how"))
    ok(any("停" in x for x in (resp.get("how") or [])), "语气回应里包含「停一下」")
    # 明确说不采纳「Oh?」——它只能在人读的说明里出现，绝不能进机器读的规则，
    # 否则程序/模型可能照着那条字面去用（规则里出现 = 它会被当成技巧）。
    all_txt = ""
    for f in kb.list_files():
        all_txt += open(f["path"], encoding="utf-8").read()
    ok("Oh?" in all_txt, "「Oh?」写在「不采纳」的说明里（这是对的，人看得见决策）")
    rule_txt = json.dumps([kb.load(f["name"]) for f in kb.list_files()], ensure_ascii=False)
    ok("Oh?" not in rule_txt, "机器读的规则里没有「Oh?」（有的话会被照字面用）")
    ok("60 秒规则" not in all_txt or "原本叫" in all_txt,
       "「60 秒规则」只以「原来叫什么」的形式出现，不是当成规则在说")

    print("\n【12】统计判定：阈值能改、流程只读、缺了要报")
    sr, serr = kb.stats_rules()
    eq(serr, "", "统计判定那份知识文件解析正常")
    st = kb._ns(sr, "stats")
    eq(st.get("regression.vif_serious"), 10, "VIF 严重阈值读到了")
    eq(st.get("regression.dw_low"), 1.5, "DW 下界读到了")
    ok(st.get("ordinal_scale.min_n"), "有序量表判据读到了", st.get("ordinal_scale"))
    eq(kb.check_stats_rules(sr, serr), [], "规则齐了就不报")
    ok(kb.check_stats_rules({}, "文件没了"), "规则缺了要报出来", kb.check_stats_rules({}, "文件没了"))

    print("\n【13】访谈备忘真的用上了知识库里的技巧")
    root4 = tempfile.mkdtemp(prefix="urw_tip_")
    try:
        os.makedirs(os.path.join(root4, "contracts"), exist_ok=True)
        os.makedirs(os.path.join(root4, "output"), exist_ok=True)
        with open(os.path.join(root4, "contracts", "research_brief.md"), "w", encoding="utf-8") as f:
            f.write("# 研究简报\n\n## 2. 研究目的\n一句话目的：识别影响续费的因素\n\n"
                    "## 3. 研究问题（RQ）\n- RQ1 因素：哪些因素影响续费\n\n"
                    "## 6. 关键变量与操作化定义\n\n"
                    "| 变量 | 角色 | 测量层次 | 操作化定义 |\n|---|---|---|---|\n"
                    "| 续费意愿 | 因变量 | 定序 | 5 级 Likert |\n")
        rg = run_block("b1_guide", {
            "brief": "contracts/research_brief.md", "minutes": 45,
            "audience": "近 90 天活跃、未开通会员的用户",   # ① 的必填项，漏了它会直接报错不干活
        }, root4)
        ok(not rg["error"], "① 能跑通", rg["error"])
        g = open(os.path.join(root4, "contracts", "interview_guide.md"), encoding="utf-8").read()
        memo = g.split("## 附：访谈者备忘")[-1] if "访谈者备忘" in g else ""
        ok("故事挖掘" in memo, "备忘里有「故事挖掘」")
        ok("带我走一遍" in memo, "脚本是从知识库来的（能改）")
        ok("语气回应" in memo, "备忘里有「语气回应」")
        ok("停几秒" in memo, "「停一下」那条进来了")
        ok("追问三板斧" not in memo, "旧的三板斧已经被换成知识库那套（不重复）")
        ok("沉默 3 秒" not in memo or "停几秒" in memo, "旧的「沉默 3 秒」说法已并入语气回应")
    finally:
        shutil.rmtree(root4, ignore_errors=True)

    print("\n【14】研究策略：方法选错要报、选对了别啰嗦")
    sr2, serr2 = kb.load("研究策略.md", with_error=True)
    eq(serr2, "", "研究策略那份知识文件解析正常")
    st2 = kb._ns(sr2, "strategy")
    ok(st2.get("methods"), "方法对照表读到了（%d 个方法）" % len(st2.get("methods") or []))
    ok(st2.get("priority_frameworks"), "优先级框架表读到了")
    for t, want in [("想了解用户平时怎么用这个功能，做深访", True),
                    ("想知道用户真实使用行为，做半结构深访", True),
                    ("想知道用户对定价的看法，做深访", False),
                    ("想看用户实际操作流程，做情境访谈和实地观察", False),
                    ("这个功能好不好用，做可用性测试", False)]:
        res = kb.check_method_fit(t)
        eq(bool(res), want, "「%s」→ %s" % (t[:18], "提醒" if want else "安静"))
    res = kb.check_priority_framework("这个功能好不好用，用户找不到入口")
    ok(res and "排序" in res[0]["msg"], "识别出可用性目标 → 提醒定排序标准", res)
    eq(kb.check_priority_framework("这批访谈做完要出结论"), [],
       "识别不出目标类型 → 不硬猜（宁可不报）")

    print("\n【15】提纲里带上沙漏结构与收尾三件套")
    root5 = tempfile.mkdtemp(prefix="urw_arc_")
    try:
        os.makedirs(os.path.join(root5, "contracts"), exist_ok=True)
        os.makedirs(os.path.join(root5, "output"), exist_ok=True)
        with open(os.path.join(root5, "contracts", "research_brief.md"), "w", encoding="utf-8") as f:
            f.write("# 研究简报\n\n## 2. 研究目的\n一句话目的：识别影响续费的因素\n\n"
                    "## 3. 研究问题（RQ）\n- RQ1 因素：哪些因素影响续费\n\n"
                    "## 6. 关键变量与操作化定义\n\n"
                    "| 变量 | 角色 | 测量层次 | 操作化定义 |\n|---|---|---|---|\n"
                    "| 续费意愿 | 因变量 | 定序 | 5 级 Likert |\n")
        ra = run_block("b1_guide", {"brief": "contracts/research_brief.md", "minutes": 45,
                                    "audience": "近 90 天活跃、未开通会员的用户"}, root5)
        ok(not ra["error"], "① 能跑通", ra["error"])
        gg = open(os.path.join(root5, "contracts", "interview_guide.md"), encoding="utf-8").read()
        memo = gg.split("## 附：访谈者备忘")[-1] if "访谈者备忘" in gg else ""
        ok("沙漏" in memo, "备忘里有沙漏结构")
        ok("开场那条最要紧" in memo or "问「事」不问「观点」" in memo, "有「开场问事不问观点」这条")
        ok("总结确认" in memo, "收尾三件套里有「总结确认」")
        ok("魔法棒" in memo, "有「魔法棒」")
        ok("转介绍" in memo, "有转介绍（滚雪球抽样的起点）")
    finally:
        shutil.rmtree(root5, ignore_errors=True)

    print("\n" + ("全部通过" if FAIL[0] == 0 else "有失败项") + "：%d 通过 / %d 失败\n"
          % (PASS[0], FAIL[0]))
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
