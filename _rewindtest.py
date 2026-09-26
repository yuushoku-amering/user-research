# -*- coding: utf-8 -*-
"""回退（rewind）功能自测

流程：
  1. 起一次 ⑤ 统计分析 → 应停在「变量类型」检查点
  2. 回答第一个检查点 → 应停在「前提检验/方法」检查点
  3. 调 rewind(upto=0) → 重跑，前面的决定一个都不回放，应重新停在第 1 个检查点
  4. 再调 rewind(upto=1) → 回放第 1 个决定，应停在第 2 个检查点

结果写 _jobs/rewindtest.txt
"""
import json
import os
import shutil
import sys
import time
import urllib.request

# ⚠ 控制台是 GBK：打印 emoji / 特殊符号会 UnicodeEncodeError 把测试打断。
#   这一句是**必须**的（踩过两次）。
try:
    sys.stdout.reconfigure(encoding=utf-8, errors=replace)
    sys.stderr.reconfigure(encoding=utf-8, errors=replace)
except Exception:
    pass


HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8765"
OUT = os.path.join(HERE, "_jobs", "rewindtest.txt")
LOG = []

# 项目从哪来：
#   1. 命令行给了就用它（python _rewindtest.py <项目目录>）
#   2. 否则用**自带素材**临时拼一个（`_fixtures/分析样例/clean_data.csv`）
# 原来写死成某个真实案例项目的绝对路径 —— 别人 clone 下来直接跑不起来，
# 而且那个项目一旦被删，测试就永久红了。测试要能在任何机器上自己活下去。
FIXTURE = os.path.join(HERE, "_fixtures", "分析样例", "clean_data.csv")


def _cur_project_root():
    """现在服务端开着哪个项目（收尾要把研究员原来那个还回去）。"""
    try:
        return (get("/api/state").get("project") or {}).get("root") or ""
    except Exception:
        return ""

PARAMS = {
    "file": "output/clean_data.csv", "question": "compare",
    "dv": "付费意愿", "group": "是否知道有付费版",
    "fallback": "nonparam", "alpha": 0.05, "gen_sps": ["sps"],
}


def say(*a):
    line = " ".join(str(x) for x in a)
    LOG.append(line)
    print(line.encode("ascii", "replace").decode("ascii"))


def get(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, data, timeout=180):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_status(jid, want, max_s=120):
    since = steps = 0
    t0 = time.time()
    while time.time() - t0 < max_s:
        j = get("/api/job?id=%s&since=%d&steps_since=%d" % (jid, since, steps))["job"]
        since, steps = j["log_count"], j["step_count"]
        if j["status"] in (want, "done", "error", "cancelled"):
            return j
        time.sleep(0.4)
    return None


def main():
    say("=" * 70)
    say("回退（rewind）功能自测")
    say("=" * 70)

    # ---------- 项目：命令行给的，或者用自带素材临时拼一个 ----------
    if len(sys.argv) > 1:
        proj = os.path.abspath(sys.argv[1])
        if not os.path.isdir(proj):
            say("给的项目目录不存在：%s" % proj); return 1
        say("用你给的项目：%s" % proj)
    else:
        if not os.path.exists(FIXTURE):
            say("找不到自带素材：%s（也可以直接给一个项目目录：python _rewindtest.py <项目>）" % FIXTURE)
            return 1
        proj = os.path.join(HERE, "_jobs", "tmp_rewind_proj")
        d = os.path.join(proj, "output")
        os.makedirs(d, exist_ok=True)
        shutil.copy2(FIXTURE, os.path.join(d, "clean_data.csv"))
        say("用自带素材临时项目：%s" % proj)

    # ⚠ 先记下研究员现在开着哪个项目 —— 下面用 `/api/run` 带 project 跑，
    #   服务端会顺手把它记成当前项目，收尾要还回去。
    saved_root = _cur_project_root()

    r = post("/api/run", {"block_id": "b5_stats", "project": proj, "params": PARAMS})
    if not r.get("ok"):
        say("起不来：%s" % r.get("error")); return 1
    jid = r["job_id"]
    j = wait_status(jid, "waiting")
    say("1) 停在检查点：%s" % (j.get("pending") or {}).get("title"))
    say("   已完成决定：%s" % [a["label"] for a in j["answers"]])

    post("/api/job/answer", {"id": jid, "choice": "ok"})
    j = wait_status(jid, "waiting")
    say("2) 回答后停在：%s" % (j.get("pending") or {}).get("title"))
    say("   已完成决定：%s" % [a["label"] for a in j["answers"]])

    say("")
    say("3) 调 rewind(upto=0)：回到第 1 个检查点之前")
    r = post("/api/job/rewind", {"id": jid, "upto": 0})
    say("   返回：%s" % (r if not r.get("ok") else {"ok": True, "new_job": r["job_id"][:8]}))
    if not r.get("ok"):
        return 1
    jid2 = r["job_id"]
    j = wait_status(jid2, "waiting")
    say("   新任务停在：%s" % (j.get("pending") or {}).get("title"))
    say("   已回放的决定：%s  ← 应该是空的" % [a["label"] for a in j["answers"]])
    ok1 = len(j["answers"]) == 0

    say("")
    say("4) 再调 rewind(upto=1)：回放第 1 个决定，停在第 2 个检查点之前")
    post("/api/job/answer", {"id": jid2, "choice": "ok"})
    j = wait_status(jid2, "waiting")
    r = post("/api/job/rewind", {"id": jid2, "upto": 1})
    say("   返回：%s" % (r if not r.get("ok") else {"ok": True, "new_job": r["job_id"][:8]}))
    if not r.get("ok"):
        return 1
    jid3 = r["job_id"]
    j = wait_status(jid3, "waiting")
    say("   新任务停在：%s" % (j.get("pending") or {}).get("title"))
    say("   已回放的决定：%s  ← 应该有 1 个（标着「回放」）"
        % [(a["label"], a.get("replayed")) for a in j["answers"]])
    ok2 = len(j["answers"]) == 1 and j["answers"][0].get("replayed")

    say("")
    say("=" * 70)
    say("结论：动作 1（回退到第 1 个检查点）%s；动作 2（回放 1 个决定）%s"
        % ("OK" if ok1 else "FAIL", "OK" if ok2 else "FAIL"))

    # 收尾：把还挂着的任务取消掉，别留后台进程
    try:
        post("/api/job/cancel", {"id": jid3})
    except Exception:
        pass
    say("（已取消收尾任务，不留后台进程）")

    # ⚠ 还要把**当前项目**还回去。这个测试用 `/api/run` 带着 `project` 参数跑，
    #   而服务端会顺手把它记成"当前项目"（写进 config.json）——
    #   于是跑一次自测，研究员原来开着的项目就被换成了测试项目（实测踩到）。
    #   测试可以借用别的项目跑，但不许改别人的工作现场。
    try:
        cur = (get("/api/state").get("project") or {}).get("root") or ""
        if os.path.normcase(cur) == os.path.normcase(proj) and saved_root and saved_root != cur:
            post("/api/project/open", {"root": saved_root})
            say("（已把当前项目切回：%s）" % saved_root)
    except Exception as e:
        say("（切回当前项目失败，不影响结论：%s）" % e)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))
    print("OK -> %s" % OUT)
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
