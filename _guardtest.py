# -*- coding: utf-8 -*-
"""入口守卫（🔒 去标识化那道关）· 专项自检

**为什么用临时项目**：守卫会往项目里写确认记录和登记表。
在工作台自己的案例项目上跑，会污染那两个文件（踩过一次：自检把案例数据洗了）。
所以这里全部在 %TEMP% 下现建一个小项目。

跑法：  python _guardtest.py
"""
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import guard, registry                      # noqa: E402
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
    ok(same, label, None if same else "实际是 %r，期望 %r" % (a, b))


def run_block(block_id, params, project_root):
    """按 runner 的规矩跑一个组块（和 _selftest 里那套一样）。"""
    import subprocess
    job = dict(params)
    job["project_root"] = project_root
    job["block_dir"] = os.path.join(HERE, "blocks", block_id)
    job["block_id"] = block_id
    jf = os.path.join(project_root, "_job.json")
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
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


RAW = """访谈记录（模拟）
访谈者：李 researcher
受访者：张伟
联系方式：13812345678，邮箱 zhangwei@example.com
张伟：我用这个 App 大概两年了，去年还在杭州那边上班。
"""

CLEAN = """访谈记录（已脱敏）
访谈者：[姓名1]
受访者：[姓名2]
联系方式：[手机1]，邮箱 [邮箱1]
[姓名2]：我用这个 App 大概两年了，去年还在 [城市1] 那边上班。
"""

PLAIN = """# 研究简报
本研究想看免费工具 App 的付费转化。目标人群：一二线城市上班族。
"""


