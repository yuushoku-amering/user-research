# -*- coding: utf-8 -*-
"""工作台 × SPSS：把语法真的跑一遍，把 SPSS 自己的输出带回来。

为什么要有这个：Python 已经算过一遍，数字由它产出；但有人就是想看 **SPSS 的输出样式**
（三线表、脚注、成对的统计量），而且两边对得上，报告才站得住。

## 现在已经弄清楚的（都是实测 + 从 SPSS 自己的程序里挖出来的）

**开关**：SPSS 不认 `-b` / `-f` 那种短写。它真正的开关是一整串长名字，
从 `SPSSClientCore.jar` 的 `CommandLineKeyword` 里挖出来的是：

    -runsyntax  -production  -background  -silent  -unicode  -codepageSyntaxFiles
    -server  -singleseat  -switchserver  -automated  -help  -nologo  -password
    -user  -symbol  -source  -download  -embedding  -external  -statssrv …

其中 **`-runsyntax` 就是我们要的**：打开 SPSS 并**自动运行**指定的语法（不用手按 Ctrl+R）。
资源文件里还有一句关键的话：

    指定了 -production 时，将忽略开关 -runsyntax、-singleseat、-switchserver 和 -automated

所以 `-production`（生产作业，走 .spj 文件）和 `-runsyntax` 是两条互斥的路。

**编码**：SPSS 按**本机代码页**读语法文件。UTF-8 的中文进去会变成一堆别的汉字
（连 `DOCUMENTFILE='F:\\...\\用户研究\\...'` 里的**路径**都一起读坏），
表现为「SPSS 跑了，但报表解析出错、也没产出文件」。
→ 所以 `.sps` 一律用 **GBK** 写（`spss_syntax_encoding` 可以改）。

## 三条踩出来的规矩

1. **不自动探测**。SPSS 收到不认识的开关会弹模态框等人点确定，进程一直活着；
   自动跑会变成「你关掉一个它又开一个」（真发生过）。
2. **已经开着 SPSS 就不再另开窗口**。
3. **同一时间只允许一个探测在跑**。

产物：`output\\SPSS输出_<分析名>.html`（SPSS 自己导出的，工作台只负责显示）+ 原来的 `.sps`
"""
import os
import re
import shutil
import subprocess
import threading
import time

from . import paths

# ⚠ 已知错误的短开关（-b / -f / -o …）**不要再试了**：SPSS 会弹框说「未知的开关」，
#   而那个框会一直等人点确定。
BAD_FORMS = ["-b", "-f", "-o", "/b", "/f", "/o"]

# 真正可用的两条路（按推荐顺序）
CANDIDATES = [
    ("生产作业：-production + .spj（跑完自己退出，不用碰界面）", ["-production", "{spj}"]),
    ("退回界面：把语法打开，人按 Ctrl+A / Ctrl+R", ["{sps}"]),
]

PROBE_SPS = """* 工作台 × SPSS 连通性自检（算个 1+1，不留痕）
DATA LIST FREE /x.
BEGIN DATA.
1
2
3
END DATA.
FREQUENCIES VARIABLES=x.
"""

EXPORT_TAIL = """
* ---- 让 SPSS 把这次的输出导出成 HTML（工作台要拿它显示，别的什么都不改）----
OUTPUT EXPORT /CONTENTS EXPORT=ALL /HTML DOCUMENTFILE='{html}'.
"""

DEFAULT_ENCODING = "gbk"

# SPSS 的生产作业（production job）命名空间 —— 见 D:\SPSS\production-1.4.xsd
PROD_NS = "http://www.ibm.com/software/analytics/spss/xml/production"


