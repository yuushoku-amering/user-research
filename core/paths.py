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
    "spss_exe": r"D:\SPSS\stats.exe",
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


def detect_python():
    """挑一个能跑的 Python 当统计引擎。"""
    for p in CANDIDATE_PYTHONS:
        if os.path.exists(p):
            return p
    return sys.executable


def engine_python(cfg=None):
    cfg = cfg or load_config()
    p = cfg.get("python") or ""
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
