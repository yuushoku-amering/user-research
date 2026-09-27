# -*- coding: utf-8 -*-
"""工作台 · 模型建议通道

「**模型给初稿 → 研究员在界面上改 → 再跑**」。

走 DSH 的 headless 模式 + **独立 DSH_HOME**：
- 复用前辈已经在用的凭据（**只读，不复制**，注入环境变量）
- 不往前辈的会话栏里堆记录（那条是《完全权限规范》里的硬要求）

⚠ 两个关键点（都是踩过的）：
1. headless 的任务文本只能走命令行，而 Windows 命令行装不下几十 KB。
   → 所以这里把材料**写成临时文件**，命令行只传一句「读这个文件、按里面要求做」，
     模型自己用 read 工具去读，结果从 stdout 回来。
2. 任务文本里的中文路径要当**独立的参数**传（列表形式），别自己拼字符串。

⚠ 默认关闭。不打开也能用：所有组块都能脱离模型完整跑通。
"""
import os
import re
import shutil
import subprocess
import time

from . import paths, registry
from .project import Project

DEFAULT_HOME = os.path.join(paths.WORKBENCH, "dsh-home")
CRED_FILE = os.path.join(os.path.expanduser("~"), ".dsh", ".credentials.yaml")
MAX_MATERIAL_CHARS = 20000        # 单个材料文件最多喂这么多字
_NODE_FALLBACK = r"F:\New Folder\node.exe"


# --------------------------------------------------------------------------- #
# 环境探测
# --------------------------------------------------------------------------- #

def find_node():
    p = shutil.which("node")
    if p:
        return p
    return _NODE_FALLBACK if os.path.exists(_NODE_FALLBACK) else ""


def find_dsh_bin():
    """在 npx 缓存里找 DSH 的 bin.js（DSH 是 npx 自动升级的，所以按修改时间取最新的）。"""
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "npm-cache", "_npx")
    cands = []
    if os.path.isdir(base):
        for d in os.listdir(base):
            p = os.path.join(base, d, "node_modules", "@deepseek-ai", "dsh", "lib", "bin.js")
            if os.path.exists(p):
                cands.append((os.path.getmtime(p), p))
    cands.sort(reverse=True)
    return cands[0][1] if cands else ""


