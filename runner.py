# -*- coding: utf-8 -*-
"""工作台 · 引擎子进程入口

用法：  <python> runner.py <job.json>

job.json 里是本次任务的参数（由 core/jobs.py 写好）。
和父进程的约定：**stdout 一行一个 JSON**，父进程只认这个。

    {"t":"log",    "msg":"正在读文件…", "level":"info"}
    {"t":"result", "data":{ ... 给界面用的结构化结果 ... }}
    {"t":"error",  "msg":"为什么失败"}

组块只要在 engine.py 里写一个 `run(ctx)` 就行，其余交给这里。
"""
import importlib.util
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(HERE, "libs")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def read_text_any(path, errors="replace"):
    """按可能的编码读一个文本文件：UTF-8（带/不带 BOM）→ GB18030。

    为什么需要：**SPSS 语法是按本机代码页写的**（见 save_text 的说明），
    而别的产物都是 UTF-8。读的时候不能想当然。
    """
    if not path or not os.path.exists(path):
        return ""
    raw = b""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", errors)

# ⚠ 本机那个 Python 是嵌入式发行版，带 python39._pth —— 它会**完全忽略 PYTHONPATH**，
#   所以第三方包必须在这里手动挂进去。
for p in (LIBS, HERE):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)


def _clean(o):
    """把 numpy 类型 / NaN / Inf 收拾成能 JSON 化的形状。

    ⚠ 坑：json.dumps 默认允许 NaN，会写出非法的 `NaN` 字面量，前端 JSON.parse 直接炸。
    """
    if isinstance(o, float):
        if o != o or o in (float("inf"), float("-inf")):
            return None
        return o
    try:
        import numpy as _np
        if isinstance(o, _np.generic):
            return _clean(o.item())
        if isinstance(o, _np.ndarray):
            return [_clean(x) for x in o.tolist()]
    except ImportError:
        pass
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_clean(x) for x in o]
    if isinstance(o, (str, int, bool)) or o is None:
        return o
    return str(o)


def emit(obj):
    sys.stdout.write(json.dumps(_clean(obj), ensure_ascii=False) + "\n")
    sys.stdout.flush()


