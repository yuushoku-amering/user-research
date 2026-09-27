# -*- coding: utf-8 -*-
"""工作台 · 本地服务（零依赖，只用 Python 标准库）

它干三件事：
1. 把 web/ 下的界面发给你
2. 把「有哪些组块、项目什么状态」用 JSON 发给界面
3. 收到「运行」后起一个引擎子进程，把日志**实时流回**界面

只在 127.0.0.1 上听；关掉窗口就停。开机不自启、不写注册表、不建计划任务。
"""
import json
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Windows 控制台默认是 GBK，打印 emoji / 特殊中文会直接抛 UnicodeEncodeError 把服务打死。
# 统一成 UTF-8，遇到编码不了的就替换，不让它崩。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(HERE, "libs")
# ⚠ 引擎那个 Python 是嵌入式发行版（带 python39._pth），**会完全忽略 PYTHONPATH**，
#   所以第三方包（openpyxl / pyreadstat）只能手动挂进 sys.path。
for _p in (LIBS, HERE):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from core import guard, jobs, paths, registry               # noqa: E402
from core.project import Project, create_project, list_projects   # noqa: E402

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

STATE = {"project_root": None}
LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #

def current_project(cfg=None):
    """当前项目；**没选项目就返回 None**（界面上就是空栏）。

    ⚠ 这里要**看一眼 config.json 有没有在磁盘上被改过**再决定用谁。
      踩过：为了修一个跑偏的路径，直接改了 config.json，可运行中的服务把旧值缓存在
      STATE 里，界面一刷新又把旧值写回配置 —— 外面改的东西白改了。
      也踩过：记着的路径不存在时「顺手」退回默认目录，界面回写就把配置覆盖了，
      「项目不见了」变成「项目悄悄换了」。所以现在的规矩是：
        · 没记项目（空）→ None
        · 记着的不是真项目 → 返回带 missing_root 的 Project，让界面照实说
    """
    if cfg is None:
        cfg = paths.load_config()
    # ⚠ 一定要同步，哪怕 cfg 是调用方传进来的 —— 有的调用点先 load_config 再传过来，
    #   只在 cfg is None 的分支里同步就会被绕过（第一版就是这么写的，被自己的测试抓到了）。
    _sync_state_from_cfg(cfg)
    # ⚠ 没记项目就返回 None（界面是空栏），**不拿项目之家凑数** ——
    #   踩过好几次：项目之家（F:\try\用户研究）长得像项目，被当成当前项目之后，
    #   产物落进历史目录、界面上还看不出哪里不对。规矩改成：没选就是没选。
    root = STATE.get("project_root")
    if root is None:
        root = cfg.get("project_root") or ""
    if not str(root).strip():
        return None
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        p = Project(root)
        p.missing_root = root
        return p
    if not _is_real_project(root):
        p = Project(root)          # 存在、但不是项目（最典型：项目之家自己）
        p.missing_root = root
        p.not_a_project = True
        return p
    return Project(root)


def _is_real_project(path):
    """这个目录是不是一个真正的研究项目。

    ⚠ 关键一条：**项目之家自己不算项目**。
      它下面躺着 `projects/` 和历史产物，长得跟项目很像，但它不是。
    """
    if not path or not os.path.isdir(path):
        return False
    try:
        if os.path.normcase(os.path.abspath(path)) == \
                os.path.normcase(os.path.abspath(base_root())):
            return False
    except Exception:
        pass
    if os.path.exists(os.path.join(path, "project.json")):
        return True
    return any(os.path.isdir(os.path.join(path, d))
               for d in ("contracts", "output", "data", "samples"))


def _sync_state_from_cfg(cfg=None):
    """config.json 在磁盘上变过 → 让内存里的当前项目跟着变。"""
    cfg = cfg or paths.load_config()
    try:
        mt = os.path.getmtime(paths.CONFIG_FILE)
    except OSError:
        return
    if STATE.get("_cfg_mtime") != mt:
        STATE["_cfg_mtime"] = mt
        disk = os.path.abspath(cfg.get("project_root") or "") if cfg.get("project_root") else ""
        if disk != os.path.abspath(STATE.get("project_root") or ""):
            # ⚠ 「清空」也要同步过来。第一版写成 `if disk and ...`，
            #   于是把项目清空之后内存里还留着旧项目 —— 界面照旧显示上一份研究，
            #   而配置明明是空的。空值也是一种值。
            STATE["project_root"] = disk


def set_project(root, remember=True):
    """切换当前项目。**顺手记住它**——否则重启服务后又回到默认根目录，
    人一不留神就在旧项目上跑新数据（踩过一次：在 F:\\try\\用户研究 这个历史目录上跑了 ⓪，
    产物全落错了地方）。

    ⚠ `remember=False`：**只在本次会话里切**，不写进 config.json。
      什么时候用：传进来的路径在**系统临时目录**里（测试脚手架的一次性项目）。
      踩过的坑：`_apitest.py` 在临时项目上跑了一次 ⑤，`set_project()` 就把那个临时路径
      记进了配置，而它随后被 `rmtree` 删掉 —— 下次启动界面顶着「记着的项目不见了」、
      项目栏空着，**研究员原来在用的项目被静默挤掉了**，他还不知道为什么。
      临时项目天生一次性，记它没有任何意义，所以这里自动不记（见 paths.is_temp_path）。
    """
    root = os.path.abspath(root)
    if not remember or paths.is_temp_path(root):
        # 临时目录里的项目：**能用，但不记**
        with LOCK:
            STATE["project_root"] = root
        return Project(root)
    with LOCK:
        changed = STATE.get("project_root") != root
        STATE["project_root"] = root
    if remember and changed:
        try:
            cfg = paths.load_config()
            if os.path.abspath(cfg.get("project_root") or "") != root:
                cfg["project_root"] = root
                paths.save_config(cfg)
                # 记下我们自己刚写过的时间戳，免得下一句 _sync 又把内存值当成"外面改的"再覆盖一次
                try:
                    STATE["_cfg_mtime"] = os.path.getmtime(paths.CONFIG_FILE)
                except OSError:
                    pass
        except Exception as e:
            print("[warn] 记住项目失败（不影响本次使用）：%s" % e)
        _note_recent_project(root)
    return Project(root)


NO_PROJECT_MSG = ("还没选项目 —— 先在顶栏「新建」一个，或从下拉里选一个 / 点「打开…」选目录。"
                  "（产物要落在项目里，我不替你随便找个地方放。）")


def _cur_root():
    """当前项目的根目录；**没选项目就是空字符串**（调用方自己决定怎么说）。"""
    p = current_project()
    return getattr(p, "root", "") if p is not None else ""


# 「这条提醒别再问了」的名单存哪 —— 放项目里（跟着项目走，换机器/打包带走都还在）。
IGNORED_REL = "忽略的提醒.json"

# 「最近用过的项目」流水：**只记路径**，最多 RECENT_MAX 条，临时目录/非项目不记。
# ⚠ 为什么需要它（2026-09-24 实测踩到）：
#   有些操作会把「当前项目」清掉 —— 测试要验"清空之后真的是空的"、研究员误点、
#   或者换"项目之家"。清完想恢复时才发现**原值本来就是空的**，于是"正在用的那个项目"
#   就找不回来了，界面只剩空栏，人也想不起刚才开的是哪个。
#   有这份流水，收尾/补救时就能把它找回来。
RECENT_FILE = os.path.join(paths.WORKBENCH, "最近项目.json")
RECENT_MAX = 20


