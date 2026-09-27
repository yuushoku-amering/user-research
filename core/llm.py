# -*- coding: utf-8 -*-
"""工作台 · 模型建议通道

「**模型给初稿 → 研究员在界面上改 → 再跑**」。

**两条路，自己选**（2026-09-27 加的第二条）：

1. **自带 API（推荐给普通用户）** —— 在界面「⚙ 设置」里填三样东西：
   接口地址 / 密钥 / 型号，然后点「测试连接」。走的是**标准 OpenAI 兼容**的
   `POST {api_base}/chat/completions`，所以 DeepSeek、硅基流动、智谱、本地
   Ollama / vLLM 都能填。**密钥只写在这台机器的 `config.json` 里**
   （那个文件在 `.gitignore` 里，不会进仓库），界面上读回来只显示"已设置"。

2. **复用 DSH headless**（原来那条，留着自己用） —— 找 npx 缓存里的 DSH、
   从 `~/.dsh/.credentials.yaml` 读凭据（**只读、不复制、不打印**），
   用 node 跑 headless，会话写进独立的 DSH_HOME（不堆进用户的会话栏）。

3. **不配也行** —— 所有组块都能脱离模型完整跑通。缺模型时界面会给
   「把任务书复制走 → 贴到任意聊天窗口 → 结果贴回来」这条零配置的路。

⚠ 两个关键点（都是踩过的）：
1. DSH 那条路的任务文本只能走命令行，而 Windows 命令行装不下几十 KB。
   → 所以把材料**写成临时文件**，命令行只传一句「读这个文件、按里面要求做」。
   （API 那条路没这个限制，整份任务书直接作为消息内容发出去。）
2. 任务文本里的中文路径要当**独立的参数**传（列表形式），别自己拼字符串。

⚠ 默认关闭。
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from . import paths, registry
from .project import Project

DEFAULT_HOME = os.path.join(paths.WORKBENCH, "dsh-home")
CRED_FILE = os.path.join(os.path.expanduser("~"), ".dsh", ".credentials.yaml")
MAX_MATERIAL_CHARS = 20000        # 单个材料文件最多喂这么多字
_NODE_FALLBACK = r"F:\New Folder\node.exe"

# 常见的 OpenAI 兼容端点：只作为「填空提示」，用户想填什么就填什么
API_BASE_HINTS = [
    ("https://api.deepseek.com/v1", "DeepSeek"),
    ("https://api.siliconflow.cn/v1", "硅基流动"),
    ("https://open.bigmodel.cn/api/paas/v4", "智谱 GLM"),
    ("http://127.0.0.1:11434/v1", "本地 Ollama"),
]
DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_API_MODEL = "deepseek-chat"


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


# --------------------------------------------------------------------------- #
# 「自带 API」那条路：配置读取与安全检查
# --------------------------------------------------------------------------- #

def api_conf(cfg=None):
    """把 llm 里跟 API 有关的几项读出来（键名固定，界面就填这几个）。"""
    llm = (cfg or paths.load_config()).get("llm") or {}
    return {
        "base": (llm.get("api_base") or "").strip(),
        "key": (llm.get("api_key") or "").strip(),
        "model": (llm.get("api_model") or "").strip(),
    }


def mask_key(k):
    """给界面看的脱敏形式：**绝不能把密钥原文发回前端**。

    只留头 3 位与尾 2 位；太短就整段打码（短密钥露头尾等于露大半）。
    """
    k = (k or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "•" * len(k)
    return k[:3] + "…" + "•" * 6 + k[-2:]


def public_conf(cfg=None):
    """**发给浏览器的 llm 配置**：密钥换成"设没设 + 脱敏形态"。

    ⚠ 为什么要有这个函数：`/api/state` 原来是把 `cfg["llm"]` **整个**发给前端的
      （`"llm": cfg.get("llm")`）。以前 llm 里只有 dsh_home / model 这类不敏感的东西，
      所以没问题；但现在多了 `api_key` —— 再整份发出去，**密钥原文就躺在浏览器里了**
      （会被写进页面状态、可能进浏览器缓存、任何人按 F12 都能看到）。
      ⇒ 规则：**凡是"往界面发的配置"，一律过这个函数**，别直接发 cfg["llm"]。
    """
    llm = dict((cfg or paths.load_config()).get("llm") or {})
    key = (llm.pop("api_key", "") or "").strip()
    llm["api_key"] = ""                    # 原文绝不外发，位置留着，前端知道有这一栏
    llm["api_key_set"] = bool(key)
    llm["api_key_mask"] = mask_key(key)
    return llm


# 界面允许改的 llm 键（白名单：别让人从接口往配置里塞任意东西）
LLM_WRITABLE = ("enabled", "provider", "api_base", "api_key", "api_model", "timeout", "model")


def sanitize_llm_patch(patch):
    """把界面发来的 llm 片段清洗成"能安全写进 config"的样子。

    两条规矩：
    1. **只认白名单里的键** —— 其它键一律丢掉（不然接口能往配置里塞任意东西）。
    2. **`api_key` 是空串时整条丢掉** —— 意思是"别动它"，而不是"清空它"。
       界面上密钥那栏永远是空的（我们只回显脱敏形态），
       如果空串直接写进去，用户每点一次保存就把自己的密钥抹掉了。
       真要清空：把 `api_key` 显式写成 `null`。
    """
    out = {}
    for k in LLM_WRITABLE:
        if k not in patch:
            continue
        v = patch[k]
        if k == "api_key":
            if v is None:
                out[k] = ""            # 显式清空
            elif str(v).strip():
                out[k] = str(v).strip()
            # 空串 / 全是空白 → 丢掉这一条，保留原来的密钥
            continue
        if k == "enabled":
            out[k] = bool(v)
        elif k == "timeout":
            try:
                t = int(v)
            except (TypeError, ValueError):
                continue
            out[k] = max(10, min(1800, t))     # 10 秒 ~ 30 分钟，别让人填出 0 或天文数字
        elif k in ("api_base", "api_model", "model", "provider"):
            out[k] = str(v or "").strip()
        else:
            out[k] = v
    return out


def api_ready(cfg=None):
    c = api_conf(cfg)
    return bool(c["base"] and c["key"] and c["model"])


def _api_chat(base, key, model, messages, timeout=240, max_tokens=None):
    """标准 OpenAI 兼容的 chat/completions 调用。**只用标准库**（不引入 requests）。

    返回 (正文, 秒数)。出错抛 RuntimeError，消息是给人看的人话。
    """
    url = base.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    payload = {"model": model, "messages": messages, "stream": False}
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # ⚠ 走系统代理（Clash 之类）时会用到这两个环境变量；urllib 默认会读它们，
    #   这里不用手动处理，但**HTTP_PROXY 大小写两版都要在**（有的库只认一种）。
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("User-Agent", "LanTai-Vesper/1.0")

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        human = {
            401: "密钥不对或没带上（HTTP 401）。检查「密钥」那一栏是不是复制全了。",
            403: "密钥没有这个模型的权限（HTTP 403）。看看「型号」写对了没。",
            404: "接口地址不对（HTTP 404）。注意地址要写到 /v1 这一层。",
            429: "被限流了（HTTP 429）。等一会儿再试，或换个型号。",
        }.get(e.code, "接口返回 HTTP %d。" % e.code)
        raise RuntimeError("%s\n服务端说：%s" % (human, detail or "(没给内容)"))
    except urllib.error.URLError as e:
        raise RuntimeError(
            "连不上这个地址：%s\n"
            "常见原因：地址写错、没开代理、或者这台机器出不去网。\n"
            "（本机 curl 是坏的，但 Python 走的是另一条路，所以别拿 curl 成不成功来判断。）"
            % (getattr(e, "reason", e),))
    except Exception as e:
        raise RuntimeError("调用失败：%s: %s" % (type(e).__name__, e))
    secs = round(time.time() - t0, 1)

    try:
        j = json.loads(raw)
    except Exception:
        raise RuntimeError("返回的不是 JSON，前 300 字：%s" % raw[:300])
    if isinstance(j, dict) and j.get("error"):
        err = j["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError("接口报错：%s" % (msg or err))
    try:
        return j["choices"][0]["message"]["content"], secs
    except Exception:
        raise RuntimeError("返回结构里没有 choices[0].message.content，前 300 字：%s" % raw[:300])


def test_api(cfg=None, timeout=30):
    """「测试连接」：发一句最短的话，只要它能回就说明三样都填对了。

    ⚠ 这里**故意不回显密钥**，也不把服务端返回的原文整段吐出去
      （有的服务端会在报错里带上你的 key）。
    """
    cfg = cfg or paths.load_config()
    c = api_conf(cfg)
    if not c["base"]:
        return {"ok": False, "error": "还没填「接口地址」。"}
    if not c["key"]:
        return {"ok": False, "error": "还没填「密钥」。"}
    if not c["model"]:
        return {"ok": False, "error": "还没填「型号」。"}
    try:
        text, secs = _api_chat(c["base"], c["key"], c["model"],
                               [{"role": "user", "content": "只回两个字：收到"}],
                               timeout=timeout, max_tokens=16)
    except Exception as e:
        return {"ok": False, "error": str(e), "model": c["model"]}
    return {"ok": True, "model": c["model"], "seconds": secs,
            "reply": (text or "").strip()[:60]}


def status(cfg=None):
    """界面用它决定「模型」那个 chip 是什么颜色、点开能不能用。

    ⚠ 这里**只报"密钥设没设"，绝不返回密钥本身**（`mask_key` 给的是脱敏形态）。
    """
    cfg = cfg or paths.load_config()
    llm = cfg.get("llm") or {}
    home = dsh_home(cfg)
    node = find_node()
    binjs = find_dsh_bin()
    key = read_key()
    dsh_ok = bool(node and binjs and key and os.path.isdir(home))

    c = api_conf(cfg)
    api_ok = bool(c["base"] and c["key"] and c["model"])

    # 优先用「自带 API」：它不需要 node / DSH，普通用户只用填三个框
    ready = api_ok or dsh_ok
    if api_ok:
        which, model = "api", c["model"]
        note = "就绪（自带 API：%s）" % c["model"]
    elif dsh_ok:
        which, model = "dsh", (llm.get("model") or "deepseek-flash")
        note = "就绪（复用 DSH：%s）" % model
    else:
        which, model = "", (c["model"] or llm.get("model") or DEFAULT_API_MODEL)
        miss = []
        if not api_ok:
            miss.append("自带 API（去「⚙ 设置」填地址/密钥/型号）")
        if not dsh_ok:
            dsh_miss = [x for x, ok in (("node", bool(node)), ("DSH bin", bool(binjs)),
                                        ("凭据", bool(key)), ("dsh-home", os.path.isdir(home))) if not ok]
            miss.append("DSH（缺 %s）" % "、".join(dsh_miss) if dsh_miss else "DSH")
        note = "两条路都还没就绪 —— " + "；".join(miss)
    return {
        "enabled": bool(llm.get("enabled")),
        "ready": ready,
        "provider": which,                 # "api" | "dsh" | ""
        "node": node,
        "dsh_bin": binjs,
        "dsh_home": home,
        "dsh_home_exists": os.path.isdir(home),
        "key_found": bool(key),            # DSH 那条路的凭据文件
        # 自带 API 的现状：**给界面看的，密钥只给脱敏形态**
        "api_base": c["base"],
        "api_model": c["model"],
        "api_key_set": bool(c["key"]),
        "api_key_mask": mask_key(c["key"]),
        "model": model,
        "note": note,
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


def pick_provider(cfg=None):
    """用哪条路：**自带 API 优先**（它不需要 node / DSH，普通用户只用填三个框）。

    返回 "api" / "dsh" / ""（两条都不行）。
    """
    cfg = cfg or paths.load_config()
    if api_ready(cfg):
        return "api"
    st = status(cfg)
    return "dsh" if st["ready"] else ""


def suggest(body):
    cfg = paths.load_config()
    llm = cfg.get("llm") or {}
    if not llm.get("enabled"):
        return {"ok": False, "skeleton": True,
                "error": "模型通道现在关着。打开方式：点界面右上角的「模型」chip，"
                         "或在「⚙ 设置」里打开。\n\n不打开也完全能用——所有组块都能脱离模型跑通。",
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

    prov = pick_provider(cfg)
    timeout = int(llm.get("timeout") or 240)
    try:
        if prov == "api":
            # ⚠ API 这条路**没有命令行的长度限制**，所以任务书整份当消息发出去，
            #   不像 DSH 那条路要「先写文件、再让模型自己去读」。
            with open(task_file, "r", encoding="utf-8") as f:
                task_text = f.read()
            c = api_conf(cfg)
            text, secs = _api_chat(
                c["base"], c["key"], c["model"],
                [{"role": "system",
                  "content": "你是用户研究的方法学助手。严格按用户给的任务书执行，"
                             "直接输出最终内容（Markdown），不要前言、不要解释你的做法、不要反问。"},
                 {"role": "user", "content": task_text}],
                timeout=timeout)
        else:
            task = ("读文件 %s ，严格按里面的【任务】和【输出要求】执行，"
                    "把结果直接作为你的最终答复输出。不要写文件、不要跑命令、不要反问。" % task_file)
            text, errs, secs, code = _run_headless(task, cfg, timeout)
    except Exception as e:
        return {"ok": False, "error": str(e), "status": st, "task_file": task_file,
                "provider": prov}

    if not text:
        return {"ok": False,
                "error": "模型没有输出。任务书在 %s，可以自己贴到聊天窗口里试。" % task_file,
                "status": st, "task_file": task_file, "provider": prov}

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
        "provider": prov,                  # "api" | "dsh"，界面用它说明"这次走的哪条路"
        "seconds": secs,
        "task_file": task_file,
        "note": "这是**初稿**：请自己过一遍再决定要不要用。模型不做算术，数字仍由 Python 产生。",
    }
