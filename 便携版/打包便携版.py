# -*- coding: utf-8 -*-
"""做一份「便携版」（自带 Python 的那个包）。

用法（在仓库根目录下）：
    python 便携版/打包便携版.py                 # 自动找一个合适的 Python 当底座
    python 便携版/打包便携版.py --python <路径>  # 指定底座
    python 便携版/打包便携版.py --no-zip        # 只做目录，不压缩（调试用）

产出：`dist_便携版/岚苔Vesper-便携版/` 和 `dist_便携版/岚苔Vesper-便携版.zip`

------------------------------------------------------------------------------
为什么要有这个脚本
------------------------------------------------------------------------------
便携版是给「电脑上没有 Python」的研究者用的。手工打包过一次，踩了两个坑，
所以把过程固化成脚本，免得下次重做时忘掉：

1. **PIL 不能删**（踩过）
   `matplotlib.colors` 里有一句 `from PIL import Image`。第一版按"代码里没 import PIL"
   就把它删了 → matplotlib 直接 import 不了、**所有图都画不出来**。
   ⇒ 所以下面的 `KEEP` 是**按依赖闭包算出来的白名单**，不是"看着没用就删"。
     要加依赖，先跑 `python -m pip check` 验证闭包没缺东西。

2. **不能靠 `Requires-Dist` 里带条件的那种**
   matplotlib 的 METADATA 里有几十条 `Requires-Dist: ...; extra == "docs"` 之类的，
   那是可选集成。把它们算进来的话，lxml / pyqt5 之类都会被误判成"必需"。
   ⇒ 只认**不带 `;` 的硬依赖**。

------------------------------------------------------------------------------
判据（要改依赖清单，改这里）
------------------------------------------------------------------------------
KEEP = 真正要留的顶层包 + 它们（递归）的硬依赖。
其余顶层包一律删掉 —— 白名单保留，比黑名单删除安全：漏删只是体积大一点，
错删会让功能静默失效（PIL 就是这么栽的）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)                 # 仓库根 = 工作台本体
APP_NAME = "岚苔Vesper"
TOP_NAME = APP_NAME + "-便携版"

# 构建产物放哪。
# ⚠ 默认**不要**放在仓库的上一层 —— 那一层在作者机器上就是**项目之家**
#   （`F:\try\用户研究`），里面是 `projects/ contracts/ data/ samples/ output/` 这些
#   **研究数据**。往那儿扔一个 350MB 的目录有两个后果：
#     ① 界面列项目时会多出一条（看着像个研究项目）
#     ② 哪天清理"测试目录"时手一滑就容易把它当垃圾扫掉
#   ⇒ 优先放到**作者机器上专门放构建/测试产物的那层**；实在找不到就落仓库上一层，
#     但会在屏幕上明确打出来（让人一眼看到它放哪了）。
#   想指定位置就 `--out <目录>`。**macOS / Linux 上建议显式传 `--out`**，
#   因为下面这些中文目录名只在作者这台机器上有意义。
def _default_out():
    """挑一个放构建产物的目录：**优先落在项目之家的外面**。

    ⚠ 这里踩过一次：`app_home` 就是项目之家（作者机器上 = `F:\\try\\用户研究`），
      我第一版去找它的**子目录** `工作台的测试` —— 但那个目录是它的**兄弟**
      （`F:\\try\\工作台的测试`），所以判断不命中，产物又落回了项目之家里，
      界面上就多出一条"项目"。
      ⇒ 找 `app_home` 的**上一层**，从那里面挑一个放构建产物的目录。
    """
    app_home = os.path.dirname(REPO)
    outer = os.path.dirname(app_home)                    # 再上一层（这里才是"外面"）
    for base in (outer, app_home):
        for name in ("工作台的测试", "dist", "_build", "build", "out"):
            cand = os.path.join(base, name)
            if os.path.isdir(cand):
                return os.path.join(cand, "dist_便携版")
    return os.path.join(outer, "dist_便携版")


OUT_ROOT = _default_out()

# 要保留的顶层包（其余删掉）。它们自己的硬依赖由脚本自动补全。
KEEP = ["matplotlib", "pandas", "scipy", "numpy", "openpyxl", "pillow",
        "et-xmlfile", "pip", "setuptools",
        # ⚠ 下面这三个不是"包"，但删了会出事 —— 都是实测踩出来的：
        #   · numpy.libs / scipy.libs = 它们**自带的 DLL 目录**（里面是 OpenBLAS 之类）。
        #     名字带点、看着像临时产物，第一版当"没用"删了 → numpy 找不到自己的 DLL，
        #     报的却是「you should not try to import numpy from its source directory」
        #     这么一句**完全指错方向**的话。留着只占 40MB。
        #   · _distutils_hack = `site-packages\distutils-precedence.pth` 里引用它，
        #     删了**每次启动 Python** 都打一行 ModuleNotFoundError。
        "numpy.libs", "scipy.libs", "_distutils_hack"]

# ---------------------------------------------------------------------------
# ⚠ 为什么默认走"黑名单"而不是"白名单"（2026-09-27 的教训）
# ---------------------------------------------------------------------------
# 一开始想用白名单（只留那 18 个包 + 依赖闭包），结果**连着踩了四次**：
#   PIL（matplotlib.colors 要它）→ numpy.libs → scipy.libs → _distutils_hack →
#   还有 pandas 的一堆 `_libs/*.pyd` 找不到 DLL。
#
# 共同点：**这些东西没有 import 名**。依赖闭包是从 `METADATA` 的 `Requires-Dist`
# 算的，而 DLL 目录（`X.libs`）和 `.pth`（`distutils-precedence.pth`）**压根不在
# METADATA 里** —— 所以"算得再准"也漏。判据本身就不成立。
#
# 而且实验**证明不了**"黑名单里那些是安全的"：我删掉的 530 个包里必然混着类似的
# 隐藏依赖，只是还没触发到而已。发一个"可能少 DLL"的包给研究者，代价远大于省下的体积。
# ⇒ 所以：**只删能明确认定与运行无关的**（PDF/OCR/HTTP/云服务/构建工具），
#   每删一批都跑完整验收（sanity_check）。要更激进地瘦身，先补一条能验证它的测试。
PRUNE = [
    # —— 文档读写（工作台不碰 PDF / Word / PPT）——
    "fitz", "pymupdf", "pdfminer", "pdfplumber", "pypdf", "PyPDF2",
    "pypdfium2", "pypdfium2_raw", "docx", "pptx", "olefile", "lxml",
    # —— OCR / 图像识别（有 PIL 就够画图了）——
    "pytesseract", "pdf2image",
    # —— HTTP / 网络（模型通道走标准库 urllib，不需要 requests）——
    "requests", "urllib3", "certifi", "idna", "charset_normalizer", "soupsieve",
    "beautifulsoup4", "bs4",
    # —— 云 / 数据库 / 大数据（工作台只用本地 csv/xlsx/sav）——
    "boto3", "botocore", "s3transfer", "google", "azure", "polars", "pyarrow",
    "sqlalchemy", "pymysql", "psycopg2", "openpyxl_style",
    # —— 构建 / 测试 / 文档工具（运行时用不到）——
    "Cython", "cython", "pytest", "numpy_distutils", "setuptools_scm", "wheel",
    "build", "pip_tools", "tox", "virtualenv", "sphinx", "jinja2", "markupsafe",
    "pygments", "docutils", "sitecustomize",
]

# 目录名 → 规范名（判"要不要保留"时用）
ALIAS = {"pil": "pillow", "dateutil": "python-dateutil", "yaml": "pyyaml",
         "fonttools": "fonttools", "pkg_resources": "setuptools"}

# 无论如何都不删的（即使上面写错了，这几个也留着 —— 它们出过事）
NEVER_DELETE = {"numpy.libs", "scipy.libs", "pandas.libs", "matplotlib.libs",
                "pillow.libs", "kiwisolver.libs", "contourpy.libs", "fonttools.libs",
                "_distutils_hack", "distutils_precedence", "pip", "setuptools",
                "pkg_resources", "_distutils_hack.pth"}

# 从底座 Python 里排除的东西（省体积，都不影响功能）
SKIP_DIRS = [
    os.path.join("Lib", "test"),
    os.path.join("Lib", "idlelib"),
    os.path.join("Lib", "tkinter"),
    os.path.join("Lib", "lib2to3"),
    os.path.join("Lib", "ensurepip"),
    "tcl", "Doc", "Tools", "include", "Libs",
]
# 应用目录里不带进发布包的东西
APP_SKIP_DIRS = [".git", "_jobs", "libs", "dsh-home", "__pycache__", "_ref", "dist_便携版"]
APP_SKIP_FILES = ["config.json", "push_log.txt", "最近项目.json",
                  "上传到GitHub.bat", "上传到GitHub_不关窗.bat"]

CONFIG_PORTABLE = {
    "_说明": "这份 config.json 是**便携版预置的**：python 指向本包自带的 _python，"
             "所以这台电脑上不用装 Python。想换端口就改 port。",
    "port": 8765,
    "host": "127.0.0.1",
    "python": "..\\_python\\python.exe",
    "spss_exe": "",
    "base_root": "",
    "project_root": "",
    "export_dir": "",
    "llm": {"enabled": False, "provider": "", "api_base": "", "api_key": "",
            "api_model": "", "dsh_home": "", "timeout": 240, "model": "deepseek-flash"},
}

LAUNCHER = r"""@echo off
rem ===========================================================================
rem  LanTai Vesper - PORTABLE LAUNCHER  (no install, Python is in this folder)
rem
rem  PURE ASCII ON PURPOSE: a .bat is parsed with the OEM code page (GBK on a
rem  Chinese Windows), so UTF-8 Chinese inside it gets shredded into byte
rem  fragments that then get executed as commands.  Keep this file 100% ASCII
rem  -- including the comments, and including any mention of Chinese file
rem  names (that mistake was made twice while writing this).
rem
rem  Because the app folder name HAS Chinese in it, we must not hardcode it.
rem  We look it up instead: the subfolder next to this file that has server.py.
rem ===========================================================================
setlocal
chcp 437 >nul 2>nul
cd /d "%~dp0"
title LanTai Vesper

