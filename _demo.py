# -*- coding: utf-8 -*-
"""一个三秒钟跑完、五分钟看完的演示：**从一份刚回收的问卷，到一个能写进报告的结论**。

    双击 `试一下_演示.bat`
或：python _demo.py

## 它做什么

不用打开浏览器、不用先建项目 —— 它自己起一个小项目，把三件事跑给你看：

    ⑤ 数据预处理   →   ⑥ 统计分析   →   把结果抄给你看

跑完你会看到（**都是真算出来的数，不是写死的**）：

  · ⑥ 的**决策树**：为什么选了 t 检验、为什么不用 Mann-Whitney、前提检验结果
  · **结论 + 95% 置信区间 + 效应量**（不是只给一个 p 值）
  · 一道 **SPSS 语法**（同一件事在 SPSS 里怎么复现，用来交叉核对）
  · 它主动报出来的缺失与异常值（以及**它没有替你填、没有替你删**）

⚠ 名字叫"五分钟"是指**看完**要五分钟；机器跑只要几秒。
   跑得快本身就是这套东西想证明的事：算数不该是瓶颈，判断才是。

## 为什么不用服务器

它直接调 `runner.py`（引擎子进程）。

⚠ 这一点很重要：**如果演示要求先开服务，那演示本身就是一道门槛** ——
   服务没开、端口被占、浏览器没刷新，任何一步都能让人卡在那儿。
   而"能不能读懂这个项目"不该被这种事挡住。

## 数据是哪来的

`_demo_data.py` 现场算出来的合成问卷（412 份），
里面**故意埋了一条真实的因果链**：Android 因为崩溃率高 → 满意度更低。
所以整条链跑出来是有话可说的，不是一堆「不显著」。

数据**不进版本库**（见 .gitignore）—— 仓库里只放"怎么造"。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ⚠ 控制台是 GBK：这个脚本要打印 ✓ ★ → 之类，必须自己兜一下
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJ = os.path.join(HERE, "_jobs", "demo_project")
LINE = "─" * 74


# ---------------------------------------------------------------------------
#  说话的方式
# ---------------------------------------------------------------------------

def h1(text):
    print("")
    print("=" * 74)
    print("  " + text)
    print("=" * 74)


def h2(text):
    print("")
    print("【%s】" % text)
    print(LINE)


def say(text=""):
    print(text)


def pause(sec=0.35):
    time.sleep(sec)


# ---------------------------------------------------------------------------
#  调引擎（直连 runner，不经过服务器）
# ---------------------------------------------------------------------------

def run_block(block_id, params):
    """跑一个组块，返回解析好的事件。"""
    job = dict(params)
    job["project_root"] = PROJ
    job["block_dir"] = os.path.join(HERE, "blocks", block_id)
    job["block_id"] = block_id

    jf = os.path.join(HERE, "_jobs", "demo_%s.json" % block_id)
    os.makedirs(os.path.dirname(jf), exist_ok=True)
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # stdin 给 DEVNULL：没人应答检查点时，引擎会**按默认值继续**，不会卡住
    p = subprocess.run([sys.executable, os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE,
                       stdin=subprocess.DEVNULL, timeout=600)

    out = p.stdout.decode("utf-8", "replace")
    logs, result, error, asks, steps = [], None, "", [], []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        t = m.get("t")
        if t == "log":
            logs.append((m.get("level", "info"), m.get("msg", "")))
        elif t == "result":
            result = m.get("data")
        elif t == "error":
            error = m.get("msg", "")
        elif t == "ask":
            asks.append(m)
        elif t == "step":
            steps.append(m)

    if p.stderr.strip():
        logs.append(("stderr", p.stderr.decode("utf-8", "replace")[:400]))

    return {"logs": logs, "result": result or {}, "error": error,
            "asks": asks, "steps": steps}


def show_logs(events, keep=("warn", "error"), limit=6):
    """把引擎的提醒挑出来给人看（info 级的过程日志跳过，太吵）。

    ⚠ 过滤掉「（没人应答，按默认…继续）」—— 那是**演示脚本自己**造成的
      （它没接 stdin，检查点自动走默认值）。对人来说这是噪音，
      而且会让人以为工作台出错了。真在界面上跑时，检查点会停下来问人。
    """
    picked = []
    for lv, m in events["logs"]:
        if lv not in keep or not m.strip():
            continue
        if "没人应答" in m:
            continue
        picked.append(m)
    for m in picked[:limit]:
        print("   ⚠ " + m.replace("\n", "\n     "))
    if len(picked) > limit:
        print("   …（还有 %d 条，界面上在「结果页」能逐条看）" % (len(picked) - limit))
    return picked


def find_table(result, *names):
    """按名字找表。给多个候选名 —— 引擎改过表名的话演示不至于静默缺一块。"""
    tables = result.get("tables") or []
    for want in names:
        for t in tables:
            if want in (t.get("name") or ""):
                return t
    return None


def _w(s):
    """显示宽度：中文算两格。"""
    s = "" if s is None else str(s)
    return sum(2 if ord(c) > 0x2000 else 1 for c in s)


def _clip(s, width):
    """按显示宽度截断，末尾加省略号。"""
    s = "" if s is None else str(s)
    if _w(s) <= width:
        return s
    out, used = "", 0
    for ch in s:
        cw = 2 if ord(ch) > 0x2000 else 1
        if used + cw > width - 1:
            break
        out += ch
        used += cw
    return out + "…"


def render_table(tbl, max_rows=14, indent="   ", max_width=104):
    """把一个表格画成文本。

    ⚠ 列宽上限：有些表（尤其决策树）某一列能到 76 个字，直接 print 会折行折成一团。
      所以每列都按显示宽度截断，并在末尾接一句"完整的在产物里"。
    """
    if not tbl:
        return
    cols = tbl.get("columns") or []
    rows = tbl.get("rows") or []
    if not cols:
        return

    def pad(s, width):
        s = _clip(s, width)
        return s + " " * max(0, width - _w(s))

    # 每列宽度：表内最长值，但封顶；然后按比例压到总宽以内
    widths = []
    for i, c in enumerate(cols):
        m = _w(c)
        for r in rows[:max_rows]:
            if i < len(r):
                m = max(m, _w(r[i]))
        widths.append(min(m, 40))
    total = sum(widths) + 2 * (len(widths) - 1)
    if total > max_width:
        over = total - max_width
        while over > 0 and max(widths) > 8:
            i = widths.index(max(widths))
            widths[i] -= 1
            over -= 1

    print(indent + "  ".join(pad(c, widths[i]) for i, c in enumerate(cols)))
    print(indent + "  ".join("─" * widths[i] for i in range(len(cols))))
    for r in rows[:max_rows]:
        print(indent + "  ".join(pad(r[i] if i < len(r) else "", widths[i])
                                 for i in range(len(cols))))
    if len(rows) > max_rows:
        print(indent + "  …（共 %d 行，完整的在产物 CSV 里）" % len(rows))
    note = tbl.get("note")
    if note:
        print(indent + "  注：" + str(note).replace("\n", "\n      "))


def _wrap(text, width):
    """按**显示宽度**折行（中文算两格），返回行列表。"""
    lines, cur = [], ""
    for ch in str(text or ""):
        cw = 2 if ord(ch) > 0x2000 else 1
        if _w(cur) + cw > width and cur:
            lines.append(cur)
            cur = ""
        cur += ch
    lines.append(cur)
    return lines or [""]


def render_kv(tbl, indent="   ", key_w=16, val_w=82):
    """把「两列表」渲染成竖排的 `键：值` —— 长文本这样读舒服得多。

    决策树、检验结果这类表本质上是"一项一项"，横着画会被列宽挤成一团
    （决策树那一列原文有 76 个字）。
    """
    if not tbl:
        return
    for r in (tbl.get("rows") or []):
        if len(r) < 2:
            continue
        k = str(r[0] or "")
        lines = _wrap(r[1], val_w)
        print(indent + k + "：" + lines[0])
        for extra in lines[1:]:
            print(indent + " " * max(_w(k), 4) + "  " + extra)


def render_steps(tbls, indent="   "):
    """把 ⑤ 的「步骤 N」那几张单列表拼成一段人话。"""
    for t in tbls:
        name = t.get("name") or ""
        if not name.startswith("步骤"):
            continue
        for r in (t.get("rows") or []):
            if r:
                print(indent + "· " + str(r[0]))


# ---------------------------------------------------------------------------
#  主流程
# ---------------------------------------------------------------------------

def step_0_prepare():
    h1("第 0 步 · 准备一个演示项目")
    say("演示项目建在这里（可以直接删掉，不影响任何东西）：")
    say("  " + PROJ)
    say("")

    # 每次都重来：演示要可重复，不能受上一次跑的影响
    if os.path.isdir(PROJ):
        shutil.rmtree(PROJ, ignore_errors=True)
    for d in ("data", "samples", "output", "contracts"):
        os.makedirs(os.path.join(PROJ, d), exist_ok=True)

    import _demo_data
    path, df = _demo_data.build(os.path.join(PROJ, "data"))
    say("造了一份合成问卷（412 份），放进 data/sim_survey.csv")
    say("  ⚠ 是**算出来的假数据**，不是真的收了 412 份问卷。")
    say("     它里面故意埋了一条真实的链：Android 崩溃率高 → 满意度低。")
    say("     所以下面跑出来的显著结果是**有东西可说**的，不是一堆「不显著」。")
    say("")
    say("  变量：平台 / 性别 / 年级 / 周使用次数 / 崩溃频率 /")
    say("        Q7_1~Q7_5（满意度五题）/ Q8_1~Q8_3（意愿三题）/ 是否愿意推荐 /")
    say("        注意力检验 / Q10_开放题")
    return df


def step_1_prep():
    h1("第 1 步 · ⑤ 数据预处理")
    say("告诉它两件人会做的事，其余让它自己算：")
    say("  · 缺失值先不动，只报告（**别一上来就用均值填**——那会压小方差、让 p 值偏乐观）")
    say("  · 把 Q7_1~Q7_5 合成一个「满意度」分数，Q8_1~Q8_3 合成「继续意愿」")
    say("")
    pause(0.6)

    params = {
        "file": "data/sim_survey.csv",
        "missing": "keep",
        "composite": "满意度 = mean(Q7_1, Q7_2, Q7_3, Q7_4, Q7_5)\n"
                     "继续意愿 = mean(Q8_1, Q8_2, Q8_3)",
        "outlier": "z3",
    }
    ev = run_block("b4_prep", params)
    if ev["error"]:
        say("!! 预处理没跑通：" + ev["error"])
        return False

    tables = ev["result"].get("tables") or []

    say("跑完了。它做了这些（这是它自己的步骤记录）：")
    render_steps(tables)
    for t in tables:
        if (t.get("name") or "").startswith("步骤"):
            continue

    tbl = find_table(ev["result"], "处理前后对比")
    if tbl:
        say("")
        say("处理前后（注意：缺失**没有替你填**，只是报出来了）：")
        render_table(tbl, max_rows=6)

    tbl = find_table(ev["result"], "信度")
    if tbl:
        say("")
        say("合成变量的信度（α 太低说明这几个题不该合成一个分数）：")
        render_table(tbl, max_rows=6)

    tbl = find_table(ev["result"], "异常值标记")
    if tbl:
        say("")
        say("异常值（只**标记**，不自动删 —— 删不删是你的判断）：")
        render_table(tbl, max_rows=6)

    say("")
    say("它给的结论：")
    for ln in str(ev["result"].get("summary") or "").split("\n"):
        say("   " + ln)

    say("")
    say("提醒（它主动指出的）：")
    got = show_logs(ev, keep=("warn", "error"))
    if not got:
        say("   （这一步没有需要提醒你的地方）")

    say("")
    say("产物：output/clean_data.csv（干净数据）、output/预处理日志.md（每步做了什么）")
    return True


def step_2_stats():
    h1("第 2 步 · ⑥ 统计分析")
    say("用**大白话**说要研究什么 —— 这一步是工作台的核心：")
    say("")
    say('   「用大白话说：Android 用户和 iOS 用户的满意度，是不是真的不一样？」')
    say("")
    say("  它不会只丢给你一个 p 值，而是先摊开它的判断过程。")
    say("")
    pause(0.8)

    params = {
        "file": "output/clean_data.csv",
        "intent": "Android 用户和 iOS 用户的满意度是不是真的不一样",
        "question": "compare",
        "dv": "满意度",
        "group": "平台",
        "fallback": "nonparam",
        "alpha": 0.05,
        "gen_sps": ["sps", "fig"],
    }
    ev = run_block("b5_stats", params)
    if ev["error"]:
        say("!! 统计分析没跑通：" + ev["error"])
        return False

    # ---- 1) 意图：它先确认"我理解你要问什么" ----
    tbl = find_table(ev["result"], "我理解你想知道什么")
    if tbl:
        h2("它先复述一遍：我理解你要问的是什么")
        render_kv(tbl, val_w=76)

    # ---- 2) 决策树：它是怎么想的 ----
    tbl = find_table(ev["result"], "分析计划", "决策")
    if tbl:
        h2("它是怎么挑方法的（决策树）")
        render_kv(tbl, key_w=14, val_w=84)

    # ---- 3) 方法推荐 ----
    tbl = find_table(ev["result"], "方法推荐")
    if tbl:
        h2("它的推荐，以及「为什么不用另一个」")
        render_kv(tbl, key_w=14, val_w=84)

    # ---- 4) 各组描述统计 ----
    tbl = find_table(ev["result"], "各组描述统计")
    if tbl:
        h2("两组各自长什么样（含均值 95% 置信区间）")
        render_table(tbl, max_rows=8)

    # ---- 5) 主结果 ----
    tbl = find_table(ev["result"], "检验结果")
    if tbl:
        h2("结果")
        render_kv(tbl, key_w=22, val_w=76)

    # ---- 6) 一句话结论 ----
    summary = ev["result"].get("summary") or ""
    if summary:
        h2("它给的结论（会写进报告的那段）")
        for ln in str(summary).split("\n"):
            say("   " + ln)

    # ---- 7) 它主动指出的问题 ----
    h2("它主动指出的问题")
    got = show_logs(ev, keep=("warn", "error"), limit=8)
    if not got:
        say("   （没有）")

    return True


def step_3_artifacts():
    h1("第 3 步 · 它留下了什么")
    out = os.path.join(PROJ, "output")
    if os.path.isdir(out):
        files = sorted(os.listdir(out))
        say("output/ 下面这些文件（都是刚才这几步真写出来的）：")
        for fn in files:
            full = os.path.join(out, fn)
            size = os.path.getsize(full) if os.path.isfile(full) else 0
            print("   %-46s %7s B" % (fn, size))

    # 挑 SPSS 语法展示 —— 这是"双轨复核"最直观的证据
    sps = None
    if os.path.isdir(out):
        for fn in sorted(os.listdir(out)):
            if fn.endswith(".sps"):
                sps = os.path.join(out, fn)
                break
    if sps:
        h2("挑一份给你看：SPSS 语法")
        say("这是**同一件事在 SPSS 里怎么跑** —— 你可以两边对一遍，数字对得上才有底气。")
        say("（工作台不会替你启动 SPSS，但语法给你写好了。）")
        say("")
        # ⚠ `.sps` 是**按 GBK 写的**（SPSS 按本机代码页读语法文件，
        #   UTF-8 的中文进去 SPSS 看到的是乱码，连文件路径都会被读坏）。
        #   所以这里读它**不能**按 UTF-8 —— 否则屏幕上就是一片乱码。
        #   这个坑我自己先踩了一次。
        text = None
        for enc in ("gbk", "gb18030", "utf-8"):
            try:
                with open(sps, "r", encoding=enc) as f:
                    text = f.read()
                break
            except UnicodeDecodeError:
                continue
        for i, ln in enumerate((text or "").splitlines()[:24], 1):
            print("   %2d | %s" % (i, ln))
        say("")
        say("   完整语法：output/分析_语法_满意度_by_平台.sps")


def ending():
    h1("完了 —— 你刚看完的就是这个工作台做的事")
    say("它替你干的活：把材料摆整齐、把该报的数字报全、**把可疑的地方指出来**。")
    say("它不替你干的活：替你理解材料、替你下方法论判断。")
    say("")
    say("刚才那三步里，最值得记住的是这两件事：")
    say("  1. 它先**摊开自己怎么挑的方法**（决策树），再给结果 —— 你能追着问「凭什么是这个」")
    say("  2. 它给的不只是一个 p 值，还有**置信区间和效应量** —— 显著性 ≠ 重要")
    say("")
    say("想看真界面（点按钮那种）就双击 `启动工作台.bat`。")
    say("")
    say("演示项目留在这里，你可以打开看产物：")
    say("  " + PROJ)
    say("想删就整个删掉，不影响任何东西。")
    say("")
    say("─" * 74)
    say("这个工作台还在早期阶段（README 里列了明确没做完的部分）。")
    say("如果你在试用里发现哪里不对、或者哪句话看不懂 —— 非常希望能告诉我们。")
    say("提建议 / 报问题：https://github.com/yuushoku-amering/user-research/issues")
    say("─" * 74)


def main():
    t0 = time.time()
    print("")
    print("  岚苔 Vesper · 用户研究工作台 · 演示")
    print("  你会看到：一份问卷 → 预处理 → 统计 → 结论，全程都是真算的。")
    print("  （机器跑只要几秒；下面这些内容是留给你看的。）")
    print("")

    step_0_prepare()
    if not step_1_prep():
        return 1
    if not step_2_stats():
        return 1
    step_3_artifacts()
    ending()

    print("")
    print("  （机器跑了 %.1f 秒；你要是慢慢看完，大概五分钟）" % (time.time() - t0))
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
