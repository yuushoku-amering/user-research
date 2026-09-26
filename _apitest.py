# -*- coding: utf-8 -*-
"""工作台 · API 自测（需要 server 已经在跑）

    python _apitest.py [http://127.0.0.1:8765]

结果写到 _jobs/apitest.txt（UTF-8），不受控制台编码影响。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

# ⚠ 控制台是 GBK：打印 emoji / 特殊符号会 UnicodeEncodeError 把测试打断。
#   这一句是**必须**的（踩过两次）。
try:
    sys.stdout.reconfigure(encoding=utf-8, errors=replace)
    sys.stderr.reconfigure(encoding=utf-8, errors=replace)
except Exception:
    pass


HERE = os.path.dirname(os.path.abspath(__file__))
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
OUT = []


def say(*a):
    OUT.append(" ".join(str(x) for x in a))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    say("=" * 70)
    say("工作台 API 自测 · %s" % BASE)
    say("=" * 70)

    st = get("/api/state")
    say("1) /api/state ok=%s" % st.get("ok"))
    # ⚠ **没选项目时 /api/state 的 project 是 null，这是合法状态**（界面显示空栏）。
    #   原来这里直接 st["project"]["name"]，一崩就是 TypeError、还看不出为什么，
    #   而"没选项目"往往正是**上一个自测把临时路径写进配置**留下的后遗症（见下方第 7 步）。
    #   所以这里给一句人话，而不是让它崩。
    if not st.get("project"):
        say("   !! 现在没有当前项目 —— 这个自测必须在**选好项目**的状态下跑。")
        if st.get("missing_root"):
            say("      记着的项目不见了：%s" % st["missing_root"])
        say("      去界面上从下拉里选一个项目（或点「打开…」），然后重跑。")
        with open(os.path.join(HERE, "_jobs", "apitest.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(OUT))
        return 2
    say("   项目：%s" % st["project"]["name"])
    say("   引擎：%s（存在=%s）" % (st["env"]["python"], st["env"]["python_exists"]))
    say("   读表包：%s" % st["env"]["libs"])
    say("   SPSS：%s（存在=%s）" % (st["env"]["spss"], st["env"]["spss_exists"]))
    say("   组块 %d 个：" % len(st["blocks"]))
    broken = []
    for b in st["blocks"]:
        say("      %-14s %-22s 引擎=%s%s" % (
            b["id"], b["name"], b.get("has_engine"),
            "  [加载失败]" if b.get("broken") else ""))
        if b.get("broken") or not b.get("has_engine"):
            broken.append(b["id"])
    if broken:
        say("")
        say("!!! 有组块加载失败：%s —— 修好再看后面的结果" % "、".join(broken))
    say("   项目产物 %d 个" % len(st["project"]["artifacts"]))

    say("")
    say("2) /api/columns（变量下拉用）")
    # ⚠ 别写死文件名——不同项目的 csv 名字不一样（写死过一次，换个项目就 404）
    cand = [a["rel"] for a in st["project"]["artifacts"] if a["rel"].lower().endswith(".csv")]
    pick = next((c for c in cand if "clean_data" in c), cand[0] if cand else "")
    say("   项目里挑了：%s（共 %d 个 csv）" % (pick, len(cand)))
    rel = urllib.parse.quote(pick)
    c = get("/api/columns?rel=" + rel)
    say("   ok=%s  %s 行 × %s 列（%s）" % (c.get("ok"), c.get("rows"), c.get("n_cols"), c.get("how")))
    if c.get("ok"):
        for x in c["columns"]:
            say("      %-18s %-12s 取值 %d 种" % (x["name"], x["kind"], x["n_unique"]))

    say("")
    say("3) /api/run → 轮询 /api/job（端到端跑一次 ⑥ 统计分析）")
    # ⚠ 别写死输入文件（写死过两次，换个项目就失败）：
    #   用「当前项目里实际存在的 clean_data.csv」，没有就跳过这一步。
    data_rel = next((a["rel"] for a in st["project"]["artifacts"]
                     if a["rel"].lower().endswith("clean_data.csv")), "")
    if data_rel:
        say("   用数据：%s" % data_rel)
        r = post("/api/run", {
            "block_id": "b5_stats",
            "project": st["project"]["root"],
            "params": {
                "file": data_rel,
                "question": "auto",
                "dv": "", "group": "", "ivs": [],
                "fallback": "nonparam", "alpha": 0.05,
                "gen_sps": ["sps"],
            },
        })
    else:
        say("   这个项目还没有 clean_data.csv，跳过端到端这一步")
        r = {"ok": False, "error": "没有可用的 clean_data.csv"}
    say("   起任务：ok=%s job_id=%s" % (r.get("ok"), r.get("job_id")))
    if not r.get("ok"):
        say("   错误：%s" % r.get("error"))
    else:
        jid, since, t0 = r["job_id"], 0, time.time()
        while time.time() - t0 < 180:
            j = get("/api/job?id=%s&since=%d" % (jid, since))["job"]
            since = j["log_count"]
            for l in j["logs"]:
                say("      [%s] %s" % (l["level"], l["msg"]))
            if j["status"] != "running":
                say("   状态：%s（%.1fs）" % (j["status"], j["elapsed"]))
                if j.get("error"):
                    say("   错误：%s" % j["error"])
                res = j.get("result") or {}
                say("   摘要：%s" % res.get("summary"))
                say("   表格 %d 张 / 图 %d 张 / 语法 %d 份" % (
                    len(res.get("tables", [])), len(res.get("figures", [])),
                    len(res.get("text", []))))
                break
            time.sleep(0.6)

    say("")
    say("5) /api/run 跑 ②b 编码汇总（用项目里那份已填的编码表）")
    code_rel = next((a["rel"] for a in st["project"]["artifacts"]
                     if a["rel"].replace("\\", "/") == "output/编码工作表.csv"), "")
    if code_rel:
        r2 = post("/api/run", {
            "block_id": "b2b_codesum",
            "project": st["project"]["root"],
            "params": {"coded_file": code_rel, "min_cover": 2, "max_themes": 6,
                       "quote_n": 3, "opts": ["list_uncoded"]},
        })
        say("   起任务：ok=%s job_id=%s" % (r2.get("ok"), r2.get("job_id")))
        if r2.get("ok"):
            jid2, t0 = r2["job_id"], time.time()
            while time.time() - t0 < 180:
                j2 = get("/api/job?id=%s&since=0&steps_since=0" % jid2)["job"]
                if j2["status"] == "waiting":
                    p = j2.get("pending") or {}
                    say("   ⏸ 停在检查点：%s" % p.get("title"))
                    post("/api/job/answer", {"id": jid2, "choice": p.get("default") or "go"})
                    say("   → 按默认值回答，继续")
                if j2["status"] not in ("running", "waiting"):
                    say("   状态：%s（%.1fs）" % (j2["status"], j2["elapsed"]))
                    if j2.get("error"):
                        say("   错误：%s" % j2["error"])
                    res2 = j2.get("result") or {}
                    say("   摘要：%s" % res2.get("summary"))
                    say("   步骤卡 %d 张 / 表 %d 张 / 图 %d 张" % (
                        len(j2.get("steps", [])), len(res2.get("tables", [])),
                        len(res2.get("figures", []))))
                    break
                time.sleep(0.6)
    else:
        say("   这个项目还没有 output/编码工作表.csv，跳过")

    say("")
    say("7) 守卫在「回退」这条路上也要拦得住")
    # 回退 = 又起了一次任务。不管这条路的话，绕过办法就是「先跑一次再回退」，
    # 素材那道关等于不存在。这里在临时项目上验一遍（跑完就删，不碰你的项目）。
    #
    # ⚠ 收尾要把当前项目**切回去**：临时项目是 `set_project()` 设过的，
    #   虽然它不会被写进 config.json（临时目录天生一次性，见 paths.is_temp_path），
    #   但会留在**本次会话**的"当前项目"里。等 `rmtree` 把它删掉，
    #   界面一刷新就显示"记着的项目不见了"—— 看着像把我项目弄丢了。
    #   原来就漏了这一步（2026-09-24 实测踩到）。
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="urw_rewind_")
    home_root = (st.get("project") or {}).get("root") or ""
    try:
        os.makedirs(os.path.join(tmp, "samples"), exist_ok=True)
        with open(os.path.join(tmp, "samples", "访谈稿.txt"), "w", encoding="utf-8") as f:
            f.write("张伟：电话 13812345678，邮箱 zhangwei@example.com\n")
        r3 = post("/api/run", {"block_id": "b2_coding", "project": tmp,
                               "params": {"transcript": "samples/访谈稿.txt", "split": "speaker"}})
        say("   不带确认直接跑：need_guard=%s（该 True）" % r3.get("need_guard"))
        r4 = post("/api/run", {"block_id": "b2_coding", "project": tmp,
                               "params": {"transcript": "samples/访谈稿.txt", "split": "speaker"},
                               "confirmed_sensitive": True})
        jid3 = r4.get("job_id")
        say("   带确认跑起来：job=%s" % jid3)
        if jid3:
            time.sleep(1.5)
            r5 = post("/api/job/rewind", {"id": jid3, "upto": 0})
            say("   不带确认回退：need_guard=%s（该 True —— 回退也是重跑）" % r5.get("need_guard"))
            r6 = post("/api/job/rewind", {"id": jid3, "upto": 0, "confirmed_sensitive": True})
            say("   带回退确认：ok=%s 新任务=%s" % (r6.get("ok"), r6.get("job_id")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        # 删之前先切回去，别留下"当前项目指向一个已删目录"的现场
        if home_root:
            try:
                post("/api/project/open", {"root": home_root})
            except Exception as e:
                say("   （切回当前项目失败，不影响前面结果：%s）" % e)

    say("")
    say("8) 再取一次 /api/state 看产物有没有变多")
    st2 = get("/api/state")
    # ⚠ 这里原来直接 `st2["project"]["artifacts"]` —— **没选项目时 project 是 null**，
    #   整个自测在第 8 步崩掉（TypeError），前面的结果全白跑。
    #   「没选项目」是合法状态（界面就是空栏），自测也得认它。
    p1, p2 = st.get("project"), st2.get("project")
    if not p2:
        say("   现在没选项目（%s）—— 跳过产物对比" % (st2.get("error") or "顶栏没选"))
    else:
        say("   产物 %d 个（原来 %d 个）" % (
            len(p2.get("artifacts") or []), len((p1 or {}).get("artifacts") or [])))
        say("   组块完成状态：")
        for b in st2["blocks"]:
            s = (p2.get("status") or {}).get(b["id"], {})
            say("      %-18s %s" % (b["id"], "✅ 已完成" if s.get("done") else "○ 未完成"))

    # 收尾：把**当前项目**切回来。
    # ⚠ 第 7 步在临时项目上跑过，那个临时路径会留在**本次会话**的"当前项目"里
    #   （不落盘，但界面一刷新就会显示"记着的项目不见了"，看着像把项目弄丢了）。
    #   不切回来的话，来看工作台的人会以为项目没了 —— 顺手恢复，不留这种惊吓。
    try:
        if st.get("project") and st["project"].get("root"):
            post("/api/project/open", {"root": st["project"]["root"]})
            say("   已把当前项目切回：%s" % st["project"]["name"])
    except Exception as e:
        say("   切回当前项目失败（不影响前面结果）：%s" % e)

    with open(os.path.join(HERE, "_jobs", "apitest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(OUT))
    print("OK -> %s" % os.path.join(HERE, "_jobs", "apitest.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