def job_xml(sps_path, out_path, out_format="html", unicode_mode=True,
            error_handling="continue", syntax_format="batch", image_format="png"):
    """拼一份生产作业文件（.spj）。

    这是 SPSS **专门为自动化设计**的路子（`-production` + `.spj`），
    取值全部从它自己的 `production-1.4.xsd` 里挖出来：

        syntaxFormat        = interactive | batch
        syntaxErrorHandling = continue | stop
        outputFormat        = viewer | viewer-pes | web-reports | html | excel
                              | word | power-point | pdf | text-codepage | text-utf8 | text-utf16
        imageFormat         = bmp | emf | eps | jpg | png | tif

    好处：**输出格式和路径直接写在作业里**，语法里连 `OUTPUT EXPORT` 都不用加。
    """
    import datetime

    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<job xmlns="%s"\n'
        '     syntaxFormat="%s"\n'
        '     syntaxErrorHandling="%s"\n'
        '     print="false"\n'
        '     unicode="%s"\n'
        '     creator="user-research-workbench"\n'
        '     date="%s">\n'
        '  <syntax syntaxPath="%s"/>\n'
        '  <output outputPath="%s" outputFormat="%s" imageFormat="%s"/>\n'
        '</job>\n'
        % (PROD_NS, esc(syntax_format), esc(error_handling),
           "true" if unicode_mode else "false",
           datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
           esc(sps_path), esc(out_path), esc(out_format), esc(image_format)))


# --------------------------------------------------------------------------- #
# 编码：SPSS 按本机代码页读语法
# --------------------------------------------------------------------------- #

def syntax_encoding(cfg=None):
    cfg = cfg or paths.load_config()
    return (cfg.get("spss_syntax_encoding") or DEFAULT_ENCODING).strip() or DEFAULT_ENCODING


def read_syntax(path, cfg=None):
    """读语法文件。

    顺序有讲究：**先试 UTF-8，再试本机代码页**。
    GBK 的双字节中文几乎不可能是合法的 UTF-8，所以「UTF-8 能解开就用它」是安全的；
    这样老版本留下的 UTF-8 语法也能正确读进来（改完会被迁成 GBK）。
    """
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", syntax_encoding(cfg), "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("gb18030", "replace")


def write_syntax(path, text, cfg=None):
    """写语法文件（默认 GBK，让 SPSS 读得懂）。"""
    enc = syntax_encoding(cfg)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding=enc, newline="\n", errors="replace") as f:
            f.write(text)
    except LookupError:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return path


# --------------------------------------------------------------------------- #
# 环境
# --------------------------------------------------------------------------- #

def find_exe(cfg=None):
    cfg = cfg or paths.load_config()
    exe = (cfg.get("spss_exe") or "").strip()
    return exe if exe and os.path.exists(exe) else ""


def explain(err):
    """把 SPSS 的报错翻译成人能看懂、能动手的一句话。

    ⚠ 别只看最后几行：真正的病根（比如 `Access denied ... registry`）
      在 Java 堆栈的**开头**，尾巴上全是 `at com.spss...Unknown Source`。
    """
    e = str(err or "")
    low = e.lower()
    if "access denied" in low or "拒绝访问" in e or "error code 5" in low:
        return ("SPSS 起不来：它要写注册表（HKCU\\Software\\JavaSoft\\Prefs），被拒绝了。\n"
                "多半是工作台被一个「权限受限」的程序拉起来的 —— 用 "
                "workbench\\启动工作台.bat 亲手重启一次工作台，就正常了。")
    if "license" in low or "许可" in e or "授权" in e:
        return "SPSS 的许可没过 —— 先手动打开一次 SPSS 确认能正常用，再回来试。"
    if "cannot find" in low or "找不到" in e:
        return "找不到 SPSS 的可执行文件 —— 看一下 config.json 里的 spss_exe。"
    if "unknown source" in low or "com.spss" in low or "exception" in low:
        return ("SPSS 启动了但立刻退出，没有产出输出文件。\n"
                "· 工作台是被「权限受限」的程序拉起来的（SPSS 写不了注册表）—— "
                "用 workbench\\启动工作台.bat 亲手重启一次；\n"
                "· 或者 SPSS 的许可/安装有问题 —— 先手动打开一次 SPSS 确认能用。")
    lines = [x for x in e.strip().splitlines() if x.strip()]
    return lines[0] if lines else "SPSS 没有给出任何信息（它可能压根没启动起来）"