rem  ===========================================================================
rem  IMPORTANT: isolate this Python from whatever Python the host machine has.
rem
rem  A user who has ever installed Python may have PYTHONHOME / PYTHONPATH set
rem  (installers and some tools do this). Those variables OVERRIDE an embedded
rem  interpreter's own paths, and the bundled Python then dies at startup with:
rem
rem      Fatal Python error: init_fs_encoding: failed to get the Python codec
rem      ModuleNotFoundError: No module named 'encodings'
rem
rem  (Reproduced for real, not theorised -- see the fix note in this file.)
rem  Clearing them here makes the portable build behave the same on every
rem  machine: it uses ONLY the Python inside this folder.
rem
rem  NOTE: `set "X="` really does produce an empty value (verified); a single
rem  space left behind would be enough to break Python again.
rem  ===========================================================================
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONSTARTUP="

set "BUNDLED=%~dp0_python\python.exe"
if not exist "%BUNDLED%" goto :nopython

set "APP="
for /d %%D in ("%~dp0*") do (
  if exist "%%~fD\server.py" set "APP=%%~fD"
)
if not defined APP goto :noapp

echo.
echo   LanTai Vesper  --  portable edition
echo   Python: the one inside this folder (nothing to install)
echo.
echo   Starting... a browser window should open by itself.
echo   CLOSE THIS WINDOW to stop the service.
echo.

