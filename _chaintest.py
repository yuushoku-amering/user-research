# -*- coding: utf-8 -*-
"""质性线**全链**回归：真实转写稿 → 🔒 → ② → 填编码 → ②b → 主题。

为什么单独一支：前面每一段都单独测过，但**从来没人把 ①→②→②b 在同一份真实材料上
从头走到尾**。组块之间的接缝（产物路径 / 列名 / 谁的输出是谁的输入）恰恰最容易断，
而它只有在整链跑的时候才暴露。

做法：
  · 材料用 `projects/_走查_大学生恋爱研究` 里作者真实的两份访谈转写稿
    （带真名和手机号 —— 所以第 0 棒必须过 🔒，这本身就是个真实场景）
  · 每一棒都断言"产物真的出现了"，关键数字留档
  · 编码那一步做**最小但真实**的手工填写（模拟研究员在 Excel 里填）
  · 最后一棒重跑 ②，验手工编码有没有被搬回来（这条曾经真的会丢数据）

跑法：python _chaintest.py
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
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from core import paths                                  # noqa: E402

TMP = os.path.join(tempfile.gettempdir(), "urw_chain")
# ⚠ 素材是**现场造**的（`_fixtures.py`），不是仓库里的文件。
#   两代踩坑史：
#     · 最早从某个"走查项目"里拷 → 那个项目被删了，整套回归当场跑不起来
#     · 后来改成提交进仓库的 `_fixtures/` 文件 → 能跑了，但那份素材里
#       **故意带真名和手机号**（🔒 那棒要拿它当靶子），摆在一个公开仓库里不合适
#   现在：仓库里只留"怎么造"，素材本体一个字节都不进库（见 .gitignore）。
from _fixtures import build_all as _build_fixtures      # noqa: E402

SRC = _build_fixtures()
PASS, FAIL = [], []


def ok(cond, label, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [FAIL] ") + str(label)
          + (("  -- " + str(extra)) if (extra and not cond) else ""))


def run(proj, block, params):
    job = dict(params)
    job.update({"project_root": proj,
                "block_dir": os.path.join(HERE, "blocks", block),
                "block_id": block})
    jf = os.path.join(proj, "_job_%s.json" % block)
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([paths.engine_python(), os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE, stdin=subprocess.DEVNULL)
    res, err, logs = None, "", []
    for ln in p.stdout.decode("utf-8", "replace").splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            m = json.loads(ln)
        except Exception:
            continue
        if m.get("t") == "result":
            res = m.get("data")
        elif m.get("t") == "error":
            err = m.get("msg", "")
        elif m.get("t") == "log":
            logs.append(str(m.get("msg") or ""))
    return {"res": res, "err": err, "logs": logs,
            "alerts": (res or {}).get("alerts") or []}


def exists(proj, *rels):
    return all(os.path.exists(os.path.join(proj, r.replace("/", os.sep))) for r in rels)


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    proj = os.path.join(TMP, "proj")
    for d in ("samples", "output", "contracts", "data"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    # 把两份真实转写稿拷进来（它们带着真名和手机号，正好检验 🔒 这一棒）
    # 素材是 `_fixtures.py` 现造的（`SRC` 就是它返回的目录）
    missing = [fn for fn in ("访谈转写稿_小周.txt", "访谈转写稿_小林.txt")
               if not os.path.exists(os.path.join(SRC, fn))]
    if missing:
        print("!! 测试素材不在：%s\n   （应该在 %s）" % ("、".join(missing), SRC))
        return 2
    for fn in ("访谈转写稿_小周.txt", "访谈转写稿_小林.txt"):
        shutil.copy2(os.path.join(SRC, fn), os.path.join(proj, "samples", fn))
    # 契约也拷进来（① 要用它；② 会从它的变量表里取项目专有词）
    shutil.copy2(os.path.join(SRC, "research_brief.md"),
                 os.path.join(proj, "contracts", "research_brief.md"))

    print("\n【第 0 棒】🔒 去标识化（转写稿里本来就有真名和手机号）")
    # 先确认守卫在这个项目上**会**报警（走查项目 samples 里有真名+手机号，
    # 而 ② 声明了 guard —— 直连 runner 时它原来会被整个绕过）
    g = run(proj, "b2_coding", {"transcript": "samples/访谈转写稿_小周.txt",
                                "split": "speaker", "keep_interviewer": ["keep_q"],
                                "min_len": 6, "top_kw": 10})
    gmsg = " ".join(str(a.get("msg") or "") for a in g["alerts"])
    ok("去标识化" in gmsg or "还没过" in gmsg,
       "没脱敏就丢进 ② 时，守卫**报警了**（原来只在服务端跑，直连 runner 会绕过）",
       gmsg[:120])
    r0 = run(proj, "b9_deident", {"file": "samples/访谈转写稿_小周.txt",
                                  "out_name": "脱敏_小周.txt",
                                  "keep_mapping": ["mapping"]})
    ok(not r0["err"], "跑通", r0["err"][:120])
    ok(exists(proj, "output/脱敏_小周.txt", "output/去标识化报告.md", "output/格式说明.md"),
       "产物三件都在（脱敏稿 / 报告 / 格式说明）")
    deid = open(os.path.join(proj, "output", "脱敏_小周.txt"), encoding="utf-8").read()
    ok("13900002222" not in deid, "原稿里的手机号没留（13900002222）")
    ok("周然" not in deid and "李明" not in deid, "原稿里的真名没留（周然 / 李明）")

    print("\n【第 1 棒】① 访谈提纲设计（从契约继承）")
    r1 = run(proj, "b1_guide", {"brief": "contracts/research_brief.md",
                                "audience": "过去一年里谈过恋爱或正在恋爱的本校本科生",
                                "duration": 45, "style": "semi", "focus": "", "channels": ""})
    ok(not r1["err"], "跑通", r1["err"][:120])
    ok(exists(proj, "contracts/interview_guide.md"), "提纲产出")
    guide = open(os.path.join(proj, "contracts", "interview_guide.md"), encoding="utf-8").read()
    ok("游戏" not in guide and "产品团队" not in guide, "没有硬编码的游戏语料残留")
    ok("大学生谈恋爱的动机" in guide, "研究问题的问句是从契约继承来的（不是空模板）")
    ok("单选：陪伴/情感支持" in guide, "契约第 4 列「怎么测」的选项进了提纲")

    print("\n【第 2 棒】② 编码整理（在**脱敏稿**上跑 —— 这才是真实使用顺序）")
    r2 = run(proj, "b2_coding", {"transcript": "output/脱敏_小周.txt",
                                 "split": "speaker", "keep_interviewer": ["keep_q"],
                                 "min_len": 6, "top_kw": 25})
    ok(not r2["err"], "跑通", r2["err"][:120])
    ok(exists(proj, "output/编码工作表.csv", "output/访谈_初步分析.md",
              "contracts/coded_transcript.md"), "三份产物都在")
    spk_line = next((x for x in r2["logs"] if "认定访谈者" in x), "")
    ok("认定访谈者" in spk_line and "访谈地点" not in spk_line,
       "说话人认对了（不是元信息标签）", spk_line)
    ws_path = os.path.join(proj, "output", "编码工作表.csv")
    csv_txt = open(ws_path, encoding="utf-8-sig").read()
    ok("[姓名" in csv_txt, "脱敏稿里的 [姓名N] 占位名能当说话人认出来")

    print("\n【第 3 棒】填编码（模拟研究员在 Excel 里逐段填）")
    import csv as _csv
    rows = list(_csv.DictReader(io.StringIO(csv_txt)))
    cols = list(rows[0].keys())
    # 造两份"人填的"编码：挑几段说得实在的，贴上开放编码/范畴/主题
    plan = [
        ("后来分了", "关系结束", "关系维持", "关系投入"),
        ("不在乎", "被忽视的感受", "情感需求", "关系投入"),
        ("花三四百", "恋爱开销", "金钱投入", "消费观念"),
        ("给多少关系很大", "家庭经济影响", "金钱投入", "消费观念"),
        ("先把简历弄好", "优先事项排序", "个人规划", "未来规划"),
        ("不会再像以前那样", "从经历中学到", "关系认知变化", "关系投入"),
    ]
    filled = 0
    hit_rows = set()
    for key, o, c, t in plan:
        for row in rows:
            if key in (row.get("原文") or ""):
                row["开放编码"], row["范畴"], row["主题"] = o, c, t
                hit_rows.add(row.get("原文"))
                break
    # ⚠ 计数要按**行**去重：两个关键词可能落在同一段上
    #   （第一版就是这么错的：说"填了 6 段"其实只有 5 段，然后拿这个数去和
    #    重跑后的 5 段比，报了个假的"没搬回来"。测试自己错会浪费一整轮排查。）
    filled = len(hit_rows)
    with open(ws_path, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    ok(filled >= 4, "填了 %d 段编码（去重后；够验证汇总了）" % filled)
    # 说话人那一列别混进访谈者，否则覆盖度会虚高
    subj = "、".join(sorted(set(r["说话人"] for r in rows if r.get("开放编码"))))
    print("     填过编码的段落来自：%s" % subj)

    print("\n【第 4 棒】②b 编码汇总（范畴 → 主题）")
    r4 = run(proj, "b2b_codesum", {"coded_file": "output/编码工作表.csv",
                                   "min_cover": 1, "max_themes": 6, "quote_n": 2,
                                   "opts": []})
    ok(not r4["err"], "跑通", r4["err"][:160])
    ok(exists(proj, "output/编码汇总.md", "output/编码_主题矩阵.csv",
              "output/编码汇总_主题.csv", "output/编码汇总_范畴.csv"),
       "四份汇总产物都在")
    summary = ((r4["res"] or {}).get("summary") or "")
    print("     摘要：%s" % summary)
    matrix = open(os.path.join(proj, "output", "编码_主题矩阵.csv"), encoding="utf-8-sig").read()
    ok("消费观念" in matrix or "关系投入" in matrix, "主题矩阵里有我填的主题")
    ok("未来规划" in matrix, "第三个主题也在（说明不是只认第一行）")
    agg = open(os.path.join(proj, "output", "编码汇总.md"), encoding="utf-8").read()
    ok("花三四百" in agg or "恋爱开销" in agg, "汇总里配了原话（不是空壳）")

    print("\n【第 5 棒】重跑 ② 之后，手工编码还在不在（最要命的那条）")
    r5 = run(proj, "b2_coding", {"transcript": "output/脱敏_小周.txt",
                                 "split": "speaker", "keep_interviewer": ["keep_q"],
                                 "min_len": 6, "top_kw": 10})
    after = open(ws_path, encoding="utf-8-sig").read()
    rows5 = list(_csv.DictReader(io.StringIO(after)))
    kept = [x for x in rows5 if (x.get("开放编码") or "").strip()]
    ok(len(kept) >= filled, "重跑之后已填的编码还在（%d 段 → %d 段）" % (filled, len(kept)))
    ok(any("搬回来" in x for x in r5["logs"]), "日志说了搬回几段")

    print("\n【全链留档】")
    gaps = [x for x in r1["alerts"] + r2["alerts"] + r4["alerts"]
            if x.get("level") in ("warn", "error")]
    print("     三棒一共 %d 条 warn/error 提醒" % len(gaps))
    for a in gaps[:6]:
        print("       - [%s] %s" % (a.get("level"), str(a.get("msg"))[:70]))
    lines = ["# 质性线全链实证 · 记录", "",
             "材料：真实访谈转写稿（含真名与手机号）",
             "路径：samples → 🔒 → output/脱敏_小周.txt → ② → 手工填编码 → ②b", "",
             "## 每一棒的结果"]
    lines += ["- 🔒：脱敏稿/报告/格式说明三件齐；原稿手机号与真名均未残留",
              "- ①：%s" % ((r1["res"] or {}).get("summary") or ""),
              "- ②：%s" % ((r2["res"] or {}).get("summary") or ""),
              "- 手工填了 %d 段编码（%d 个主题）" % (filled, len(set(p[3] for p in plan))),
              "- ②b：%s" % summary,
              "- 重跑 ② 后编码保留 %d 段" % len(kept),
              "", "## 三棒的 warn/error 提醒（%d 条）" % len(gaps)]
    for a in gaps:
        lines.append("- [%s] %s" % (a.get("level"), str(a.get("msg"))[:140]))
    open(os.path.join(TMP, "全链记录.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

    print("\n" + ("全链通过" if not FAIL else "有失败项")
          + "：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    # 留一份人类可读的记录，出问题时能直接翻
    try:
        os.makedirs(os.path.join(HERE, "_jobs"), exist_ok=True)
        with open(os.path.join(HERE, "_jobs", "chain_last.md"), "w", encoding="utf-8") as f:
            f.write(open(os.path.join(TMP, "全链记录.md"), encoding="utf-8").read())
    except OSError:
        pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
