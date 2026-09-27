# -*- coding: utf-8 -*-
"""工作台 · 路径与运行环境

这是**唯一写死路径**的地方，其余模块都从这里取。

- 软件本体：  workbench/
- 第三方包：  workbench/libs/       （openpyxl 读 xlsx、pyreadstat 读 sav；装在明处，随时能删）
- 研究项目：  config.json 里的 project_root，默认 = workbench 的上一层（F:\\try\\用户研究）
"""
import json
import os
import sys
import tempfile

WORKBENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ...\用户研究\workbench
DEFAULT_PROJECT_ROOT = os.path.dirname(WORKBENCH)                          # ...\用户研究
LIBS = os.path.join(WORKBENCH, "libs")
WEB = os.path.join(WORKBENCH, "web")
BLOCKS_DIR = os.path.join(WORKBENCH, "blocks")
RUNNER = os.path.join(WORKBENCH, "runner.py")
CONFIG_FILE = os.path.join(WORKBENCH, "config.json")
JOBS_DIR = os.path.join(WORKBENCH, "_jobs")                                # 任务日志（可随时删）

# 本机可用的 Python（带 pandas / scipy / matplotlib）。按顺序探测，先命中先用。
CANDIDATE_PYTHONS = [
    r"D:\GPT-SoVITS\GPT-SoVITS-v2pro-20250604\runtime\python.exe",
    r"D:\ComfyUI_Windows_portable\python_standalone\python.exe",
]

DEFAULT_CONFIG = {
    "port": 8765,
    "host": "127.0.0.1",
    "python": "",                    # 留空 = 自动探测
    "project_root": "",              # 留空 = 还没选项目（界面显示空栏，不拿项目之家凑数）
    # ⚠ spss_exe 留空 = 自动探测常见安装位置（core/spss.py 的 _spss_roots）。
    #   这里**以前写的是本机路径** `D:\SPSS\stats.exe` —— 后果很实在：
    #   别人 clone 下来，这份默认值会被当成"用户自己的配置"，
    #   于是工作台永远指着一个不存在的文件，而对方看到的消息是
    #   「config.json 里的 spss_exe 指向的文件不存在」——
    #   他不知道要改、更不知道改成什么。
    #   默认值里**不许出现只有本机才成立的路径**。
    "spss_exe": "",
    "llm": {
        "enabled": False,            # 模型建议通道：默认关，界面上一键开
        "mode": "dsh-headless",      # 复用前辈的 DSH 凭据，走独立 DSH_HOME
        "dsh_home": "",
        "timeout": 240,
    },
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))     # 深拷贝
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if k == "llm" and isinstance(v, dict):
                    cfg["llm"].update(v)
                else:
                    cfg[k] = v
        except Exception as e:                        # 配置坏了不能让工作台起不来
            print("[warn] config.json 读不了，用默认值：%s" % e)
    # ⚠ **不要**在这里兜底填 project_root。
    #   原来这里有 `if not cfg.get("project_root"): cfg["project_root"] = DEFAULT_PROJECT_ROOT`，
    #   看着是"别让配置空着"，实际后果是：**「没选项目」在配置文件层面根本表达不出来** ——
    #   清空之后一读又变回项目之家，界面于是把历史目录当项目用，产物落错地方还看不出来。
    #   空就是空；要表达"没选项目"就让它空着，由界面显示空栏（见 server.current_project）。
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def resolve_python_path(p):
    """把配置里的 `python` 变成一个能 `os.path.exists` 的路径。

    ⚠ **相对路径按 `WORKBENCH` 目录解析，不是按当前工作目录**（2026-09-27 便携版踩的）：
      便携包里 config.json 写的是 `..\\_python\\python.exe`（相对 workbench 的上一层），
      而原来的 `os.path.exists(p)` 是**按进程 cwd** 算的 —— 服务从别处启动时那个相对路径
      指向了完全不同的地方 → 判定"不存在" → **静默回退成自动探测**
      → 用的是这台电脑上碰巧装着的另一个 Python。
      表现：便携版跑起来了，但 `env.python` 报的是别人机器的路径（真发生过）。
    """
    p = (p or "").strip().strip('"')
    if not p:
        return ""
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(WORKBENCH, p))


