# -*- coding: utf-8 -*-
"""工作台 · 自检

直接调 runner.py 跑各组块的引擎，把日志和结果摘要打出来。
用 UTF-8 落在文件里，不受控制台编码影响（PowerShell 管道会把中文搞乱）。

    python _selftest.py              # 跑全部用例
    python _selftest.py b3_survey    # 只跑某个组块

产物：_jobs/<用例名>.out.jsonl（原始输出）、_jobs/<用例名>.summary.txt（摘要）
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import paths          # noqa: E402

# ⚠ 控制台是 GBK：打印 emoji / 特殊符号会 UnicodeEncodeError 把测试打断。
#   这一句是**必须**的（踩过两次）。
try:
    sys.stdout.reconfigure(encoding=utf-8, errors=replace)
    sys.stderr.reconfigure(encoding=utf-8, errors=replace)
except Exception:
    pass


def _pick_project():
    """自检要在**哪个项目**里跑。

    理想情况用的是工作台旁边那个演示项目（`data/sim_survey.csv` + `samples/情景_…`），
    但它不在版本库里 —— 别人 clone 下来是没有的。所以：旁边的演示项目在就用它，
    不在就用**自带素材**（`_fixtures/情景_游戏DAU/`）临时拼一个。

    ⚠ 拼的是临时项目，不是直接拿 `_fixtures` 当项目跑：好几条用例会**写产物**
      （⑤ 生成 output/clean_data.csv、② 重写编码工作表），落到素材目录会把仓库弄脏。
    """
    outer = os.path.dirname(HERE)
    if os.path.exists(os.path.join(outer, "data", "sim_survey.csv")):
        return outer

    src = os.path.join(HERE, "_fixtures", "情景_游戏DAU")
    if not os.path.isdir(src):
        raise SystemExit("找不到演示项目，也找不到自带素材 %s —— 自检跑不起来（素材不该缺）" % src)
    dst = os.path.join(HERE, "_jobs", "tmp_selftest_proj")
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    os.makedirs(os.path.join(dst, "output"), exist_ok=True)
    return dst


PROJ = _pick_project()
JOBS = os.path.join(HERE, "_jobs")

# ⚠ 最后一条用例要**先把素材拷进临时目录**再跑：②b 的产物写在编码表旁边那一层，
#   直接拿 `_fixtures` 当项目跑，产物会落进素材目录、把仓库弄脏。
_SINGLE_SRC = os.path.join(HERE, "_fixtures", "访谈样例")
_SINGLE = os.path.join(JOBS, "tmp_selftest_单人份")
if os.path.isdir(_SINGLE_SRC) and not os.path.isdir(_SINGLE):
    shutil.copytree(_SINGLE_SRC, _SINGLE, dirs_exist_ok=True)

CASES = [
    ("b3_survey", "问卷统计（全勾）", {
        "file": "data/sim_survey.csv",
        "tasks": ["profile", "freq", "desc", "cross", "alpha", "open"],
        "top_n": 8,
        "cross_vars": "平台, 是否愿意推荐",
        "open_var": "Q12_开放题",
    }),
    ("b4_prep", "预处理（合成量表 + 反向题 + 异常值）", {
        "file": "data/sim_survey.csv",
        "missing": "keep",
        "composite": "满意度 = mean(Q8_1, Q8_2, Q8_3, Q8_4, Q8_5)\n"
                     "继续意愿 = mean(Q9_1, Q9_2, Q9_3)",
        "outlier": "z3",
    }),
    ("b5_stats", "统计 · 组间差异（平台 × 满意度）", {
        "file": "output/clean_data.csv",
        "question": "compare",
        "dv": "满意度",
        "group": "平台",
        "fallback": "nonparam",
        "alpha": 0.05,
        "gen_sps": ["sps", "fig"],
    }),
    ("b5_stats", "统计 · 回归（谁在预测继续意愿）", {
        "file": "output/clean_data.csv",
        "question": "relate",
        "dv": "继续意愿",
        "ivs": ["满意度", "崩溃频率", "数值改动满意度", "周均时长_小时"],
        "fallback": "nonparam",
        "alpha": 0.05,
        "gen_sps": ["sps", "fig"],
    }),
    ("b5_stats", "统计 · 相关（满意度 × 继续意愿）", {
        "file": "output/clean_data.csv",
        "question": "relate",
        "dv": "继续意愿",
        "ivs": ["满意度"],
        "alpha": 0.05,
        "gen_sps": ["sps"],
    }),
    ("b5_stats", "统计 · 卡方（崩溃频率 × 是否愿意推荐）", {
        "file": "output/clean_data.csv",
        "question": "assoc",
        "dv": "崩溃频率",
        "group": "是否愿意推荐",
        "alpha": 0.05,
        "gen_sps": ["sps"],
    }),
    ("b1_guide", "访谈提纲设计（读情景简报生成）", {
        "brief": "samples/情景_游戏DAU下滑_研究简报.md",
        "audience": "近 30 天内流失的 Android 老玩家",
        "duration": 45,
        "style": "semi",
        "focus": "闪退到底影响了哪些具体场景\n数值改动前后，玩家的投入感受变化",
        "channels": "游戏内弹窗 + 官方 QQ 群",
    }),
    ("b2_coding", "访谈编码（拆发言单元 + 线索 + 引语候选）", {
        "transcript": "samples/情景_游戏DAU下滑_访谈转写稿.txt",
        "split": "speaker",
        "keep_interviewer": ["keep_q", "drop_short"],
        "min_len": 6,
        "top_kw": 25,
    }),
    ("b9_deident", "去标识化（访谈转写稿，含真实格式的 PII）", {
        "file": "samples/情景_游戏DAU下滑_访谈转写稿.txt",
        "keep_mapping": ["mapping", "clean_log"],
        "extra_rules": "星海科技有限公司 = 某科技公司",
    }),
    ("b2b_codesum", "编码汇总（范畴 → 主题，用自带的那份已填编码表）", {
        # 素材在版本库里（`_fixtures/访谈样例/`）：一人份、已填好码的编码工作表。
        # 原来用某个真实案例项目的 output/编码工作表.csv —— 那个项目不在库里，
        # 别人 clone 下来这一条必然红，而且红的理由跟被测代码无关。
        "__project__": _SINGLE,
        "coded_file": "编码工作表_单人份.csv",
        "min_cover": 2,
        "max_themes": 6,
        "quote_n": 3,
        "opts": ["list_uncoded"],
    }),
    # ⚠ 「跑在脱敏稿上」那条回归用例放在 _codesum_test.py 里，用临时项目跑。
    #   放这儿会出事：② 会重写 output/编码工作表.csv，把案例里已填的码清空
    #   （踩过一次——自检把案例项目的数据洗了）。
]


# ⚠ 这一条要**先把素材拷进临时目录**再跑：②b 的产物写在编码表旁边那一层，
#   直接拿 `_fixtures` 当项目跑，产物会落进素材目录、把仓库弄脏。
#   （临时目录的建立放在上面 `CASES` 之前了；这里只留说明。）


def run_case(block_id, name, params, idx):
    job = dict(params)
    job["project_root"] = job.pop("__project__", PROJ)
    job["block_dir"] = os.path.join(HERE, "blocks", block_id)
    job["block_id"] = block_id
    jf = os.path.join(JOBS, "self_%02d_%s.json" % (idx, block_id))
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([paths.engine_python(), os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE,
                       stdin=subprocess.DEVNULL)   # 无人应答：检查点会退回默认值，不会卡住
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")

    raw = os.path.join(JOBS, "self_%02d.out.jsonl" % idx)
    with open(raw, "w", encoding="utf-8") as f:
        f.write(out + ("\n--- STDERR ---\n" + err if err.strip() else ""))

    msgs, result, error = [], None, ""
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("t") == "log":
            msgs.append("[%s] %s" % (m.get("level", "info"), m.get("msg", "")))
        elif m.get("t") == "result":
            result = m.get("data")
        elif m.get("t") == "error":
            error = m.get("msg", "")

    head = "=" * 72
    lines = [head, "【%s】%s" % (block_id, name), head]
    lines += msgs
    if error:
        lines.append("!!! 失败：%s" % error)
    if result:
        lines.append("-" * 72)
        lines.append("摘要：" + str(result.get("summary", "")))
        for t in result.get("tables", []):
            lines.append("  表：%s（%d 行 × %d 列）" % (
                t.get("name"), len(t.get("rows", [])), len(t.get("columns", []))))
            for r in t.get("rows", [])[:6]:
                lines.append("      " + " | ".join(str(x) for x in r))
        for f in result.get("figures", []):
            lines.append("  图：%s → %s" % (f.get("name"), f.get("rel")))
        for tx in result.get("text", []):
            lines.append("  文本：%s（%d 字）" % (tx.get("name"), len(tx.get("text", ""))))
    lines.append("")
    return "\n".join(lines), (result is not None and not error)


def check_block_decls():
    """先确认每个组块的 block.py 都能读、engine.py 都在，编号也不撞车。

    踩过一次：改了 block.py 里的提示词，字符串没闭合 → 整个组块在界面上变成 ⚠ 加载失败，
    而引擎自检照样全过（runner 是直接按目录跑引擎的，根本不 import block.py）。

    编号（num）以前是写死在 name 里的，出现过 b5_stats 的注释写 ⑤、界面上却是 ⑥ 这种
    对不上的情况。现在编号进了声明，这里就顺手守住：不能缺、不能重、分组必须认识。
    """
    from core import registry
    bad = []
    seen = {}
    known = set(g["key"] for g in registry.RAIL_GROUPS)
    for b in registry.load_blocks():
        if b.get("broken"):
            bad.append("%s（block.py 读不了）" % b.get("id"))
            continue
        if not b.get("has_engine"):
            bad.append("%s（缺 engine.py）" % b.get("id"))
        num = b.get("num")
        if not num:
            bad.append("%s（没声明 num —— 界面上没有编号符号）" % b.get("id"))
        elif num in seen:
            bad.append("%s 和 %s 的 num 撞了：%s" % (b.get("id"), seen[num], num))
        else:
            seen[num] = b.get("id")
        if b.get("group") not in known:
            bad.append("%s 的 group=%r 不在 %s 里"
                       % (b.get("id"), b.get("group"), sorted(known)))
        if not b.get("title"):
            bad.append("%s（title 没生成出来）" % b.get("id"))
    return bad


def check_suites_utf8():
    """每个测试脚本开头都得有 **UTF-8 输出包装**。

    ⚠ 为什么专门查这个（同一个 bug 踩过两次）：
      这台机器控制台是 **GBK**，而测试脚本要打印 `✅ ❌ ⚠ 🔒` 这类符号 ——
      没包装的话 `print` 直接抛 `UnicodeEncodeError`，**整个套件当场断掉**。
      更阴的是：**用 PowerShell 直接跑没事**（它把管道当 UTF-8），
      但 `cmd` / 某些调用方式下会炸 —— 于是"我这儿明明是绿的"。
      实测 `_statstest.py` 就这么在批量回归里挂过一次，单独跑却好好的。
    """
    import glob
    import re as _re
    bad = []
    for f in sorted(glob.glob(os.path.join(HERE, "_*test*.py"))):
        src = open(f, encoding="utf-8").read()
        guarded = ("TextIOWrapper" in src) or ("reconfigure(encoding" in src)
        has_sym = bool(_re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2705\u274C\u26A0]",
                                  src))
        if has_sym and not guarded:
            bad.append(os.path.basename(f))
    return bad


def main():
    os.makedirs(JOBS, exist_ok=True)
    want = sys.argv[1:]

    bad = check_block_decls()
    if bad:
        print("!! 组块声明有问题，先修这个：")
        for x in bad:
            print("   - %s" % x)
        return 1
    print("[OK ] 组块声明：所有 block.py 都能读、engine.py 都在")

    bad8 = check_suites_utf8()
    if bad8:
        print("!! 这些测试脚本打印符号却没做 UTF-8 包装（GBK 控制台下会 UnicodeEncodeError）：")
        for x in bad8:
            print("   - %s" % x)
        print("   修法：开头加 sys.stdout = io.TextIOWrapper(sys.stdout.buffer,"
              " encoding='utf-8', errors='replace')")
        return 1
    print("[OK ] 测试脚本：打印符号的都做了 UTF-8 包装")

    chunks, ok_all = [], True
    for i, (bid, name, params) in enumerate(CASES, 1):
        if want and bid not in want:
            continue
        txt, ok = run_case(bid, name, params, i)
        ok_all = ok_all and ok
        chunks.append(txt)
        print("[%s] %s %s" % ("OK " if ok else "FAIL", bid, name))
    body = "\n".join(chunks)
    with open(os.path.join(JOBS, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(body)
    print("\n详细结果 → %s" % os.path.join(JOBS, "summary.txt"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
