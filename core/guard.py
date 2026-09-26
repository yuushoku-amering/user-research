# -*- coding: utf-8 -*-
"""工作台 · 素材入口守卫（🔒 去标识化那道关）

**它不拦人，它把风险摆到台面上。**

素材里带着手机号、邮箱、身份证这种直接标识符，就该在进分析之前先过一遍 🔒。
问题是「先过一遍」全靠自觉 —— 所以这道关做的事是：
在你按下运行之前，把这个项目里**还没脱敏的素材**列出来，说清每份命中了什么，
然后要你说一句「我知道，继续」。这句话会落进项目目录，谁什么时候放行的都查得到。

三条刻意的取舍：

1. **只认直接标识符**（手机 / 邮箱 / 身份证 / 微信 / QQ / 学号工号）。
   姓名和准标识符（年龄、单位、城市）**不参与判定** —— 姓名要上下文才认得出，
   一认就误报；天天弹的提示等于没有提示。准标识符的提示留在 🔒 的报告里。
2. **不硬拦**。研究员知道自己在干什么（比如这份材料已经口头授权、或者压根是模拟数据），
   工作台不该替他把路堵死。要的是「确认过」，不是「不许过」。
3. **证据优先**：只要登记表里有记录、或者文件名带「脱敏」，就当已经处理过。
   没登记的才去看内容 —— 免得把已经脱敏的文件又吓你一次。
"""
import csv
import json
import os
import re
import time

# 扫哪些目录找素材（项目内的相对路径）
SCAN_DIRS = ("data", "samples", "materials", "raw", "contracts")

# 这些目录里的东西是流程自己产出的，不算「原始素材」。
# 例外：如果研究员明确挑了这里的某个文件当输入，那还是要看（见 _picked_rels）。
DERIVED_DIRS = ("output", "_history", "_jobs", ".git")

TEXT_EXT = (".txt", ".md", ".srt", ".csv", ".tsv", ".log")

MAX_FILE_BYTES = 4 * 1024 * 1024      # 超大文件不读，读它没意义还慢

REGISTRY_REL = "contracts/去标识化清单.json"   # 🔒 引擎跑完登记在这
ACK_REL = "output/去标识化_确认.json"          # 「我知道，继续」记在这
MAX_ACK = 50                                   # 确认记录最多留这么多条