def _stats_pids():
    """现在有几个 stats.exe 在跑。用来判断 SPSS 是不是开着。"""
    try:
        p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq stats.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (p.stdout or b"").decode("utf-8", "replace")
        pids = set()
        for line in out.splitlines():
            parts = [x.strip().strip('"') for x in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.add(int(parts[1]))
        return pids
    except Exception:
        return None


def stats_running():
    """界面上要判断「SPSS 是不是开着」时用这个（返回个数）。"""
    return len(_stats_pids() or ())


def ascii_run_dir(prefix="urw_spss"):
    """给 SPSS 一个**全 ASCII** 的工作目录（项目路径里有中文，少一个变量少一种玄学）。"""
    base = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    if not base or not os.path.isdir(base) or any(ord(c) > 127 for c in base):
        base = os.path.abspath(os.sep)
    d = os.path.join(base, "%s_%s" % (prefix, time.strftime("%H%M%S")))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# 语法加工
# --------------------------------------------------------------------------- #

def drop_encoding_header(text):
    """把以前的 `* Encoding: UTF-8.` 去掉 —— 现在语法是按本机代码页写的，
    留着那一行反而会让 SPSS 按 UTF-8 读，等于自己把自己弄乱码。"""
    lines = str(text or "").split("\n")
    while lines and lines[0].strip().lower().startswith("* encoding"):
        lines.pop(0)
    return "\n".join(lines)


def set_export_target(text, html_path):
    """把导出路径指向指定文件（没有导出尾巴就补一条）。"""
    t = re.sub(r"OUTPUT\s+EXPORT.*?DOCUMENTFILE\s*=\s*'[^']*'",
               lambda m: "OUTPUT EXPORT /CONTENTS EXPORT=ALL /HTML DOCUMENTFILE='%s'"
                         % str(html_path).replace("'", "''"),
               str(text or ""), flags=re.I | re.S)
    if "OUTPUT EXPORT" not in t.upper():
        t = t.rstrip() + "\n" + EXPORT_TAIL.format(html=html_path) + "\n"
    return t


def prepare_syntax(sps_path, html_path, cfg=None):
    """把一份语法改成「跑完会把输出导出成 HTML」的样子，并按 SPSS 认的编码写回去。"""
    if not os.path.exists(sps_path):
        return False
    body = read_syntax(sps_path, cfg)
    new = set_export_target(drop_encoding_header(body), html_path)
    if new != body:
        write_syntax(sps_path, new, cfg)
        return True
    return False


_DATA_RE = re.compile(r"(/FILE\s*=\s*')([^']*)(')", re.I)


def strip_export(text):
    """把 `OUTPUT EXPORT` 那段去掉（生产作业里已经指定输出目标了，不用它再导一次）。"""
    t = re.sub(r"\n?\*[^\n]*OUTPUT EXPORT[^\n]*\n", "\n", str(text or ""), flags=re.I)
    t = re.sub(r"OUTPUT\s+EXPORT[^.]*\.\s*", "", t, flags=re.I | re.S)
    return t


def build_run_copy(body, run_dir, html_name="out.html", with_export=False):
    """把语法改造成「在临时目录里跑」的版本：路径全 ASCII。

    ⚠ 为什么非要搬进临时目录：SPSS 的**生产作业文件（.spj）自己也按本机代码页读**，
      路径里的中文一进去就变成问号，然后它报「无法使用给定的文件指定项来访问文件」。
      把数据、语法、作业全放到全 ASCII 的临时目录里，这个坑就彻底没有了。
    """
    text = drop_encoding_header(body)
    if with_export:
        text = set_export_target(text, os.path.join(run_dir, html_name))
    else:
        text = strip_export(text)
    copied = False
    m = _DATA_RE.search(text)
    if m:
        src = m.group(2)
        if os.path.exists(src):
            dst = os.path.join(run_dir, "data" + os.path.splitext(src)[1])
            shutil.copyfile(src, dst)
            text = text[:m.start(2)] + dst + text[m.end(2):]
            copied = True
    return text, copied


# --------------------------------------------------------------------------- #
# 跑
# --------------------------------------------------------------------------- #

def run_production(project_root, sps_rel, out_rel, cfg=None, timeout=420,
                   out_format="html", progress=None):
    """用**生产作业**跑一份语法：`stats.exe -production <作业.spj>`。

    为什么改用它而不是 `-runsyntax`：
      · `-runsyntax` 走的是 `openSyntaxDocument`（**打开**语法，不是「跑」），
        实测 SPSS 一闪就没了、什么也没产出
      · 生产作业是 SPSS **专门为自动化设计**的：格式、输出路径、编码都在作业文件里写明，
        跑完就退出，不需要人碰界面
    """
    cfg = cfg or paths.load_config()
    exe = find_exe(cfg)
    if not exe:
        return {"ok": False, "error": "config.json 里的 spss_exe 指向的文件不存在"}
    sps_path = os.path.join(project_root, sps_rel)
    out_path = os.path.join(project_root, out_rel)
    if not os.path.exists(sps_path):
        return {"ok": False, "error": "找不到语法文件：%s" % sps_rel}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)
    # 整条链都在**全 ASCII 的临时目录**里跑：
    #   .spj 里的路径、语法文件、数据文件，全是 ASCII ——
    #   SPSS 把 .spj 按本机代码页读，路径里有中文就会变成问号、然后报「无法访问文件」（踩过）
    run_dir = ascii_run_dir()
    try:
        body = read_syntax(sps_path, cfg)
        run_body, copied = build_run_copy(body, run_dir, with_export=False)
        run_sps = os.path.join(run_dir, "syntax.sps")
        write_syntax(run_sps, run_body, cfg)
        run_out = os.path.join(run_dir, "out.html")
        spj = os.path.join(run_dir, "job.spj")
        xml = job_xml(run_sps, run_out, out_format=out_format,
                      unicode_mode=(syntax_encoding(cfg).lower().startswith("utf")),
                      error_handling=(cfg.get("spss_error_handling") or "continue"))
        with open(spj, "w", encoding="utf-8", newline="\n") as f:
            f.write(xml)

        if progress:
            progress("用生产作业跑 SPSS（-production，路径全 ASCII）…")
        code, out, err, secs = _run(exe, ["-production", spj], run_dir, timeout)
        ok = os.path.exists(run_out) and os.path.getsize(run_out) > 0
        res = {"ok": ok, "mode": "production", "seconds": round(secs, 1), "code": code,
               "sps": sps_rel, "html": out_rel, "data_copied": copied,
               "spj": os.path.splitext(out_rel)[0] + ".spj"}
        if ok:
            shutil.copyfile(run_out, out_path)          # 输出拷回项目
            res["size"] = os.path.getsize(out_path)
            # ⚠ SPSS 失败时**照样会产出 HTML**（里面是它的日志）。
            #   看内容判断是「真结果」还是「报错」，不然界面会显示一张空表让人发懵。
            ready, html_text = collect(out_path)
            res["warning"] = html_diagnosis(html_text) if ready else ""
            # 顺手把作业文件也留一份到项目里（方便研究员自己看/复现）
            try:
                with open(os.path.join(project_root, res["spj"]), "w",
                          encoding="utf-8", newline="\n") as f:
                    f.write(xml)
            except Exception:
                pass
        else:
            res["error"] = (explain(err) or explain(out)
                            or ("生产作业跑了 %.1f 秒，但没有产出输出文件（退出码 %s）"
                                % (secs, code)))
            res["stderr_tail"] = " | ".join((err or "").strip().splitlines()[-3:])
            res["stdout_tail"] = " | ".join((out or "").strip().splitlines()[-3:])
        return res
    finally:
        # 把这次跑的现场留一份到 _jobs\_spss_last：作业文件、语法、SPSS 的输出都能翻
        try:
            last = os.path.join(paths.JOBS_DIR, "_spss_last")
            shutil.rmtree(last, ignore_errors=True)
            shutil.copytree(run_dir, last)
        except Exception:
            pass
        shutil.rmtree(run_dir, ignore_errors=True)