def _note_recent_project(root):
    """把 root 记进「最近用过的项目」流水（去重、最新的在前、最多 20 条）。"""
    try:
        if not root or paths.is_temp_path(root) or not _is_real_project(root):
            return
        r = os.path.abspath(root)
        items = []
        if os.path.exists(RECENT_FILE):
            try:
                with open(RECENT_FILE, "r", encoding="utf-8") as f:
                    items = ((json.load(f) or {}).get("recent") or [])
            except Exception:
                items = []
        items = [x for x in items if isinstance(x, str)]
        items = [x for x in items if os.path.normcase(x) != os.path.normcase(r)]
        items.insert(0, r)
        # 顺手清掉已经不在的（被删/被搬走），再截到上限
        items = [x for x in items if os.path.isdir(x)][:RECENT_MAX]
        with open(RECENT_FILE, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"note": "最近用过的工作项目（只存路径）。删掉某条不影响项目本身。",
                       "recent": items}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[warn] 记「最近项目」失败（不影响使用）：%s" % e)


def recent_projects():
    """最近用过的项目（只要还存在的），最新的在前。"""
    if not os.path.exists(RECENT_FILE):
        return []
    try:
        with open(RECENT_FILE, "r", encoding="utf-8") as f:
            d = json.load(f) or {}
        return [x for x in (d.get("recent") or [])
                if isinstance(x, str) and os.path.isdir(x)]
    except Exception:
        return []


def _load_ignored(proj):
    try:
        p = proj.safe(IGNORED_REL)
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as f:
            import json as _json
            d = _json.load(f)
        v = d.get("ignored") if isinstance(d, dict) else d
        return [str(x) for x in (v or []) if str(x).strip()]
    except Exception:
        return []