def read_key():
    """从前辈的凭据文件里取 DEEPSEEK_API_KEY。

    **只读、不复制、不打印、不外传。** 环境变量优先（和 dsh-credentials-local 的层叠顺序一致）。
    """
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    try:
        with open(CRED_FILE, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("DEEPSEEK_API_KEY:"):
                    v = s.split(":", 1)[1].strip().strip("'\"")
                    if v:
                        return v
    except Exception:
        pass
    return ""


def dsh_home(cfg=None):
    cfg = cfg or paths.load_config()
    return (cfg.get("llm") or {}).get("dsh_home") or DEFAULT_HOME


def status(cfg=None):
    cfg = cfg or paths.load_config()
    llm = cfg.get("llm") or {}
    home = dsh_home(cfg)
    node = find_node()
    binjs = find_dsh_bin()
    key = read_key()
    ready = bool(node and binjs and key and os.path.isdir(home))
    return {
        "enabled": bool(llm.get("enabled")),
        "ready": ready,
        "node": node,
        "dsh_bin": binjs,
        "dsh_home": home,
        "dsh_home_exists": os.path.isdir(home),
        "key_found": bool(key),
        "model": llm.get("model") or "deepseek-flash",
        "note": ("就绪" if ready else
                 "缺：" + "、".join([x for x, ok in
                                    (("node", bool(node)), ("DSH bin", bool(binjs)),
                                     ("凭据", bool(key)), ("dsh-home", os.path.isdir(home))) if not ok])),
    }


# --------------------------------------------------------------------------- #
# 组装任务
# --------------------------------------------------------------------------- #

def _build_prompt_file(block, params, project_root):
    """把「提示词 + 材料 + 界面填写内容」写成一份任务书，返回路径。"""
    spec = block.get("llm") or {}
    proj = Project(project_root)
    labels = {f.get("key"): f.get("label", f.get("key")) for f in (block.get("form") or [])}

    L = []
    # ⚠ 任务书抬头同样保持「用户研究工作台」（理由见 core/report.py 那处注释）
    L.append("# 任务书（由用户研究工作台自动生成）\n")
    L.append("## 【任务】\n")
    L.append(spec.get("prompt", "").strip())
    L.append("")

    L.append("## 【研究员在界面上填的内容】\n")
    any_param = False
    for k, v in (params or {}).items():
        if v in ("", None, [], {}):
            continue
        if k in ("project_root", "block_dir", "block_id"):
            continue
        if isinstance(v, list):
            v = "、".join(str(x) for x in v)
        L.append("- **%s**：%s" % (labels.get(k, k), v))
        any_param = True
    if not any_param:
        L.append("（界面上的表单还是空的——那就只依据下面的材料做）")
    L.append("")

    mats = spec.get("materials") or []
    if mats:
        L.append("## 【材料】\n")
        for rel in mats:
            txt = proj.read_text(rel)
            if not txt.strip():
                L.append("### %s\n（文件不存在或为空）\n" % rel)
                continue
            if len(txt) > MAX_MATERIAL_CHARS:
                txt = txt[:MAX_MATERIAL_CHARS] + "\n\n…（内容过长已截断）"
            L.append("### 文件：%s\n" % rel)
            L.append("```")
            L.append(txt.strip())
            L.append("```")
            L.append("")

    L.append("## 【输出要求】\n")
    L.append(spec.get("output_rules",
                      "- 直接输出最终内容（Markdown），不要前言、不要解释你打算怎么做。\n"
                      "- 不要写文件、不要跑命令、不要反问。"))
    L.append("")

    # 组块如果声明了「输出小节 → 表单字段」的映射，就让模型严格按小节写，
    # 后端好按小节切回来、一键填进表单（不然研究员只能对着十几个输入框手工搬）。
    ofields = spec.get("output_fields") or []
    if ofields:
        L.append("## 【必须按小节输出】\n")
        L.append("下面这几节是**会被一键填回界面表单**的，标题请原样照抄，用二级标题 `## ` 开头，")
        L.append("顺序不要变、不要合并、不要改名。**标题前带序号也可以**"
                 "（写成 `## 1. 背景与业务问题` 一样能对上，切分时会忽略序号）。\n")
        for f in ofields:
            L.append("## %s" % f.get("title"))
            if f.get("hint"):
                L.append("（%s）" % f["hint"])
            L.append("")
        L.append("如果上面的【任务】里还要求了别的小节，那些也照写，排在后面就行。")
        L.append("除此之外不要输出任何别的东西——不要前言、不要总结、不要额外的说明段落。")
        L.append("")
    L.append("## 【信息不足时怎么写】\n")
    L.append("**不要编**。凡是材料里没给、你也不确定的地方，写成 `（待确认：要确认的是什么）`：\n")
    L.append("")
    L.append("- 好：`目标人群：（待确认：是只招付费用户，还是全体用户？）`")
    L.append("- 好：`假设：（待确认：这条假设有数据能检验吗？）`")
    L.append("- 差：`目标人群：25-35 岁一线城市白领` ← 材料里没有，这是编的")
    L.append("")
    L.append("工作台会把每一条「（待确认：…）」收进研究员界面右边的**待确认项侧栏**，"
             "他可以一条条填掉。所以：**该确认的地方就大方地留成待确认，别硬凑**。")
    L.append("")

    L.append("> 本轮你只需要读这一份任务书，然后把结果作为最终答复输出。")

    os.makedirs(os.path.join(paths.JOBS_DIR, "llm"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = os.path.join(paths.JOBS_DIR, "llm", "task_%s_%s.md" % (block.get("id", "x"), stamp))
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    return p


# --------------------------------------------------------------------------- #
# 调 DSH headless
# --------------------------------------------------------------------------- #

def _run_headless(task, cfg, timeout):
    node = find_node()
    binjs = find_dsh_bin()
    home = dsh_home(cfg)
    key = read_key()
    if not node or not binjs:
        raise RuntimeError("找不到 node 或 DSH 的 bin.js")
    if not key:
        raise RuntimeError("没找到 DEEPSEEK_API_KEY（看 ~/.dsh/.credentials.yaml）")

    env = dict(os.environ)
    env["DSH_HOME"] = home                    # 独立 home：会话不会进前辈的列表
    env["DSH_SHELL"] = ""
    env["DEEPSEEK_API_KEY"] = key
    env["PYTHONIOENCODING"] = "utf-8"

    # ⚠ 任务文本当独立参数传，别自己拼字符串（中文路径 + 空格会踩坑）
    cmd = [node, binjs, "--profile", "headless", task]
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=paths.WORKBENCH, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise RuntimeError("模型超时（%d 秒）——材料太长或网络慢，可以把 timeout 调大" % timeout)

    text = (out or b"").decode("utf-8", "replace").strip()
    errs = (err or b"").decode("utf-8", "replace").strip()
    return text, errs, round(time.time() - t0, 1), proc.returncode


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #

_NUM_PREFIX = re.compile(
    r"^\s*[（(【\[]?\s*(?:\d{1,2}|[一二三四五六七八九十]{1,2})\s*[)）】\]]?\s*"
    r"(?:[.、,，:：)）]\s*|\s+)")


def _norm_head(s):
    """把标题归一化：去掉 #、*、编号（`1.`/`一、`/`（2）`）、结尾的冒号句号。

    踩过一次：提示词正文里让模型写 `## 1. 背景与业务问题`，切分器却按
    `背景与业务问题` 精确匹配 → 一个小节都没切出来，「⤵ 填回表单」按钮直接消失。
    """
    s = str(s if s is not None else "").strip()
    prev = None
    while prev != s:                      # 「## 1. **背景…**」这种套娃，剥到不动为止
        prev = s
        s = s.strip("#*_ 　\t")
        s = _NUM_PREFIX.sub("", s)
    s = re.sub(r"[\s：:。.、,，]+$", "", s)
    return s.strip()


def _split_fields(text, ofields):
    """按声明的小节标题，把模型的整段输出切回表单字段。

    容错：标题写成 `###` / `**加粗**` / 带编号 / 前后有空格，都认。
    切不到的小节干脆不返回，前端会告诉研究员「这几项没解析出来」。
    """
    out = {}
    if not ofields:
        return out
    want = []
    for f in ofields:
        t = _norm_head(f.get("title"))
        if t:
            want.append((t, f.get("key")))
    if not want:
        return out

    lines = str(text or "").replace("\r", "").split("\n")
    heads = []                            # [(行号, 归一化后的标题)]
    bounds = []                           # 任何 `#`/`##` 级标题都算「这里换节了」
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or len(s) > 80:
            continue
        if s.startswith("#") or re.match(r"^\*\*[^*]+\*\*[:：]?$", s):
            h = _norm_head(s)
            if h:
                heads.append((i, h))
            lvl = len(s) - len(s.lstrip("#"))
            if not s.startswith("#") or lvl <= 2:
                bounds.append(i)

    # 先精确匹配（避免「研究目的」和「一句话研究目的」这种互相包含的标题抢位置）
    pairs, used = {}, {}
    for t, k in want:
        for i, h in heads:
            if h == t and i not in used:
                pairs[k] = i
                used[i] = k
                break
    # 再放宽：允许标题带尾巴（「研究目的（为什么做）」）或只写了个开头
    for t, k in want:
        if k in pairs or not k:
            continue
        for i, h in heads:
            if i in used:
                continue
            if h.startswith(t) or (len(h) >= 3 and t.startswith(h)):
                pairs[k] = i
                used[i] = k
                break

    # ⚠ 一节的内容必须在「下一个任何级别的 ## 标题」处断开 ——
    #   否则模型多写的、没声明成字段的小节会被整段塞进上一个字段里
    #   （踩过：⓪ 的「7. 数据条件 / 8. 分析思路」被吞进「6. 关键变量」，变量表全烂了）
    marks = sorted((i, k) for k, i in pairs.items())
    for n, (i, key) in enumerate(marks):
        limit = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
        stop = next((b for b in bounds if b > i), None)
        if stop is not None:
            limit = min(limit, stop)
        val = "\n".join(lines[i + 1:limit]).strip()
        val = re.sub(r"^```[a-zA-Z]*\s*", "", val)          # 去掉模型爱加的代码块围栏
        val = re.sub(r"\s*```$", "", val).strip()
        if val and key:
            out[key] = val
    return out


def suggest(body):
    cfg = paths.load_config()
    llm = cfg.get("llm") or {}
    if not llm.get("enabled"):
        return {"ok": False, "skeleton": True,
                "error": "模型通道现在关着。打开方式：改 workbench\\config.json 里 llm.enabled = true，"
                         "或在界面右上角点「模型 关」。\n\n不打开也完全能用——七个组块都能脱离模型跑通。",
                "status": status(cfg)}

    block_id = body.get("block_id") or ""
    params = body.get("params") or {}
    # 没选项目就报错，别拿项目之家凑数（和分组块同一条规矩）
    project_root = body.get("project") or (cfg.get("project_root") or "")
    if not project_root:
        return {"ok": False, "error": "还没选项目 —— 先在顶栏「新建」一个，或从下拉里选一个。"}

    blocks = registry.load_blocks()
    block = registry.find(block_id, blocks)
    if not block:
        return {"ok": False, "error": "没有这个组块：%s" % block_id}
    if not (block.get("llm") or {}).get("prompt"):
        return {"ok": False,
                "error": "「%s」还没配模型提示词——这个组块的活本来也不该交给模型。"
                         % block.get("name", block_id),
                "status": status(cfg)}

    st = status(cfg)
    if not st["ready"]:
        return {"ok": False, "error": "模型通道还没就绪：%s" % st["note"], "status": st}

    try:
        task_file = _build_prompt_file(block, params, project_root)
    except Exception as e:
        return {"ok": False, "error": "组装任务书失败：%s" % e, "status": st}

    task = ("读文件 %s ，严格按里面的【任务】和【输出要求】执行，"
            "把结果直接作为你的最终答复输出。不要写文件、不要跑命令、不要反问。" % task_file)

    try:
        text, errs, secs, code = _run_headless(task, cfg, int(llm.get("timeout") or 240))
    except Exception as e:
        return {"ok": False, "error": str(e), "status": st, "task_file": task_file}

    if not text:
        return {"ok": False,
                "error": "模型没有输出（退出码 %s）。stderr 末尾：%s"
                         % (code, " | ".join(errs.splitlines()[-3:]) or "（空）"),
                "status": st, "task_file": task_file}

    ofields = (block.get("llm") or {}).get("output_fields") or []
    fields = _split_fields(text, ofields)
    missing = [f.get("title") for f in ofields if f.get("key") not in fields]

    # 把模型的原始输出留档：刷新页面 / 重启服务之后还能翻回来照抄，
    # 不至于「模型跑了半分钟，一刷新就没了」
    out_file = ""
    try:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_file = os.path.join(paths.JOBS_DIR, "llm", "out_%s_%s.md" % (block_id, stamp))
        with open(out_file, "w", encoding="utf-8", newline="\n") as f:
            f.write("<!-- 模型：%s · 组块：%s · %s -->\n\n" % (st["model"], block_id,
                                                              time.strftime("%Y-%m-%d %H:%M")))
            f.write(text)
    except Exception as e:
        print("[warn] 模型输出留档失败：%s" % e)

    return {
        "ok": True,
        "text": text,
        "out_file": out_file,
        "fields": fields,
        "fields_meta": [{"key": f.get("key"), "title": f.get("title"),
                         "label": f.get("label") or f.get("title")} for f in ofields],
        "missing_fields": missing,
        "block_id": block_id,
        "block_name": block.get("name"),
        "title": (block.get("llm") or {}).get("title") or "模型初稿",
        "model": st["model"],
        "seconds": secs,
        "task_file": task_file,
        "note": "这是**初稿**：请自己过一遍再决定要不要用。模型不做算术，数字仍由 Python 产生。",
    }
