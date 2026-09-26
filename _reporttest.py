# -*- coding: utf-8 -*-
"""报告汇总 + 产物分层 · 专项自检

守两件事：
  1. **产物分层**：研究员自己标的「关键结果」在前，中间件折叠在后；
     标了要能取消、不能凭空标不存在的文件、备注不会被静默清空
  2. **报告汇总**：只搬运 + 标来源，**不产生任何新结论**；数字能顺着文件名回查

跑法：  python _reporttest.py
"""
import io
import os
import re
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import report as R                          # noqa: E402
from core.project import Project                      # noqa: E402

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


def seed(proj):
    os.makedirs(proj.safe("contracts"), exist_ok=True)
    os.makedirs(proj.safe("output"), exist_ok=True)
    proj.write_text("contracts/research_brief.md",
                    "# 研究简报\n\n## 2. 研究目的\n识别影响续费的关键因素\n\n"
                    "## 6. 关键变量与操作化定义\n\n| 变量 | 角色 |\n|---|---|\n| 续费意愿 | 因变量 |\n")
    proj.write_text("contracts/interview_guide.md", "# 访谈提纲\n\n## 1. 暖场\n聊聊你平时怎么用\n")
    proj.write_text("output/问卷_概要.md", "# 问卷概要\n\n样本 240 份，有效 216 份。\n")
    proj.write_text("output/预处理日志.md", "# 预处理日志\n\n缺失值 3 个，反向题 2 道已重编码。\n")
    proj.write_text("output/分析报告_回归_续费意愿.md",
                    "# 回归分析\n\nR²=0.399，F=13.58，n=216。价格敏感度 β=-0.307。\n")
    proj.write_text("output/分析报告_描述统计.md", "# 描述统计\n\n均值、标准差见下。\n")
    proj.write_text("output/问卷_频数_性别.csv", "性别,n\n男,90\n女,126\n")
    proj.write_text("output/分析_语法.sps", "REGRESSION\n  /DESCRIPTIVES MEAN STDDEV\n")


