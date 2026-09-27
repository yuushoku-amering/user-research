# -*- coding: utf-8 -*-
"""装依赖 + 体检：让「源码版」也能一次装好。

用法
------------------------------------------------------------------------------
    python _install_deps.py              # 装必需依赖，然后体检
    python _install_deps.py --check      # 只体检，不装任何东西
    python _install_deps.py --optional   # 把可选依赖也装上
    python _install_deps.py --python <exe>   # 指定用哪个 Python

或者直接双击 `安装依赖.bat`（跟本脚本放在一起）。

它做什么
------------------------------------------------------------------------------
1. **找一个能用的 Python**（3.8+，且找得到 pip）
2. **装依赖**：`python -m pip install -r requirements.txt`
   · 默认先试**清华镜像**（国内快），失败再回落到官方 PyPI
   · 加 `--only-binary=:all:` —— 强制用 wheel，避免在用户机器上现场编译
     （编译要 C 工具链，绝大多数研究者没有；宁可早点报错让人换 Python 版本）
3. **体检**：真的 `import` 一遍，而不是只看 pip 说"装好了"
4. **写一份人话报告**到 `install-report.txt`
   —— 报告用 UTF-8 写文件，**不靠控制台**：cmd 是 GBK，中文和 ✅ 会乱码甚至报错

⚠ 两个踩过的坑（写在代码里免得再犯）
------------------------------------------------------------------------------
· `.bat` 必须 **100% 纯 ASCII**（连注释都算）—— cmd 按 OEM 代码页解析，
  UTF-8 中文会被撕成字节碎片然后当命令执行。这个坑在打包脚本里踩了三次。
· **不要用 `import pandas` 来判断装没装**：没装时它抛的是 ImportError，
  而报错信息里常带一堆路径，看着吓人。用 `importlib.util.find_spec`（不执行导入）。
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))   # 仓库根 = 工作台本体
REPO = HERE
REQ = os.path.join(REPO, "requirements.txt")
REQ_OPT = os.path.join(REPO, "requirements-optional.txt")
REPORT = os.path.join(REPO, "install-report.txt")

MIRRORS = [
    ("https://pypi.tuna.tsinghua.edu.cn/simple", "清华镜像（国内快）"),
    ("", "官方 PyPI"),
]

# 必需：装完必须能 import 这些
NEED = ["pandas", "scipy", "matplotlib", "numpy", "openpyxl"]
# 可选：能 import 更好，不能也不拦
OPT = ["pyreadstat", "sklearn"]

MIN_PY = (3, 8)


def log(msg=""):
    print(msg)
    sys.stdout.flush()


def run(cmd, timeout=None, env=None):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env=env,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def find_python(explicit=""):
    """找一个 3.8+ 且带 pip 的 Python。

    ⚠ 挑的时候**优先"已经装好依赖"的那个**（2026-09-27 实测踩到）：
      本来只是从新到旧找第一个 3.8+，结果这台机器上挑中了 Python 3.12
      （缺 pandas/scipy/matplotlib），而 3.10 是**四个包都齐**的 ——
      于是它会去 3.12 上白装一遍，而用户真正的引擎 Python 还是缺包。
      ⇒ 分两轮：第一轮找"能 import pandas 的"，找到就用；没有再做第二轮。
    """
    cands = []
    if explicit:
        cands.append(explicit)
    la = os.environ.get("LOCALAPPDATA", "")
    for v in ("312", "311", "310", "313", "39"):
        cands.append(os.path.join(la, r"Programs\Python\Python%s\python.exe" % v))
        cands.append(r"C:\Python%s\python.exe" % v)
    # 工作台真正在用的那只也算候选（它可能不在常见位置）
    try:
        sys.path.insert(0, REPO)
        from core import paths as _paths                     # noqa
        e = _paths.engine_python()
        if e:
            cands.insert(0, e)
    except Exception:
        pass
    if sys.executable:
        cands.append(sys.executable)

    usable = []          # [(path, ver, has_deps)]
    nopip = []           # 没有 pip 的（要给用户一条明确的出路）
    seen = set()
    for p in cands:
        if not p or p in seen:
            continue
        seen.add(p)
        if not os.path.isfile(p):
            continue
        r = run([p, "-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"])
        if r.returncode != 0:
            continue
        try:
            ver = tuple(int(x) for x in r.stdout.strip().split("."))
        except Exception:
            continue
        if ver < MIN_PY:
            log("  [跳过] %s —— Python %s 太老（要 %d.%d+）"
                % (p, ".".join(map(str, ver)), MIN_PY[0], MIN_PY[1]))
            continue
        if run([p, "-m", "pip", "--version"]).returncode != 0:
            log("  [跳过] %s —— 这个 Python 没有 pip" % p)
            nopip.append(p)
            continue
        usable.append((p, ver, have(p, "pandas")))

    # ⚠ 一种容易让人困惑的情况：**用户就是从某个 Python 跑本脚本的，而它没 pip**，
    #   于是这里默默跳到别的 Python 上去了（"我明明双击的是 A，怎么装的 B？"）。
    #   ⇒ 明确说出来，并给一条能照着敲的命令。
    if nopip and sys.executable and os.path.abspath(sys.executable) in \
            [os.path.abspath(x) for x in nopip]:
        log("")
        log("  [!] 注意：**你刚才是用这个 Python 跑的**，但它没有 pip —— 所以下面会用别的：")
        log("        %s" % sys.executable)
        log("      想用它的话，先给它装 pip：")
        log("        %s -m ensurepip --upgrade" % sys.executable)
        log("")

    if not usable:
        return "", ()

    # 第一轮：已经能 import pandas 的（说明这个环境基本就是给工作台用的）
    for p, ver, has in usable:
        if has:
            log("  用这个：%s（Python %s，**依赖已经齐了**）"
                % (p, ".".join(map(str, ver))))
            return p, ver
    # 第二轮：都没有的话，用最新的那个去装
    p, ver, _ = usable[0]
    log("  用这个：%s（Python %s，还没装依赖，接下来给它装）"
        % (p, ".".join(map(str, ver))))
    return p, ver


def have(py, mod):
    """装没装：用 find_spec（不真的执行导入，避免把报错信息当结果）。

    ⚠ 必须把 `libs/` 也算进来（2026-09-27 实测踩到）：
      本机工作台的 openpyxl / pyreadstat 装在 **`workbench\\libs\\`**，
      运行时靠 PYTHONPATH 挂上去（见 reader.py / runner.py 的 `sys.path.insert`）。
      只用"Python 自己的 site-packages"判断，会**误报缺包** → 让人白装一遍，
      而工作台本来就能用。
      ⇒ 判断时也带上 libs/（跟 `core/paths.can_import` 同一套口径）。
    """
    code = ("import importlib.util,sys,os;"
            "sys.exit(0 if importlib.util.find_spec(%r) else 1)" % mod)
    env = dict(os.environ)
    libs = os.path.join(REPO, "libs")
    if os.path.isdir(libs):
        # ⚠ 光设 PYTHONPATH 不够：本机那只嵌入式 Python 带 python39._pth，
        #   它会**忽略 PYTHONPATH**。所以再让子进程自己把 libs 插进 sys.path。
        code = ("import importlib.util,sys,os;"
                "sys.path.insert(0, %r);"
                "sys.exit(0 if importlib.util.find_spec(%r) else 1)" % (libs, mod))
        old = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = libs + (os.pathsep + old if old else "")
    return run([py, "-c", code], env=env).returncode == 0


def missing(py, mods):
    return [m for m in mods if not have(py, m)]


def pip_install(py, req_file, optional=False):
    """装依赖：先清华、再官方。返回 (成功?, 用的是哪个源, pip 输出末尾)。"""
    if not os.path.isfile(req_file):
        return False, "", "找不到依赖清单：%s" % req_file
    last = ""
    for idx, (index, label) in enumerate(MIRRORS):
        cmd = [py, "-m", "pip", "install", "--only-binary=:all:",
               "--disable-pip-version-check", "-r", req_file]
        if index:
            cmd += ["-i", index]
        log("  用 %s 装…（可能要几分钟，看网速）" % label)
        t0 = time.time()
        r = run(cmd)
        tail = "\n".join((r.stdout or "").rstrip().splitlines()[-6:])
        last = tail
        if r.returncode == 0:
            log("  装好了（%.0f 秒）" % (time.time() - t0))
            return True, label, tail
        log("  [失败] %s 返回码 %s" % (label, r.returncode))
        if idx + 1 < len(MIRRORS):
            log("  换下一个源再试一次…")
    return False, "", last


def write_report(lines):
    """报告写文件（UTF-8）。不靠控制台 —— cmd 是 GBK，中文和符号会乱码。"""
    try:
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception as e:
        log("  [warn] 写报告失败：%s" % e)
        return False


def main():
    ap = argparse.ArgumentParser(description="装依赖 + 体检")
    ap.add_argument("--check", action="store_true", help="只体检，不装东西")
    ap.add_argument("--optional", action="store_true", help="把可选依赖也装上")
    ap.add_argument("--python", default="", help="指定用哪个 Python")
    args = ap.parse_args()

    R = []          # 报告内容（逐行）
    def add(s=""):
        R.append(s)

    log("=" * 64)
    log("  岚苔 Vesper · 安装依赖")
    log("=" * 64)

    log("\n【1/4】找一个能用的 Python")
    py, ver = find_python(args.python)
    if not py:
        log("\n[×] 没找到合用的 Python（要 3.8+ 且带 pip）。")
        log("    去 https://www.python.org/downloads/ 装一个 Python 3.12，")
        log("    安装时**勾上 Add Python to PATH**，装完重新双击本脚本。")
        add("结果：失败 —— 没找到 Python 3.8+")
        add("")
        add("请先装 Python 3.12（python.org），安装时勾选 Add Python to PATH，再重跑。")
        write_report(R)
        return 2
    add("Python：%s（%s）" % (py, ".".join(map(str, ver))))

    log("\n【2/4】检查依赖装没装")
    miss = missing(py, NEED)
    add("缺失的必需依赖：%s" % ("、".join(miss) if miss else "（无，都装好了）"))
    if miss:
        log("  缺：%s" % "、".join(miss))
    else:
        log("  必需依赖都齐了")

    if miss and not args.check:
        log("\n【3/4】装依赖")
        ok, label, tail = pip_install(py, REQ)
        add("安装：%s%s" % ("成功" if ok else "失败",
                          ("（源：%s）" % label) if label else ""))
        if tail:
            add("pip 输出末尾：")
            for ln in tail.splitlines():
                add("    " + ln)
        if not ok:
            log("\n[×] 装失败了。上面那几行是 pip 的原话。")
    elif args.check:
        log("\n【3/4】--check：跳过安装")
        add("安装：跳过（--check）")
    else:
        log("\n【3/4】依赖已齐，跳过安装")
        add("安装：跳过（已齐）")

    if args.optional and not args.check:
        log("  顺带装可选依赖…")
        ok2, label2, _ = pip_install(py, REQ_OPT, optional=True)
        add("可选依赖：%s" % ("装好了" if ok2 else "没装上（不影响主流程）"))

    log("\n【4/4】体检（真的 import 一遍）")
    miss2 = missing(py, NEED)
    optok = [m for m in OPT if have(py, m)]
    optmiss = [m for m in OPT if m not in optok]

    add("")
    add("体检：")
    for m in NEED:
        add("    [%s] %s" % ("OK " if m not in miss2 else "缺 ", m))
        log("  %s %s" % ("[OK]    " if m not in miss2 else "[缺]    ", m))
    for m in OPT:
        add("    [%s] %s（可选）" % ("OK " if m in optok else "— ", m))
        log("  %s %s（可选）" % ("[OK]    " if m in optok else "[—]     ", m))

    ok_all = not miss2
    log("")
    log("=" * 64)
    if ok_all:
        log("  [OK] 装好了。下一步：双击仓库根目录的 启动工作台.bat")
        add("")
        add("结果：成功 —— 可以双击 启动工作台.bat 了")
    else:
        log("  [×] 还缺：%s" % "、".join(miss2))
        log("      常见原因：pip 卡在编译（Python 版本太新、还没有 wheel）")
        log("      → 换成 Python 3.11 / 3.12 再跑一次，最省事")
        add("")
        add("结果：还不齐 —— 缺 %s" % "、".join(miss2))
        add("建议：换成 Python 3.11 / 3.12 再跑一次（新版 Python 可能还没有这些包的 wheel）")
    if optmiss:
        add("")
        add("可选依赖没装的：%s" % "、".join(optmiss))
        add("  想要的话：python -m pip install -r requirements-optional.txt")
    add("")
    add("（这份报告是 UTF-8 的，用记事本打开可能显示为乱码 ——")
    add("  那就用 VS Code / 写字板打开，或者直接看上面那个黑窗口。）")

    log("")
    log("  详细报告写到了：install-report.txt（UTF-8）")
    log("=" * 64)
    write_report(R)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