def _run(exe, args, workdir, timeout):
    t0 = time.time()
    try:
        p = subprocess.run([exe] + args, cwd=workdir, capture_output=True,
                           timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return None, "", "等了 %d 秒还没跑完" % timeout, time.time() - t0
    out = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out, err, time.time() - t0


def open_syntax(exe, sps_path, autorun=True, force=False):
    """把语法交给 SPSS：默认用 `-runsyntax`，**打开就自动跑**，不用手按 Ctrl+R。

    ⚠ `force=False` 时已经有 SPSS 开着就不另开一个 —— 不然每跑一次分析就多一个窗口。
    """
    if not exe or not os.path.exists(exe):
        return {"ok": False, "error": "没找到 SPSS 可执行文件（看 config.json 的 spss_exe）"}
    if not sps_path or not os.path.exists(sps_path):
        return {"ok": False, "error": "找不到语法文件：%s" % sps_path}
    if not force and _stats_pids():
        return {"ok": True, "already": True, "autorun": False, "error": ""}
    args = ["-runsyntax", sps_path] if autorun else [sps_path]
    try:
        subprocess.Popen([exe] + args, cwd=os.path.dirname(sps_path) or None)
    except Exception as e:
        return {"ok": False, "error": "打不开 SPSS：%s" % e}
    return {"ok": True, "already": False, "autorun": bool(autorun), "error": ""}


# 旧的调用名，别处还在用
def launch_gui(exe, sps_path, with_banner=True, force=False):
    if with_banner:
        add_banner(sps_path, autorun=True)
    return open_syntax(exe, sps_path, autorun=True, force=force)


def open_in_gui(exe, target, wait=False):
    """把一个文件丢给 SPSS 打开（语法或输出都行）。"""
    if not exe or not os.path.exists(exe):
        return False, "没找到 SPSS 可执行文件"
    if not target or not os.path.exists(target):
        return False, "找不到这个文件：%s" % target
    try:
        subprocess.Popen([exe, target], cwd=os.path.dirname(target) or None)
    except Exception as e:
        return False, "打不开 SPSS：%s" % e
    return True, ""


def banner(autorun=True):
    """贴在语法最上面的说明。"""
    if autorun:
        how = "* 【怎么跑】工作台会自动用 SPSS 的生产作业跑它，你不用按键。\n"
    else:
        how = ("* 【怎么跑】工作台会自动跑；想手动跑也行：按 Ctrl+A 全选，再按 Ctrl+R。\n")
    return ("* " + "=" * 66 + "\n"
            + how +
            "*   跑完 SPSS 会把这次的输出导成 HTML，工作台会自动把它收回去显示。\n"
            "* " + "=" * 66 + "\n")


def add_banner(sps_path, autorun=True, cfg=None):
    body = read_syntax(sps_path, cfg)
    if "【怎么跑】" in body:
        return False
    body = drop_encoding_header(body)
    write_syntax(sps_path, banner(autorun) + body, cfg)
    return True


def html_diagnosis(text):
    """看一眼 SPSS 导出的 HTML：是正经结果，还是它自己的报错。

    为什么要这一步：SPSS 跑失败时**照样会产出一个 HTML**，里面是它的日志/报错。
    如果不看内容就当成「成功」，界面会显示一张空表，人根本不知道发生了什么（踩过）。
    """
    t = str(text or "")
    low = t.lower()
    has_table = "<table" in low
    marks = []
    for pat in (r"错误\s*[号#]?\s*\d+", r"错误\s*命令名", r"警告\s*[号#]?\s*\d+",
                r"无法[使访]用", r"无法访问文件", r"执行停止", r"Cannot ", r"ERROR\b"):
        m = re.search(pat, t)
        if m:
            marks.append(m.group(0).strip())
    if not has_table and marks:
        hint = ""
        if "无效的字符" in t or "问号" in t:
            hint = ("看起来是**编码**问题：SPSS 读某个文件时把字符变成了问号。"
                    "检查一下路径里有没有它认不出的字。")
        elif "无法访问文件" in t or "无法使用" in t:
            hint = "SPSS 打不开某个文件 —— 多半是路径。"
        return ("SPSS 报错了，这次**没有产出结果表**。" +
                ("（%s）" % "、".join(marks[:3])) + ("\n" + hint if hint else ""))
    if not has_table:
        return "SPSS 跑完了，但输出里没有表格 —— 看看下面它导出的原文。"
    return ""


def collect(html_path, since=0):
    """看 SPSS 有没有把输出导出来。返回 (好了没, 内容)。"""
    if not html_path or not os.path.exists(html_path):
        return False, ""
    try:
        if since and os.path.getmtime(html_path) <= float(since):
            return False, ""
        with open(html_path, "rb") as f:
            raw = f.read()
        text = None
        for enc in ("utf-8-sig", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("gb18030", "replace")
        return True, strip_html(text)
    except Exception as e:
        return False, "输出读不出来：%s" % e


def strip_html(text, limit=2_000_000):
    """SPSS 导出的 HTML 直接用；只做个大小保护，免得把界面撑死。"""
    t = str(text or "")
    if len(t) > limit:
        t = t[:limit] + "\n<!-- 内容过长已截断 -->"
    return t


# --------------------------------------------------------------------------- #
# 自检（要人点，不自动跑）
# --------------------------------------------------------------------------- #

_DETECT_LOCK = threading.Lock()


def detect(cfg=None, timeout=90):
    """试一次 `-runsyntax`：SPSS 会不会被打开、会不会**自动跑**并产出输出文件。

    ⚠ 这条会真的打开 SPSS（因为 `-runsyntax` 就是走界面）。所以：
      · 只有人点了「试一下」才会调用
      · 同一时间只允许一个
      · 已经开着 SPSS 就不试（免得窗口混在一起）
      · 不认识的短开关（-b/-f/…）一律不再碰，那些只会弹框
    """
    if not _DETECT_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "已经有一个 SPSS 自检在跑了，等它结束再试。"}
    try:
        return _detect_inner(cfg, timeout)
    finally:
        _DETECT_LOCK.release()


def _detect_inner(cfg, timeout):
    cfg = cfg or paths.load_config()
    exe = find_exe(cfg)
    if not exe:
        return {"ok": False, "error": "config.json 里的 spss_exe 指向的文件不存在"}
    running = _stats_pids()
    if running:
        return {"ok": False,
                "error": "现在已经有 SPSS 开着（%d 个）。先把它关掉再自检 —— "
                         "否则分不清哪个窗口是新开的。" % len(running)}
    d = ascii_run_dir("urw_spss_probe")
    sps = os.path.join(d, "probe.sps")
    html = os.path.join(d, "probe.html")
    try:
        write_syntax(sps, drop_encoding_header(PROBE_SPS) + EXPORT_TAIL.format(html=html), cfg)
        base = _stats_pids() or set()
        r = open_syntax(exe, sps, autorun=True, force=True)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error")}
        # 等它自己跑完并导出（自动运行，不用按键）
        import time as _t
        waited = 0.0
        while waited < timeout:
            _t.sleep(1.0)
            waited += 1
            if os.path.exists(html) and os.path.getsize(html) > 0:
                cfg2 = paths.load_config()
                cfg2["spss_args"] = ["-runsyntax", "{sps}"]
                paths.save_config(cfg2)
                return {"ok": True, "args": ["-runsyntax", "{sps}"],
                        "seconds": round(waited, 1),
                        "tries": [{"args": "-runsyntax（自动运行）", "code": None,
                                   "seconds": round(waited, 1), "html": True,
                                   "note": "SPSS 已打开并自动跑完，输出导出来了"}]}
        opened = bool((_stats_pids() or set()) - base)
        return {"ok": False,
                "error": ("SPSS 是打开了，但 %d 秒内没等到它导出的输出文件。\n"
                          "· 看一下那个 SPSS 窗口：语法跑完了吗？有没有报错？\n"
                          "· 如果是「未知的开关」那种弹框，说明这台机器的 SPSS 版本不一样。"
                          % timeout) if opened else
                         "SPSS 没能打开（看 config.json 里的 spss_exe 对不对）。",
                "tries": [{"args": "-runsyntax（自动运行）", "code": None,
                           "seconds": round(waited, 1), "html": False,
                           "note": "打开了界面" if opened else "没打开"}]}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def get_args(cfg=None):
    cfg = cfg or paths.load_config()
    a = cfg.get("spss_args")
    if isinstance(a, list) and a and all(x not in BAD_FORMS for x in a):
        return a
    return None
