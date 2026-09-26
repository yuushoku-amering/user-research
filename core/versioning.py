# -*- coding: utf-8 -*-
"""工作台 · 版本对比

契约文件（研究简报 / 访谈提纲 / 编码表 / 分析报告…）每被覆盖一次，
`runner.Ctx.save_text` 就会把旧版留一份到 `_history/<名字>_<时间戳><后缀>`。
**历史一直在存，但从来没人看得见** —— 这个模块把"改了什么"显示出来。

三件事：

1. `list_versions(proj, rel)` —— 某份文件有哪些历史版本（新的在前）
2. `diff_texts(a, b, kind)` —— 两份文本的差异，**按文件类型给不同粒度**：
   - `md`：先按小节标题对齐 → 新增/删除/改动的小节，再看行级增删
   - `table`：按行比对（变量表、编码表这类，行就是一条）
   - `text`：退到行级
3. 标签/备注：旁挂在 `_history/版本说明.json`，**不动历史文件本身**
   （它们是不可再生的证据，只读）

⚠ 只读，不改任何历史版本。
"""
import difflib
import io
import json
import os
import re
import time

LABELS_REL = "_history/版本说明.json"

# 历史文件名的形态：<原名>_<YYYYmmdd_HHMMSS><后缀>
# ⚠ 末尾那个可选的 `_2`/`_3` 是**同一秒里连改多次**时的防撞号（见 project.unique_hist_name）。
#   不认它，这些备份就不会被列进版本列表 —— 实测踩到：连改两次，只看到 2 个版本。
_STAMP = re.compile(r"^(?P<stem>.+)_(?P<stamp>\d{8}_\d{6})(?:_\d+)?(?P<ext>\.[A-Za-z0-9]+)$")


def _read(path):
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


def _labels(proj):
    p = proj.safe(LABELS_REL)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def load_labels(proj):
    """读标签表：{历史文件名: {label, note, at}}。"""
    return _labels(proj).get("files") or {}


def set_label(proj, hist_name, label="", note=""):
    """给某个历史版本打标签 / 写备注。

    ⚠ 只写这份 json，**绝不碰历史文件**——那是证据，改了就不是证据了。
    """
    hist_name = os.path.basename(str(hist_name or ""))
    if not hist_name:
        return {"ok": False, "error": "没说要给哪个版本打标签"}
    hp = proj.safe(os.path.join("_history", hist_name))
    if not os.path.exists(hp):
        return {"ok": False, "error": "找不到这个历史版本：%s" % hist_name}
    data = _labels(proj)
    files = data.get("files") or {}
    rec = files.get(hist_name) or {}
    if label is not None and str(label).strip():
        rec["label"] = str(label).strip()[:60]
    if note is not None and str(note).strip():
        rec["note"] = str(note).strip()[:400]
    rec["at"] = time.strftime("%Y-%m-%d %H:%M")
    files[hist_name] = rec
    data["files"] = files
    data["note"] = ("给历史版本起的人话名字。程序只写这个文件，不动 _history 里的历史本身。"
                    "默认标签是程序给的事实（行数/条目数），不好认就改成人话。")
    p = proj.safe(LABELS_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "file": hist_name, "label": rec.get("label", "")}


def _pair(hist_name, base_name):
    """历史文件名 → (原文件名, 时间戳文字)。解析不出来就返回 (去后缀的名字, '')。"""
    m = _STAMP.match(hist_name)
    if not m:
        return (hist_name, "")
    ext = m.group("ext")
    return (m.group("stem") + ext, m.group("stamp"))


