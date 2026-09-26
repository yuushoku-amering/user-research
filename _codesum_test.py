# -*- coding: utf-8 -*-
"""组块 ②b 编码汇总 · 专项自检

三个用例：
  A 三人份的合成编码表 —— 数得对不对（覆盖人数、矩阵、提醒）
  B 案例项目里那份已填的编码表 —— 单人份，普遍性提醒该不该出现
  C 编码有冲突时研究员选「停一下」—— 必须真的停下、不产出文件

    python _codesum_test.py
产物：_jobs/codesum_*.jsonl（原始输出）、_jobs/codesum_summary.txt
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import paths          # noqa: E402

JOBS = os.path.join(HERE, "_jobs")
# B / D 两段原来跑在**某个真实项目**上（`..\projects\小鹰扫描_付费转化研究`）。
# 2026-09-27 改：那个项目在本机之外根本不存在 —— 别人 clone 下来一跑就红，
# 而红的理由跟被测代码毫无关系。素材改成工作台自带（`_fixtures\访谈样例\`），
# 内容一字不差（就是从那两份产物直接拷的：一人份编码工作表 + 已脱敏转写稿）。
DEMO = os.path.join(HERE, "_fixtures", "访谈样例")
DEMO_OK = os.path.isdir(DEMO)
if not DEMO_OK:
    sys.exit("找不到自带素材 %s —— B / D 两段跑不了（素材不该缺，缺了就是仓库不完整）" % DEMO)
TMP = os.path.join(JOBS, "tmp_codesum")

HEAD = ["#", "说话人", "字数", "原文", "关键词（线索）", "开放编码", "范畴", "主题", "可作引语"]

THREE = [
    [1, "访员", 12, "先聊聊你平时怎么用的", "", "", "", ""],
    [2, "甲", 20, "批量扫描太慢了，我一次要扫几十页，得一份一份来", "", "批量扫描慢", "批量处理", "T1 效率痛点"],
    [3, "乙", 18, "一次扫不完，只能分开扫，特别费时间", "", "批量扫描慢", "批量处理", "T1 效率痛点"],
    [4, "丙", 16, "我都不知道还有付费版这个东西", "", "不知道有付费版", "付费版认知", "T2 认知盲区"],
    [5, "甲", 14, "一年一百以内我可能就直接买了", "", "百元以内可接受", "价格接受度", "T3 价格门槛"],
    [6, "乙", 15, "没看到哪里说要收费，一直用免费的", "", "不知道有付费版", "付费版认知", "T2 认知盲区"],
    [7, "访员", 10, "那你希望怎么被通知？", "", "", "", ""],
    [8, "丙", 17, "几十页的时候一次能扫完就省事多了", "", "批量扫描慢", "批量处理", "T1 效率痛点"],
    [9, "甲", 13, "这个我没什么想法", "", "", "", ""],
]

CONFLICT = [
    [1, "访员", 12, "随便聊聊", "", "", "", ""],
    [2, "甲", 20, "批量扫描太慢了，我一次要扫几十页", "", "批量扫描慢", "效率痛点", "T1 效率"],
    [3, "乙", 18, "一次扫不完，只能分开扫", "", "批量扫描慢", "操作习惯", "T2 习惯"],
]


def write_csv(path, rows):
    import pandas as pd
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = [list(r) + [""] * (len(HEAD) - len(r)) for r in rows]
    pd.DataFrame(rows, columns=HEAD).to_csv(path, index=False, encoding="utf-8-sig")


def write_csv_merged(path, rows, meta_lines):
    """写一张**多场访谈拼在一起**的编码表：开头先放转写稿的元信息行。

    ② 生成的合并表就是这样 —— 每场开头的 `访谈者：` / `受访者：` 会作为
    发言单元留在「原文」列里，而 ②b 正是靠它们认出「谁是访谈者」。
    """
    with_meta = [[i + 1, "（元信息）", len(t), t, "", "", "", "", ""]
                 for i, t in enumerate(meta_lines)] + [list(r) for r in rows]
    write_csv(path, with_meta)


def run_block(project_root, params, answer=None, tag="case", block="b2b_codesum"):
    job = dict(params)
    job["project_root"] = project_root
    job["block_dir"] = os.path.join(HERE, "blocks", block)
    job["block_id"] = block
    jf = os.path.join(JOBS, "codesum_%s.json" % tag)
    os.makedirs(JOBS, exist_ok=True)
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    kw = {}
    if answer:
        kw["input"] = (json.dumps({"choice": answer}) + "\n").encode("utf-8")
    else:
        kw["stdin"] = subprocess.DEVNULL
    p = subprocess.run([paths.engine_python(), os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE, **kw)
    out = p.stdout.decode("utf-8", "replace")
    with open(os.path.join(JOBS, "codesum_%s.jsonl" % tag), "w", encoding="utf-8") as f:
        f.write(out + ("\n--- STDERR ---\n" + p.stderr.decode("utf-8", "replace")
                       if p.stderr.strip() else ""))

    logs, result, error, asks, steps = [], None, "", [], []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("t") == "log":
            logs.append("[%s] %s" % (m.get("level"), m.get("msg")))
        elif m.get("t") == "result":
            result = m.get("data")
        elif m.get("t") == "error":
            error = m.get("msg", "")
        elif m.get("t") == "ask":
            asks.append(m)
        elif m.get("t") == "step":
            steps.append(m)
    return {"logs": logs, "result": result, "error": error, "asks": asks, "steps": steps}


PASS, FAIL = [], []


def _ensure(dirpath, filename):
    """建好目录，返回要写的完整路径（素材一律拷进临时项目再跑）。"""
    os.makedirs(dirpath, exist_ok=True)
    return os.path.join(dirpath, filename)


def ok(cond, label, extra=""):
    (PASS if cond else FAIL).append(label + ("" if cond else "  ← " + str(extra)))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if os.path.isdir(TMP):
        shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)

    # ---------------- A：三人份 ----------------
    proj = os.path.join(TMP, "proj3")
    write_csv(os.path.join(proj, "output", "编码工作表.csv"), THREE)
    r = run_block(proj, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                         "max_themes": 6, "quote_n": 3, "opts": ["list_uncoded"]}, tag="three")
    res = r["result"] or {}
    ok(not r["error"], "A 能跑通", r["error"])
    tmap = {t["name"]: t for t in res.get("tables", [])}
    themes = tmap.get("主题汇总", {}).get("rows", [])
    by_theme = {row[1]: row for row in themes}
    ok(len(themes) == 3, "A 数出 3 个主题", len(themes))
    ok(by_theme.get("T1 效率痛点", [None] * 8)[5] == 3, "A T1 覆盖 3 位受访者",
       by_theme.get("T1 效率痛点"))
    ok(by_theme.get("T1 效率痛点", [None] * 8)[4] == 3, "A T1 有 3 段证据")
    ok(by_theme.get("T2 认知盲区", [None] * 8)[5] == 2, "A T2 覆盖 2 位受访者")
    ok(by_theme.get("T3 价格门槛", [None] * 8)[5] == 1, "A T3 只覆盖 1 位受访者")

    mtx = os.path.join(proj, "output", "编码_主题矩阵.csv")
    ok(os.path.exists(mtx), "A 主题 × 受访者矩阵有产出")
    if os.path.exists(mtx):
        import pandas as pd
        m = pd.read_csv(mtx, encoding="utf-8-sig")
        ok([c for c in m.columns] == ["编号", "主题", "甲", "乙", "丙", "合计"],
           "A 矩阵的列是三位受访者", list(m.columns))
        row1 = m[m["主题"] == "T1 效率痛点"].iloc[0]
        ok([int(row1["甲"]), int(row1["乙"]), int(row1["丙"])] == [1, 1, 1], "A T1 行 = 1/1/1",
           list(row1))
        row3 = m[m["主题"] == "T3 价格门槛"].iloc[0]
        ok([int(row3["甲"]), int(row3["乙"]), int(row3["丙"])] == [1, 0, 0], "A T3 行 = 1/0/0",
           list(row3))

    alert_txt = " ".join(" ".join(str(c) for c in a) for a in tmap.get("体检", {}).get("rows", []))
    ok("没达到" in alert_txt and "T3" in alert_txt, "A 点名了只有 1 人提过的主题", alert_txt[:200])
    ok("只有 1 位受访者" not in alert_txt, "A 三人份不该出现「只有 1 位受访者」的提醒")
    ok("还没编码" in alert_txt, "A 提醒了未编码段落")

    figs = [f["rel"] for f in res.get("figures", [])]
    ok(len(figs) == 2, "A 出了两张图（结构图 + 覆盖矩阵）", figs)
    for rel in figs:
        ok(os.path.exists(os.path.join(proj, rel)), "A 图确实落盘：%s" % rel)
    ok(os.path.exists(os.path.join(proj, "contracts", "coded_transcript.md")),
       "A 回填了契约文件 coded_transcript.md")

    # ---------------- B：单人份（素材自带，见 _fixtures/访谈样例） ----------------
    # ⚠ 要先把素材**拷进临时项目**再跑：②b 的产物是写在编码表旁边那一层的，
    #   直接拿 _fixtures 当项目跑，产物就会落在素材目录里、把仓库弄脏。
    ok(DEMO_OK, "B/D 用到的单人份素材在 _fixtures/访谈样例/ 里")
    projB = os.path.join(TMP, "proj1")
    shutil.copy2(os.path.join(DEMO, "编码工作表_单人份.csv"),
                 _ensure(os.path.join(projB, "output"), "编码工作表.csv"))
    r2 = run_block(projB, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                           "max_themes": 6, "quote_n": 3, "opts": ["list_uncoded"]}, tag="demo")
    res2 = r2["result"] or {}
    ok(not r2["error"], "B 单人份案例能跑通", r2["error"])
    t2 = {t["name"]: t for t in res2.get("tables", [])}
    th2 = t2.get("主题汇总", {}).get("rows", [])
    ok(len(th2) == 5, "B 单人份归出 5 个主题", len(th2))
    al2 = " ".join(" ".join(str(c) for c in a) for a in t2.get("体检", {}).get("rows", []))
    ok("只有 1 位受访者" in al2, "B 单人份必须提醒「普遍性下不了结论」")
    ok("不能写成" in al2, "B 提醒里写了「不能写成普遍现象」")
    ok(len(res2.get("figures", [])) == 1, "B 单人份只出结构图，不出覆盖矩阵",
       [f["rel"] for f in res2.get("figures", [])])
    ok(os.path.exists(os.path.join(projB, "output", "编码汇总.md")), "B 报告落盘")

    # ---------------- B2：**统计只算受访者的话**（访谈者的提问不算证据） ----------------
    # 守的坑（2026-09-24 修）：`is_iv()` 原来只用在一个地方（未编码清单里标"是谁在说"），
    #   而**段落数 / 覆盖受访者数**是全量算的。一份访谈里提问常占一半（实测 35/70），
    #   于是"这个主题有 N 段证据"直接虚一倍 —— 这个数要写进报告，不能虚。
    # ⚠ 造这个用例时要注意：THREE 里那两段提问**是空的**，过滤前后结果一样，
    #   所以它证明不了这条修复（第一版就白跑了一遍）。这里**故意给提问段也填上码** ——
    #   模拟"有人在提问上编了码"，看统计认不认它。
    print("\n【B2】访谈者的提问不算证据（给提问段也填上码来压这条线）")
    projQ = os.path.join(TMP, "proj_scope")
    with_q = [list(x) for x in THREE]
    for _row in with_q:
        if _row[1] == "访员":
            # ⚠ 提问段分两种，两种都要有，才测得到两件事：
            #   ① 编了码的提问 → 不能算进证据段数
            #   ② 没编的提问   → 要留在"未编码清单"里（那张表有「是谁在说」列）
            if "希望怎么被通知" in str(_row[3]):
                _row[5], _row[6], _row[7] = "先聊聊", "访问引导", "T1 效率痛点"
            else:
                _row[3] = "后面还有要补充的吗？"      # 留空 = 没编
    write_csv(os.path.join(projQ, "output", "编码工作表.csv"), with_q)
    rq = run_block(projQ, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                           "max_themes": 6, "quote_n": 3, "opts": ["list_uncoded"]}, tag="scope")
    resq = rq["result"] or {}
    ok(not rq["error"], "B2 能跑通", rq["error"])
    stq = {s.get("id"): s for s in (rq.get("steps") or [])}
    ok("scope" in stq, "B2 有一张「统计口径：只算受访者的话」的步骤卡",
       list(stq.keys()))
    if "scope" in stq:
        txt = str(stq["scope"].get("detail") or "")
        # 全表 9 段，访员占 2 段（编号 #1 #7）→ 受访者 7 段
        ok("全表 9 段" in txt and "提问 2 段" in txt and "**7 段受访者的话**" in txt,
           "B2 口径卡把三个数都写清了（全表 9 / 提问 2 / 受访者 7）", txt[:90])
    tq = {t["name"]: t for t in resq.get("tables", [])}
    byq = {row[1]: row for row in tq.get("主题汇总", {}).get("rows", [])}
    # 提问那两段被算进去的话，T1 会变成 5 段 / 3 人（甲1+乙1+丙2+提问2）
    ok(byq.get("T1 效率痛点", [None] * 8)[4] == 3,
       "B2 **提问段的码没算进段落数**（T1 仍是 3 段，不是 5 段）",
       byq.get("T1 效率痛点"))
    ok(byq.get("T1 效率痛点", [None] * 8)[5] == 3, "B2 T1 仍覆盖 3 位受访者")
    ok("访员" not in [c for c in
                      (tq.get("主题 × 受访者矩阵") or tq.get("主题矩阵") or {}).get("columns", [])],
       "B2 矩阵的列里没有访谈者")
    mtxq = os.path.join(projQ, "output", "编码_主题矩阵.csv")
    if os.path.exists(mtxq):
        import pandas as pd
        mq = pd.read_csv(mtxq, encoding="utf-8-sig")
        ok("访员" not in list(mq.columns), "B2 矩阵 CSV 里也没有访谈者", list(mq.columns))
    # 未编码清单要**保留**提问段（那一列「是谁在说」才有意义）
    ucq = os.path.join(projQ, "output", "编码_未编码段落.csv")
    if os.path.exists(ucq):
        import pandas as pd
        uq = pd.read_csv(ucq, encoding="utf-8-sig")
        col = "是谁在说" if "是谁在说" in uq.columns else uq.columns[-1]
        vals = set(str(x) for x in uq[col].tolist())
        ok("访谈者提问" in vals,
           "B2 未编码清单仍列出访谈者的提问（那张表要看得出哪段是提问）", vals)

    # ---------------- B3：口径要把"排除了谁"摆出来，认错的可能性也要说 ----------------
    # "第一个开口的是访谈者"是**推断**。试过更聪明的判据（"被当成访谈者的人不该说得最多"）
    #   → 判不准（正规访谈里提问也可能比任何受访者都多），所以改成**老实摆事实**：
    #   说清排除了谁、各几段，以及多场拼稿时可能认反。
    print("\n【B3】统计口径要摆出来：排除了谁、可能认错在哪")
    # 正例：一份普通访谈（访员 2 段提问）—— 提示里要点名排除了谁
    projS = os.path.join(TMP, "proj_scope2")
    write_csv(os.path.join(projS, "output", "编码工作表.csv"), THREE)
    rs = run_block(projS, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                           "max_themes": 6}, tag="scope2")
    trs = {t["name"]: t for t in (rs["result"] or {}).get("tables", [])}
    alrs = " ".join(" ".join(str(c) for c in a) for a in trs.get("体检", {}).get("rows", []))
    ok("统计口径" in alrs, "B3 体检表里有「统计口径」这条", alrs[:140])
    ok("访员" in alrs, "B3 **点名排除了谁**（访员）", alrs[:200])
    ok("多场访谈拼在一起" in alrs or "认反" in alrs,
       "B3 说清了**多场拼稿可能认反**这件事", alrs[:220])

    # 反例（极端）：被排除的人比任何一位受访者都说得都多 → 升级成「⚠ 注意」并直接提"可能认反"
    # ⚠ 这个场景**顺便证明了一件事**：认反的后果是"受访者编好的码全被排除掉" ——
    #   我用上一版数据跑时，它直接撞到"受访者那 1 段一格都没填"，等于把人家的作业判没了。
    #   所以这条提示不是锦上添花，是**防止静默算错**。
    projR2 = os.path.join(TMP, "proj_rev2")
    write_csv(os.path.join(projR2, "output", "编码工作表.csv"), [
        [1, "李访", 10, "先随便聊聊", "", "", "", ""],
        [2, "李访", 10, "还有呢？", "", "", "", ""],
        [3, "李访", 10, "再想想？", "", "", "", ""],
        [4, "李访", 10, "嗯？", "", "", "", ""],
        [5, "小周", 20, "批量扫描太慢，一次扫不完", "", "批量扫描慢", "痛点", "T1 效率"],
    ])
    rr2 = run_block(projR2, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                             "max_themes": 6}, tag="reversed2")
    resr2 = rr2["result"] or {}
    t2r = {t["name"]: t for t in resr2.get("tables", [])}
    rows_r2 = t2r.get("体检", {}).get("rows", [])
    alr2 = " ".join(" ".join(str(c) for c in a) for a in rows_r2)
    ok("说得都多" in alr2 or "认反" in alr2,
       "B3 排除的人比任何受访者都多时 → **直接提「可能认反」**", alr2[:220])
    ok(any("统计口径" in str(r[1]) and str(r[0]).startswith("⚠") for r in rows_r2),
       "B3 这种情形升级成「⚠ 注意」级别（不是普通 info）",
       [str(r[0]) for r in rows_r2][:6])

    # ---------------- C：冲突时选「停一下」 ----------------
    proj3 = os.path.join(TMP, "proj_conflict")
    write_csv(os.path.join(proj3, "output", "编码工作表.csv"), CONFLICT)
    r3 = run_block(proj3, {"coded_file": "output/编码工作表.csv"}, answer="stop", tag="stop")
    res3 = r3["result"] or {}
    ok(len(r3["asks"]) == 1, "C 冲突时停下来问了", len(r3["asks"]))
    ok(res3.get("stopped") is True, "C 选了「停一下」就真的停了", res3.get("summary"))
    ok(not os.path.exists(os.path.join(proj3, "output", "编码汇总.md")),
       "C 停下时不产出汇总文件")

    # 同一个冲突，选「继续」要能跑完
    r4 = run_block(proj3, {"coded_file": "output/编码工作表.csv"}, answer="go", tag="go")
    res4 = r4["result"] or {}
    ok(res4.get("stopped") is not True, "C 同一个冲突选「继续」能跑完")
    al4 = " ".join(" ".join(str(c) for c in a) for a in
                   {t["name"]: t for t in res4.get("tables", [])}.get("体检", {}).get("rows", []))
    ok("分到了不同范畴" in al4, "C 继续跑时把冲突写进了体检表")

    # ---------------- D：② 跑在脱敏稿上（说话人是 [姓名1] 这种占位名） ----------------
    # 回归用：正则不认方括号 → 39 段会被静默吞成 21 段。必须在**临时项目**里跑，
    # 因为 ② 会重写 output/编码工作表.csv —— 在案例项目上跑会把已填的码洗掉。
    projD = os.path.join(TMP, "proj_deid")
    src = os.path.join(DEMO, "脱敏_访谈转写稿.txt")
    shutil.copy2(src, _ensure(os.path.join(projD, "samples"), "脱敏_访谈转写稿.txt"))
    r5 = run_block(projD, {
        "transcript": "samples/脱敏_访谈转写稿.txt",
        "split": "speaker", "keep_interviewer": ["keep_q", "drop_short"],
        "min_len": 6, "top_kw": 25,
    }, tag="deid", block="b2_coding")
    ok(not r5["error"], "D ② 能跑在脱敏稿上", r5["error"])
    split_line = next((l for l in r5["logs"] if "切成" in l and "发言单元" in l), "")
    ok("切成 40 个发言单元" in split_line,
       "D 脱敏稿没被吞段（40 段，不是 21 段）", split_line)
    seen = " ".join(r5["logs"])
    import pandas as pd
    ws = pd.read_csv(os.path.join(projD, "output", "编码工作表.csv"), encoding="utf-8-sig")
    speakers = set(ws["说话人"].astype(str))
    ok("[姓名1]" in speakers, "D 认出了括号占位名当说话人", sorted(speakers))
    ok(len(ws) >= 35, "D 段数没被吞（工作表里 %d 行）" % len(ws), len(ws))
    ok("林晓" in speakers, "D 访谈者也认出来了", sorted(speakers))

    # ---------------- 收尾 ----------------
    # ------------------------------------------------------------------ #
    # 走查补的三条：② 自动挑材料 / 两份候选不硬挑 / 结果里带下一步卡片
    # ------------------------------------------------------------------ #
    one = ("访谈时间：2026年3月12日 下午\n访谈地点：学校二食堂二楼\n"
           "采访者：李明\n受访者：小林，女，20岁，大二\n\n"
           "李明：那我们就开始吧，先随便聊聊。\n"
           "小林：我平时不太用这个功能，主要是找不到入口。\n"
           "李明：那你一般会怎么做？\n"
           "小林：就干脆不弄了，等室友帮我。\n")
    troot = tempfile.mkdtemp(prefix="urw_auto_")
    try:
        os.makedirs(os.path.join(troot, "samples"), exist_ok=True)
        os.makedirs(os.path.join(troot, "output"), exist_ok=True)
        with open(os.path.join(troot, "samples", "转写稿A.txt"), "w", encoding="utf-8") as f:
            f.write(one)
        # 一份不像转写稿的 txt：不该被吃掉
        with open(os.path.join(troot, "samples", "买牛奶清单.txt"), "w", encoding="utf-8") as f:
            f.write("下次记得买牛奶。\n还要交作业。\n")

        ra = run_block(troot, {"transcript": "", "split": "speaker",
                               "keep_interviewer": ["keep_q"]}, tag="auto1", block="b2_coding")
        ok(not ra["error"], "只有一份像转写稿时，不选也能跑起来：%s" % (ra["error"] or "OK"))
        notes = str(((ra.get("result") or {}).get("notes")) or "")
        ok("转写稿我替你选了" in notes, "**明说**了是它替你选的（不能默默替人决定）")
        ok("samples/转写稿A.txt" in notes, "说清了选的是哪一份：%s" % notes[:60].replace("\n", " "))
        ok("买牛奶清单" not in notes, "不像转写稿的 txt 没被误吃")

        with open(os.path.join(troot, "samples", "转写稿B.txt"), "w", encoding="utf-8") as f:
            f.write(one.replace("小林", "小周"))
        rb = run_block(troot, {"transcript": "", "split": "speaker"}, tag="auto2", block="b2_coding")
        ok(bool(rb["error"]), "两份候选 → 停下来让人选，不硬挑")
        ok("请先选" in str(rb["error"] or ""), "错误信息说的是「请先选」，不是崩了")

        rc = run_block(troot, {"transcript": "samples/转写稿A.txt", "split": "speaker",
                               "keep_interviewer": ["keep_q"]}, tag="auto3", block="b2_coding")
        nxt = ((rc.get("result") or {}).get("next")) or {}
        ok(bool(nxt.get("title")), "② 的结果里带「下一步」卡片：%s" % str(nxt.get("title"))[:50])
        whole = str(nxt.get("title") or "") + str(nxt.get("body") or "")
        ok("工作台外面" in whole, "卡片里说明白这一步发生在工作台外面")
        ok("编码工作表.csv" in whole and "②b" in whole,
           "卡片里给了具体动作（打开哪张表、跑哪个组块）")
        prog = ((rc.get("result") or {}).get("coded_progress")) or {}
        ok(prog.get("filled") == 0, "刚跑完填了 0 段（%s）" % prog.get("filled"))
        ok((prog.get("total") or 0) >= 2, "总段数对得上（%s）" % prog.get("total"))

        # ---------------- 范畴名归一：同一个东西的不同写法不能算成两个范畴 ----------------
        # 研究员自己提过的真实痛点：手填的表里「经济压力」「经济压力 」「 经济压力」
        # 「经济压力（花钱）」会被算成 4 个范畴 —— 范畴数虚高、正确的提醒被稀释。
        print("\n【范畴名归一】写法不同、其实是同一个 → 要并到一起")
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "b2b_eng", os.path.join(HERE, "blocks", "b2b_codesum", "engine.py"))
        _m = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_m)
        mp = _m._unify_cats(["经济压力", "经济压力 ", " 经济压力", "经济压力（花钱）",
                            "花钱", "金钱花费", "时间投入"])
        ok(mp["经济压力 "] == "经济压力" and mp[" 经济压力"] == "经济压力",
           "带空格的写法并到同一个")
        ok(mp["经济压力（花钱）"] == "经济压力",
           "括号补充说明被去掉（基础名在别处出现过）")
        ok(mp["花钱"] == "花钱" and mp["金钱花费"] == "金钱花费",
           "**同义词不猜**（「花钱」和「金钱花费」保持分开）—— 合并错了是改结论")
        ok(mp["时间投入"] == "时间投入", "不相关的名字不动")
    finally:
        shutil.rmtree(troot, ignore_errors=True)

    # ---------------- E：**多场访谈拼一张表** —— 访谈者要从表头元信息里认 ----------------
    # 守的坑（2026-09-26 修）：②b 原来只按「第一个开口的人」认访谈者。
    #   三份稿拼一张表时（实测：苏雨桐 + 周然 + 林小雨），第二场的采访者
    #   **【姓名5】李明** 会被当成一位新受访者 —— 覆盖人数从此虚高，
    #   而这个数正是"这算不算普遍现象"的依据。
    #   更糟的另一种错法：万一「受访者：[姓名4]」被当成访谈者，
    #   那位受访者的证据会**整段消失**（苏雨桐那 35 段被当提问排掉），还不报错。
    print("\n【E】多场访谈拼一张表：访谈者认不认得出")
    MERGE_META = [
        "访谈对象：[姓名1]", "访谈时间：2026年9月18日 下午 3:20", "访谈者：[姓名2]",
        "访谈时间：2026年3月14日 晚上", "采访者：[姓名5]", "受访者：[姓名4]，男，21岁，大三",
        "访谈时间：2026年3月12日 下午", "采访者：[姓名5]（我）", "受访者：[姓名6]，女，20岁，大二",
    ]
    MERGE_ROWS = [
        ["访谈者问的", "[姓名2]", 12, "雨桐你好，先谢谢你下午抽时间过来。", "", "", "", ""],
        ["受访者答的", "[姓名1]", 20, "我觉得是得花时间的，你不投入就不行。", "", "时间投入", "责任观", "T1 责任观"],
        ["受访者答的", "[姓名4]", 18, "这个跟家里给多少关系很大。", "", "经济依赖", "经济来源", "T2 经济"],
        ["受访者答的", "[姓名6]", 16, "车票一次来回一百六，一个月得六七百吧。", "", "异地开销", "经济压力", "T2 经济"],
        ["受访者答的", "[姓名1]", 14, "我妈跟我说过大学别瞎谈，别耽误正事。", "", "家里态度", "家庭态度", "T1 责任观"],
        ["受访者答的", "[姓名6]", 15, "我爸不太同意，觉得影响学习。", "", "家里态度", "家庭态度", "T1 责任观"],
    ]
    projM = os.path.join(TMP, "proj_merged")
    write_csv_merged(os.path.join(projM, "output", "编码工作表.csv"), MERGE_ROWS, MERGE_META)
    rM = run_block(projM, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                           "max_themes": 6, "quote_n": 3, "opts": ["list_uncoded"]}, tag="merged")
    ok(not rM["error"], "E 多场拼接能跑通", rM["error"])
    ok(any("访谈者（编码表里带的" in l and "[姓名2]" in l and "[姓名5]" in l for l in rM["logs"]),
       "E 两位采访者都从表头认出来了", [l for l in rM["logs"] if "访谈者" in l][:2])
    resM = rM["result"] or {}
    tM = {t["name"]: t for t in resM.get("tables", [])}
    thM = tM.get("主题汇总", {}).get("rows", [])
    byM = {row[1]: row for row in thM}
    ok(byM.get("T1 责任观", [None] * 8)[5] == 2, "E T1 覆盖 2 位受访者（不含采访者）",
       byM.get("T1 责任观"))
    alM = " ".join(" ".join(str(c) for c in a) for a in tM.get("体检", {}).get("rows", []))
    ok("4 位" not in alM, "E 没有把采访者算成第 4 位受访者", alM[:200])
    mtxM = os.path.join(projM, "output", "编码_主题矩阵.csv")
    if os.path.exists(mtxM):
        import pandas as pd
        mM = pd.read_csv(mtxM, encoding="utf-8-sig")
        four = list(mM.columns)
        ok("[姓名5]" not in four and "[姓名2]" not in four,
           "E 矩阵的列里没有采访者", four)
        # 列 = 编号 + 主题 + 3 位受访者 + 合计 = 6
        ok(len(four) == 6, "E 矩阵列数 = 编号 + 主题 + 3 位受访者 + 合计", four)
    ok(len(resM.get("figures", [])) == 2, "E 有主题时两张图都出",
       [f["rel"] for f in resM.get("figures", [])])

    # ---------------- F：**一个主题都没归出来时不画图** ----------------
    # 守的坑（2026-09-26 修）：主题列一段没填时 `rec_themes()` 返回占位符
    #   `（还没归主题）`，图那条循环拿它当主题名 → `KeyError`，整块图静默不出；
    #   就算绕过去，图二还会 `Invalid shape (0,) for image data`（0 行矩阵 imshow 不了），
    #   而图一会画出一张**空轴的白图**——比不画更让人以为程序坏了。
    print("\n【F】主题列还空着：不画空图、不崩")
    NO_THEME = [
        [1, "访员", 12, "先随便聊聊你平时怎么用的。", "", "", "", "", ""],
        [2, "甲", 20, "批量扫描太慢了，我一次要扫几十页。", "", "批量扫描慢", "批量处理", "", ""],
        [3, "乙", 18, "一次扫不完，只能分开扫。", "", "批量扫描慢", "批量处理", "", ""],
    ]
    projN = os.path.join(TMP, "proj_notheme")
    write_csv(os.path.join(projN, "output", "编码工作表.csv"), NO_THEME)
    rN = run_block(projN, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                           "max_themes": 6, "quote_n": 3, "opts": ["list_uncoded"]}, tag="notheme")
    ok(not rN["error"], "F 主题列为空也能跑通（不崩）", rN["error"])
    ok(not any("画图失败" in l for l in rN["logs"]),
       "F 没有「画图失败」", [l for l in rN["logs"] if "画图" in l])
    ok(not (rN["result"] or {}).get("figures"),
       "F 一个主题都没有 → 一张图都不出（不留空图）",
       [f["rel"] for f in (rN["result"] or {}).get("figures", [])])
    alN = " ".join(" ".join(str(c) for c in a) for a in
                   {t["name"]: t for t in (rN["result"] or {}).get("tables", [])}
                   .get("体检", {}).get("rows", []))
    ok("主题列还空着" in alN, "F 提醒了「主题列还空着」（该看的是这条，不是空图）", alN[:160])
    cN = os.path.join(projN, "output", "编码汇总_范畴.csv")
    if os.path.exists(cN):
        import pandas as pd
        cNdf = pd.read_csv(cN, encoding="utf-8-sig")
        ok("（还没归主题）" in " ".join(cNdf["归属主题"].astype(str)),
           "F 范畴表里仍然写「（还没归主题）」——那个占位符是给表看的，不是主题名")

    # ---------------- E2：**② 通过元信息小文件把访谈者传给 ②b** ----------------
    # 守的坑（2026-09-26 修，比 E 更接近真实）：② 生成的编码表里**没有**元信息行 ——
    #   表头那几行在切分时就被丢掉了（实测：真实那张表里 '访谈'/'受访' 一个字都搜不到）。
    #   所以 ②b 光靠表**无从得知**谁是访谈者，只能按"第一个开口的人"猜，
    #   结果把第 2 位采访者算成了一位受访者（实测：算成 4 位，实际 3 位）。
    #   修法：② 把访谈者写进 `output/编码工作表_元信息.json`，②b 读它。
    #   ⚠ 不写进 CSV 当注释行 —— 那会改掉「第一行是表头」，Excel 和逐段编码面板都会坏。
    print("\n【E2】② 的元信息小文件：访谈者跟着表走")
    projS2 = os.path.join(TMP, "proj_sidecar")
    clean_rows = [r for r in MERGE_ROWS]          # 一张**没有元信息行**的表（贴近真实）
    write_csv(os.path.join(projS2, "output", "编码工作表.csv"), clean_rows)
    side = os.path.join(projS2, "output", "编码工作表_元信息.json")
    with open(side, "w", encoding="utf-8") as f:
        json.dump({"interviewers": ["[姓名2]", "[姓名5]"],
                   "interviewer_source": "稿子开头的「采访者：」",
                   "transcript": "output/脱敏_合并_访谈转写稿_三场.txt",
                   "segments": len(clean_rows)}, f, ensure_ascii=False, indent=2)
    rS2 = run_block(projS2, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                             "max_themes": 6, "quote_n": 3, "opts": ["list_uncoded"]},
                    tag="sidecar")
    ok(not rS2["error"], "E2 能跑通", rS2["error"])
    ok(any("② 留下的元信息" in l for l in rS2["logs"]),
       "E2 访谈者是从元信息小文件读的（不是猜的）",
       [l for l in rS2["logs"] if "访谈者" in l][:2])
    resS2 = rS2["result"] or {}
    alS2 = " ".join(" ".join(str(c) for c in a) for a in
                    {t["name"]: t for t in resS2.get("tables", [])}
                    .get("体检", {}).get("rows", []))
    ok("4 位" not in alS2, "E2 没把采访者算成第 4 位受访者", alS2[:200])
    mtxS2 = os.path.join(projS2, "output", "编码_主题矩阵.csv")
    if os.path.exists(mtxS2):
        import pandas as pd
        mS2 = pd.read_csv(mtxS2, encoding="utf-8-sig")
        colsS2 = list(mS2.columns)
        ok("[姓名2]" not in colsS2 and "[姓名5]" not in colsS2,
           "E2 矩阵列里没有采访者", colsS2)
    # 小文件删掉 → 要能**退回**老规则（不退回去就是把研究员锁死在这条路上）
    os.remove(side)
    rS3 = run_block(projS2, {"coded_file": "output/编码工作表.csv", "min_cover": 2,
                             "max_themes": 6, "quote_n": 3, "opts": ["list_uncoded"]},
                    tag="sidecar_gone")
    ok(not rS3["error"], "E2 删掉小文件也能跑（容错）", rS3["error"])
    alS3 = " ".join(" ".join(str(c) for c in a) for a in
                    {t["name"]: t for t in (rS3["result"] or {}).get("tables", [])}
                    .get("体检", {}).get("rows", []))
    ok("指明谁是访谈者" in alS3 or "4 位" in alS3,
       "E2 没有元信息时，**提醒**把访谈者填上（而不是悄悄算错）", alS3[:200])

    body = []
    for name, r in (("A 三人份", r), ("B 案例项目", r2), ("C 冲突-停", r3),
                    ("C 冲突-继续", r4), ("D 脱敏稿", r5),
                    ("E 多场拼接", rM), ("F 主题为空", rN),
                    ("E2 元信息小文件", rS2), ("E2 删掉小文件", rS3)):
        body.append("=" * 70)
        body.append("【%s】" % name)
        body += r["logs"]
        if r["error"]:
            body.append("!!! %s" % r["error"])
        if r["result"]:
            body.append("摘要：" + str(r["result"].get("summary")))
            for t in r["result"].get("tables", []):
                body.append("  表：%s" % t.get("name"))
                for row in t.get("rows", [])[:8]:
                    body.append("      " + " | ".join(str(x) for x in row))
            for f in r["result"].get("figures", []):
                body.append("  图：%s" % f.get("rel"))
        body.append("")
    body.append("=" * 70)
    body.append("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for x in PASS:
        body.append("  ✅ " + x)
    for x in FAIL:
        body.append("  ❌ " + x)
    txt = "\n".join(body)
    with open(os.path.join(JOBS, "codesum_summary.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    print("\n详细 → %s" % os.path.join(JOBS, "codesum_summary.txt"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