def bundled_python():
    """便携版自带的那只 Python：`<发布根>\\_python\\python.exe`。

    发布包会把工作台放在 `<发布根>\\岚苔Vesper\\`，Python 放在 `<发布根>\\_python\\`，
    所以从 workbench 往上一层的 `_python` 就是它。
    **存在就优先用它** —— 便携版的全部意义就是"不依赖用户机器上装了什么"。
    """
    p = os.path.normpath(os.path.join(WORKBENCH, "..", "_python", "python.exe"))
    return p if os.path.isfile(p) else ""


def detect_python():
    """挑一个能跑的 Python 当统计引擎。"""
    b = bundled_python()                      # 便携版自带的排最前：它一定是对的
    if b:
        return b
    for p in CANDIDATE_PYTHONS:
        if os.path.exists(p):
            return p
    return sys.executable


def can_import(module, py=None):
    """引擎 Python 到底能不能用这个模块。

    ⚠ 为什么要两个判据合起来（2026-09-27 便携版踩了两头）：
      ① 老写法 `os.path.isdir(LIBS/openpyxl)` —— 那是"包被塞进 workbench\\libs\\"的做法。
         便携版把整只 Python 带走、包装在 site-packages 里、**`libs/` 压根不存在**，
         于是界面报「导入 缺包」，而它明明能 import（误报"坏"）。
      ② 只改成"真的 import 一次" —— 反过来又会误报：本机这只嵌入式 Python
         （GPT-SoVITS runtime）带 `python39._pth`，**它会忽略 PYTHONPATH**，
         而 `libs/` 正是靠 PYTHONPATH 挂进去的 → 子进程看不到 libs 里的 openpyxl（误报"缺"）。
    ⇒ **两个都算数**：谁认了就算有。
    """
    import subprocess
    py = py or engine_python()
    # 判据一：libs 目录里真有这个包（嵌入式 Python + PYTHONPATH 那条路）
    try:
        if os.path.isdir(os.path.join(LIBS, module)):
            return True
    except Exception:
        pass
    # 判据二：让引擎 Python 自己去 import（site-packages 那条路，便携版走这条）
    if not py:
        return False
    code = ("import importlib.util,sys;"
            "sys.exit(0 if importlib.util.find_spec(%r) else 1)" % module)
    env = child_env()
    try:
        r = subprocess.run([py, "-c", code], env=env, timeout=25,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def engine_python(cfg=None):
    cfg = cfg or load_config()
    p = resolve_python_path(cfg.get("python"))
    if p and os.path.exists(p):
        return p
    return detect_python()


def child_env():
    """给引擎子进程的环境：把 libs 挂进 PYTHONPATH，别的都照旧。"""
    env = dict(os.environ)
    old = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = LIBS + (os.pathsep + old if old else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["MPLBACKEND"] = "Agg"
    return env


def is_temp_path(path):
    """这个路径在**系统临时目录**里吗？（临时目录里的东西随时会被清掉，不能记进配置）

    ⚠ 为什么单列一个函数：踩过一次很隐蔽的坑 ——
      `_apitest.py` 第 7 步为了验"回退也要过脱敏守卫"，在一个**临时项目**上跑了一次 ⑤，
      而 `/api/run` 会走 `set_project()`，`set_project()` 又**顺手把当前项目记进 config.json**。
      于是磁盘上的配置变成了
        `C:\\Users\\…\\Temp\\dsh-XXXX\\urw_rewind_q1ff4kkj`
      —— 那个目录是 apitest 自己 `shutil.rmtree` 删掉的。下次启动：

        1. 配置里记着的项目不存在 → 界面顶着红条「记着的项目不见了」、**项目栏是空的**
        2. 更要紧的是：**研究员上一次真正在用的那个项目被静默挤掉了**，
           他得自己再去下拉里找回来，而且完全不知道为什么

      临时目录里的项目**天生就是一次性的**，记它没有任何意义。
      规矩：**`set_project()` 不把临时目录里的项目写进配置**（本次会话照常能用）。
    """
    try:
        t = os.path.normcase(os.path.abspath(path or ""))
        base = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
    except Exception:
        return False
    if not t or not base:
        return False
    return t == base or t.startswith(base + os.sep)


def ensure_dirs():
    for d in (LIBS, JOBS_DIR):
        os.makedirs(d, exist_ok=True)