def list_versions(proj, rel):
    """某份文件的历史版本 + 当前版。新的在前。

    返回 [{kind:"current"|"history", name, rel, at, size, lines, label, note, is_base}]
    """
    rel = str(rel or "").replace("\\", "/").lstrip("./")
    if not rel:
        return []
    base = os.path.basename(rel)
    stem, ext = os.path.splitext(base)
    hdir = proj.safe("_history")
    out = []
    labels = load_labels(proj)

    cur_p = proj.safe(rel)
    if os.path.exists(cur_p):
        txt = _read(cur_p)
        out.append({
            "kind": "current", "name": base, "rel": rel,
            "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(cur_p))),
            "size": os.path.getsize(cur_p), "lines": len(txt.splitlines()),
            "label": "当前版本", "note": "", "is_base": True,
        })

    if os.path.isdir(hdir):
        for name in os.listdir(hdir):
            if not name.lower().endswith(ext.lower()) or not name.startswith(stem):
                continue
            fp = os.path.join(hdir, name)
            if not os.path.isfile(fp):
                continue
            orig, stamp = _pair(name, base)
            if orig != base:
                continue                     # 别的文件的历史，别混进来
            txt = _read(fp)
            rec = labels.get(name) or {}
            at = rec.get("at")
            if not at and stamp:
                at = "%s-%s-%s %s:%s:%s" % (stamp[0:4], stamp[4:6], stamp[6:8],
                                            stamp[9:11], stamp[11:13], stamp[13:15])
            out.append({
                "kind": "history", "name": name, "rel": "_history/" + name,
                "at": at or "", "size": os.path.getsize(fp),
                "lines": len(txt.splitlines()),
                "label": rec.get("label") or "", "note": rec.get("note") or "",
                "is_base": False,
            })
    # 时间新的在前；当前版永远在最前
    hist = [x for x in out if x["kind"] == "history"]
    hist.sort(key=lambda x: (x.get("at") or "", x.get("name") or ""), reverse=True)
    cur = [x for x in out if x["kind"] == "current"]
    return cur + hist


# --------------------------------------------------------------------------- #
# 差异
# --------------------------------------------------------------------------- #

def _split_sections(md):
    """Markdown → [(小节标题, 正文)]。标题行归到那一节里。"""
    heads, cur_t, cur_b = [], "(开头)", []
    for ln in (md or "").splitlines():
        if ln.strip().startswith("#"):
            heads.append((cur_t, "\n".join(cur_b).strip()))
            cur_t, cur_b = ln.strip(), []
        else:
            cur_b.append(ln)
    heads.append((cur_t, "\n".join(cur_b).strip()))
    return [(t, b) for t, b in heads if t or b]


def _line_diff(a, b):
    """两份文本的行级增删。"""
    al, bl = (a or "").splitlines(), (b or "").splitlines()
    added, removed = [], []
    for ln in difflib.unified_diff(al, bl, lineterm="", n=0):
        if ln.startswith("+++") or ln.startswith("---") or ln.startswith("@@"):
            continue
        if ln.startswith("+"):
            s = ln[1:].strip()
            if s:
                added.append(s)
        elif ln.startswith("-"):
            s = ln[1:].strip()
            if s:
                removed.append(s)
    return added, removed


def _cell_rows(text, header_markers=("变量", "题号", "变量名", "说话人", "段号", "原文")):
    """表格类文本 → 数据行（跳过表头行和 |---| 分隔行）。"""
    rows = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("|"):
            if re.match(r"^\|[\s\-:|]+\|$", s):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and cells[0] in header_markers:
                continue
            key = cells[0] if cells else ""
        else:
            key = s.split(",")[0].strip().strip('"') if "," in s else s
            if key in header_markers or key in ("变量名", "题号"):
                continue
        if key:
            rows.append(key)
    return rows


def diff_texts(old, new, kind="text"):
    """两份文本的差异。

    kind:
      md    —— 先按小节对齐，再给行级增删
      table —— 按行（第一条字段）比对
      text  —— 行级
    返回 dict：{kind, sections:[{title,status,added,removed}], added:[], removed:[],
                summary:{added,removed,changed}}
    """
    kind = kind if kind in ("md", "table", "text") else "text"
    out = {"kind": kind, "sections": [], "added": [], "removed": [],
           "summary": {"added": 0, "removed": 0, "changed": 0}}

    if kind == "md":
        a = _split_sections(old)
        b = _split_sections(new)
        amap, bmap = {}, {}
        for t, body in a:
            amap.setdefault(t, []).append(body)
        for t, body in b:
            bmap.setdefault(t, []).append(body)
        for t, body in b:
            if t not in amap:
                out["sections"].append({"title": t, "status": "新增", "added": body.splitlines()[:20],
                                        "removed": []})
            elif amap.get(t, [""])[0].strip() != body.strip():
                ad, rm = _line_diff(amap[t][0], body)
                out["sections"].append({"title": t, "status": "改动", "added": ad[:20],
                                        "removed": rm[:20]})
        for t, body in a:
            if t not in bmap:
                out["sections"].append({"title": t, "status": "删除", "added": [],
                                        "removed": body.splitlines()[:20]})
        out["summary"]["added"] = sum(1 for s in out["sections"] if s["status"] == "新增")
        out["summary"]["removed"] = sum(1 for s in out["sections"] if s["status"] == "删除")
        out["summary"]["changed"] = sum(1 for s in out["sections"] if s["status"] == "改动")
        return out

    if kind == "table":
        ar, br = _cell_rows(old), _cell_rows(new)
        aset, bset = set(ar), set(br)
        out["added"] = [x for x in br if x not in aset]
        out["removed"] = [x for x in ar if x not in bset]
        out["summary"] = {"added": len(out["added"]), "removed": len(out["removed"]),
                          "changed": 0, "rows_old": len(ar), "rows_new": len(br)}
        return out

    ad, rm = _line_diff(old, new)
    out["added"], out["removed"] = ad, rm
    out["summary"] = {"added": len(ad), "removed": len(rm), "changed": 0}
    return out


