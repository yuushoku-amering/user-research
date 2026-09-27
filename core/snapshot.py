# -*- coding: utf-8 -*-
"""工作台 · 项目快照

把**整个项目目录**打成一个文件（`.urwproj`，里面就是个 zip），放到你指定的文件夹；
以后选这个文件导进来，就能把现场原样还原。

要不要这个东西，是因为踩过一次：模型给的初稿、手工填的参数都在浏览器内存里，
一刷新就没了。文件落盘才是真的留着。

约定：
    · 一个快照 = 一个项目目录的全部内容（含 `_history/` 备份，除非你勾掉）
    · 里面放一份 `快照信息.json`，记着原始路径、导出时间、文件数 —— 便于日后认领
    · **导入时绝不覆盖已有项目**，重名就加 `_导入_时间` 后缀
    · 解压前逐条校验路径，禁止 `..`、绝对路径、盘符 —— 免得别人给的快照到处写文件
"""
import json
import os
import re
import shutil
import time
import zipfile

EXT = ".urwproj"
MANIFEST = "快照信息.json"
SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "__MACOSX"}
# ⚠ 快照的"格式名"：这里**保留**「用户研究工作台」，不跟着界面换成「岚苔 Vesper」
#   （2026-09-27 前辈拍板：产出里的落款保持中性）。
#   安全性：`FMT` 只在**导出**时写进 快照信息.json，导入时不做校验，所以改名也不影响读旧快照；
#   而 `_snapshottest.py` 的断言是 `.endswith("项目快照")` —— 只要尾巴是「项目快照」就仍然过。
FMT = "用户研究工作台 · 项目快照"


def safe_name(name):
    """项目名 → 能当文件夹名的样子。"""
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "").strip())
    n = n.strip(" .")
    return n or "导入的项目"


def _count(root, with_history):
    n = b = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and (with_history or d != "_history")]
        for fn in filenames:
            try:
                b += os.path.getsize(os.path.join(dirpath, fn))
                n += 1
            except OSError:
                pass
    return n, b


def export(root, dest_dir, with_history=True, note=""):
    """把项目打包到 dest_dir 下的一个 `.urwproj` 文件。返回一份说明。"""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise ValueError("项目目录不存在：%s" % root)
    dest_dir = os.path.abspath(os.path.expanduser(dest_dir or ""))
    if not dest_dir:
        raise ValueError("请先选一个保存到哪个文件夹")
    if dest_dir.startswith(root + os.sep) or dest_dir == root:
        raise ValueError("别把快照存在项目目录里面 —— 换一个文件夹（比如桌面）")
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        raise ValueError("这个文件夹建不出来：%s（%s）" % (dest_dir, e))
    if not os.access(dest_dir, os.W_OK):
        raise ValueError("这个文件夹没法写入：%s" % dest_dir)

    proj_name = safe_name(os.path.basename(root.rstrip("\\/")))
    stamp = time.strftime("%Y%m%d_%H%M")
    out = os.path.join(dest_dir, "%s_%s%s" % (proj_name, stamp, EXT))
    i = 2
    while os.path.exists(out):
        out = os.path.join(dest_dir, "%s_%s(%d)%s" % (proj_name, stamp, i, EXT))
        i += 1

    n_files, raw_bytes = _count(root, with_history)
    manifest = {
        "格式": FMT,
        "版本": 1,
        "项目名": proj_name,
        "原始路径": root,
        "导出时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "文件数": n_files,
        "未压缩字节": raw_bytes,
        "含 _history": bool(with_history),
        "备注": note,
        "说明": "这是工作台的项目快照。在界面上点「导入…」选这个文件就能还原现场；"
                "里面就是一个普通 zip，你也可以直接解开看。",
    }

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                           and (with_history or d != "_history")]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root).replace("\\", "/")
                if rel == MANIFEST:
                    continue
                try:
                    z.write(full, rel)
                except OSError:
                    continue
        z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))

    return {
        "file": out,
        "dir": dest_dir,
        "size": os.path.getsize(out),
        "files": n_files,
        "raw_bytes": raw_bytes,
        "project": proj_name,
        "with_history": bool(with_history),
    }


def _check_member(name):
    p = str(name).replace("\\", "/")
    if not p or p.endswith("/"):
        return None
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        raise ValueError("快照里有绝对路径，不安全：%s" % name)
    if any(part in ("..", "") for part in p.split("/")):
        raise ValueError("快照里有可疑路径，不安全：%s" % name)
    return p


def peek(zip_path):
    """不解压，先看看这是不是本工作台的快照、里面是什么。"""
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("这不是一个项目快照文件（.urwproj 里面应该是个 zip）")
    info = {}
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if MANIFEST in names:
            try:
                info = json.loads(z.read(MANIFEST).decode("utf-8"))
            except Exception:
                info = {}
        info["_文件数"] = sum(1 for n in names if not n.endswith("/"))
    return info


def import_snapshot(zip_path, parent_dir, name=None):
    """把快照解到一个新项目目录里（**绝不覆盖已存在的项目**）。返回 (项目根, 说明)。"""
    zip_path = os.path.abspath(zip_path)
    if not os.path.exists(zip_path):
        raise ValueError("找不到这个文件：%s" % zip_path)
    info = peek(zip_path)
    parent_dir = os.path.abspath(parent_dir)
    os.makedirs(parent_dir, exist_ok=True)

    want = safe_name(name or info.get("项目名")
                     or os.path.splitext(os.path.basename(zip_path))[0])
    target = os.path.join(parent_dir, want)
    if os.path.exists(target):
        target = os.path.join(parent_dir, "%s_导入_%s" % (want, time.strftime("%Y%m%d_%H%M%S")))
    if os.path.exists(target):
        raise ValueError("同名项目已经在，而且连时间后缀都撞上了：%s" % target)

    tmp = target + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        with zipfile.ZipFile(zip_path) as z:
            for m in z.infolist():
                rel = _check_member(m.filename)
                if rel is None or rel == MANIFEST:
                    continue
                dest = os.path.join(tmp, rel.replace("/", os.sep))
                if not os.path.abspath(dest).startswith(tmp + os.sep):
                    raise ValueError("快照里的路径逃出了项目目录：%s" % m.filename)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(m) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        # 元信息里记一笔「这份是从哪来的」
        pj = os.path.join(tmp, "project.json")
        meta = {}
        if os.path.exists(pj):
            try:
                with open(pj, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
        meta.setdefault("name", want)
        meta["imported"] = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "from": os.path.basename(zip_path),
            "original_root": info.get("原始路径", ""),
            "exported_at": info.get("导出时间", ""),
        }
        with open(pj, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.rename(tmp, target)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return target, info