def _save_ignored(proj, items):
    import json as _json
    p = proj.safe(IGNORED_REL)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        _json.dump({"note": "研究员点过「这条不用再问」的提醒。删掉某一条就能让它重新出现。",
                    "ignored": list(dict.fromkeys([str(x) for x in items if str(x).strip()]))},
                   f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p


def project_from(q, cfg=None):
    """GET 接口里按 `?project=` 取项目；没给就用当前项目；都没有就是 None。

    ⚠ 新加的项目级接口**必须**走这里。踩过：几个新接口直接用了 `current_project()`，
      于是 `?project=别的项目` 被无视，永远读当前那个项目 —— 静默答错，
      而且看起来"接口是通的"（返回 ok、只是数据不对）。这种最难查。
    ⚠ 返回 None 表示**没选项目**，调用方要自己 `if proj is None: return self.err(NO_PROJECT_MSG)`。
    """
    root = (q.get("project") or [None])[0]
    return set_project(root) if root else current_project(cfg)


def project_from_body(body, cfg=None):
    """POST 接口里按 body 的 `project` 取项目；没给就用当前项目；都没有就是 None。

    和 `project_from` 同一个道理：新加的项目级接口别直接用 current_project()，
    否则传进来的项目路径会被无视（踩过：接口返回 ok，数据却是另一个项目的）。
    """
    root = (body or {}).get("project")
    return set_project(root) if root else current_project(cfg)


def save_text_hist(proj, rel, text):
    """写一个文本产物，**覆盖前先把旧版留进 _history**。

    为什么单独抽出来：引擎（runner.Ctx.save_text）是这么做的，
    而「在界面上直接改产物」也必须这么做 —— 不然人改一版、程序再跑一次覆盖掉，
    前面改的东西就无声消失了。这条规矩两边得一样。

    返回 (rel, 备份名 or "")。备份失败不阻断（但会说）。
    """
    p = proj.safe(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    backup = ""
    if os.path.exists(p):
        try:
            old = ""
            for enc in ("utf-8-sig", "utf-8", "gb18030"):
                try:
                    with open(p, "r", encoding=enc) as f:
                        old = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            if old != text:
                hdir = proj.safe("_history")
                os.makedirs(hdir, exist_ok=True)
                from core.project import unique_hist_name
                backup = unique_hist_name(hdir, rel)      # 不撞名，见那个函数的注释
                with open(os.path.join(hdir, backup), "w", encoding="utf-8", newline="\n") as f:
                    f.write(old)
        except Exception as e:
            print("[warn] 备份旧版失败：%s" % e)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return rel, backup


def base_root(cfg=None):
    """**项目之家**：`projects/` 所在的那一层。

    ⚠ 和「当前项目」是两回事。踩过两次：
      · 拿当前项目当父目录去新建/导入 → 套成 `projects/A/projects/B`
      · 拿当前项目当根去列项目 → 下拉里只剩当前这一个，别的都看不见了
    """
    cfg = cfg or paths.load_config()
    return os.path.abspath(cfg.get("base_root") or paths.DEFAULT_PROJECT_ROOT)


def projects_parent(cfg=None):
    """「新建项目 / 导入快照」往哪儿放。"""
    return os.path.join(base_root(cfg), "projects")


def default_export_dir():
    """快照默认存到哪：优先桌面，没有就放项目之家下的 _快照/。"""
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desk):
        return desk
    return os.path.join(base_root(), "_快照")


def _ps_quote(s):
    return str(s if s is not None else "").replace("'", "''")


def _picker_script(kind, title, start, filt):
    """生成一段 PowerShell：弹 Windows 原生的选择框，把选中的路径打到标准输出。

    为什么要走这条路：浏览器拿不到本地路径（`<input type=file>` 只给 File 对象，
    `showDirectoryPicker()` 只给文件夹**名**）。但工作台是**本机服务**，
    由它去弹原生对话框，就能拿到真正的完整路径——而且要填进框里的也正是这个路径。
    """
    head = ("$ErrorActionPreference = 'Stop'\n"
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
            "$start = '%s'\n" % _ps_quote(start))
    if kind == "dir":
        return head + (
            "$shell = New-Object -ComObject Shell.Application\n"
            "if ($start -ne '' -and (Test-Path -LiteralPath $start)) {\n"
            "  $sel = $shell.BrowseForFolder(0, '%s', 0, $start)\n"
            "} else {\n"
            "  $sel = $shell.BrowseForFolder(0, '%s', 0, 0)\n"
            "}\n"
            "if ($sel -ne $null) { [Console]::Out.WriteLine($sel.Self.Path) }\n"
            % (_ps_quote(title), _ps_quote(title)))
    return head + (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "$dlg = New-Object System.Windows.Forms.OpenFileDialog\n"
        "$dlg.Title = '%s'\n"
        "$dlg.Filter = '%s'\n"
        "$dlg.Multiselect = $false\n"
        "$dlg.CheckFileExists = $false\n"
        "if ($start -ne '' -and (Test-Path -LiteralPath $start)) {\n"
        "  $it = Get-Item -LiteralPath $start\n"
        "  if ($it.PSIsContainer) { $dlg.InitialDirectory = $start }\n"
        "  else { $dlg.InitialDirectory = (Split-Path -LiteralPath $start -Parent); "
        "$dlg.FileName = $it.Name }\n"
        "}\n"
        "if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::Out.WriteLine($dlg.FileName) }\n"
        % (_ps_quote(title), _ps_quote(filt)))


PROBE_PS = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.Form
$h = $f.Handle
$f.Dispose()
[Console]::Out.WriteLine('OK')
"""


def probe_picker():
    """**不弹窗**地探一下：这个进程能不能创建窗口？

    为什么要探：服务要是跑在「没有桌面」的会话里，原生的选择框根本弹不出来，
    用户会以为按钮坏了。所以启动/自检时先问一句，答不上来就老实说。
    """
    d = os.path.join(paths.JOBS_DIR, "_pick")
    os.makedirs(d, exist_ok=True)
    ps1 = os.path.join(d, "probe.ps1")
    with open(ps1, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(PROBE_PS)
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                            "-File", ps1], capture_output=True, timeout=60)
    except FileNotFoundError:
        return False, "这台机器上找不到 powershell"
    except subprocess.TimeoutExpired:
        return False, "探测超时"
    out = (p.stdout or b"").decode("utf-8", "replace").strip()
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    if "OK" in out:
        return True, ""
    tail = " | ".join(err.splitlines()[-2:]) or "（没有报错信息）"
    return False, tail


def run_picker(kind, title, start, filt, timeout=300):
    """真的去弹框。返回 (路径, 出错说明)。用户点了取消就返回 ('', '')。"""
    script = _picker_script(kind, title, start, filt)
    d = os.path.join(paths.JOBS_DIR, "_pick")
    os.makedirs(d, exist_ok=True)
    ps1 = os.path.join(d, "pick_%s.ps1" % kind)
    with open(ps1, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(script)
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                            "-File", ps1],
                           capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return "", "这台机器上找不到 powershell，只能手打路径了"
    except subprocess.TimeoutExpired:
        return "", "选择框一直没关（等了 %d 秒）—— 可能被别的窗口挡住了，再试一次" % timeout
    out = (p.stdout or b"").decode("utf-8", "replace").strip()
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    if lines:
        return lines[-1], ""
    if p.returncode != 0:
        tail = " | ".join(err.splitlines()[-3:]) or "（没有报错信息）"
        return "", "选择框没能弹出来：%s" % tail
    return "", ""          # 没报错也没选 → 用户取消了


def check_env(cfg):
    """工作台「能不能干活」的自检：引擎、依赖包、SPSS。"""
    py = paths.engine_python(cfg)
    # ⚠ 依赖的判据是**真的 import 一次**，不是「libs 目录里有没有那个文件夹」——
    #   便携版把整只 Python 带走，包装在 site-packages 里、根本没有 libs/，
    #   老写法会把能用的环境报成「缺包」（见 core/paths.can_import 的注释）。
    libs_ok = {}
    for name in ("openpyxl", "pyreadstat"):
        libs_ok[name] = paths.can_import(name, py)
    spss = cfg.get("spss_exe") or ""
    return {
        "python": py,
        "python_exists": os.path.exists(py),
        "libs": libs_ok,
        "libs_dir": paths.LIBS,
        "spss": spss,
        "spss_exists": bool(spss) and os.path.exists(spss),
        "workbench": paths.WORKBENCH,
    }


def api_state(query):
    cfg = paths.load_config()
    root = (query.get("project") or [None])[0]
    proj = set_project(root) if root else current_project(cfg)
    blocks = registry.load_blocks()
    from core import llm as llm_mod
    # 记着的项目不见了 / 不是项目：**照实说**，不要默默换成别的项目
    # （默默换掉之后界面一回写就把配置覆盖了，于是「项目不见了」变成「项目悄悄换了」）。
    if proj is not None and getattr(proj, "missing_root", ""):
        # 记着的项目不见了 / 不是项目：**照实说**，但别把那个不存在的路径当"当前项目"发出去
        # —— 前端拿着一个不存在的 root 到处用，就是在各种地方踩空。
        # 规矩：项目栏留空 + 一条红条说清为什么，由人来选。
        missing = proj.missing_root
        why = ("「%s」不是一个研究项目（多半是**项目之家**那一层）" % missing
               if getattr(proj, "not_a_project", False)
               else "记着的项目不见了：%s" % missing)
        return {
            "ok": True, "workbench": paths.WORKBENCH,
            "env": check_env(cfg),
            # ⚠ `llm` 一律过 public_conf —— 它会把 api_key 换成"设没设 + 脱敏形态"，
            #   别直接发 cfg.get("llm")（那会把密钥原文送进浏览器）
            "config": {"port": cfg.get("port"), "llm": llm_mod.public_conf(cfg),
                       "llm_status": llm_mod.status(cfg),
                       "export_dir": cfg.get("export_dir") or default_export_dir()},
            "blocks": [registry.public(b) for b in blocks],
            "rail_groups": registry.RAIL_GROUPS,
            "projects": list_projects(base_root(cfg)),
            "project": None,
            "no_project": True,
            "missing_root": missing,
            "error": "%s —— 从下面的列表里挑一个，或点「新建」／「打开…」。" % why,
        }
    if proj is None:
        # **没选项目**：给一个空栏，别拿项目之家凑数
        return {
            "ok": True, "workbench": paths.WORKBENCH,
            "env": check_env(cfg),
            # ⚠ `llm` 一律过 public_conf —— 它会把 api_key 换成"设没设 + 脱敏形态"，
            #   别直接发 cfg.get("llm")（那会把密钥原文送进浏览器）
            "config": {"port": cfg.get("port"), "llm": llm_mod.public_conf(cfg),
                       "llm_status": llm_mod.status(cfg),
                       "export_dir": cfg.get("export_dir") or default_export_dir()},
            "blocks": [registry.public(b) for b in blocks],
            "rail_groups": registry.RAIL_GROUPS,
            "projects": list_projects(base_root(cfg)),
            "project": None,
            "no_project": True,
        }
    return {
        "ok": True,
        "workbench": paths.WORKBENCH,
        "env": check_env(cfg),
        # ⚠ 同上：这处也要过 public_conf（别把 api_key 原文发进浏览器）
        "config": {"port": cfg.get("port"), "llm": llm_mod.public_conf(cfg),
                   "llm_status": llm_mod.status(cfg),
                   "export_dir": cfg.get("export_dir") or default_export_dir()},
        "blocks": [registry.public(b) for b in blocks],
        "rail_groups": registry.RAIL_GROUPS,
        "projects": list_projects(base_root(cfg)),
        "project": proj.summary(blocks),
        # 「这条不用再问」的名单（存项目里，跟着项目走）
        "ignored_alerts": _load_ignored(proj),
    }


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = "URW/0.1"
    protocol_version = "HTTP/1.1"

    # ---- 底层发送 ----

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def err(self, msg, code=400):
        self.json({"ok": False, "error": msg}, code)

    def body_bytes(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def body_json(self):
        raw = self.body_bytes()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def log_message(self, fmt, *args):        # 别刷屏，只在出错时说话
        if args and str(args[0]).startswith(("4", "5")):
            sys.stderr.write("[http] " + (fmt % args) + "\n")

    # ---- 静态 ----

    def serve_static(self, rel):
        rel = rel.replace("\\", "/").lstrip("/")
        target = os.path.abspath(os.path.join(paths.WEB, rel))
        if not target.startswith(os.path.abspath(paths.WEB)):
            return self.err("路径越界", 403)
        if not os.path.exists(target):
            return self.err("没有这个文件：%s" % rel, 404)
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        with open(target, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- GET ----

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(u.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if path in ("/", "/index.html"):
                return self.serve_static("index.html")
            if path.startswith("/web/"):
                return self.serve_static(path[5:])
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if path == "/api/state":
                return self.json(api_state(q))
            if path == "/api/job":
                job = jobs.MANAGER.get((q.get("id") or [""])[0])
                if not job:
                    return self.err("没有这个任务", 404)
                since = int((q.get("since") or ["0"])[0])
                steps_since = int((q.get("steps_since") or ["0"])[0])
                return self.json({"ok": True, "job": job.snapshot(since, steps_since)})
            if path == "/api/alerts/ignored":
                # 「这条提醒不用再问」的名单 —— 研究员提的：
                #   「为了防止有如…这种复杂情况，最好加一个选项来跳过或者无视这一提醒」。
                # 存项目里（不是浏览器）：换台机器、把项目打包带走再打开，忽略状态还在。
                proj = project_from(q)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                return self.json({"ok": True, "ignored": _load_ignored(proj),
                                  "rel": IGNORED_REL})
            if path == "/api/artifact":
                return self.api_artifact(q)
            if path == "/api/columns":
                return self.api_columns(q)
            if path == "/api/deident/state":
                proj = current_project()
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                return self.json({"ok": True, "deident": guard.summary_for_ui(proj.root),
                                  "materials": guard.scan(proj)})
            if path == "/api/report/artifacts":
                # 产物分两层：研究员标过的「关键结果」在前，过程产物放后面
                proj = project_from(q)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                from core import report as report_mod
                return self.json({"ok": True, "layers": report_mod.classify(proj),
                                  "flags": report_mod.load_flags(proj)})
            if path == "/api/forms":
                # 表单里填过的东西（按组块存）。
                # **为什么放项目目录而不是浏览器**：localStorage 的键带项目路径，
                # 项目打包带走、导入回来之后路径变了 → 键对不上 → 表单全空。
                # 存进项目，快照一打包就跟着走，「导入回来接着做」才是真的接着做。
                # ⚠ 这是 GET —— 别插到 do_POST 里去（插错过一次，接口直接报"没有这个接口"）。
                proj = project_from(q)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                from core import formstate
                return self.json({"ok": True, "forms": formstate.load(proj),
                                  "rel": formstate.REL})
            if path == "/api/versions":
                # 某份文件有哪些历史版本（含当前版，新的在前）
                proj = project_from(q)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = (q.get("rel") or [""])[0]
                from core import versioning
                return self.json({"ok": True, "rel": rel,
                                  "versions": versioning.list_versions(proj, rel)})
            if path == "/api/version/diff":
                proj = project_from(q)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = (q.get("rel") or [""])[0]
                a = (q.get("a") or [""])[0]
                b = (q.get("b") or [""])[0]
                from core import versioning
                d = versioning.diff_versions(proj, rel, a, b)
                if not d.get("ok"):
                    return self.err(d.get("error") or "对比不了")
                d["markdown"] = versioning.diff_to_markdown(rel, d)
                return self.json(d)
            if path == "/api/brief/sections":
                # 「填回表单」：把简报里各小节的**原文**读完给界面。
                # 为什么必须有这个：简报里明明写着研究员填过的背景/目的/RQ/人群，
                # 但表单文件里没有（表单文件只记"界面碰过的字段"），
                # 于是重新打开/导入回来之后，那些文本框是空的 —— 人得重新打一遍。
                proj = project_from(q)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = (q.get("rel") or ["contracts/research_brief.md"])[0]
                from core import kit
                p = proj.safe(rel)
                if not os.path.exists(p):
                    return self.json({"ok": True, "rel": rel, "exists": False, "sections": {}})
                text = ""
                for enc in ("utf-8-sig", "utf-8", "gb18030"):
                    try:
                        with open(p, "r", encoding=enc) as f:
                            text = f.read()
                        break
                    except UnicodeDecodeError:
                        continue
                    except OSError as e:
                        return self.err("读不了 %s：%s" % (rel, e))
                return self.json({"ok": True, "rel": rel, "exists": True,
                                  "sections": kit.brief_sections(text)})
            if path == "/api/brief/variables":                # 界面那张变量表格的「读回」：读简报 → 用和引擎同一套规则解析
                proj = current_project()
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = (q.get("rel") or ["contracts/research_brief.md"])[0]
                from core import kit
                p = proj.safe(rel)
                rows = kit.brief_variables(p)
                return self.json({"ok": True, "rel": rel, "exists": os.path.exists(p),
                                  "rows": [list(r) for r in rows]})
            if path == "/api/ping":
                return self.json({"ok": True, "t": time.time()})
            if path == "/api/settings":
                return self.json(self.settings_state())
            return self.err("没有这个接口：%s" % path, 404)
        except Exception as e:
            traceback.print_exc()
            return self.err("%s: %s" % (type(e).__name__, e), 500)

    def settings_state(self):
        """「⚙ 设置」面板要的全部信息。**密钥只给脱敏形态 + 设没设**。

        这里**不返回任何密钥原文**（前端拿到的 `api_key` 永远是空串），
        所以这个接口即使被截图、被贴到聊天里，也不会泄露。
        """
        from core import spss as spss_mod
        from core import llm as llm_mod          # ⚠ 必须显式导入：`llm_mod` 只是 api_state
        cfg = paths.load_config()                #    里的局部名，别指望它在别的方法里也在
        pub = llm_mod.public_conf(cfg)
        st = llm_mod.status(cfg)
        exe = ""
        try:
            exe = spss_mod.find_exe() or ""
        except Exception:
            exe = ""
        cands = []
        try:
            for c in spss_mod.spss_candidates():
                cands.append(c if isinstance(c, dict) else {"path": c, "label": ""})
        except Exception:
            cands = []
        return {
            "ok": True,
            "workbench": paths.WORKBENCH,
            "config_file": getattr(paths, "CONFIG_FILE", ""),
            "spss": {
                "exe": exe,
                "exists": bool(exe and os.path.exists(exe)),
                "find_help": ("" if (exe and os.path.exists(exe))
                              else spss_mod.explain_not_found(cfg)),
                "candidates": cands,
                "running": bool(spss_mod.stats_running()),
            },
            "llm": {
                "enabled": bool(pub.get("enabled")),
                "provider": st["provider"],                      # "api" / "dsh" / ""
                "api_base": pub.get("api_base") or "",
                "api_model": pub.get("api_model") or "",
                "api_key_set": bool(pub.get("api_key_set")),
                "api_key_mask": pub.get("api_key_mask") or "",
                "has_dsh": bool(st["ready"] and st["provider"] == "dsh"),
                "base_hints": [{"base": b, "name": n} for b, n in llm_mod.API_BASE_HINTS],
                "default_base": llm_mod.DEFAULT_API_BASE,
                "default_model": llm_mod.DEFAULT_API_MODEL,
                "timeout": (cfg.get("llm") or {}).get("timeout") or 240,
            },
        }

    def api_artifact(self, q):
        """项目内的文件：图片直接出二进制，文本出 JSON。"""
        proj = current_project()
        if proj is None:
            return self.err(NO_PROJECT_MSG)
        rel = (q.get("rel") or [""])[0]
        if not rel:
            return self.err("缺 rel 参数")
        try:
            target = proj.safe(rel)
        except ValueError as e:
            return self.err(str(e), 403)
        if not os.path.exists(target):
            return self.err("文件不存在：%s" % rel, 404)
        ext = os.path.splitext(target)[1].lower()
        images = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}
        if ext in images:
            with open(target, "rb") as f:
                return self._send(200, f.read(), images[ext])
        text_exts = {".md", ".csv", ".txt", ".json", ".sps", ".py", ".log", ".html", ".xml"}
        if ext in text_exts:
            # ⚠ .sps 是**按本机代码页写的**（SPSS 只认那种），不能一律当 UTF-8 读
            raw = b""
            with open(target, "rb") as f:
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
            return self.json({"ok": True, "rel": rel, "text": text,
                              "size": os.path.getsize(target)})
        return self.json({"ok": True, "rel": rel, "binary": True,
                          "size": os.path.getsize(target)})

    def api_columns(self, q):
        """读一个数据文件的列名 + 类型——界面上的「变量下拉」靠它。"""
        proj = current_project()
        if proj is None:
            return self.err(NO_PROJECT_MSG)
        rel = (q.get("rel") or [""])[0]
        if not rel:
            return self.err("缺 rel 参数")
        try:
            target = proj.safe(rel)
        except ValueError as e:
            return self.err(str(e), 403)
        if not os.path.exists(target):
            return self.err("文件不存在：%s" % rel, 404)
        from core import kit
        try:
            df, how = kit.read_table(target)
            df = kit.clean_columns(df)
        except Exception as e:
            return self.err("读不了这个文件：%s" % e)
        cols = []
        for c in df.columns:
            s = df[c]
            cols.append({"name": str(c), "kind": kit.infer_kind(s),
                         "n_unique": int(s.nunique(dropna=True))})
        return self.json({"ok": True, "columns": cols, "rows": int(df.shape[0]),
                          "n_cols": int(df.shape[1]), "how": how})

    # ---- POST ----

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(u.path)
        # 上传快照时 body 是原始字节，不是 JSON —— 所以先原样读下来再决定怎么解
        raw = self.body_bytes()
        body = {}
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = {}
        try:
            if path == "/api/project/open":
                root = body.get("root") or ""
                if not os.path.isdir(root):
                    return self.err("这个目录不存在：%s" % root)
                proj = set_project(root)
                blocks = registry.load_blocks()
                if not os.path.exists(proj.path("project.json")):
                    proj.ensure()
                return self.json({"ok": True, "project": proj.summary(blocks)})

            if path == "/api/artifact/save":
                # 在界面上直接改产物（POST）。
                # 为什么必须有：**检测再聪明也会漏** —— 「广东莞」这种同形词、
                # 记录里缺一格导致位置错位、昵称不在姓氏表里…… 都没法靠规则穷尽。
                # 最后一道保险就是：研究员能自己动手改，改完立刻生效，旧版进 _history。
                proj = project_from_body(body)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = (body.get("rel") or "").replace("\\", "/").lstrip("./")
                if not rel:
                    return self.err("没说要改哪个文件")
                if os.path.splitext(rel)[1].lower() in (".png", ".jpg", ".jpeg", ".webp",
                                                        ".gif", ".xlsx", ".xls", ".sav"):
                    return self.err("这个格式不能在界面上直接改（是二进制）。")
                p = proj.safe(rel)
                if not os.path.exists(p):
                    return self.err("项目里没有这个文件：%s" % rel)
                if "text" not in body:
                    return self.err("没收到新的内容")
                new_text = body.get("text")
                if not isinstance(new_text, str):
                    return self.err("内容得是文本")
                old_size = os.path.getsize(p)
                rel2, backup = save_text_hist(proj, rel, new_text)
                return self.json({"ok": True, "rel": rel2, "backup": backup,
                                  "old_size": old_size, "size": len(new_text)})

            if path == "/api/alerts/ignore":
                # 研究员点「这条不用再问」→ 记进项目里，下次跑完不再显示它。
                proj = project_from_body(body)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                sig = (body.get("sig") or "").strip()
                if not sig:
                    return self.err("缺 sig（要忽略哪一条提醒）")
                cur = _load_ignored(proj)
                if body.get("undo"):
                    cur = [x for x in cur if x != sig]
                    _save_ignored(proj, cur)
                    return self.json({"ok": True, "ignored": cur, "undo": True})
                cur.append(sig)
                try:
                    _save_ignored(proj, cur)
                except OSError as e:
                    return self.err("记不下来：%s" % e)
                return self.json({"ok": True, "ignored": list(dict.fromkeys(cur))})

            if path == "/api/forms/save":
                proj = project_from_body(body)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                from core import formstate
                r = formstate.save(proj, body.get("block") or "", body.get("fields") or {})
                return self.json(r) if r.get("ok") else self.err(r.get("error") or "存不上")

            if path == "/api/project/delete":
                # 删项目。**这是不可逆操作，所以门槛要立起来**：
                #   · 只删「项目之家/projects」下面的目录（不许删项目之家自己、不许越界）
                #   · 不给删非项目目录（没有 project.json 又没有标准子目录的）
                #   · 要确认两次：前端先问一遍，这里再要求 confirm 字段带上项目名
                # 不直接 unlink —— 先改名成「_已删_<名字>_<时间>」再删，
                # 万一删错了，回收站/改名记录还能救。
                root = (body.get("root") or "").strip()
                if not root:
                    return self.err("没说要删哪个项目")
                root = os.path.abspath(root)
                parent = os.path.abspath(projects_parent())
                if not (root == parent or root.startswith(parent + os.sep)):
                    return self.err("只允许删「项目之家/projects」下面的项目，不动别的地方")
                if root == parent:
                    return self.err("那是 projects 目录本身，不能删")
                if not os.path.isdir(root):
                    return self.err("这个目录不存在：%s" % root)
                if not _is_real_project(root):
                    return self.err("「%s」不是一个研究项目，不敢删" % os.path.basename(root))
                # ⚠ 这里**不再要求手打项目名**。研究员说得对：
                #   「删除了为什么还要再输一次项目名，别这么搞，多加一个确认键就好了」——
                #   让人手打名字是用**输入成本**假装安全，既烦又没真拦住什么
                #   （要删的人照样会打）。真正的安全是**删了能找回来**。
                #   所以：删除 = **移进回收站**（带时间戳改名），要真删自己去回收站删。
                if os.path.normcase(root) == os.path.normcase(os.path.abspath(_cur_root() or "")):
                    cleared = True
                else:
                    cleared = False
                trash_dir = os.path.join(os.path.dirname(parent), ".trash")
                stamp = time.strftime("%Y%m%d_%H%M%S")
                dest = os.path.join(trash_dir, "%s_%s" % (os.path.basename(root), stamp))
                try:
                    os.makedirs(trash_dir, exist_ok=True)
                    n = 2
                    while os.path.exists(dest):        # 同一秒删两次也别撞名
                        dest = os.path.join(trash_dir, "%s_%s_%d" % (os.path.basename(root), stamp, n))
                        n += 1
                    shutil.move(root, dest)
                    with open(os.path.join(dest, "_删除记录.json"), "w",
                              encoding="utf-8", newline="\n") as f:
                        json.dump({"原来在哪": root,
                                   "删于": time.strftime("%Y-%m-%d %H:%M:%S"),
                                   "怎么还原": "把整个目录移回原来那个路径就行（或者点界面上的「撤销」）"},
                                  f, ensure_ascii=False, indent=2)
                except Exception as e:
                    return self.err("删不掉：%s" % e)
                if cleared:
                    cfg2 = paths.load_config()
                    cfg2["project_root"] = ""
                    paths.save_config(cfg2)
                    with LOCK:
                        STATE["project_root"] = ""
                        try:
                            STATE["_cfg_mtime"] = os.path.getmtime(paths.CONFIG_FILE)
                        except OSError:
                            STATE["_cfg_mtime"] = None
                return self.json({"ok": True, "deleted": os.path.basename(root),
                                  "trash": dest, "undo_token": os.path.basename(dest),
                                  "cleared_current": cleared})

            if path == "/api/project/undelete":
                # 「撤销删除」：把回收站里那份搬回原处。
                # 有了它，"删除"才配得上只要一次确认 —— 手滑了能回来。
                token = (body.get("token") or "").strip()
                if not token:
                    return self.err("缺 token（要还原回收站里的哪一份）")
                parent = os.path.abspath(projects_parent())
                trash_dir = os.path.abspath(os.path.join(os.path.dirname(parent), ".trash"))
                src = os.path.abspath(os.path.join(trash_dir, token))
                # 只认回收站里的东西，别让人拿这个接口去搬别处的目录
                if not (src == trash_dir or src.startswith(trash_dir + os.sep)) or not os.path.isdir(src):
                    return self.err("回收站里没有这一份：%s" % token)
                rec_path = os.path.join(src, "_删除记录.json")
                back = ""
                try:
                    if os.path.exists(rec_path):
                        with open(rec_path, "r", encoding="utf-8") as f:
                            back = (json.load(f) or {}).get("原来在哪") or ""
                except Exception:
                    back = ""
                if not back:
                    return self.err("这份回收站记录里没写原来在哪，还原不了（可以手动搬）")
                if os.path.exists(back):
                    return self.err("原来的位置已经被别的项目占了：%s —— 先给它改个名再还原" % back)
                try:
                    shutil.move(src, back)
                    try:
                        os.remove(os.path.join(back, "_删除记录.json"))
                    except OSError:
                        pass
                except Exception as e:
                    return self.err("还原不了：%s" % e)
                return self.json({"ok": True, "restored": back})

            if path == "/api/project/home":
                # 改「项目之家」（projects/ 所在那一层），并可顺手清空当前项目。
                # 以前只能手改 config.json —— 改完还得重启服务才认，很容易把自己绕进去。
                home = (body.get("base_root") or "").strip()
                if home:
                    home = os.path.abspath(home)
                    if not os.path.isdir(home):
                        return self.err("这个目录不存在：%s" % home)
                    cfg2 = paths.load_config()
                    cfg2["base_root"] = home
                    # 顺手清掉可能指向旧之家外面的当前项目（免得两边对不上）
                    cur = cfg2.get("project_root") or ""
                    if body.get("clear_project") or (cur and not cur.startswith(home)):
                        cfg2["project_root"] = ""
                    # 先落盘、再同步内存：顺序反过来的话，写盘会改 mtime，
                    # 下一次读配置又会把内存覆盖一遍（踩过）。
                    paths.save_config(cfg2)
                    with LOCK:
                        STATE["project_root"] = os.path.abspath(cfg2["project_root"]) \
                            if cfg2.get("project_root") else ""
                        try:
                            STATE["_cfg_mtime"] = os.path.getmtime(paths.CONFIG_FILE)
                        except OSError:
                            STATE["_cfg_mtime"] = None
                elif body.get("clear_project"):
                    cfg2 = paths.load_config()
                    cfg2["project_root"] = ""
                    paths.save_config(cfg2)
                    with LOCK:
                        STATE["project_root"] = ""
                        try:
                            STATE["_cfg_mtime"] = os.path.getmtime(paths.CONFIG_FILE)
                        except OSError:
                            STATE["_cfg_mtime"] = None
                blocks = registry.load_blocks()
                # 直接读配置回答，别再调 _cur_root() —— 那个会走一遍「同步内存」，
                # 有可能把刚设好的值又覆盖一次（接口自称的值必须是它刚设的那个）。
                now_root = paths.load_config().get("project_root") or ""
                return self.json({"ok": True, "base_root": base_root(),
                                  "current": os.path.abspath(now_root) if now_root else ""})

            if path == "/api/project/create":
                try:
                    proj = create_project(projects_parent(), body.get("name"))
                except ValueError as e:
                    return self.err(str(e))
                set_project(proj.root)
                blocks = registry.load_blocks()
                return self.json({"ok": True, "project": proj.summary(blocks)})

            # ---- 项目快照：存成一个文件 / 从文件还原现场 ----
            if path == "/api/project/export":
                from core import snapshot
                cfg = paths.load_config()
                dest = (body.get("dir") or cfg.get("export_dir") or "").strip()
                try:
                    info = snapshot.export(_cur_root(), dest,
                                           with_history=bool(body.get("with_history", True)))
                except ValueError as e:
                    return self.err(str(e))
                cfg["export_dir"] = info["dir"]
                paths.save_config(cfg)                 # 记住上次存到哪儿
                return self.json({"ok": True, "snapshot": info})

            if path == "/api/project/import":
                from core import snapshot
                if not raw:
                    return self.err("没收到文件内容")
                tmp = os.path.join(paths.JOBS_DIR, "_upload.urwproj")
                os.makedirs(os.path.dirname(tmp), exist_ok=True)
                with open(tmp, "wb") as f:
                    f.write(raw)
                try:
                    root, info = snapshot.import_snapshot(
                        tmp, projects_parent(),
                        name=(u.query and urllib.parse.parse_qs(u.query).get("name", [""])[0]) or "")
                except ValueError as e:
                    return self.err(str(e))
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                proj = set_project(root)
                blocks = registry.load_blocks()
                return self.json({"ok": True, "project": proj.summary(blocks),
                                  "snapshot": {k: v for k, v in info.items()
                                               if not k.startswith("_")}})

            if path == "/api/pick":
                # 弹原生选择框，把路径回填到输入框；dry_run 只把脚本还回来（自检用，不弹框）
                # kind: "dir" = 选文件夹；"file" / "anyfile" = 选文件（都走 OpenFileDialog）。
                #   ⚠ "anyfile" 只是**语义区分**：前端用它表示"我要绝对路径、别把文件拷进项目"
                #     （设置页选 SPSS 的 stats.exe 就是这种）。这里的行为和 "file" 一样。
                kind = body.get("kind") or "file"
                if kind not in ("dir", "file", "anyfile"):
                    kind = "file"
                title = body.get("title") or ("选择文件夹" if kind == "dir" else "选择文件")
                start = body.get("start") or ""
                filt = body.get("filter") or "所有文件 (*.*)|*.*"
                if body.get("probe"):
                    okp, why = probe_picker()
                    return self.json({"ok": True, "can_pick": okp, "why": why})
                if body.get("dry_run"):
                    return self.json({"ok": True, "script": _picker_script(kind, title, start, filt)})
                sel, err = run_picker(kind, title, start, filt)
                if err:
                    return self.err(err)
                # 顺手告诉前端这个路径在不在项目里 —— 在外面的话前端会问要不要拷进来
                rel, inside = "", False
                if sel:
                    try:
                        root = os.path.abspath(_cur_root())
                        p = os.path.abspath(sel)
                        if p == root or p.startswith(root + os.sep):
                            rel = os.path.relpath(p, root).replace("\\", "/")
                            inside = True
                    except Exception:
                        pass
                return self.json({"ok": True, "path": sel, "rel": rel, "inside": inside,
                                  "cancelled": not sel})

            if path == "/api/file/import":
                # 从项目外面挑来的文件，拷进项目里 ——
                # 一来引擎只认项目内相对路径，二来项目还能整体打包带走
                proj = current_project()
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                src = (body.get("src") or "").strip()
                if not src or not os.path.isfile(src):
                    return self.err("找不到这个文件：%s" % src)
                sub = body.get("sub") or "data"
                if sub not in ("data", "samples", "contracts", "output"):
                    sub = "data"
                d = proj.path(sub)
                os.makedirs(d, exist_ok=True)
                name = os.path.basename(src)
                dst = os.path.join(d, name)
                i = 2
                while os.path.exists(dst):
                    stem, ext = os.path.splitext(name)
                    dst = os.path.join(d, "%s(%d)%s" % (stem, i, ext))
                    i += 1
                shutil.copy2(src, dst)
                rel = os.path.relpath(dst, proj.root).replace("\\", "/")
                return self.json({"ok": True, "rel": rel, "size": os.path.getsize(dst),
                                  "from": src})

            if path == "/api/spss/state":
                # SPSS 面板要的信息：装了没、有没有可用的静默开关、现在开着几个
                from core import spss as spss_mod
                return self.json({"ok": True,
                                  "exe": spss_mod.find_exe(),
                                  "batch_args": spss_mod.get_args(),
                                  "syntax_encoding": spss_mod.syntax_encoding(),
                                  "running": spss_mod.stats_running()})

            if path == "/api/spss/probe":
                # 挨个试 SPSS 的批处理开关，看哪个能把语法真跑出输出文件（会启动 SPSS，慢）
                from core import spss as spss_mod
                return self.json(spss_mod.detect())

            if path == "/api/spss/launch":
                # 把语法丢给 SPSS 界面打开（不依赖任何命令行开关，这条路一定走得通）
                from core import spss as spss_mod
                proj = current_project()
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = body.get("rel") or ""
                html_rel = body.get("html") or ""
                try:
                    target = proj.safe(rel)
                except ValueError as e:
                    return self.err(str(e))
                if html_rel:
                    try:
                        spss_mod.prepare_syntax(target, proj.safe(html_rel))
                    except ValueError:
                        pass
                lr = spss_mod.open_syntax(spss_mod.find_exe(), target, autorun=True, force=True)
                return self.json({"ok": bool(lr.get("ok")), "error": lr.get("error") or ""})

            if path == "/api/spss/collect":
                # 看 SPSS 跑完没有、把导出的输出收回来
                from core import spss as spss_mod
                proj = current_project()
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                try:
                    p = proj.safe(body.get("rel") or "")
                except ValueError as e:
                    return self.err(str(e))
                ready, text = spss_mod.collect(p, since=body.get("since") or 0)
                out = {"ok": True, "ready": ready}
                if ready:
                    out["text"] = text
                    out["size"] = os.path.getsize(p)
                return self.json(out)

            if path == "/api/spss/open":
                # 把语法/输出丢给 SPSS 打开
                from core import spss as spss_mod
                proj = current_project()
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = body.get("rel") or ""
                if rel:
                    try:
                        target = proj.safe(rel)
                    except ValueError as e:
                        return self.err(str(e))
                else:
                    target = body.get("path") or ""
                ok, why = spss_mod.open_in_gui(spss_mod.find_exe(), target)
                return self.json({"ok": ok, "error": why})

            if path == "/api/reveal":
                # 本地小工具：在资源管理器里定位一个文件/文件夹
                target = (body.get("path") or "").strip()
                if not target or not os.path.exists(target):
                    return self.err("这个路径不存在：%s" % target)
                try:
                    if os.path.isdir(target):
                        subprocess.Popen(["explorer", os.path.normpath(target)])
                    else:
                        subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
                except Exception as e:
                    return self.err("打不开资源管理器：%s" % e)
                return self.json({"ok": True})

            if path == "/api/run":
                return self.api_run(body)

            if path == "/api/deident/ack":
                proj = current_project()
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                blocks = registry.load_blocks()
                block = registry.find(body.get("block_id") or "", blocks)
                r = guard.ack(proj.root, block, body.get("rels") or [], body.get("note") or "")
                return self.json(r) if r.get("ok") else self.err(r.get("error") or "记不下这次确认")

            if path == "/api/report/flag":
                # 标 / 取消标一个产物为「关键结果」。**研究员自己标，程序不猜。**
                proj = project_from_body(body)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                from core import report as report_mod
                r = report_mod.toggle_flag(proj, body.get("rel") or "",
                                           bool(body.get("on", True)),
                                           body.get("note") or "")
                return self.json(r) if r.get("ok") else self.err(r.get("error") or "标不上")
            if path == "/api/report/build":
                # 按固定骨架串一份汇总（只搬运 + 标来源，不写新结论）
                proj = project_from_body(body)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                from core import report as report_mod
                r = report_mod.write(proj, body.get("title") or "")
                return self.json(r)

            if path == "/api/version/label":
                # 给历史版本起个人话名字（只写旁挂的 json，不动历史文件）
                proj = project_from_body(body)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                from core import versioning
                r = versioning.set_label(proj, body.get("name") or "",
                                         body.get("label") or "", body.get("note") or "")
                return self.json(r) if r.get("ok") else self.err(r.get("error") or "打不上标签")

            if path == "/api/version/export":
                # 差异导出成 markdown 放进项目 output/，研究员可以在上面写「为什么改」
                proj = project_from_body(body)
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = body.get("rel") or ""
                a = body.get("a") or ""
                b = body.get("b") or ""
                from core import versioning
                d = versioning.diff_versions(proj, rel, a, b)
                if not d.get("ok"):
                    return self.err(d.get("error") or "对比不了")
                md = versioning.diff_to_markdown(rel, d)
                stem = os.path.splitext(os.path.basename(rel))[0]
                out_rel = "output/版本对比_%s_%s.md" % (stem, time.strftime("%Y%m%d_%H%M"))
                proj.write_text(out_rel, md)
                return self.json({"ok": True, "rel": out_rel})

            if path == "/api/vartable/parse":                # 把一段变量表文本（模型输出的 Markdown 表格、或人贴的一堆行）解析成逐行数据。
                # 必须走这个接口，别让前端自己劈：解析规则要和引擎**同一套**，
                # 否则界面上看到的变量和 ③ 出题用的变量会悄悄对不上。
                from core import kit
                rows = kit.parse_var_table(body.get("text") or "")
                return self.json({"ok": True, "rows": [list(r) for r in rows]})

            if path == "/api/job/cancel":
                ok = jobs.MANAGER.cancel(body.get("id") or "")
                return self.json({"ok": ok})

            if path == "/api/job/answer":
                ok = jobs.MANAGER.answer(body.get("id") or "", body.get("choice"))
                if not ok:
                    return self.err("这个任务现在不在等决定（可能已经跑完了）")
                return self.json({"ok": True})

            if path == "/api/job/rewind":
                # ⚠ 回退是「重跑一遍」，等于又起了一次任务 —— 守卫必须也管这里。
                #   不管的话，绕过方式就是：先跑一次、再回退，素材那道关等于不存在。
                #   检查放在真正回退**之前**：被拦下时旧任务不动，确认过了再回退。
                jid = body.get("id") or ""
                old = jobs.MANAGER.get(jid)
                if old and getattr(old, "block", None) and not body.get("confirmed_sensitive"):
                    g = guard.guard_for(old.block, os.path.abspath(old.project_root),
                                        dict(getattr(old, "params_raw", {}) or {}))
                    if g.get("need"):
                        return self.json({"ok": False, "need_guard": True, "guard": g})
                newjob = jobs.MANAGER.rewind(jid, body.get("upto") or 0)
                if not newjob:
                    return self.err("回退不了：这个任务没有可重跑的组块记录（可能是旧任务）")
                return self.json({"ok": True, "job_id": newjob.id})

            if path == "/api/file/save":
                proj = current_project()
                if proj is None:
                    return self.err(NO_PROJECT_MSG)
                rel = body.get("rel") or ""
                if not rel:
                    return self.err("缺 rel")
                p = proj.write_text(rel, body.get("text") or "")
                return self.json({"ok": True, "rel": rel, "path": p})

            if path == "/api/llm":
                from core import llm
                return self.json(llm.suggest(body))

            # ---------- ⚙ 设置面板 ----------
            if path == "/api/settings/save":
                from core import llm as llm_mod
                cfg = paths.load_config()
                data = body.get("settings") or {}
                what = []
                sp = data.get("spss") or {}
                if "exe" in sp:
                    exe = str(sp.get("exe") or "").strip().strip('"')
                    # 给了路径但文件不在 → 存下去没意义，还会让后面每次找都失败
                    if exe and not os.path.isfile(exe):
                        return self.err("这个路径下没有找到文件：\n%s\n\n"
                                        "确认一下是不是 stats.exe 的完整路径"
                                        "（在资源管理器里按住 Shift 右键它 →「复制文件地址」）。" % exe)
                    cfg["spss_exe"] = exe
                    what.append("SPSS 路径" + ("（清空了，改回自动探测）" if not exe else ""))
                ll = data.get("llm") or {}
                if ll:
                    cleaned = llm_mod.sanitize_llm_patch(ll)
                    if cleaned:
                        cfg.setdefault("llm", {}).update(cleaned)
                        if "api_key" in cleaned:
                            what.append("模型密钥（已更新）")
                        if "api_base" in cleaned or "api_model" in cleaned:
                            what.append("模型接口")
                        if "enabled" in cleaned:
                            what.append("模型通道" + ("打开" if cleaned["enabled"] else "关闭"))
                paths.save_config(cfg)
                return self.json({"ok": True, "saved": what, "settings": self.settings_state()})

            if path == "/api/llm/test":
                from core import llm
                return self.json(llm.test_api())

            if path == "/api/spss/apply":
                from core import spss as spss_mod
                cfg = paths.load_config()
                exe = spss_mod.find_exe(cfg)
                return self.json({"ok": bool(exe), "exe": exe,
                                  "candidates": spss_mod.spss_candidates(),
                                  "help": "" if exe else spss_mod.explain_not_found(cfg)})

            if path == "/api/config/save":
                from core import llm as llm_mod
                cfg = paths.load_config()
                data = body.get("config") or {}
                for k in ("python", "port", "spss_exe"):
                    if k in data:
                        cfg[k] = data[k]
                if "llm" in data:
                    # ⚠ 空密钥 = "别动它"，不是"清空它"。
                    #   界面上密钥那一栏永远是空的（我们只回显脱敏形态），
                    #   如果空串直接写进去，用户每次点保存都会把自己的密钥抹掉。
                    cfg["llm"].update(llm_mod.sanitize_llm_patch(data["llm"]))
                paths.save_config(cfg)
                # 端口下回启动才生效，这里只回存了什么
                return self.json({"ok": True, "config": cfg})

            return self.err("没有这个接口：%s" % path, 404)
        except Exception as e:
            traceback.print_exc()
            return self.err("%s: %s" % (type(e).__name__, e), 500)

    def api_run(self, body):
        block_id = body.get("block_id") or ""
        params = body.get("params") or {}
        blocks = registry.load_blocks()
        block = registry.find(block_id, blocks)
        if not block:
            return self.err("没有这个组块：%s" % block_id)
        # 没选项目就不许跑：产物总得有个地方落。
        # 以前这里会退回项目之家，于是产物落进历史目录、界面上还看不出哪里不对。
        root = body.get("project") or ""
        if not root:
            cur = current_project()
            root = getattr(cur, "root", "") if cur is not None else ""
        if not root or not _is_real_project(root):
            return self.err("还没选项目 —— 先在顶栏「新建」一个，或从下拉里选一个 / 点「打开…」选目录。"
                            "（产物要落在项目里，我不替你随便找个地方放。）")
        set_project(root)
        if not block.get("has_engine"):
            return self.err("「%s」还没有引擎文件，先在 blocks/%s/engine.py 里写实现"
                            % (block.get("name"), block.get("_module")))

        # 素材入口守卫：素材里有手机/邮箱/身份证这种直接标识符、又没过 🔒，就先摆到台面上。
        # 不是硬拦 —— 前端会显示「哪几份、命中什么」，研究员点「我知道，继续」再回来，
        # 那一句确认会落进项目目录（guard.ack）。
        if not body.get("confirmed_sensitive"):
            g = guard.guard_for(block, os.path.abspath(root), params)
            if g.get("need"):
                return self.json({"ok": False, "need_guard": True, "guard": g})

        job = jobs.MANAGER.start(block, params, os.path.abspath(root))
        return self.json({"ok": True, "job_id": job.id})


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #

def free_port(start):
    for p in range(start, start + 40):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            continue
        finally:
            try:
                s.close()
            except Exception:
                pass
    raise RuntimeError("8765 附近没有可用端口")


def main(argv):
    paths.ensure_dirs()
    cfg = paths.load_config()

    # ⚠ 以前这里**完全忽略命令行参数**（端口只从 config.json 读）。
    #   后果：`python server.py --port 8799` 会**静默**去听 8765 ——
    #   排查时探测 8799 一直连不上，会误判成"服务起不来"。
    #   静默忽略参数属于"看着生效了、其实没有"那一类坑，所以现在：
    #     · `--port N` 真的生效（临时覆盖 config，不写回文件）
    #     · 不认识的参数**明确报错退出**，别假装没看见
    want = int(cfg.get("port") or 8765)
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--port":
            if i + 1 >= len(argv):
                print("[x] --port 后面要跟端口号，例如： --port 8799")
                return 2
            try:
                want = int(argv[i + 1])
            except ValueError:
                print("[x] --port 后面要是数字，收到的是 %r" % argv[i + 1])
                return 2
            i += 2
            continue
        if a.startswith("--port="):
            try:
                want = int(a.split("=", 1)[1])
            except ValueError:
                print("[x] --port= 后面要是数字，收到的是 %r" % a)
                return 2
            i += 1
            continue
        if a == "--no-open":
            i += 1
            continue
        if a in ("-h", "--help"):
            print("用法： python server.py [--port N] [--no-open]")
            print("  --port N    换一个端口（默认取 config.json 里的 port，通常是 8765）")
            print("  --no-open   不要自动打开浏览器")
            return 0
        print("[x] 不认识的参数：%r" % a)
        print("    用法： python server.py [--port N] [--no-open]")
        print("    （以前这里会**默默忽略**，于是你以为换了端口、其实没有。）")
        return 2

    port = free_port(want)
    if port != want:
        # ⚠ 踩过的坑：曾经有个旧的 server 还占着 8765，新起的这个静默换到了 8766，
        #   结果浏览器/脚本连的还是旧进程、跑的还是旧代码，排查了半天。
        #   所以这里必须吼一声——而且要说清「谁占着」。
        holder = ""
        try:
            r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
            for line in (r.stdout or "").splitlines():
                if (":%d " % want) in line and "LISTENING" in line:
                    holder = line.split()[-1]
                    break
        except Exception:
            pass
        print("⚠ 端口 %d 已被占用%s，本次改用 %d。"
              % (want, ("（占用它的进程 PID %s）" % holder) if holder else "", port))
        print("  → 如果你以为是新代码在跑但行为不对，先确认没有旧的 server 进程。")
        print("  → 关掉旧进程的办法：Stop-Process -Id %s -Force" % (holder or "<PID>"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/" % port
    proj = current_project(cfg)
    print("=" * 62)
    print("  🐟 岚苔 Vesper · 用户研究工作台")
    print("  界面：  %s" % url)
    # 没选项目是**合法状态**（界面显示空栏），别在这里崩，也别拿项目之家冒充
    print("  项目：  %s" % (proj.root if proj is not None else "（还没选——在界面上「新建」或「打开…」）"))
    print("  引擎：  %s" % paths.engine_python(cfg))
    print("  关掉这个窗口 = 停止服务（不留后台常驻）")
    print("=" * 62)
    if "--no-open" not in argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n收到停止信号，关闭中…")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    # ⚠ 要把 main 的返回值当退出码用：参数写错时 `main` 返回 2，
    #   以前这里不接返回值 → 进程照样退 0，脚本/自检就看不出"没起来"。
    sys.exit(main(sys.argv[1:]))
