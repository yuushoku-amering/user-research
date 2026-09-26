# -*- coding: utf-8 -*-
"""工作台 · 任务执行

引擎跑在**独立子进程**里，理由有三：
1. 组块崩了不会拖垮工作台（界面还在，你能看到错误）
2. Python 版本 / 依赖各管各的，互不污染
3. 日志能实时流回界面，长任务看得见进度

父子之间用「一行一个 JSON」说话。协议见 runner.py。
"""
import json
import os
import subprocess
import threading
import time
import uuid

from . import paths

MAX_LOGS = 800          # 每个任务最多留这么多行日志，防止界面卡
KEEP_JOBS = 40          # 内存里最多留这么多个任务记录


class Job(object):
    def __init__(self, jid, block_id, params, project_root):
        self.id = jid
        self.block_id = block_id
        self.params = params
        self.project_root = project_root
        self.status = "running"          # running | waiting | done | error | cancelled
        self.logs = []
        self.steps = []                  # 步骤卡：过程可见
        self.pending = None              # 正在等研究员拍板的检查点
        self.answers = []                # 研究员做过的决定（留档）
        self.result = None
        self.error = ""
        self.started = time.time()
        self.ended = None
        self.proc = None
        self.waiting_since = None        # 进入检查点等待的时刻
        self.wait_seconds = 0.0          # 累计「等研究员做决定」花掉的时间
        self.auto_answers = []           # 回退重跑时，预置的答案（自动回放，不停）
        self.params_raw = dict(params or {})   # 原始参数（回退重跑要用）
        self.block = None                # 组块声明（回退重跑要用）

    def log(self, msg, level="info"):
        self.logs.append({"t": round(time.time() - self.started, 2),
                          "level": level, "msg": msg})
        if len(self.logs) > MAX_LOGS:
            del self.logs[:len(self.logs) - MAX_LOGS]

    def elapsed(self):
        """真正在跑的时间 —— 把「等你做决定」的时间扣掉。

        否则会出现「完成 · 161.9s」这种看着像卡了的事（其实 150 秒都在等你）。
        """
        now = self.ended or time.time()
        extra = (now - self.waiting_since) if self.waiting_since else 0.0
        return round(now - self.started - self.wait_seconds - extra, 1)

    def snapshot(self, since=0, steps_since=0):
        return {
            "id": self.id,
            "block_id": self.block_id,
            "status": self.status,
            "error": self.error,
            "result": self.result,
            "logs": self.logs[since:],
            "log_count": len(self.logs),
            "steps": self.steps[steps_since:],
            "step_count": len(self.steps),
            "pending": self.pending,
            "answers": self.answers,
            "elapsed": self.elapsed(),
            "wait_seconds": round(self.wait_seconds, 1),
        }