class Ctx(object):
    """交给 engine 的上下文：取参数、记日志、写文件、要产物目录。"""

    def __init__(self, params):
        self.params = params
        self.project_root = params.get("project_root", "")
        self.outputs = []          # 本次产出的文件（相对项目根）
        # 组块声明里的「这条提醒能往哪个框里填规则」（目前只有 🔒 有，见 main()）
        self.rules_field = ""

    # --- 参数 ---
    def get(self, key, default=None):
        v = self.params.get(key, default)
        return default if v is None else v

    def var_rows(self, key="variables", fallback=None):
        """变量表的**逐行数据**（界面上的表格直接传过来）。

        界面把表格既存成 [[名, 角色, 层次, 怎么测], …]，也序列化成一份文本（key 本身）。
        这里优先用结构化那份 —— 省得把「逗号/中文逗号」这种老坑再踩一遍；
        没有（比如命令行、旧任务回放）就退回 `fallback`（通常是 kit.parse_var_table(文本)）。
        """
        rows = self.params.get(key + "_rows")
        if isinstance(rows, list) and rows:
            out = []
            for r in rows:
                if isinstance(r, dict):                     # 也认对象写法
                    r = [r.get("name"), r.get("role"), r.get("level"), r.get("op")]
                if not isinstance(r, (list, tuple)):
                    continue
                cells = [str(c).strip() if c is not None else "" for c in r]
                while len(cells) < 4:
                    cells.append("")
                if any(cells):
                    out.append(tuple(cells[:4]))
            if out:
                return out
        return fallback if fallback is not None else []

    # --- 说话 ---
    def log(self, msg, level="info"):
        emit({"t": "log", "msg": str(msg), "level": level})

    def warn(self, msg):
        self.log(msg, "warn")

    def error(self, msg):
        self.log(msg, "error")

    # --- 让研究员看见（过程可见）---
    def step(self, sid, title, detail=None, rows=None, columns=None):
        """报告一个「我在做什么」。界面渲染成一张步骤卡，跑完还能回看。"""
        msg = {"t": "step", "id": str(sid), "title": str(title)}
        if detail:
            msg["detail"] = str(detail)
        if rows is not None:
            msg["columns"] = list(columns or [])
            msg["rows"] = rows
        emit(msg)

    # --- 停下来等研究员拍板（可插手）---
    def ask(self, cid, title, detail=None, options=None, default=None,
            rows=None, columns=None):
        """**在这里停下来。**

        options = [{"value": "...", "label": "...", "hint": "..."}, …]
        返回被选中的 value。研究员可以「让它继续」，也可以选「我改一改」——
        怎么处理由 engine 自己决定。

        没人应答时（比如在命令行里手动跑）会退回 default，不会卡死。
        """
        opts = options or [{"value": "__ok__", "label": "继续"}]
        msg = {
            "t": "ask", "id": str(cid), "title": str(title), "options": opts,
            "default": default if default is not None else opts[0].get("value"),
        }
        if detail:
            msg["detail"] = str(detail)
        if rows is not None:
            msg["columns"] = list(columns or [])
            msg["rows"] = rows
        emit(msg)
        try:
            line = sys.stdin.readline()
        except Exception:
            line = ""
        if not line:
            self.log("（没人应答，按默认「%s」继续）" % msg["default"], "warn")
            return msg["default"]
        try:
            ans = json.loads(line)
            return ans.get("choice") or msg["default"]
        except Exception:
            return msg["default"]

    # --- 路径 ---
    def path(self, *parts):
        return os.path.join(self.project_root, *parts)

    def out_path(self, *parts):
        return os.path.join(self.project_root, "output", *parts)

    def data_path(self, *parts):
        return os.path.join(self.project_root, "data", *parts)

    def ensure_out(self, *parts):
        d = os.path.join(self.project_root, "output", *parts)
        os.makedirs(d, exist_ok=True)
        return d

    # --- 产物登记 ---
    def made(self, path):
        """登记一个产出文件（界面据此显示「产物」）。"""
        rel = os.path.relpath(path, self.project_root).replace("\\", "/")
        self.outputs.append(rel)
        self.log("产物 → %s" % rel, "made")
        return rel

    def save_text(self, rel, text, encoding="utf-8"):
        """写一个文本产物。

        `encoding` 一般不用管（UTF-8 就对了）。唯一的例外是 **SPSS 语法**：
        这台机器上的 SPSS 按**本机代码页**读语法文件，UTF-8 的中文进去全是乱码
        （连里面的文件路径都会被读坏）。所以 .sps 用 GBK 写。
        备份到 _history 的旧版仍统一存 UTF-8，免得备份文件自己也带一份怪编码。
        """
        p = os.path.join(self.project_root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # 覆盖前先留一份历史：人改过的东西，不能被程序无声吃掉
        if os.path.exists(p):
            try:
                old = read_text_any(p)
                if old != text:
                    hdir = os.path.join(self.project_root, "_history")
                    os.makedirs(hdir, exist_ok=True)
                    # 不撞名：同一秒里连改两次，两个备份原来会同名 → 后一个覆盖前一个，丢版本
                    from core.project import unique_hist_name
                    hname = unique_hist_name(hdir, rel)
                    with open(os.path.join(hdir, hname), "w", encoding="utf-8", newline="\n") as f:
                        f.write(old)
                    self.log("覆盖前备份旧版 → _history/%s" % hname, "meta")
            except Exception as e:
                self.warn("备份旧版失败（不影响本次产物）：%s" % e)
        txt = text if isinstance(text, str) else str(text)
        try:
            with open(p, "w", encoding=encoding, newline="\n", errors="replace") as f:
                f.write(txt)
        except LookupError:
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(txt)
        return self.made(p)

    def read_text(self, rel):
        p = os.path.join(self.project_root, rel)
        return read_text_any(p)

    def save_table(self, name, df_or_rows, columns=None):
        import pandas as pd
        p = self.out_path(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # ⚠ 覆盖前**必须**留一份历史 —— 这个曾经漏掉，代价很实在：
        #   `save_text` 一直有备份，`save_table` 没有。而**唯一的人工作业载体**
        #   恰恰是表格：`编码工作表.csv` 是研究员一段段手工填出来的。
        #   实测：重跑 ② 之后 1284 字节 / 9 段编码 → 189 字节 / 0 段，
        #   `_history/` 里一条备份都没有，界面也没问一句 —— 白填。
        #   规矩：**写任何产物之前都先备份**，不管它是 text 还是 table。
        if os.path.exists(p):
            try:
                old = read_text_any(p)
                new_probe = None
                if isinstance(df_or_rows, pd.DataFrame):
                    new_probe = df_or_rows.to_csv(index=False)
                else:
                    new_probe = pd.DataFrame(df_or_rows, columns=columns).to_csv(index=False)
                if old and old.lstrip("\ufeff") != (new_probe or "").lstrip("\ufeff"):
                    hdir = os.path.join(self.project_root, "_history")
                    os.makedirs(hdir, exist_ok=True)
                    from core.project import unique_hist_name
                    hname = unique_hist_name(hdir, name)
                    with open(os.path.join(hdir, hname), "w", encoding="utf-8", newline="\n") as f:
                        f.write(old)
                    self.log("覆盖前备份旧版 → _history/%s" % hname, "meta")
            except Exception as e:
                self.warn("备份旧版失败（不影响本次产物）：%s" % e)
        if isinstance(df_or_rows, pd.DataFrame):
            df_or_rows.to_csv(p, index=False, encoding="utf-8-sig")
        else:
            pd.DataFrame(df_or_rows, columns=columns).to_csv(p, index=False, encoding="utf-8-sig")
        return self.made(p)

    def finish(self, data):
        emit({"t": "result", "data": data})

    # --- 出事了要说出来（别只写日志）---
    def alert(self, msg, level="warn", rel="", fix="", source="", kind="", options=None,
              locate=None, line=None):
        """给结果页挂一条**显眼的**提醒。

        为什么单独一套：日志在「日志」页，而跑完默认落在「结果」页 ——
        实测过：③ 拿着「0 个变量」的简报照样给出摘要、照样落盘，那条 warn 没人看得到。
        这类「解析不出来但假装成功」的事必须出现在人会看到的地方。

        source / kind 是给**知识库规则**用的：这条判定从哪来、属于行业惯例还是某家观点。
        研究员有权知道依据，也有权不认同——所以依据要摆在提醒里，而不是藏在代码里。

        options 是**可以直接点的选项**：每条形如
            {"label": 显示给人看的, "line": "原文 = 替换为", "hint": 说明}
        `line` 就是「自定义替换」那一栏要的一行 —— 研究员点一下，界面把它并进那个框，
        不用自己去记格式（研究员提的要求：「在提示处增加选项与自定义填写，必须带有 =」）。

        line / locate 是**跳转定位**（研究员提的：「加一个跳转到原文档对应位置直接查看的
        功能，自己翻原文档一行行找太要命了」）：
          · `line`   这条提醒说的是原文的第几行
          · `locate` {"file": "samples/x.txt", "line": 17} —— 点「看原文」直接翻到那一行
        界面据此给出「看原文第 N 行」的按钮，而不是让人自己去搜。
        """
        if not hasattr(self, "_alerts"):
            self._alerts = []
        item = {"msg": str(msg), "level": level}
        if rel:
            item["rel"] = str(rel)        # 界面据此给一个「打开这份文件」的按钮
        if fix:
            item["fix"] = str(fix)
        if source:
            item["source"] = str(source)
        if kind:
            item["kind"] = str(kind)
        if line:
            item["line"] = int(line)
        if locate and locate.get("file"):
            item["locate"] = {"file": str(locate["file"]),
                              "line": int(locate.get("line") or 1)}
            if not item.get("line"):
                item["line"] = item["locate"]["line"]
        if options:
            item["options"] = [o for o in options if isinstance(o, dict) and o.get("label")]
        # 这条提醒能不能"填进某个表单字段"？能就带上字段名，前端才摆那套替换输入框。
        # ⚠ 无条件摆过一次，结果 ③ 的"筛选题怎么写"提醒底下跟着去标识化的填法（前辈报的）。
        if getattr(self, "rules_field", ""):
            item["rules_field"] = self.rules_field
        self._alerts.append(item)
        self.log(str(msg), "error" if level == "error" else "warn")

    def alerts_from(self, items):
        """把一批判定结果（dict 列表）转成提醒。判定方只管给结论和依据。"""
        for it in (items or []):
            if not isinstance(it, dict) or not it.get("msg"):
                continue
            self.alert(it["msg"], it.get("level", "warn"), it.get("rel", ""),
                       it.get("fix", ""), it.get("source", ""), it.get("kind", ""),
                       it.get("options"), it.get("locate"), it.get("line"))

    def take_alerts(self):
        a = list(getattr(self, "_alerts", []) or [])
        self._alerts = []
        return a


def _guard_check(params, ctx):
    """直连 runner 时的脱敏守卫：素材没过 🔒 就提醒（不拦，只报警）。

    ⚠ 为什么是"提醒"而不是"拒绝"：工作台的一贯立场是**提示、不拦人**
      （研究员有权明知风险往下走）。但**必须让人看见** —— 所以落成一条 error 级 alert，
      而不是静默通过。
    """
    try:
        block_dir = params.get("block_dir") or ""
        bpath = os.path.join(os.path.dirname(block_dir), os.path.basename(block_dir), "block.py")
        # block.py 在组块目录里；从 block_dir 读它的声明
        decl_path = os.path.join(block_dir, "block.py")
        if not os.path.exists(decl_path):
            return
        spec = importlib.util.spec_from_file_location("urw_block_decl_guard", decl_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        block = getattr(mod, "BLOCK", None)
        if not isinstance(block, dict):
            return
        root = params.get("project_root") or os.getcwd()
        from core import guard as guard_mod
        g = guard_mod.guard_for(block, root, params)
        if g.get("need"):
            names = "、".join(m.get("rel") or m.get("name") or "?" for m in g["materials"][:5])
            ctx.alert("这个项目里有素材**还没过 🔒 去标识化**：%s" % names,
                      level="error", kind="internal",
                      fix="先去 🔒 把那几份材料脱敏，再回来跑这一步。"
                          "（如果你是明知风险要继续，那就在界面上确认一次；"
                          "直接调 runner 时这条只提示、不拦。）")
    except Exception as e:
        # 守卫自己坏了不能把引擎带崩 —— 但要留痕
        try:
            ctx.log("脱敏守卫没跑成（不影响本次）：%s" % e, "warn")
        except Exception:
            pass


def main():
    if len(sys.argv) < 2:
        emit({"t": "error", "msg": "runner 需要 job.json 参数"})
        return 2
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        params = json.load(f)

    block_dir = params.get("block_dir") or ""
    engine_name = params.get("engine") or "engine.py"
    engine_path = os.path.join(block_dir, engine_name)

    if not block_dir or not os.path.exists(engine_path):
        emit({"t": "error", "msg": "找不到引擎文件：%s" % engine_path})
        return 3

    ctx = Ctx(params)
    # 组块声明里如果有 `rules_field`（"这条提醒能往哪个框里填规则"，目前只有 🔒 有），
    # 就告诉 ctx —— 它会把字段名写进每条 alert，前端据此决定要不要摆那套替换输入框。
    # ⚠ 用 try 包住：别让"读声明"这件事把引擎带崩（读不到就当没有，前端自然会不摆）。
    try:
        import importlib.util as _ilu2
        _spec2 = _ilu2.spec_from_file_location("urw_alert_rules", os.path.join(block_dir, "block.py"))
        _mod2 = _ilu2.module_from_spec(_spec2)
        _spec2.loader.exec_module(_mod2)
        _rf = (getattr(_mod2, "BLOCK", None) or {}).get("rules_field")
        if _rf:
            ctx.rules_field = str(_rf)
    except Exception:
        pass
    # ⚠ **守卫在这里也要跑一次**。原来它只在 `server.py` 里执行 —— 界面走服务端所以没问题，
    #   但"直接调 runner"（测试脚手架、批处理脚本、以后可能有的命令行）会**整个绕过**它。
    #   而它守的是"素材还没过 🔒 就别拿去分析"：实测走查项目的 `samples/` 里确实有
    #   学号 + 手机号，绕过去就等于把没脱敏的材料喂进分析、产物再扩散出去。
    #   规矩：**安全相关的检查不能只写在一条调用路径上**。
    _guard_check(params, ctx)

    try:
        spec = importlib.util.spec_from_file_location("urw_engine", engine_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "run", None)
        if not callable(fn):
            emit({"t": "error", "msg": "engine.py 里没有 run(ctx) 函数"})
            return 4
        result = fn(ctx)
        if result is None:
            result = {}
        if isinstance(result, dict):
            result.setdefault("outputs", ctx.outputs)
            # 引擎跑完还留着的提醒，挂到结果上 —— 这样它会出现在「结果」页，而不是埋在日志里
            alerts = ctx.take_alerts()
            if alerts:
                result["alerts"] = list(result.get("alerts") or []) + alerts
        emit({"t": "result", "data": result})
        return 0
    except Exception as e:
        emit({"t": "error", "msg": "%s: %s" % (type(e).__name__, e)})
        for line in traceback.format_exc().splitlines():
            emit({"t": "log", "msg": line, "level": "error"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