def main():
    root = tempfile.mkdtemp(prefix="urw_rep_")
    try:
        proj = Project(root)
        proj.ensure()
        seed(proj)
        KEY = "output/分析报告_回归_续费意愿.md"

        print("\n【1】没标之前：**按约定自动分**（改过：原来必须手动 ⭐ 才算核心）")
        # ⚠ 这一节原来断言"关键结果是空的" —— 那个行为在 2026-09-24 改掉了：
        #   前辈提「需要编辑或分析时必须看的信息的核心产出，不要放在过程产物里」，
        #   于是有了 core/report.py: key_reason() 这套**按约定自动归**的规则。
        #   契约、分析报告、问卷概要这类天生在主干上的产物，现在自己就在前面。
        c = R.classify(proj)
        key_rels = sorted(a["rel"] for a in c["key"])
        eq(key_rels, sorted([
            "contracts/research_brief.md", "contracts/interview_guide.md",
            "output/问卷_概要.md", "output/分析报告_回归_续费意愿.md",
            "output/分析报告_描述统计.md"]),
            "自动归到核心产出的是这 5 个（2 契约 + 2 分析报告 + 问卷概要）")
        eq(c["flagged"], 0, "手动标的仍然是 0 个（还没点过 ⭐）")
        eq(c["auto"], 5, "其中自动归的 5 个")
        eq(sorted(a["rel"] for a in c["other"]),
           sorted(["output/预处理日志.md", "output/问卷_频数_性别.csv", "output/分析_语法.sps"]),
           "过程产物是这 3 个（预处理日志 / 频数表 / SPSS 语法）")
        ok(all(a["auto_why"] for a in c["key"]), "每个自动归的都带一句**理由**（界面 title 上显示）")
        ok(all(not a["manual"] for a in c["key"]), "自动归的不算「手动标的」")
        # 逐条核理由，别只核"有几个"
        why = dict((a["rel"], a["auto_why"]) for a in c["key"])
        ok("契约" in why["contracts/research_brief.md"], "契约的理由说的是契约",
           why["contracts/research_brief.md"])
        ok("报告" in why["output/分析报告_回归_续费意愿.md"], "分析报告的理由说的是报告正文",
           why["output/分析报告_回归_续费意愿.md"])
        ok(R.key_reason("output/预处理日志.md") == "",
           "**诊断件（预处理日志）不自动进核心** —— 它也叫「日志」",
           R.key_reason("output/预处理日志.md"))
        ok(R.key_reason("output/分析_语法.sps") == "", "SPSS 语法是过程产物（复核用，不是要看的东西）")
        ok(R.key_reason("output/问卷_频数_性别.csv") == "",
           "频数表是过程产物（报告从它取数，但不需要你逐条编辑）")
        ok(R.key_reason("output/编码工作表.csv") != "",
           "**编码工作表自动进核心产出**（前辈点名的那一类：要打开来逐段编辑）",
           R.key_reason("output/编码工作表.csv"))
        ok(R.key_reason("output/_history/旧版.md") == "", "_history 里的旧版不凑热闹")
        ok(R.key_reason("契约.md") == "" and R.key_reason("") == "", "边界：根目录的散文件/空路径不自动归")

        print("\n【2】标一个 → 手动标记和自动归类是**两回事**")
        r = R.toggle_flag(proj, KEY, True, note="主结论")
        ok(r.get("ok"), "标上了", r)
        eq(r["count"], 1, "手动计数是 1")
        c2 = R.classify(proj)
        eq(c2["flagged"], 1, "手动标的 1 个")
        eq(c2["auto"], 4,
           "剩下的 4 个仍算自动归（KEY 现在归手动那一份，auto 就少一个）")
        eq(len(c2["key"]), 5, "两层合起来还是这 5 个（KEY 本来就在自动那批里，不重复）")
        man = [a["rel"] for a in c2["key"] if a["manual"]]
        eq(man, [KEY], "手动那一份标出来了")
        eq(c2["key"][0]["note"] if c2["key"][0]["rel"] == KEY else
           [a for a in c2["key"] if a["rel"] == KEY][0]["note"], "主结论", "备注带出来了")
        ok(os.path.exists(proj.safe(R.FLAGS_REL)), "标记落在 output/关键结果.json")
        # 一个**不在**自动那批里的产物，标了也要进核心
        OTHER = "output/分析_语法.sps"
        R.toggle_flag(proj, OTHER, True, note="复核用")
        c2b = R.classify(proj)
        ok(OTHER in [a["rel"] for a in c2b["key"]],
           "手动标的能把**自动归不进来**的产物提到核心产出")
        eq(c2b["key"][[a["rel"] for a in c2b["key"]].index(OTHER)]["manual"], True, "而且标着是手动的")

        print("\n【3】备注不会被静默清空；取消标记则整条记录都撤掉")
        R.toggle_flag(proj, KEY, True)
        eq(R.load_flags(proj)[KEY]["note"], "主结论",
           "记录还在时重标（没填备注）→ 已有备注留着")
        R.toggle_flag(proj, KEY, True, note="改了备注")
        eq(R.load_flags(proj)[KEY]["note"], "改了备注", "填了新备注就换成新的")
        R.toggle_flag(proj, KEY, True, note="主结论")
        R.toggle_flag(proj, OTHER, False)
        eq(R.load_flags(proj).get(OTHER), None, "取消标记 → 整条记录撤掉（连备注一起）")
        R.toggle_flag(proj, KEY, False)
        eq(R.classify(proj)["flagged"], 0, "手动标记全撤掉后，flagged 归零")
        eq(len(R.classify(proj)["key"]), 5,
           "**但自动归的那 5 个还在核心产出里**（取消 ⭐ 不等于把它从前面挪走）")
        R.toggle_flag(proj, KEY, True, note="主结论")

        print("\n【4】边界：不存在的产物标不上、路径不能越界")
        # ⚠ 用**前后对比**而不是假定一个数：这一节只是要证"越界/不存在的操作没改动标记表"，
        #   假设一个具体值会把上一节留下的状态也一起断言进去（踩过一次，假红）。
        before_flags = len(R.load_flags(proj))
        ok(not R.toggle_flag(proj, "output/没这个文件.md", True).get("ok"),
           "不存在的文件 → 拒绝")
        eq(R.toggle_flag(proj, "", True).get("ok"), False, "空路径 → 拒绝")
        outside = os.path.join(os.path.dirname(root), "urw_越界测试.txt")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("不该被碰到\n")
        try:
            rb = R.toggle_flag(proj, "../urw_越界测试.txt", True)
            ok(not rb.get("ok"), "越界路径被拒（说找不到这个产物）", rb)
        except Exception as e:
            ok(True, "越界路径被抛异常拦住：%s" % type(e).__name__)
        finally:
            with open(outside, encoding="utf-8") as f:
                ok(f.read().strip() == "不该被碰到", "项目外的文件没被改动")
            try:
                os.remove(outside)
            except OSError:
                pass
        # ⚠ 这里核的是**"标记表有没有被污染"**，所以看手动标记数，别看 key 的总数 ——
        #   key 里还混着"按约定自动归"的那批，拿总数断言会随规则变化而假红（刚踩过）。
        eq(len(R.load_flags(proj)), before_flags,
           "越界/不存在的操作**没改动标记表**（前后都是 %d 条）" % before_flags)

        print("\n【5】报告汇总：按骨架串，每个来源可回查")
        r2 = R.write(proj, title="测试研究")
        ok(r2.get("ok"), "汇总生成了", r2)
        md = proj.read_text(R.REPORT_REL)
        for sec in ["背景与研究问题", "方法、提纲与问卷", "数据与预处理", "分析结果", "这份研究哪里不硬"]:
            ok(("## " + sec) in md, "有「%s」这一节" % sec)
        ok("分析报告_回归_续费意愿.md" in md, "发现那一节把回归报告串进来了")
        ok("问卷_概要.md" in md and "预处理日志.md" in md, "数据与预处理那一节串进来了")

        print("\n【6】硬线：不产生新结论、不新增数字")
        ok("不会替你写结论" in md or "不会新增任何数字" in md,
           "报告开头自己声明了「只搬运不写结论」")
        nums_in_md = set(re.findall(r"\d+\.\d+", md))
        src = ""
        for f in ["output/分析报告_回归_续费意愿.md", "output/问卷_概要.md",
                  "output/预处理日志.md", "contracts/research_brief.md"]:
            src += proj.read_text(f)
        src_nums = set(re.findall(r"\d+\.\d+", src))
        eq(sorted(nums_in_md - src_nums), [],
           "报告里的小数没有一个是不在源文件里的（%d 个数字全部可回查）" % len(nums_in_md))
        for w in ["因此我们建议", "本研究证明", "建议立即", "综上所述，我们应当"]:
            ok(w not in md, "没有「%s」这类替你下结论的措辞" % w)

        print("\n【7】标了 ⭐ 的会在报告里被标出来")
        r3 = R.write(proj)
        md3 = proj.read_text(R.REPORT_REL)
        ok("⭐" in md3, "标记过的产物在报告里有 ⭐")
        ok("主结论" in md3, "备注也带进报告了")
        ok(r3["stat"]["flagged"] >= 1, "统计里记了标记数", r3["stat"])

        print("\n【8】产物少的时候也不炸、空项目也不炸")
        empty = Project(tempfile.mkdtemp(prefix="urw_rep0_"))
        empty.ensure()
        eq(R.classify(empty)["total"], 0, "空项目的产物数是 0")
        r4 = R.write(empty)
        ok(r4.get("ok"), "空项目也能生成（不会崩）", r4)
        md4 = empty.read_text(R.REPORT_REL)
        ok("这一步还没有产物" in md4, "空的地方明确写「还没有产物」，不是空白")
        eq(R.classify(empty)["total"], 1, "生成之后多出来的那个产物就是报告本身")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + ("全部通过" if FAIL[0] == 0 else "有失败项") + "：%d 通过 / %d 失败\n"
          % (PASS[0], FAIL[0]))
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