def build_project(with_clean=True, with_raw=True, with_registry=False, with_ack=False):
    root = tempfile.mkdtemp(prefix="urw_guard_")
    proj = Project(root)
    proj.ensure()
    for sub in ("data", "samples", "output", "contracts"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    if with_raw:
        with open(os.path.join(root, "samples", "访谈转写稿_张伟.txt"), "w", encoding="utf-8") as f:
            f.write(RAW)
    if with_clean:
        with open(os.path.join(root, "samples", "脱敏_访谈转写稿_张伟.txt"), "w", encoding="utf-8") as f:
            f.write(CLEAN)
    with open(os.path.join(root, "contracts", "research_brief.md"), "w", encoding="utf-8") as f:
        f.write(PLAIN)
    # 嵌套子目录：素材常被分类放，只扫一层会漏
    os.makedirs(os.path.join(root, "data", "2026-03"), exist_ok=True)
    if with_raw:
        with open(os.path.join(root, "data", "2026-03", "深访_王芳.txt"), "w", encoding="utf-8") as f:
            f.write("王芳：我的微信是 wangfang1988，电话 13900001111。\n")
    if with_registry:
        guard.register(root, "samples/访谈转写稿_张伟.txt",
                       "output/脱敏_访谈转写稿_张伟.txt", [("手机号", "13812345678", "[手机1]", 1, "high")])
    if with_ack:
        guard.ack(root, {"id": "b2_coding", "name": "访谈记录编码整理", "title": "② 访谈记录编码整理"},
                  ["data/2026-03/深访_王芳.txt"], note="这批是模拟数据")
    return root


def main():
    blocks = registry.load_blocks()
    by_id = {b["id"]: b for b in blocks}

    print("\n【1】声明：哪些组块该被这道关看着")
    ok(by_id["b9_deident"].get("guard") is False, "🔒 自己不被自己拦（不然没法干活）")
    ok(by_id["b0_brief"].get("guard") in (None, False), "⓪ 研究设计不拦（它只读表单）")
    for bid in ("b1_guide", "b2_coding", "b2b_codesum", "b3_survey", "b4_prep", "b5_stats"):
        ok(by_id[bid].get("guard") is True, "%s 受守卫管" % bid)

    print("\n【2】扫得出「没脱敏的素材」，而且认得准")
    root = build_project()
    try:
        mats = guard.scan(Project(root))
        rels = [m["rel"] for m in mats]
        eq(len(mats), 2, "两份原始素材被认出来")
        ok("samples/访谈转写稿_张伟.txt" in rels, "samples 下那份认出来了")
        ok("data/2026-03/深访_王芳.txt" in rels, "嵌套子目录里那份也认出来了（不只扫一层）")
        ok("samples/脱敏_访谈转写稿_张伟.txt" not in rels, "带「脱敏_」前缀的跳过")
        ok("contracts/research_brief.md" not in rels, "简报里没有直接标识符，不误报")
        m0 = [m for m in mats if m["rel"].endswith("访谈转写稿_张伟.txt")][0]
        labels = sorted(h["label"] for h in m0["hits"])
        eq(labels, ["手机号", "邮箱"], "命中类型对得上")
        ok(any("13812345678" in (h["sample"] or "") or "zhangwei" in (h["sample"] or "")
               for h in m0["hits"]), "样例里带了命中的原文（好认）")

    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【3】登记表 = 「这份处理过了」的证据")
    root = build_project(with_registry=True)
    try:
        mats = guard.scan(Project(root))
        rels = [m["rel"] for m in mats]
        ok("samples/访谈转写稿_张伟.txt" not in rels, "登记过的源文件不再被摆出来")
        ok("data/2026-03/深访_王芳.txt" in rels, "没登记的那份还是会被摆出来")
        # 登记表里那条要能读出「脱敏件在哪」
        reg = guard.read_json(Project(root), guard.REGISTRY_REL)
        rec = reg["files"]["samples/访谈转写稿_张伟.txt"]
        eq(rec["out_rel"], "output/脱敏_访谈转写稿_张伟.txt", "登记里写了脱敏件路径")
        eq(rec["replaced"], 1, "登记里记了替换几处")
        eq(rec["kinds"], ["手机号"], "登记里记了命中类型")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【4】「我知道，继续」记下来之后就不再问")
    root = build_project(with_ack=True)
    try:
        mats = guard.scan(Project(root))
        rels = [m["rel"] for m in mats]
        ok("data/2026-03/深访_王芳.txt" not in rels, "确认过的素材不再被摆出来")
        ok("samples/访谈转写稿_张伟.txt" in rels, "没确认过的那份照旧")
        ack = guard.read_json(Project(root), guard.ACK_REL)
        rec = ack["files"]["data/2026-03/深访_王芳.txt"]
        ok(rec.get("note") == "这批是模拟数据", "确认理由记进去了")
        ok(rec.get("at"), "记了时间")
        ok(os.path.exists(os.path.join(root, guard.ACK_REL.replace("/", os.sep))),
           "确认记录真的落在项目目录里（能被审计）")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【5】守卫本体：该问的问、不该问的别问")
    root = build_project()
    try:
        g = guard.guard_for(by_id["b2_coding"], root)
        ok(g["need"] is True, "② 有个没脱敏的素材 → 拦一下")
        eq(g["total"], 2, "拦的时候列出两份")
        ok("标识符" in g["why"], "给了理由（说清为什么拦）")

        g2 = guard.guard_for(by_id["b9_deident"], root)
        ok(g2["need"] is False, "🔒 自己去跑不被拦")

        g3 = guard.guard_for(by_id["b0_brief"], root)
        ok(g3["need"] is False, "⓪ 不被拦")

        # 表单里明确挑了 output 下的文件：那也要看一眼
        proj = Project(root)
        with open(os.path.join(root, "output", "手工整理.txt"), "w", encoding="utf-8") as f:
            f.write("联系人手机 13700007777\n")
        g4 = guard.guard_for(by_id["b2_coding"], root, {"transcript": "output/手工整理.txt"})
        rels4 = [m["rel"] for m in g4["materials"]]
        ok("output/手工整理.txt" in rels4, "研究员明确挑了 output 里的文件 → 照样看一眼")
        # 没挑的时候，output 里的产物不参与扫描
        g5 = guard.guard_for(by_id["b2_coding"], root, {})
        rels5 = [m["rel"] for m in g5["materials"]]
        ok("output/手工整理.txt" not in rels5, "没挑它的时候，output 里的产物不参与扫描")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【6】干净项目：一句废话都不说")
    root = build_project(with_raw=False, with_clean=False)
    try:
        g = guard.guard_for(by_id["b5_stats"], root)
        ok(g["need"] is False, "没有敏感素材 → 不打扰")
        s = guard.summary_for_ui(root)
        eq(s["registered"], 0, "没登记过")
        eq(s["acked"], 0, "没确认过")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【7】确认记录别无限长大")
    root = build_project()
    try:
        proj = Project(root)
        for i in range(guard.MAX_ACK + 12):
            fn = "data/f%03d.txt" % i
            with open(os.path.join(root, fn.replace("/", os.sep)), "w", encoding="utf-8") as f:
                f.write("手机 1380000%04d\n" % i)
            guard.ack(root, None, [fn], note="批量测试")
        ack = guard.read_json(proj, guard.ACK_REL)
        eq(len(ack["files"]), guard.MAX_ACK, "确认记录封顶在 %d 条" % guard.MAX_ACK)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【8】坏文件不该把守卫拖死")
    root = build_project(with_raw=False, with_clean=False)
    try:
        with open(os.path.join(root, "data", "坏编码.txt"), "wb") as f:
            f.write(b"\xff\xfe\x00\x01\x02\x03 not utf8 \x80\x81")
        with open(os.path.join(root, "data", "带手机.txt"), "w", encoding="utf-8") as f:
            f.write("电话 13611112222\n")
        mats = guard.scan(Project(root))
        rels = [m["rel"] for m in mats]
        ok("data/带手机.txt" in rels, "坏文件旁边的正常文件照样能认出来")
        ok(True, "读不了的文件没让守卫抛异常")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【9】脱敏不能漏掉受访者的名字（走查时抓到的严重 bug）")
    # 现场：转写稿最常见的写法「受访者：林小雨，女，20岁，…」——
    # 规则明明抓到了「林小雨」，却因为「林」不在姓氏表里被丢掉，
    # 于是脱敏稿里**受访者的真名原样留着**，手机号学号都换了、名字没换。
    # 修法是：有明确角色标记时直接采信，不要用姓氏表二次否决。
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "de_engine", os.path.join(HERE, "blocks", "b9_deident", "engine.py"))
    de = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(de)
    ok("林" in de.SURNAME, "「林」这类常见姓在姓氏表里（原来缺了它）")

    def names_in(t):
        out = []
        for idx, pat in enumerate(de.NAME_PATTERNS):
            contextual = (idx == 4)
            for m in re.finditer(pat, t, flags=re.M):
                nm = m.group(1)
                if len(nm) < 2:
                    continue
                if not contextual and nm[0] not in de.SURNAME:
                    continue
                out.append(nm)
        return out

    for t in ["受访者：林小雨，女，20岁，大二",
              "被访者：欧阳雪，24岁",
              "访谈对象：苏芮"]:
        got = names_in(t)
        ok(bool(got), "带角色标记的名字抓得到：「%s」→ %s" % (t[:16], got))
    eq(names_in("我们学校挺大的，我觉得还好"), [], "普通句子不会误抓成人名")
    eq(names_in("受访者：我"), [], "一个字的不当名字")

    print("\n【10】端到端：脱敏稿里受访者名字必须没了")
    root = build_project(with_raw=False, with_clean=False)
    try:
        src = ("访谈时间：2026年3月12日\n采访者：李明\n"
               "受访者：林小雨，女，20岁，大二，学号 2024010338，电话 13812345678\n"
               "李明：那我们就开始吧。\n林小雨：好。\n")
        with open(os.path.join(root, "samples", "转写稿.txt"), "w", encoding="utf-8") as f:
            f.write(src)
        r = run_block("b9_deident", {"file": "samples/转写稿.txt",
                                     "keep_mapping": ["mapping"]}, root)
        ok(not r.get("error"), "脱敏跑通", r.get("error"))
        out = open(os.path.join(root, "output", "脱敏_转写稿.txt"), encoding="utf-8").read()
        for k in ("林小雨", "李明", "13812345678", "2024010338"):
            ok(k not in out, "脱敏稿里没有「%s」" % k)
        ok("[姓名" in out, "换成了姓名占位")
        ok("13812345678" not in out and "[手机" in out, "手机号换成了手机占位")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + ("全部通过" if FAIL[0] == 0 else "有失败项") + "：%d 通过 / %d 失败\n" % (PASS[0], FAIL[0]))
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
