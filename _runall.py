# -*- coding: utf-8 -*-
"""工作台 · 全量回归（一条命令跑完所有自测）

    python _runall.py            # 跑全部（Python + 前端 JS）
    python _runall.py --py       # 只跑 Python
    python _runall.py --js       # 只跑前端 JS

**为什么要有这个脚本**

    以前是手敲一段 PowerShell 循环。踩到的坑很实在（2026-09-26）：

      `_currentprojtest.py` 会**故意**把「项目之家」（`F:\\try\\用户研究`）写进
      `config.json` 的 `project_root` —— 那正是它在测的东西（"项目之家自己不算项目"），
      靠收尾那一步恢复。可它跑到一半出错、或者 `_apitest.py` 紧随其后，
      配置里就留下一个**不是项目**的路径；再跑一轮，收尾只能恢复成"空"。

      结果：打开界面，顶栏是空的、还说"这不是研究项目"——
      **他正在用的那个项目看着像丢了**，而它其实好好的躺在 `projects/` 下面。

    → 所以"批量回归"这件事必须自己负责现场：
      **跑之前记下当前项目，跑完检查配置还健不健康，不健康就用「最近项目」找回来。**
      测试可以弄乱自己的临时目录，但不许弄乱研究员的工作现场。

产物：`_jobs/runall.txt`（每套的 exit code + 判定），进程退出码 = 失败套数（0 = 全过）。
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
JOBS = os.path.join(HERE, "_jobs")
CFG = os.path.join(HERE, "config.json")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    # 理论上到不了这里：项目要求 Python 3.7+，那时 reconfigure 一定存在。
    # 真到了这里说明 Python 太老 —— UTF-8 保护**没生效**，必须让人知道，
    # 不能"静静跳过"（那等于假装有保护）。
    print("[warn] Python too old: sys.stdout.reconfigure missing, "
          "the UTF-8 guard did NOT take effect (needs Python 3.7+)")
except Exception as _e:
    # 别的失败是 bug（比如编码名写错），要叫出来，不许静默
    print("[warn] stdout/stderr UTF-8 guard failed: %r" % (_e,))


def _engine_python():
    try:
        from core import paths
        return paths.engine_python()
    except Exception:
        return sys.executable


def _read_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _cur_root():
    return (_read_cfg().get("project_root") or "").strip()


def _is_real_project(root):
    """用**服务端自己那把尺子**判"是不是真项目"。

    ⚠ 别自己写一套（比如"有没有 project.json"）—— 那比服务端严，
      会把 `projects/_脱敏格式演示` 这种合法项目判成坏值。
    """
    try:
        import server as _srv
        return bool(_srv._is_real_project(root))
    except Exception:
        return bool(root) and os.path.isdir(root) and \
            bool(os.path.exists(os.path.join(root, "project.json")))


def _restore_project(saved, why):
    """把「当前项目」恢复到一个说得通的值。返回 (值, 说明)。"""
    if saved and _is_real_project(saved):
        return saved, "原值就是真项目"
    try:
        import server as _srv
        for r in _srv.recent_projects():
            if _is_real_project(r):
                return r, "从「最近项目」流水里找回（原值%s）" % (why or "不可用")
    except Exception:
        pass
    return "", "没有可恢复的项目（%s）" % (why or "未知")


def _fix_config(target):
    """把 project_root 写回配置并让服务端也切过去。失败不影响测试结论。"""
    if not target:
        return
    try:
        cfg = _read_cfg()
        if os.path.normcase(os.path.abspath(cfg.get("project_root") or "")) != \
                os.path.normcase(os.path.abspath(target)):
            cfg["project_root"] = target
            with open(CFG, "w", encoding="utf-8", newline="\n") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("  （写配置失败：%s）" % e)
    # 服务还活着的话，顺手把内存里的当前项目也切过去
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:8765/api/project/open",
            data=json.dumps({"root": target}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception:
        pass          # 服务没跑也算正常（大部分测试不需要服务）


def _run_one(cmd, fn, kind, saved):
    """跑一套，跑完**立刻检查现场**；被弄乱了就当场恢复。

    ⚠ 为什么要"每套都查"：实测（2026-09-26）有两套会动到 `config.json` 的当前项目 ——
      `_rewindtest.py` 用 `/api/run` 带 project 跑，服务端顺手把它记成当前项目；
      `_versiontest.py` 走完之后配置里成了「项目之家」。
      它们各自都没打算破坏现场，但**批量跑**的时候后一套在前一套留下的状态上继续，
      最后一查就是坏的。只在最后查一次只能知道"坏了"，查不出是谁——所以要一套一查、当场纠正。
    """
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, cwd=HERE)
    dt = time.time() - t0
    out = (p.stdout or b"").decode("utf-8", "replace") + \
          (p.stderr or b"").decode("utf-8", "replace")
    tail = ""
    for line in out.splitlines():
        if "通过" in line and "失败" in line:
            tail = line.strip()

    # ⚠ exit code 2 是「**这套自己拒绝跑**」，不是失败（2026-09-27 修）。
    #   典型是 `_currentprojtest.py`：它要临时清空「当前项目」再恢复，
    #   而在**干净环境**（刚 clone、还没有任何项目）里没有可恢复的目标，
    #   于是它宁可不跑也不冒把项目弄丢的风险 —— 那是好设计，不该记成失败。
    #   以前一律 `returncode != 0 → FAIL`，导致 README 承诺的"31 套全绿"
    #   在干净机器上永远做不到，新人会以为自己的环境坏了。
    SKIP_CODES = (2,)
    if p.returncode == 0:
        tag = "OK"
    elif p.returncode in SKIP_CODES:
        tag = "SKIP"
    else:
        tag = "FAIL"
    if tag == "SKIP" and not tail:
        tail = "跳过（这套自己拒绝跑：没有它需要的现场）"
    print("%-4s %-22s exit=%-3d %5.1fs  %s" % (tag, fn, p.returncode, dt, tail))

    # 现场检查
    now = _cur_root()
    if not (now and _is_real_project(now)):
        tgt, why = _restore_project(saved, "现在是 %r" % now)
        if tgt:
            _fix_config(tgt)
            print("     ⚠ 这一套把「当前项目」弄乱了（%r）→ 已恢复：%s" % (now, tgt))
            print("       依据：%s" % why)
            tail = (tail + "  [现场已修复]").strip()
        else:
            # ⚠ 干净环境（刚 clone、还没建过项目）本来就没有现场可恢复 ——
            #   那不是"修复失败"，别用一句话吓人。`_currentprojtest` 这类
            #   需要现场的套件此时会以 exit 2 自己跳过（见上面 SKIP_CODES）。
            print("     （干净环境：没有项目现场，无需恢复）")
    return (kind, fn, p.returncode, dt, tail)


def _srv_alive(url, timeout=4):
    """服务在不在（探一下 /api/ping）。"""
    try:
        with urllib.request.urlopen(url + "/api/ping", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _start_srv_if_needed(py, srv_url):
    """自己起一个服务给那几套接口测试用。

    为什么值得自动起（而不是让人先双击 `启动工作台.bat`）：
      · 有 5 套测试走真实 HTTP，但它们里的 4 套**把地址写死在 8765**，
        所以"起在别的端口"这条路走不通；
      · 而"服务没开就跳过 5 套"会让人以为测试不全 —— 明明机器上什么都有。
    所以：**没人占用 8765 就自己起一个**，跑完关掉。
    有人占着（比如用户自己开着工作台）就**不动它**，直接用那个。
    """
    if _srv_alive(srv_url):
        print("服务已经在跑（%s）—— 用它，我不会另起。" % srv_url)
        return None
    print("服务没在跑：自己起一个临时的（跑完自动关掉，不影响你开着的那个）…")
    try:
        p = subprocess.Popen(
            [py, "-u", os.path.join(HERE, "server.py"), "--no-open"],
            cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        print("  ⚠ 起不来：%s —— 那 5 套会跳过（不是失败）" % e)
        return None
    for _ in range(40):                      # 最多等 20 秒
        time.sleep(0.5)
        if _srv_alive(srv_url, timeout=2):
            print("  起来了（pid %d）。" % p.pid)
            return p
    print("  ⚠ 等了 20 秒还没起来 —— 那 5 套会跳过")
    try:
        p.terminate()
    except Exception:
        pass
    return None


def _stop_srv(proc):
    if not proc:
        return
    print("-" * 72)
    print("关掉我刚才起的那个临时服务（pid %d）…" % proc.pid)
    try:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception as e:
        print("  （没关干净：%s —— 你自己看一眼任务管理器）" % e)


def main():
    # ⚠ 只用标准库：urllib 探服务、subprocess 起/关临时服务、time 等就绪
    do_py = do_js = False
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    do_py = only in ("", "--py")
    do_js = only in ("", "--js")
    py = _engine_python()

    print("=" * 72)
    print("工作台 · 全量回归")
    print("  python：%s" % py)
    print("=" * 72)

    saved = _cur_root()
    if saved and not _is_real_project(saved):
        print("⚠ 开跑前「当前项目」就不是真项目：%s" % saved)
        print("  （多半是上一次测试留下的现场；跑完我会用「最近项目」找回来）")
    elif saved:
        print("现场已记下：%s" % saved)

    # ---------- 先把测试素材造出来 ----------
    # 素材**不进版本库**（见 `.gitignore` 里 `_fixtures/` 那一段），
    # 定义在 `_fixtures.py`，跑测试时现造到 `_jobs/fixtures/`。
    # 放在最前面造一次，后面各套就不用各自判断了。
    try:
        import importlib
        fx = importlib.import_module("_fixtures")
        root = fx.build_all()
        print("测试素材已生成：%s" % root)
    except Exception as e:
        print("⚠ 测试素材生成失败：%s" % e)
        print("  （几套依赖素材的会报「找不到素材」，其余照跑）")
    print("")

    # ---------- 有 5 套要走真实 HTTP 接口：需要服务 ----------
    # 它们原来在服务没开时是**抛异常**，看着像"环境坏了" —— 其实只是没开服务
    # （实测：服务开着 32 套全过；服务没开 5 套 exit=1）。
    # ⇒ 而且它们里的 4 套**把地址写死在 8765**，所以不能"起在别的端口绕开"。
    #   这里的做法：**没人占 8765 就自己起一个临时的**，跑完关掉；
    #   你要是自己开着工作台，就用你那个，我不动它。
    SRV = "http://127.0.0.1:8765"
    NEED_SRV = {"_apitest.py", "_rewindtest.py", "_versiontest.py",
                "_picktest.py", "_llmtest.py"}
    srv_proc = _start_srv_if_needed(py, SRV)
    srv_up = _srv_alive(SRV) or bool(srv_proc)
    if not srv_up:
        print("  → 需要接口的 %d 套会**跳过**（不是失败）。" % len(NEED_SRV))
    print("")

    results = []
    if do_py:
        for fn in sorted(os.listdir(HERE)):
            if not (fn.startswith("_") and fn.endswith(".py") and "test" in fn):
                continue
            if fn in NEED_SRV and not srv_up:
                # 记成"跳过"（exit 2 那套计分逻辑认它），别让人以为环境坏了
                print("%-4s %-22s %s" % ("SKIP", fn, "跳过（起不来服务）"))
                results.append(("py", fn, 2, 0.0,
                                "跳过（服务没在跑，而且我没能起起来）"))
                continue
            results.append(_run_one([py, "-X", "utf8", os.path.join(HERE, fn)],
                                    fn, "py", saved))

    if do_js:
        for fn in ("_uitest.js", "_tbltest.js"):
            fp = os.path.join(HERE, fn)
            if not os.path.exists(fp):
                continue
            results.append(_run_one(["node", fp], fn, "js", saved))

    # ---------------- 收尾 ----------------
    # ⚠ 先关我起的那个临时服务（用 try 包住，中途出错也别留残留进程）
    try:
        _stop_srv(srv_proc)
    except Exception as e:
        print("  （关临时服务时出错：%s —— 看一眼任务管理器有没有多出来的 python）" % e)
    srv_proc = None

    print("")
    print("-" * 72)
    now = _cur_root()
    if now and _is_real_project(now):
        print("现场没问题：当前项目 = %s" % now)
    else:
        target, why = _restore_project(saved, "现在是 %r" % now)
        if target:
            _fix_config(target)
            print("⚠ 批量回归把「当前项目」弄乱了（%r）→ 已恢复：%s" % (now, target))
            print("  依据：%s" % why)
        else:
            print("⚠ 现在没有当前项目，而且「最近项目」里也没有可用的 —— 请在界面上选一个。")

    skipped = [r for r in results if r[2] == 2]          # 自己拒绝跑（不算失败）
    bad = [r for r in results if r[2] != 0 and r[2] != 2]
    npass = len(results) - len(bad) - len(skipped)
    print("")
    print("=" * 72)
    print("共 %d 套：通过 %d，失败 %d%s"
          % (len(results), npass, len(bad),
             ("，跳过 %d" % len(skipped)) if skipped else ""))
    for _kind, fn, code, _dt, _tail in bad:
        print("   ❌ %s（exit=%d）" % (fn, code))
    for _kind, fn, _code, _dt, t in skipped:
        print("   ⏭ %s —— %s" % (fn, t or "这套自己拒绝跑"))
    if skipped:
        print("   （跳过的不是坏：它们需要一段现场（比如已选好的项目），干净环境里没有）")

    os.makedirs(JOBS, exist_ok=True)
    with open(os.path.join(JOBS, "runall.txt"), "w", encoding="utf-8") as f:
        f.write("工作台全量回归 %s\n\n" % time.strftime("%Y-%m-%d %H:%M"))
        for kind, fn, code, dt, tail in results:
            f.write("[%s] %-22s exit=%-3d %5.1fs  %s\n"
                    % (kind, fn, code, dt, tail))
        f.write("\n通过 %d / 失败 %d / 跳过 %d\n" % (npass, len(bad), len(skipped)))
    print("\n详细 → %s" % os.path.join(JOBS, "runall.txt"))
    return len(bad)


if __name__ == "__main__":
    sys.exit(main())
