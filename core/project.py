# -*- coding: utf-8 -*-
"""工作台 · 项目

一个「研究项目」就是一个目录，结构沿用 README 里定的：

    contracts/    中间契约（组块之间传什么）
    data/         数据（**脱敏后**才放这里）
    output/       产物（报告 / 图表 / SPSS 输出）
    samples/      示例
    project.json  项目元信息（工作台生成，人也能改）

界面上的「项目」下拉，列的就是这些目录。
"""
import json
import os
import time

SUBS = ("contracts", "data", "output", "samples")


class Project(object):
    def __init__(self, root):
        self.root = os.path.abspath(root)

    # ---------- 基本 ----------

    @property
    def name(self):
        return os.path.basename(self.root.rstrip("\\/")) or self.root

    def exists(self):
        return os.path.isdir(self.root)

    def ensure(self):
        os.makedirs(self.root, exist_ok=True)
        for d in SUBS:
            os.makedirs(os.path.join(self.root, d), exist_ok=True)

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def safe(self, rel):
        """把相对路径锁在项目目录内——前端传来的路径不能逃出去。"""
        rel = (rel or "").replace("/", os.sep).replace("\\", os.sep)
        p = os.path.abspath(os.path.join(self.root, rel))
        root = os.path.abspath(self.root)
        if os.path.normcase(p) != os.path.normcase(root) and \
           not os.path.normcase(p).startswith(os.path.normcase(root) + os.sep):
            raise ValueError("路径越界：%s" % rel)
        return p

    # ---------- 元信息 ----------

    def meta(self):
        p = self.path("project.json")
        m = {"name": self.name, "created": "", "scenario": "", "note": ""}
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    m.update(json.load(f))
            except Exception:
                pass
        return m

    def save_meta(self, m):
        p = self.path("project.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

    # ---------- 读写 ----------

    def read_text(self, rel):
        p = self.safe(rel)
        if not os.path.exists(p):
            return ""
        # ⚠ 不能一律当 UTF-8 读：SPSS 语法是按本机代码页写的（SPSS 只认那种）
        with open(p, "rb") as f:
            raw = f.read()
        for enc in ("utf-8-sig", "utf-8"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("gb18030", "replace")

    def write_text(self, rel, text):
        p = self.safe(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return p
    def list_files(self, rel="", exts=None):
        d = self.safe(rel) if rel else self.root
        out = []
        if not os.path.isdir(d):
            return out
        for name in sorted(os.listdir(d)):
            fp = os.path.join(d, name)
            if not os.path.isfile(fp):
                continue
            if exts and os.path.splitext(name)[1].lower() not in exts:
                continue
            rel_path = os.path.relpath(fp, self.root).replace("\\", "/")
            out.append({
                "rel": rel_path,
                "name": name,
                "size": os.path.getsize(fp),
                "mtime": int(os.path.getmtime(fp)),
            })
        return out

    def artifacts(self):
        """output / contracts / data 下所有产物，界面「产物」页用。"""
        out = []
        for sub in ("output", "contracts", "data"):
            out.extend(self.list_files(sub))
        return sorted(out, key=lambda x: -x["mtime"])

    # ---------- 状态 ----------

    def status(self, blocks):
        """每个组块「做完了没」+「**过期了没**」。

        ⚠ 只判"文件在不在"是不够的（这是实测踩到的）：
          上游契约 19:49 改过、而提纲是 19:48 生成的 —— 文件都在，界面显示"已完成"，
          于是研究员拿着一份**按旧契约生成的**提纲继续往下做，而且不知道。
          这类静默的过期产物比"缺文件"更危险：缺文件会被发现，过期不会。

        判据：**本组块最旧的产物 vs 它声明依赖的文件的最新修改时间**。
        产物更旧 → 过期，并给出"哪个依赖变了"。
        """
        st = {}
        for b in blocks:
            files = list(b.get("detect") or [])
            done = False
            if files:
                try:
                    done = all(os.path.exists(self.safe(f)) for f in files)
                except Exception:
                    done = False
            info = {"done": done, "files": files, "stale": False, "stale_why": ""}
            if done:
                try:
                    # 本组块产物里**最旧**的那个（任一份没更新都算过期）
                    out_times = [(f, os.path.getmtime(self.safe(f))) for f in files]
                    out_old = min(t for _f, t in out_times)
                    out_old_f = [f for f, t in out_times if t == out_old][0]
                    why = []
                    # ⚠ **只比它自己声明依赖的东西**（`needs`）。
                    #   第一版还比了 samples/ 和 data/ 里的**全部**文件，结果新往项目里
                    #   丢一份别的材料，所有组块都被标成"过期" —— 假警报比漏报更糟，
                    #   人会很快学会无视它。
                    for need in (b.get("needs") or []):
                        p = self.safe(need)
                        if os.path.exists(p) and os.path.getmtime(p) > out_old:
                            why.append(need)
                    if why:
                        info["stale"] = True
                        info["stale_why"] = "、".join(dict.fromkeys(why))[:200]
                        info["stale_out"] = out_old_f
                except Exception:
                    pass
            st[b["id"]] = info
        return st

    def summary(self, blocks=None):
        return {
            "root": self.root,
            "name": self.name,
            "meta": self.meta(),
            "exists": self.exists(),
            "artifacts": self.artifacts(),
            "status": self.status(blocks) if blocks else {},
        }


def unique_hist_name(hdir, rel, when=None):
    """给历史备份起一个**不撞车**的名字。

    ⚠ 为什么需要：原来用 `%Y%m%d_%H%M%S`（秒级）。同一秒里改两次 ——
      比如在界面上手改产物、连点两下保存 —— **两个备份撞名，后一个把前一个覆盖了**，
      中间那一版就永久丢了（实测踩到）。
      撞了就在后面加 `_2`、`_3`…… 保证"改几次就留几版"。
    """
    stem, ext = os.path.splitext(os.path.basename(rel))
    stamp = when or time.strftime("%Y%m%d_%H%M%S")
    name = "%s_%s%s" % (stem, stamp, ext)
    n = 2
    while os.path.exists(os.path.join(hdir, name)):
        name = "%s_%s_%d%s" % (stem, stamp, n, ext)
        n += 1
    return name


def _looks_like_project_dir(path):
    """这个目录自己像不像一个研究项目？

    ⚠ 光看「有没有子目录」不够：装了项目的文件夹（`projects/`）也有子目录，
      它会被当成一个项目混进下拉里（踩过：下拉里多出一项叫 "projects"）。
      认准 `/project.json` 这个标记，或者自己声明了 contracts/output/data/samples。
    """
    if not os.path.isdir(path):
        return False
    if os.path.exists(os.path.join(path, "project.json")):
        return True
    return any(os.path.isdir(os.path.join(path, d))
               for d in ("contracts", "output", "data", "samples"))


def list_projects(default_root, extra_dirs=("projects",), depth=2):
    """列出可选项目：默认项目 + <项目之家>/projects/* 下的子目录。

    **多认一层**：如果 `projects/` 下面那一层不是项目、而是"装着项目的文件夹"
    （比如误建出的 `projects/projects/<名字>`），就往下再找一层。
    这样即使目录结构被套错了，研究员的项目也不会从下拉里消失
    （踩过：项目在 `projects/projects/` 里，下拉里只看到那个文件夹本身，项目打不开）。
    """
    out = []
    seen = set()

    def add(root):
        r = os.path.abspath(root)
        key = os.path.normcase(r)
        if key in seen or not os.path.isdir(r):
            return
        seen.add(key)
        out.append({"root": r, "name": os.path.basename(r.rstrip("\\/")) or r})

    def scan(base, level):
        if not os.path.isdir(base):
            return
        for name in sorted(os.listdir(base)):
            sub = os.path.join(base, name)
            if not os.path.isdir(sub):
                continue
            if _looks_like_project_dir(sub):
                add(sub)
            elif level < depth:
                scan(sub, level + 1)          # 不是项目，那就再往里看一眼

    add(default_root)
    for extra in extra_dirs:
        scan(os.path.join(default_root, extra), 1)
    return out


def create_project(parent_root, name):
    """在 **parent_root** 下建一个新项目。

    ⚠ `parent_root` 就是"项目们住的那一层"（服务端传的是 `<项目之家>/projects`）。
      **这里不要再自己拼一次 `projects/`** —— 那会套成 `projects/projects/<名字>`，
      项目建出来了、但下拉列表里看不见它（踩过，真丢过一次）。
    """
    name = (name or "").strip().strip("\\/")
    if not name:
        raise ValueError("项目名不能为空")
    if any(c in name for c in '<>:"/\\|?*'):
        raise ValueError("项目名里有不能用的字符")
    root = os.path.join(parent_root, name)
    if os.path.exists(root):
        raise ValueError("已经有一个叫「%s」的项目了" % name)
    p = Project(root)
    p.ensure()
    p.save_meta({"name": name, "created": time.strftime("%Y-%m-%d %H:%M"),
                 "scenario": "", "note": "由工作台创建"})
    return p
