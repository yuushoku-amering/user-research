# -*- coding: utf-8 -*-
"""② 访谈记录编码整理 · 回归测试

跑法（跟别的测试一样）：python _codingtest.py
需要引擎 Python（config.json 里那个）。
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
from core import paths                                     # noqa: E402
from core import kw as KW                                  # noqa: E402

PASS, FAIL = [], []


def ok(cond, label, extra=""):
    if cond:
        PASS.append(label)
        print("  [OK] " + str(label))
    else:
        FAIL.append(label)
        print("  [FAIL] " + str(label) + (("  -- " + str(extra)) if extra else ""))


def eq(a, b, label):
    same = a == b
    ok(same, label, None if same else "实际 %r，期望 %r" % (a, b))


def run_block(root, params, block="b2_coding"):
    job = dict(params)
    job["project_root"] = root
    job["block_dir"] = os.path.join(HERE, "blocks", block)
    job["block_id"] = block
    jf = os.path.join(root, "_job.json")
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([paths.engine_python(), os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE, stdin=subprocess.DEVNULL)
    out = p.stdout.decode("utf-8", "replace")
    res, err, logs = None, "", []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("t") == "result":
            res = m.get("data")
        elif m.get("t") == "error":
            err = m.get("msg", "")
        elif m.get("t") == "log":
            logs.append(str(m.get("msg") or ""))
    return {"result": res, "error": err, "logs": logs,
            "alerts": ((res or {}).get("alerts") or [])}


def write(root, rel, text, enc="utf-8"):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding=enc, newline="") as f:
        f.write(text)


def read_out(root, name):
    p = os.path.join(root, "output", name)
    if not os.path.exists(p):
        return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(p, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""


# 前辈那份真实转写稿的样子：开头是元信息块，正文是「说话人：内容」
# ⚠ 这个头部就是踩过的坑：`访谈地点：线上语音` 被当成了**说话人**，
#   于是"认定访谈者：访谈地点"，后面整条发言人判定都歪了。
TRANSCRIPT = """访谈时间：2026年3月14日 晚上
访谈地点：线上语音
采访者：李明
受访者：周然，男，21岁，大三，计算机学院，联系电话 13900002222

李明：你现在是单身对吧？
周然：对，单了快一年了。
李明：上一段是什么情况？
周然：大二上学期在一起的，同班的，谈了七八个月吧。后来分了。
        她想要我每天陪她，但我那阵子在准备比赛，经常要去实验室。