def kind_for(rel):
    """按文件类型决定差异粒度。"""
    e = (os.path.splitext(str(rel or ""))[1] or "").lower()
    if e in (".md",):
        return "md"
    if e in (".csv", ".tsv"):
        return "table"
    return "text"


def diff_versions(proj, rel, name_a, name_b):
    """对比两个版本（name 用 list_versions 里的 name；当前版就是 basename(rel)）。"""
    rel = str(rel or "").replace("\\", "/").lstrip("./")
    base = os.path.basename(rel)

    def _path(name):
        if name == base or not name:
            return proj.safe(rel)
        return proj.safe(os.path.join("_history", os.path.basename(name)))

    pa, pb = _path(name_a), _path(name_b)
    if not os.path.exists(pa) or not os.path.exists(pb):
        return {"ok": False, "error": "有一份版本找不到"}
    a, b = _read(pa), _read(pb)
    d = diff_texts(a, b, kind_for(rel))
    d["ok"] = True
    d["rel"] = rel
    d["a"] = {"name": name_a or base, "lines": len(a.splitlines())}
    d["b"] = {"name": name_b or base, "lines": len(b.splitlines())}
    return d


def diff_to_markdown(rel, d):
    """把差异导出成一份 markdown —— 研究员可以在上面写「这一轮为什么改」。"""
    L = []
    L.append("# 版本对比 · %s\n" % os.path.basename(str(rel or "")))
    L.append("> 由工作台生成（`difflib`，不联网、不花模型额度）。")
    L.append("> 旧的：`%s`（%d 行）　新的：`%s`（%d 行）\n"
             % (d.get("a", {}).get("name"), d.get("a", {}).get("lines", 0),
                d.get("b", {}).get("name"), d.get("b", {}).get("lines", 0)))
    s = d.get("summary") or {}
    L.append("## 这一轮改了什么\n")
    if d.get("kind") == "md":
        L.append("- 新增 %d 个小节、改动 %d 个、删掉 %d 个\n"
                 % (s.get("added", 0), s.get("changed", 0), s.get("removed", 0)))
        for sec in d.get("sections") or []:
            L.append("### [%s] %s" % (sec.get("status"), sec.get("title")))
            for x in sec.get("removed") or []:
                L.append("- ~~%s~~" % x)
            for x in sec.get("added") or []:
                L.append("- %s" % x)
            L.append("")
    elif d.get("kind") == "table":
        L.append("- 新增 %d 条、删掉 %d 条（旧 %s 条 → 新 %s 条）\n"
                 % (s.get("added", 0), s.get("removed", 0),
                    s.get("rows_old", 0), s.get("rows_new", 0)))
        if d.get("added"):
            L.append("**新增**")
            for x in d["added"]:
                L.append("- %s" % x)
            L.append("")
        if d.get("removed"):
            L.append("**删掉**")
            for x in d["removed"][:200]:
                L.append("- %s" % x)
            L.append("")
    else:
        L.append("- 新增 %d 行、删掉 %d 行\n" % (s.get("added", 0), s.get("removed", 0)))
        for x in (d.get("removed") or [])[:200]:
            L.append("- ~~%s~~" % x)
        for x in (d.get("added") or [])[:200]:
            L.append("- %s" % x)
    L.append("\n## 这一轮为什么改\n")
    L.append("（在这里写一句：是哪次访谈 / 哪个反馈 / 哪个发现让你改的。")
    L.append("这句话是研究记录的一部分，将来答辩或交接时会被问到。）\n")
    return "\n".join(L)