# 只认这些 —— 精确度优先。银行卡（16~19 位纯数字）和座机太容易误伤，故意不收。
DIRECT = [
    ("手机号", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("身份证", r"(?<!\d)\d{17}[\dXx](?!\d)"),
    ("邮箱", r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    ("微信号", r"(?i)(?:微信|wechat|vx)\s*(?:号|ID)?\s*(?:是|为|[:：])?\s*([A-Za-z][\w\-]{5,19})"),
    ("QQ/群号", r"(?i)(?:QQ|扣扣)\s*(?:群|号)?\s*(?:是|为|[:：])?\s*(\d{5,12})"),
    ("学号工号", r"(?:学号|工号|员工号|工牌)\s*[:：]?\s*([A-Za-z0-9\-]{4,20})"),
]


def _read(path):
    """尽量读出来；读不了就返回空串（守卫不该因为一个坏文件把运行卡死）。"""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return ""
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def read_json(proj, rel):
    p = proj.safe(rel)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def write_json(proj, rel, data):
    p = proj.safe(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p


def public_rels(proj):
    """登记表里已经脱敏过的源文件（=「这份我处理过了」）。"""
    reg = read_json(proj, REGISTRY_REL)
    out = set()
    for rec in (reg.get("files") or {}).values():
        if isinstance(rec, dict) and rec.get("src_rel"):
            if (rec.get("out_rel") or "").strip() or rec.get("note"):
                out.add(str(rec["src_rel"]).replace("\\", "/"))
    return out


def acked_rels(proj):
    """研究员按下过「我知道，继续」的文件。"""
    ack = read_json(proj, ACK_REL)
    out = set()
    for k, rec in (ack.get("files") or {}).items():
        if isinstance(rec, dict) and rec.get("src_rel"):
            out.add(str(rec["src_rel"]).replace("\\", "/"))
        elif isinstance(rec, dict):
            out.add(str(k).replace("\\", "/"))
    return out


def looks_deidentified(rel):
    base = os.path.basename(rel)
    return ("脱敏" in base) or ("deident" in base.lower()) or ("anonym" in base.lower())


def _walk_files(proj, sub, exts=TEXT_EXT):
    """递归列目录下的文件（素材常被分门别类放进子目录，只扫一层会漏）。"""
    out = []
    base = proj.safe(sub)
    if not os.path.isdir(base):
        return out
    for cur, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for n in names:
            if exts and os.path.splitext(n)[1].lower() not in exts:
                continue
            fp = os.path.join(cur, n)
            try:
                sz = os.path.getsize(fp)
            except OSError:
                continue
            out.append({
                "rel": os.path.relpath(fp, proj.root).replace("\\", "/"),
                "name": n, "size": sz,
                "mtime": int(os.path.getmtime(fp)),
            })
    return out


def _picked_rels(proj, params):
    """这次运行表单里明确挑的文件。挑了的就算在 output 里也要看一眼。

    表单里文件值的写法不统一（'output/x.csv'、'data\\x.csv'、带引号…），所以宽松地认：
    只要某个值规整之后等于项目里某个真实文件的相对路径，就算「挑了这个文件」。
    """
    vals = []
    for v in (params or {}).values():
        if isinstance(v, str):
            vals.append(v.strip().strip('"').strip("'"))
        elif isinstance(v, (list, tuple)):
            vals.extend(str(x).strip().strip('"').strip("'") for x in v)
    want = set(v.replace("\\", "/").lstrip("./") for v in vals if v)
    out = []
    for sub in SCAN_DIRS + DERIVED_DIRS:
        for f in _walk_files(proj, sub):
            if f["rel"] in want:
                out.append(f["rel"])
    return out


def scan(proj, params=None):
    """扫出「还没脱敏、但能认出直接标识符」的素材。

    返回 [{rel, name, size, hits:[{label, count, sample}], hit_total}]，按命中数从多到少。
    """
    skip = public_rels(proj) | acked_rels(proj)
    picked = set(_picked_rels(proj, params))

    cands = []
    for sub in SCAN_DIRS + DERIVED_DIRS:
        for f in _walk_files(proj, sub):
            rel = f["rel"]
            if rel in skip or looks_deidentified(rel):
                continue
            if any(rel.startswith(d + "/") for d in DERIVED_DIRS) and rel not in picked:
                continue                      # 流程自己的产物，不是原始素材
            cands.append(f)

    out = []
    for f in cands:
        txt = _read(proj.safe(f["rel"]))
        if not txt:
            continue
        hits = []
        for label, pat in DIRECT:
            found = re.findall(pat, txt)
            if not found:
                continue
            uniq = list(dict.fromkeys(str(x) for x in found if x))
            hits.append({"label": label, "count": len(found),
                         "sample": "、".join(uniq[:2])[:40]})
        if hits:
            out.append({
                "rel": f["rel"], "name": f["name"], "size": f["size"],
                "hits": hits, "hit_total": sum(h["count"] for h in hits),
            })
    out.sort(key=lambda x: -x["hit_total"])
    return out


def guard_for(block, project_root, params=None):
    """这个组块这次能不能直接跑？返回 {"need": bool, ...}。

    need=True 时带着 materials（哪几份素材）和 why（为什么拦），前端照着显示。
    """
    if not block.get("guard"):
        return {"need": False, "materials": [], "why": ""}
    from .project import Project
    proj = Project(project_root)
    mats = scan(proj, params)
    if not mats:
        return {"need": False, "materials": [], "why": ""}
    return {
        "need": True,
        "materials": mats,
        "total": len(mats),
        "why": "这些素材还没过 🔒 去标识化，里面能认出直接标识符。"
               "分析产物（图、表、报告）会带着它们扩散出去。",
        "block_id": block.get("id"),
        "block_title": block.get("title") or block.get("name"),
    }


def ack(project_root, block, rels, note="", who="研究员"):
    """记下「我知道，继续」——一条落盘的确认记录。"""
    from .project import Project
    proj = Project(project_root)
    rels = [str(r).replace("\\", "/") for r in (rels or []) if r]
    if not rels:
        return {"ok": False, "error": "没有要确认的素材"}
    ack_data = read_json(proj, ACK_REL)
    files = ack_data.get("files") or {}
    stamp = time.strftime("%Y-%m-%d %H:%M")
    for rel in rels:
        p = proj.safe(rel)
        rec = {
            "src_rel": rel,
            "at": stamp,
            "by": who,
            "block_id": block.get("id") if block else "",
            "block_title": (block.get("title") or block.get("name")) if block else "",
            "note": note or "研究员确认知悉后继续（未做去标识化）",
            "size": os.path.getsize(p) if os.path.exists(p) else 0,
        }
        files[rel] = rec
    order = sorted(files.items(), key=lambda kv: kv[1].get("at", ""), reverse=True)[:MAX_ACK]
    ack_data["files"] = dict(order)
    ack_data["note"] = ("这份记录 = 「当时知道素材没脱敏，还是继续跑了」。"
                        "它是研究过程的一部分，不会被自动清掉；不想要了就删这个文件。")
    p = write_json(proj, ACK_REL, ack_data)
    return {"ok": True, "file": os.path.relpath(p, proj.root).replace("\\", "/"),
            "acked": rels, "at": stamp}


def register(project_root, src_rel, out_rel, hits, note=""):
    """🔒 跑完之后登记：这份源文件处理过了，脱敏件在这里。

    登记表是「已处理」的凭据，所以只由引擎写。
    """
    from .project import Project
    proj = Project(project_root)
    reg = read_json(proj, REGISTRY_REL)
    files = reg.get("files") or {}
    src_rel = str(src_rel).replace("\\", "/")
    files[src_rel] = {
        "src_rel": src_rel,
        "out_rel": str(out_rel or "").replace("\\", "/"),
        "at": time.strftime("%Y-%m-%d %H:%M"),
        "replaced": sum(int(h[3]) for h in hits) if hits else 0,
        "kinds": sorted(set(h[0] for h in hits)) if hits else [],
        "note": note,
    }
    reg["files"] = files
    reg["note"] = ("哪些素材已经过 🔒、脱敏件在哪。工作台靠它判断「这份处理过了」，"
                   "不会拿它自动替换什么。")
    p = write_json(proj, REGISTRY_REL, reg)
    return os.path.relpath(p, proj.root).replace("\\", "/")


def summary_for_ui(project_root):
    """给界面状态栏用的一句话摘要。"""
    from .project import Project
    proj = Project(project_root)
    reg = read_json(proj, REGISTRY_REL)
    ack_data = read_json(proj, ACK_REL)
    return {
        "registered": len(reg.get("files") or {}),
        "acked": len(ack_data.get("files") or {}),
        "registry_rel": REGISTRY_REL,
        "ack_rel": ACK_REL,
    }