李明：你觉得是谁的问题？
周然：都有吧。我觉得我当时确实没太在意她的感受。
李明：那你会主动去找吗？
周然：不太会。我现在更想先把简历弄好，找个实习。
"""


def main():
    root = tempfile.mkdtemp(prefix="urw_code_")
    try:
        os.makedirs(os.path.join(root, "samples"), exist_ok=True)
        os.makedirs(os.path.join(root, "output"), exist_ok=True)

        print("\n【1】转写稿头部的元信息**不能**被当成说话人")
        # 现场：`访谈地点：线上语音` 的标签含"地点"，但 META_KEYS 里没有「访谈地点」，
        #       于是程序说「认定访谈者：访谈地点」—— 后面每个说话人都判错。
        write(root, "samples/t.txt", TRANSCRIPT)
        r1 = run_block(root, {"file": None, "transcript": "samples/t.txt",
                              "split": "speaker", "keep_interviewer": ["keep_q"],
                              "min_len": 2, "top_kw": 15})
        ok(not r1["error"], "跑通", (r1["error"] or "")[:120])
        logs1 = " ".join(r1["logs"])
        ok("认定访谈者：李明" in logs1,
           "认定访谈者是「李明」（不是「访谈地点」）", logs1[:200])
        for bad in ("访谈地点", "访谈时间", "受访者", "采访者"):
            ok(("认定访谈者：%s" % bad) not in logs1, "没把「%s」当说话人" % bad)
        csv1 = read_out(root, "编码工作表.csv")
        ok("线上语音" not in csv1, "元信息行的内容没被当成发言", csv1[:200])
        ok("李明" in csv1 and "周然" in csv1, "真的说话人在表里")

        print("\n【2】续行（同一个人说好几行）要合并成同一段")
        ok("准备比赛" in csv1 and "实验室" in csv1, "续行内容进了发言单元")
        # 续行不该单独成段：它上面那段的原文里应该同时有"后来分了"和"实验室"
        import csv as _csv
        rows2 = list(_csv.DictReader(io.StringIO(csv1.lstrip("\ufeff"))))
        merged = [x for x in rows2 if "后来分了" in (x.get("原文") or "")]
        ok(bool(merged) and "实验室" in merged[0]["原文"],
           "「谈了七八个月…后来分了」和续行「…经常要去实验室」在同一条里",
           (merged[0]["原文"][:60] if merged else "没找到那条"))

        print("\n【3】关键词不能是从词中间切出来的碎片")
        # 现场：2-gram 切法把 `谈恋爱` 切成 `谈恋`、`那阵子在准备` 切出 `期在`，
        #       前 25 个"关键词"里有一小半不是词，研究员没法用。
        write(root, "samples/kw.txt",
              "周然：我上一段一个月大概花三四百。\n"
              "周然：她是异地，我们天天视频。\n"
              "周然：我觉得谈恋爱得看人，以前就是想着开心。\n")
        r3 = run_block(root, {"transcript": "samples/kw.txt", "split": "speaker",
                              "keep_interviewer": ["keep_q"], "min_len": 2, "top_kw": 20})
        logs3 = " ".join(r3["logs"])
        ok("关键词" in logs3, "有报关键词", logs3[:150])
        for frag in ("期在", "么情", "谈恋(", "得花(", "不太(", "就是("):
            ok(frag not in logs3, "没有碎片「%s」" % frag, logs3[:200])
        ok("谈恋爱" in logs3, "「谈恋爱」是整体，没被切断", logs3[:200])
        ok("异地" in logs3, "认出「异地」", logs3[:200])

        print("\n【4】词表：一行多个词要能拆开读")
        # 现场：词表文件是一行多个词（方便人读），第一版整行当一个词，
        #       于是词表里躺着一条超长"词"，切词一个都命中不了 → 关键词直接空。
        lex = KW.load_lexicon()
        ok(len(lex) > 100, "词表读进来了（%d 个词）" % len(lex))
        ok("谈恋爱" in lex and "异地" in lex, "词表里有「谈恋爱」「异地」")
        for w in lex:
            if " " in w:
                ok(False, "词表里不该有带空格的假词：%r" % w[:40])
                break
        else:
            ok(True, "词表里没有带空格的条目（说明按空格拆开了）")
        # 加词入口：传 extra 就该认
        got = KW.keyword_hits(["这是个蓝鲸科技的项目"], extra=["蓝鲸科技"])
        ok(any(w == "蓝鲸科技" for w, _c, _o in got),
           "extra 传进去的词能被认出来（研究员加词的入口）", got)
        # 停用词要拦住
        got2 = KW.keyword_hits(["我觉得就是这样的"])
        ok(not any(w in ("觉得", "就是", "这样") for w, _c, _o in got2),
           "停用词（觉得/就是）不会当成线索", got2)

        print("\n【5】CSV 别被人名里的逗号/引号搞错位")
        # 原文里带英文逗号、双引号、中文顿号 —— CSV 必须正确转义，
        # 否则研究员在 Excel 里会看到整张表错列（而且不一定看得出来）。
        write(root, "samples/comma.txt",
              '李明：你平时怎么花钱？\n'
              '周然：吃饭、看电影，还有"礼物"，大概三百。\n'
              '周然：他说"我请你"，然后就AA了。\n')
        r5 = run_block(root, {"transcript": "samples/comma.txt", "split": "speaker",
                              "keep_interviewer": ["keep_q"], "min_len": 2, "top_kw": 10})
        ok(not r5["error"], "带逗号引号的稿子跑通", (r5["error"] or "")[:120])
        csv5 = read_out(root, "编码工作表.csv")
        ncol = len((csv5.splitlines() or [""])[0].split(","))
        rows5 = list(_csv.DictReader(io.StringIO(csv5.lstrip("\ufeff"))))
        ok(all(len(x) == ncol for x in rows5),
           "每一行的列数都一致（没被逗号/引号搞错位）",
           [len(x) for x in rows5][:6])
        ok(any("吃饭" in (x.get("原文") or "") and "礼物" in (x.get("原文") or "")
               for x in rows5),
           "带逗号的原文完整地待在一个单元格里")

        print("\n【7】重跑**不能**抹掉人填好的编码（这一条最要命）")
        # 现场：研究员会反复回来调参数（换切法、改最短字数），而每次重跑都会重写编码表。
        #   原来写出来的是一张全空的新表 → 手工编码全没，界面也不问一声。
        #   实测过的损失：1284 字节 / 9 段编码 → 189 字节 / 0 段，`_history` 里连备份都没有。
        # ⚠ 重跑时**不要换切法**：换切法意味着段落边界变了，"同一句话还是同一句话"
        #   这个对齐前提就不成立（程序只能留空，不该硬猜）。
        #   真实的反复重跑是"调不改变切分的参数"（关键词个数、是否丢附和、最短字数微调）。
        write(root, "samples/carry.txt", TRANSCRIPT)
        run_block(root, {"transcript": "samples/carry.txt", "split": "speaker",
                         "keep_interviewer": ["keep_q"], "min_len": 2, "top_kw": 10})
        csvp = os.path.join(root, "output", "编码工作表.csv")
        # 手工填两段（模拟研究员在 Excel 里填）
        with open(csvp, encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
            cols = list(rows[0].keys())
        filled_txt = (rows[1]["原文"] or "").strip()
        rows[1]["开放编码"] = "关系结束"
        rows[1]["范畴"] = "关系维持"
        rows[1]["主题"] = "关系投入"
        with open(csvp, "w", encoding="utf-8-sig", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        # 用**不同参数**重跑（只改不改变切分的：关键词个数）
        r7 = run_block(root, {"transcript": "samples/carry.txt", "split": "speaker",
                              "keep_interviewer": ["keep_q"], "min_len": 2, "top_kw": 25})
        csv7 = read_out(root, "编码工作表.csv")
        rows7 = list(_csv.DictReader(io.StringIO(csv7.lstrip("\ufeff"))))
        got = [x for x in rows7 if (x.get("原文") or "").strip() == filled_txt]
        ok(bool(got), "重跑之后那一段还在表里（行号变了也认得出来）",
           "填过的那句：%s" % filled_txt[:40])
        if got:
            ok(got[0].get("开放编码") == "关系结束" and got[0].get("范畴") == "关系维持"
               and got[0].get("主题") == "关系投入",
               "**填过的三列原样搬回来了**（没被新表冲成空白）",
               {k: got[0].get(k) for k in ("开放编码", "范畴", "主题")})
        logs7 = " ".join(r7["logs"])
        ok("搬回来" in logs7, "日志里说了搬回几段（不是悄悄做的）", logs7[:200])
        al7 = " ".join(str(a.get("msg") or "") for a in (r7.get("alerts") or []))
        ok("保留" in al7, "结果页也提醒了「你填过的编码保留下来了」", al7[:150])
        # 备份也要有：旧表覆盖前留一份
        hdir = os.path.join(root, "_history")
        hist = os.listdir(hdir) if os.path.isdir(hdir) else []
        ok(any("编码工作表" in h for h in hist),
           "旧编码表在 _history/ 里留了备份（兜底退路）", hist[:6])

        print("\n【8】过滤参数真的有用（填了不能没效果）")
        r6a = run_block(root, {"transcript": "samples/t.txt", "split": "speaker",
                               "keep_interviewer": [], "min_len": 2, "top_kw": 10})
        ok("访谈者提问 0" not in " ".join(r6a["logs"]),
           "不勾「保留访谈者的话」时，访谈者的提问真的被丢掉了",
           " ".join(r6a["logs"])[:200])
        r6b = run_block(root, {"transcript": "samples/t.txt", "split": "sentence",
                               "keep_interviewer": ["keep_q"], "min_len": 2, "top_kw": 10})
        n6a = len((read_out(root, "编码工作表.csv") or "").splitlines())
        ok(n6a > 0, "换切法（按句子）也能跑通")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + ("全部通过" if not FAIL else "有失败项")
          + "：%d 通过 / %d 失败\n" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