cd /d "%APP%"
"%BUNDLED%" -u server.py
echo.
echo   The service has stopped.
goto :done

:nopython
echo.
echo   [!] _python\python.exe is missing.
echo.
echo       Unpack the WHOLE zip again, and do not move or delete the
echo       _python folder that sits next to this file.
echo.
goto :done

:noapp
echo.
echo   [!] Cannot find the application folder (the one with server.py) next
echo       to this file.  Unpack the whole zip again and start this file
echo       from inside the unpacked folder.
echo.

:done
pause
endlocal
"""


def log(msg):
    print("  " + msg)
    sys.stdout.flush()


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kw)


def dist_meta_name(site_packages, top):
    """找出 `top` 这个顶层包对应的 <名字>-<版本>.dist-info 目录名。"""
    want = top.lower().replace("_", "-")
    for d in os.listdir(site_packages):
        if not d.endswith(".dist-info"):
            continue
        base = d[: -len(".dist-info")]
        name = base.split("-")[0].lower().replace("_", "-")
        if name == want:
            return d
    return ""


def hard_requires(site_packages, distinfo):
    """只取不带 `;` 的硬依赖（带条件的是 extras，不算）。"""
    mf = os.path.join(site_packages, distinfo, "METADATA")
    if not os.path.isfile(mf):
        return []
    out = []
    with open(mf, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.startswith("Requires-Dist:"):
                continue
            v = line.split(":", 1)[1].strip()
            if ";" in v:                     # 条件依赖（extras）→ 跳过
                continue
            n = re.split(r"[<>=!\[ ]", v)[0].strip()
            if n:
                out.append(n.lower().replace("_", "-"))
    return out


def closure(site_packages):
    """要保留的顶层包 + 它们的硬依赖闭包。"""
    keep = set()
    stack = [k.lower().replace("_", "-") for k in KEEP]
    while stack:
        n = stack.pop()
        if n in keep:
            continue
        keep.add(n)
        di = dist_meta_name(site_packages, n)
        if di:
            for r in hard_requires(site_packages, di):
                if r not in keep:
                    stack.append(r)
        else:
            log(" [!] 底座里没有 %s 的 dist-info（可能是内置模块，忽略）" % n)
    return keep


def find_base_python(explicit=""):
    """找一个能当底座的 Python。

    两个条件缺一不可：
      1. **能 import 那四个核心包**（不然做出来的便携版跑不了分析）
      2. **体积别太夸张** —— 这条是踩出来的：候选里原本把
         `D:\\ComfyUI_Windows_portable\\python_standalone` 排在前面，它是 8.2GB
         （带着 torch），复制要 500 多秒、做出来的包也没法发。
         一个干净的 CPython + 那四个包也就 500MB 上下，**超过 1.5GB 的直接跳过**。
    """
    SIZE_CAP = 1536 * 1024 * 1024            # 1.5 GB
    cands = []
    if explicit:
        cands.append(explicit)
    la = os.environ.get("LOCALAPPDATA", "")
    # ⚠ 顺序：独立安装的 CPython 优先（体积正常），最后才是 ComfyUI 那种大杂烩
    for v in ("313", "312", "311", "310"):
        cands.append(os.path.join(la, r"Programs\Python\Python%s\python.exe" % v))
    for v in ("313", "312", "311", "310", "39"):
        cands.append(r"C:\Python%s\python.exe" % v)
    cands += [r"D:\ComfyUI_Windows_portable\python_standalone\python.exe",
              sys.executable]
    seen = set()
    for p in cands:
        if not p or p in seen:
            continue
        seen.add(p)
        if not os.path.isfile(p):
            continue
        d = os.path.dirname(p)
        size = sum(os.path.getsize(os.path.join(dp, f))
                   for dp, dn, fn in os.walk(d) for f in fn)
        if size > SIZE_CAP:
            log("[skip] %s —— %.1f GB，太大了（复制慢、包也发不出去）" % (p, size / 1073741824.0))
            continue
        r = run([p, "-c", "import pandas,scipy,matplotlib,numpy"])
        if r.returncode != 0:
            log("[skip] %s —— 缺 pandas / scipy / matplotlib / numpy" % p)
            continue
        log("  %s（%.0f MB）" % (p, size / 1048576.0))
        return p
    return ""


def prune_site_packages(py_dir, keep=None):
    """按**黑名单**删：只删 `PRUNE` 里明确认定与运行无关的包（含它的 .dist-info）。

    为什么不是白名单 —— 见文件顶部 `PRUNE` 上面那段说明
    （PIL / numpy.libs / scipy.libs / _distutils_hack / pandas 的 _libs 连着踩了四次）。
    """
    sp = os.path.join(py_dir, "Lib", "site-packages")
    if not os.path.isdir(sp):
        log(" [!] 找不到 site-packages：%s" % sp)
        return 0, 0
    targets = set(t.lower().replace("_", "-") for t in PRUNE)
    freed = 0
    removed = []
    for d in list(os.listdir(sp)):
        full = os.path.join(sp, d)
        if d == "__pycache__":
            continue
        # 顶层 .py 一律不动：可能是依赖的一部分，而且都很小
        if os.path.isfile(full):
            continue
        name = re.sub(r"\.dist-info$|\.egg-info$", "", d)
        base = name.split("-")[0].lower().replace("_", "-")
        if d.lower().replace("_", "-") in NEVER_DELETE or base in NEVER_DELETE:
            continue
        if base not in targets:
            continue
        size = sum(os.path.getsize(os.path.join(dp, f))
                   for dp, dn, fn in os.walk(full) for f in fn)
        freed += size
        removed.append(d)
        shutil.rmtree(full, ignore_errors=True)
    log("删掉 %d 个与运行无关的包，省下 %.0f MB" % (len(removed), freed / 1048576.0))
    if removed:
        log("  删的是：" + ", ".join(sorted(removed)[:14]) +
            (" …" if len(removed) > 14 else ""))

    # 顺手清掉"孤儿 dist-info"：包的目录删了、元数据还在的话，
    # `pip check` 会一直报「X requires Y, which is not installed」——
    # 明明 X 已经不在了，这条噪声会让人以为环境缺东西。
    orphan = 0
    for d in list(os.listdir(sp)):
        if not (d.endswith(".dist-info") or d.endswith(".egg-info")):
            continue
        name = re.sub(r"\.dist-info$|\.egg-info$", "", d)
        base = name.split("-")[0].lower().replace("_", "-")
        if base in targets and base not in NEVER_DELETE:
            pkg_dir = os.path.join(sp, name.split("-")[0])
            if not os.path.isdir(pkg_dir):
                shutil.rmtree(os.path.join(sp, d), ignore_errors=True)
                orphan += 1
    if orphan:
        log("  另清了 %d 个孤儿 dist-info（对应的包已经删了）" % orphan)
    return freed, len(removed)


def clean_caches(root):
    """清 __pycache__ / *.pyc（白占体积）。"""
    n = 0
    for dp, dn, fn in os.walk(root):
        for d in list(dn):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dp, d), ignore_errors=True)
                dn.remove(d)
                n += 1
    return n


def copy_python(base_exe, dst):
    py_dir = os.path.dirname(base_exe)
    log("复制底座 Python：%s" % py_dir)
    t0 = time.time()
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(py_dir, dst, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "test", "idlelib", "lib2to3", "ensurepip"),
        symlinks=False, dirs_exist_ok=False)
    for d in SKIP_DIRS:
        p = os.path.join(dst, d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    log("  复制完成（%.0f 秒）" % (time.time() - t0))
    return dst


def copy_app(dst):
    log("复制工作台源码")
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)

    def ignore(dirname, names):
        skip = set()
        for n in names:
            if n in APP_SKIP_DIRS or n in APP_SKIP_FILES:
                skip.add(n)
            if n.endswith(".pyc"):
                skip.add(n)
        return skip

    shutil.copytree(REPO, dst, ignore=ignore)
    return dst


def sanity_check(py_exe, app_dir, do_demo=True):
    """**发出去之前必须过的几关**（这几关任何一关不过，包就是废的）。

    ⚠ 所有回传都走**纯 ASCII 信号**（`PREFIX_SAME=1` 这种），不靠读路径字符串 ——
      打包脚本自己可能跑在 GBK 控制台上，中文路径一乱码就会把"其实一样"判成"不一样"
      （实测踩过：包明明是好的，验收却报 prefix 没跟着走）。
    """
    ok = True
    py_dir = os.path.dirname(os.path.abspath(py_exe))

    log("① 内置 Python 换路径后能不能起来（prefix 要跟着走）")
    code = ("import sys,os;"
            "print('PREFIX_SAME=%d' % (1 if os.path.abspath(sys.prefix)=="
            "os.path.abspath(sys.argv[1]) else 0))")
    r = run([py_exe, "-c", code, py_dir])
    if r.returncode != 0:
        log("   [FAIL] 起不来：%s" % ((r.stderr or r.stdout or "")[:200])); return False
    if "PREFIX_SAME=1" not in (r.stdout or ""):
        log("   [FAIL] prefix 没跟着走（sys.prefix 不等于 _python 目录）—— 换台机器就会坏")
        ok = False
    else:
        log("   [OK] 就地可用（sys.prefix = 本包里的 _python）")

    log("② 四个核心包 + 出图（真跑一次，不只看能不能 import）")
    code = ("import matplotlib;matplotlib.use('Agg');"
            "import matplotlib.pyplot as plt,numpy,pandas,scipy,openpyxl,PIL;"
            "from scipy import stats;"
            "fig,ax=plt.subplots();ax.plot([1,2,3]);fig.savefig('_sanity.png',dpi=40);"
            "print('SANITY_OK=1')")
    r = run([py_exe, "-X", "utf8", "-c", code], cwd=app_dir)
    if r.returncode != 0 or "SANITY_OK=1" not in (r.stdout or ""):
        log("   [FAIL] %s" % ((r.stderr or r.stdout or "")[-300:])); ok = False
    else:
        log("   [OK] 全部可 import，图也画出来了")

    log("②b 启动脚本有没有把主机的 Python 环境变量隔离掉")
    # ⚠ 实测过：用户机器上若设了 PYTHONHOME，内置 Python 会**直接起不来**
    #   （Fatal Python error: init_fs_encoding / No module named 'encodings'）。
    #   所以启动脚本必须清掉 PYTHONHOME / PYTHONPATH / PYTHONSTARTUP。
    launcher = os.path.join(os.path.dirname(app_dir), "start-portable.bat")
    ltxt = ""
    if os.path.isfile(launcher):
        ltxt = open(launcher, encoding="ascii", errors="replace").read()
    need = ['set "PYTHONHOME="', 'set "PYTHONPATH="', 'set "PYTHONSTARTUP="']
    miss = [x for x in need if x not in ltxt]
    if miss:
        log("   [FAIL] 启动脚本里缺这几行：%s" % "、".join(miss))
        log("          （缺了的话，机器上设过 PYTHONHOME 的用户会打不开）")
        ok = False
    else:
        log("   [OK] PYTHONHOME / PYTHONPATH / PYTHONSTARTUP 都清掉了")

    log("③ 依赖闭包有没有缺（pip check）")
    r = run([py_exe, "-m", "pip", "check"])
    # ⚠ 只报"我们要留的包"的抱怨。被删掉的包（连它的目录一起删了、但 dist-info 可能还在，
    #   或反过来）会抱怨自己的依赖没了 —— 那是**噪声**，跟运行无关。
    #   例如：`python-docx requires lxml, which is not installed` —— docx 本身都删了。
    NOISE = re.compile(r"^(pdfplumber|pytesseract|python-docx|docx|python-pptx|pptx|"
                       r"PyPDF2|pypdf|pdfminer|pdfminer-six|fitz|pymupdf|lxml|"
                       r"requests|urllib3|certifi|Cython|pytest|sphinx)\b", re.I)
    bad = [l for l in (r.stdout or "").splitlines()
           if l.strip() and "which is not installed" in l and not NOISE.match(l.strip())]
    if bad:
        log("   [!] 有缺失：%s" % " | ".join(bad[:3]))
        ok = False                       # 只跟**留下的包**有关的缺失，才算真问题
    else:
        log("   [OK] 留下的包都没缺依赖")
        noise = [l for l in (r.stdout or "").splitlines()
                 if l.strip() and "which is not installed" in l]
        if noise:
            log("        （另有 %d 条是已删包的噪声，已忽略）" % len(noise))

    log("④ 工作台真能跑（_demo.py 全流程）")
    if do_demo:
        t0 = time.time()
        r = run([py_exe, "-X", "utf8", "_demo.py"], cwd=app_dir)
        if r.returncode != 0:
            log("   [FAIL] 演示失败：%s" % ((r.stderr or r.stdout or "")[-300:])); ok = False
        else:
            log("   [OK] 演示跑完（%.1f 秒）" % (time.time() - t0))
    else:
        log("   （--no-demo，跳过）")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default="", help="当底座的 Python（要带 pandas/scipy/matplotlib/numpy）")
    ap.add_argument("--no-zip", action="store_true", help="只做目录，不压缩")
    ap.add_argument("--no-demo", action="store_true", help="跳过演示验收")
    ap.add_argument("--out", default=OUT_ROOT, help="输出到哪")
    args = ap.parse_args()

    print("=" * 66)
    print("  打包便携版（自带 Python）")
    print("=" * 66)

    base = find_base_python(args.python)
    if not base:
        print("\n[FAIL] 找不到合适的底座 Python。")
        print("   需要一个**已经装了** pandas / scipy / matplotlib / numpy 的 Python，")
        print("   装上它们再跑：pip install pandas scipy matplotlib numpy openpyxl")
        return 2
    log("底座：%s" % base)

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    top = os.path.join(out, TOP_NAME)
    if os.path.isdir(top):
        shutil.rmtree(top, ignore_errors=True)
    os.makedirs(top)

    t0 = time.time()
    py_dir = copy_python(base, os.path.join(top, "_python"))

    log("按黑名单删掉与运行无关的包（白名单会漏 DLL，见文件顶部说明）")
    prune_site_packages(py_dir)
    n = clean_caches(py_dir)
    log("清了 %d 个 __pycache__" % n)

    app_dir = copy_app(os.path.join(top, APP_NAME))
    n = clean_caches(app_dir)
    log("  应用目录清了 %d 个 __pycache__" % n)

    # 便携版预置的 config（指向自带的 Python）
    with open(os.path.join(app_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(CONFIG_PORTABLE, f, ensure_ascii=False, indent=2)

    launcher = os.path.join(top, "start-portable.bat")
    # ⚠ .bat 必须 100% 纯 ASCII（cmd 按 OEM 代码页解析，UTF-8 中文会被撕成
    #   字节碎片当命令执行）。这条我踩过两次，所以在写之前就断言，
    #   别等写入时抛 UnicodeEncodeError（那个报错还看不出是哪一行中文）。
    first_bad = next((i for i, ch in enumerate(LAUNCHER) if ord(ch) > 127), None)
    if first_bad is not None:
        raise SystemExit(" [FAIL] start-portable.bat 里有非 ASCII 字符："
                         "位置 %d 是 %r —— .bat 必须纯 ASCII，改掉再打包"
                         % (first_bad, LAUNCHER[first_bad]))
    with open(launcher, "w", encoding="ascii", newline="\r\n") as f:
        f.write(LAUNCHER)

    # 便携版说明（从仓库里拿，保持只有一份）
    src_readme = os.path.join(HERE, "README-便携版.md")
    if os.path.isfile(src_readme):
        shutil.copy2(src_readme, os.path.join(top, "README-便携版.md"))

    print("\n" + "-" * 66)
    print("  验收（发出去之前必须全过）")
    print("-" * 66)
    ok = sanity_check(os.path.join(py_dir, "python.exe"), app_dir, not args.no_demo)

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, dn, fn in os.walk(top) for f in fn)
    print("\n" + "-" * 66)
    log("未压缩体积：%.0f MB" % (size / 1048576.0))

    zip_path = ""
    if not args.no_zip:
        zip_path = top + ".zip"
        log("压缩中…")
        if os.path.isfile(zip_path):
            os.remove(zip_path)
        import zipfile
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for dp, dn, fn in os.walk(top):
                for f in fn:
                    full = os.path.join(dp, f)
                    z.write(full, os.path.relpath(full, os.path.dirname(top)))
        mb = os.path.getsize(zip_path) / 1048576.0
        log("zip：%.1f MB" % mb)
        if mb > 100:
            log(" [!] 超过 GitHub 单文件 100 MiB 上限 —— **不能直接用 git 传**，")
            log("  要走 Release 附件或网盘（见 便携版/上传说明.md）")

    print("-" * 66)
    print("  %s   总耗时 %.0f 秒" % ("[OK] 全部验收通过" if ok else "[FAIL] 有验收没过，别发这个包",
                                      time.time() - t0))
    print("  产物：%s" % top)
    if zip_path:
        print("        %s" % zip_path)
    print("=" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