class JobManager(object):
    def __init__(self):
        self._jobs = {}
        self._order = []
        self._lock = threading.Lock()

    # ---------- 起任务 ----------

    def start(self, block, params, project_root, cfg=None):
        cfg = cfg or paths.load_config()
        jid = uuid.uuid4().hex[:12]
        job = Job(jid, block.get("id"), params, project_root)
        job.block = block

        params = dict(params or {})
        params["project_root"] = project_root
        params["block_dir"] = block.get("_dir", "")
        params["block_id"] = block.get("id")

        os.makedirs(paths.JOBS_DIR, exist_ok=True)
        job_file = os.path.join(paths.JOBS_DIR, "%s.json" % jid)
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

        with self._lock:
            self._jobs[jid] = job
            self._order.append(jid)
            while len(self._order) > KEEP_JOBS:
                old = self._order.pop(0)
                self._jobs.pop(old, None)

        engine = os.path.join(block.get("_dir", ""), block.get("engine", "engine.py"))
        if not os.path.exists(engine):
            job.status = "error"
            job.error = "这个组块还没写引擎（缺 %s）" % block.get("engine", "engine.py")
            job.ended = time.time()
            return job

        py = paths.engine_python(cfg)
        cmd = [py, paths.RUNNER, job_file]
        job.log("引擎：%s" % py, "meta")
        job.log("组块：%s" % block.get("name"), "meta")

        try:
            job.proc = subprocess.Popen(
                cmd,
                cwd=paths.WORKBENCH,
                stdin=subprocess.PIPE,           # 检查点靠它把研究员的决定送回子进程
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=paths.child_env(),
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            job.status = "error"
            job.error = "起不了引擎进程：%s" % e
            job.ended = time.time()
            return job

        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        return job

    # ---------- 读输出 ----------

    def _pump(self, job):
        try:
            for line in job.proc.stdout:
                line = (line or "").rstrip("\r\n")
                if not line:
                    continue
                if line.startswith("{"):
                    try:
                        msg = json.loads(line)
                    except Exception:
                        job.log(line)
                        continue
                    t = msg.get("t")
                    if t == "log":
                        job.log(msg.get("msg", ""), msg.get("level", "info"))
                    elif t == "step":
                        job.steps.append({
                            "id": msg.get("id"), "title": msg.get("title"),
                            "detail": msg.get("detail"),
                            "columns": msg.get("columns"), "rows": msg.get("rows"),
                            "t": round(time.time() - job.started, 2),
                        })
                    elif t == "ask":
                        # 回退重跑时，前面那些决定按原样自动回放，不停下来烦人
                        if job.auto_answers:
                            choice = job.auto_answers.pop(0)
                            opt = next((o for o in (msg.get("options") or [])
                                        if o.get("value") == choice), None)
                            try:
                                job.proc.stdin.write(
                                    json.dumps({"choice": choice}, ensure_ascii=False) + "\n")
                                job.proc.stdin.flush()
                            except Exception as e:
                                job.status = "error"
                                job.error = "回放决定失败：%s" % e
                                return
                            job.answers.append({
                                "id": msg.get("id"), "title": msg.get("title"),
                                "choice": choice,
                                "label": (opt or {}).get("label", choice),
                                "replayed": True,
                            })
                            job.log("↩ 自动回放：%s（%s）"
                                    % ((opt or {}).get("label", choice), msg.get("title")), "meta")
                            continue
                        job.pending = {
                            "id": msg.get("id"), "title": msg.get("title"),
                            "detail": msg.get("detail"),
                            "options": msg.get("options") or [],
                            "default": msg.get("default"),
                            "columns": msg.get("columns"), "rows": msg.get("rows"),
                            "t": round(time.time() - job.started, 2),
                        }
                        job.status = "waiting"
                        job.waiting_since = time.time()
                        job.log("⏸ 停下等你决定：%s" % msg.get("title"), "ask")
                    elif t == "result":
                        job.result = msg.get("data")
                    elif t == "error":
                        job.error = msg.get("msg", "未知错误")
                        job.log(job.error, "error")
                    else:
                        job.log(line)
                else:
                    job.log(line)
            job.proc.wait()
            if job.status == "running":
                code = job.proc.returncode
                if code == 0:
                    job.status = "done"
                else:
                    job.status = "error"
                    if not job.error:
                        job.error = "引擎退出码 %s（详见日志）" % code
        except Exception as e:
            if job.status == "running":
                job.status = "error"
                job.error = "读取引擎输出失败：%s" % e
        finally:
            job.ended = time.time()

    # ---------- 查询 / 取消 ----------

    def get(self, jid):
        with self._lock:
            return self._jobs.get(jid)

    def answer(self, jid, choice):
        """把研究员的决定写回子进程，让它接着跑。"""
        job = self.get(jid)
        if not job or job.status != "waiting" or not job.pending:
            return False
        if job.waiting_since:
            job.wait_seconds += time.time() - job.waiting_since
            job.waiting_since = None
        try:
            job.proc.stdin.write(json.dumps({"choice": choice}, ensure_ascii=False) + "\n")
            job.proc.stdin.flush()
        except Exception as e:
            job.status = "error"
            job.error = "把决定送回引擎失败：%s" % e
            job.log(job.error, "error")
            return False

        opt = next((o for o in (job.pending.get("options") or [])
                    if o.get("value") == choice), None)
        job.answers.append({
            "id": job.pending.get("id"),
            "title": job.pending.get("title"),
            "choice": choice,
            "label": (opt or {}).get("label", choice),
        })
        job.log("▶ 你的决定：%s" % ((opt or {}).get("label", choice)), "ask")
        job.pending = None
        job.status = "running"
        return True

    def rewind(self, jid, upto, cfg=None):
        """↩ 回到第 upto 个检查点之前（0-based）。

        engine 是无状态的，所以做法是：**杀掉当前进程，用同样的参数重跑一遍**，
        把前 upto 个决定照原样自动答回去（`auto_answers`），然后在第 upto+1 个检查点
        停下来等研究员重新拍板。

        这样研究员能回到任何一个他拍过板的地方改主意，包括改成「就停在这儿」。
        旧任务标记为 cancelled，历史保留；返回新任务。
        """
        old = self.get(jid)
        if not old or not getattr(old, "block", None):
            return None
        upto = max(0, int(upto))
        choices = [a.get("choice") for a in (old.answers or [])]
        choices = choices[:upto]
        try:
            if old.proc:
                old.proc.kill()
        except Exception:
            pass
        old.status = "cancelled"
        old.ended = time.time()
        old.pending = None
        old.log("↩ 回退：回到第 %d 个检查点之前，重跑一遍" % (upto + 1), "warn")
        cfg = cfg or paths.load_config()
        newjob = self.start(old.block, dict(old.params_raw), old.project_root, cfg)
        newjob.auto_answers = list(choices)
        if choices:
            newjob.log("↩ 前面 %d 个决定照原样回放，到第 %d 个检查点会停下"
                       % (len(choices), upto + 1), "meta")
        else:
            newjob.log("↩ 从第一个检查点重新开始", "meta")
        return newjob

    def cancel(self, jid):
        job = self.get(jid)
        if not job or job.status not in ("running", "waiting"):
            return False
        try:
            job.proc.kill()
        except Exception:
            pass
        job.status = "cancelled"
        job.ended = time.time()
        job.pending = None
        job.log("已取消", "warn")
        return True


MANAGER = JobManager()
