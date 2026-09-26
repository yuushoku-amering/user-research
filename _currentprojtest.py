# -*- coding: utf-8 -*-
"""当前项目 / 空栏 · 真环境测试（需要服务在跑）

守三个坑：

  1. config.json 在磁盘上被改过，运行中的服务却把旧值缓存在内存里，界面一刷新
     又把旧值写回去 —— 外面改的东西白改了。
  2. **空值兜底**：`load_config` 里原来有一句 `if not project_root: 填默认值`，
     看着是"别让配置空着"，实际让「没选项目」在配置层面根本表达不出来 ——
     清空之后一读又变回项目之家，界面把历史目录当项目用，产物落错地方还看不出来。
  3. 记着的项目不见了 / 不是项目（比如项目之家自己）→ 要照实说，不悄悄换别的项目。

跑法（先启动工作台）：
    python _currentprojtest.py

**会动到 config.json 的 project_root**；用的是临时项目。
原值如果不是真项目，收尾恢复成「空」而不是原样写回去。

⚠ **前提**：跑之前配置里得有一个**真项目**（或者服务端正开着一个）。
  这个测试会临时清空当前项目，跑完要恢复回去；没有可恢复的目标就**直接不跑**——
  宁可跑不了并说清原因，也不要"跑完了、前辈的项目没了"。
  （2026-09-26 踩过：判"真项目"用的是 `project.json` 存在与否，比服务端那把尺子严，
   把 `projects/_脱敏格式演示` 这种合法项目当成坏值 → 收尾清空配置 → 界面显示"没选项目"。）
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import paths                                     # noqa: E402

BASE = "http://127.0.0.1:8765"
CFG = paths.CONFIG_FILE

PASS = [0]
FAIL = [0]


def _is_temp_path(p):
    """这个路径在系统临时目录里吗（和 server 里那条判据同一个实现）。"""
    try:
        return paths.is_temp_path(p)
    except Exception:
        import tempfile as _tf
        try:
            t = os.path.normcase(os.path.abspath(p or ""))
            b = os.path.normcase(os.path.abspath(_tf.gettempdir()))
            return bool(t) and (t == b or t.startswith(b + os.sep))
        except Exception:
            return False


def ok(cond, label, extra=None):
    if cond:
        PASS[0] += 1
        print("  [OK] " + label)
    else:
        FAIL[0] += 1
        print("  [!!] " + label + ("" if extra is None else "  —— %s" % (extra,)))


def eq(a, b, label):
    same = a == b
    ok(same, label, None if same else "实际 %r，期望 %r" % (a, b))


def get(p):
    with urllib.request.urlopen(BASE + p, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def post(p, d):
    q = urllib.request.Request(BASE + p, data=json.dumps(d).encode("utf-8"),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(q, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 服务端拒绝是 HTTP 400 + {"ok":false,"error":...}。
        # **要把 body 解析出来**：不然调用方拿到的是 None，断言就会说"理由说得清：None"，
        # 看着像服务端没给理由，其实是这里没读。
        raw = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(raw)
            j.setdefault("http_error", e.code)
            return j
        except Exception:
            return {"http_error": e.code, "error": raw[:200], "ok": False}


def write_cfg_root(root):
    """直接改磁盘上的 config.json（模拟「人在外面改了配置」）。"""
    with open(CFG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["project_root"] = root
    with open(CFG, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    time.sleep(1.1)          # 让 mtime 明显不同（文件系统时间戳精度不一）


def main():
    try:
        st = get("/api/state")
    except Exception as e:
        print("服务没起来？先启动工作台。%s" % e)
        return 2

    # 原来的项目设置**从配置文件读**（别从 /api/state 读：现在没选项目时它是空的，
    # 而且服务端允许「空栏」，测试不该假设一定有个当前项目）
    cfg0 = json.load(open(CFG, encoding="utf-8"))
    home = cfg0.get("base_root") or paths.DEFAULT_PROJECT_ROOT
    original = cfg0.get("project_root") or ""
    # ⚠ 收尾要恢复成一个**说得通的值**：原值如果不是真项目（比如历史遗留的项目之家），
    #   就别原样写回去 —— 那等于让测试跑完在配置里留一个"不是项目的路径"，
    #   下次界面就顶着一条红条说"这不是研究项目"（踩过，还是我手动正回来的）。
    #   不是真项目 → 恢复成「空」。
    #
    # ⚠⚠ 但判"是不是真项目"**必须用服务端自己那一套**（`server._is_real_project`），
    #    不能用「有没有 project.json」：
    #      2026-09-26 实测踩到 —— `projects/_脱敏格式演示` 是工作台自己建的，
    #      **没有 project.json**，但它在服务器眼里是正经项目。
    #      本文件原来按 project.json 判，于是把一个**合法项目**当成坏值 → `original=""`
    #      → 收尾走 `clear_project` → **config 里的当前项目被清空**。
    #      两次批量回归之后，前辈打开界面看到的就是「没选项目」，
    #      而那个项目其实好好的躺在 projects/ 下面 —— 项目被测试"弄丢"了。
    #    所以这里统一用服务器那把尺子，并且**在开跑前就拒绝在不健康的状态下跑**。
    try:
        sys.path.insert(0, HERE)
        import server as _srv                       # noqa: E402
        _is_proj = _srv._is_real_project
    except Exception:
        _is_proj = lambda p: bool(p) and os.path.exists(os.path.join(p, "project.json"))

    if original and not _is_proj(original):
        print("   注意：配置里的 project_root（%s）不是真项目，收尾会恢复成「空」" % original)
        original = ""

    # ⚠ **前提检查**：这个测试会让"当前项目"暂时消失（它要验"清空之后真的是空的"）。
    #   所以它只该在"配置本来就健康"时跑 —— 否则一旦跑到一半出错，
    #   收尾就再也没有可恢复的目标，只能留一个空配置，等于把前辈正在用的项目弄丢。
    #   宁可**跑不了**并说清楚为什么，也不要"跑完了、项目没了"。
    if not original:
        cur = ""
        try:
            cur = (get("/api/state").get("project") or {}).get("root") or ""
        except Exception:
            pass
        if not _is_proj(cur):
            print("")
            print("  !! 现在没有可恢复的当前项目（配置里是空的，服务端也没开着项目）。")
            print("     这个测试会临时清空当前项目，跑完必须有个目标恢复回去 ——")
            print("     没目标就不跑，免得把项目弄丢。")
            print("     请先在界面上选一个项目（或跑 `_picktest.py` 恢复一次），再跑本测试。")
            return 2
        original = cur
    pparent = os.path.join(home, "projects")

    a = os.path.join(pparent, "_当前项目测试A")
    b = os.path.join(pparent, "_当前项目测试B")
    try:
        print("\n【0】准备两个临时项目")
        for p in (a, b):
            r = post("/api/project/create", {"name": os.path.basename(p)})
            ok(r.get("ok"), "建出 %s" % os.path.basename(p), r)
        ok(os.path.isdir(a) and os.path.isdir(b), "两个临时项目都在")

        print("\n【1】通过接口切到 A —— 内存和配置都该是 A")
        post("/api/project/open", {"root": a})
        eq(get("/api/state")["project"]["root"], a, "接口返回 A")
        eq(json.load(open(CFG, encoding="utf-8"))["project_root"], a, "config 里也是 A")

        print("\n【2】直接在磁盘上把 config 改成 B（模拟外部改动）")
        write_cfg_root(b)
        got = get("/api/state")["project"]["root"]
        eq(got, b, "**不重启**，接口立刻认了外部改动（B）")
        ok(json.load(open(CFG, encoding="utf-8"))["project_root"] == b,
           "而且没有把旧值写回去（这正是原来出错的地方）")

        print("\n【3】通过接口切回 A —— 接口说话仍然算数")
        post("/api/project/open", {"root": a})
        eq(get("/api/state")["project"]["root"], a, "切回 A")
        eq(json.load(open(CFG, encoding="utf-8"))["project_root"], a, "config 也是 A")

        print("\n【4】config 指向一个不存在/不是项目的目录时：**照实回报**，不悄悄换别的项目")
        # 行为变过：以前这里会静默退回默认目录，界面一回写就把配置覆盖了，
        # 「项目不见了」变成「项目悄悄换了」。现在改成：返回带 missing_root 的项目对象 +
        # 一条说得清的 error，由人来定 —— 所以断言也跟着变。
        ghost = os.path.join(pparent, "_不存在的项目_测试")
        write_cfg_root(ghost)
        st = get("/api/state")
        ok(st.get("no_project") and not st.get("project"),
           "项目栏留空（不把那个不存在的路径当当前项目发出去）",
           str(st.get("project"))[:60])
        eq(st.get("missing_root"), ghost, "把原路径带出来，好让人知道是哪个不见了")
        ok(bool(st.get("error")), "给了一条说得清的错误：%s" % str(st.get("error"))[:56])
        ok("不见了" in str(st.get("error") or "") or "不是" in str(st.get("error") or ""),
           "错误文案讲的是「不见了 / 不是项目」")

        print("\n【5】项目之家那一层自己不算项目")
        home = cfg0.get("base_root") or paths.DEFAULT_PROJECT_ROOT
        write_cfg_root(home)
        st2 = get("/api/state")
        p2 = st2.get("project") or {}
        ok(p2.get("missing_root") == home or st2.get("no_project"),
           "把项目之家当项目设进去 → 被识破（不是照单全收）",
           str(p2.get("missing_root") or st2.get("no_project"))[:60])
        ok(json.load(open(CFG, encoding="utf-8"))["project_root"] == home,
           "而且没有偷偷改成别的项目（配置保持人写的那个值）")

        print("\n【6】清空之后要**真的是空的**（配置层不许兜底填回默认项目）")
        # 守的坑：load_config 里原来有 `if not project_root: cfg[...] = 默认项目`。
        # 于是「没选项目」根本表达不出来 —— 清了又回来，界面把项目之家当项目用。
        post("/api/project/home", {"clear_project": True})
        cfg_now = json.load(open(CFG, encoding="utf-8"))
        ok(not cfg_now.get("project_root"), "config 里 project_root 是空的",
           repr(cfg_now.get("project_root")))
        st3 = get("/api/state")
        ok(st3.get("no_project") and not st3.get("project"), "接口也报「没选项目」",
           str(st3.get("project"))[:60])
        try:
            sys.path.insert(0, HERE)
            from core import paths as _paths
            eq(_paths.load_config().get("project_root") or "", "",
               "load_config 不会把空值兜底成默认项目")
        except Exception as e:
            ok(False, "读 paths.load_config 失败：%s" % e)

        print("\n【7】没选项目时不许开跑（产物总得有地方落）")
        r = post("/api/run", {"block_id": "b0_brief", "params": {}})
        ok(not r.get("ok"), "开跑被拒")
        ok("还没选项目" in str(r.get("error") or ""),
           "理由说得清：%s" % str(r.get("error"))[:46])

        print("\n【7b】「无意把当前项目清了」要能**找回来**（最近项目流水）")
        # 守的坑（2026-09-24 实测踩到）：【6】把当前项目清空之后，
        #   收尾想恢复才发现"原来配置里本来就是空的" —— 于是**研究员当时正开着的那个项目丢了**，
        #   界面只剩空栏（紧接着跑 _apitest 就直接报"现在没有当前项目"）。
        #   现在有了「最近项目」流水：切过的项目只留路径、最多 20 条、临时目录不记。
        try:
            sys.path.insert(0, HERE)
            import server as _srv                     # noqa: E402
            rec = _srv.recent_projects()
            ok(isinstance(rec, list), "能读出「最近项目」流水（%d 条）" % len(rec))
            # ⚠ 这里只能验「**系统临时目录**里的项目不进流水」——
            #   本测试自己建的 `_当前项目测试A/B` 是**真项目**（就在项目之家里，
            #   有 project.json），服务端无从知道它是一次性的、也不该去猜名字。
            #   早先写成了"凡带 '_当前项目测试' 字样就不许进"，那是把测试的实现细节
            #   当成产品要求了（测试自己红了）。真正的产品要求见下面 server 里的注释：
            #   临时目录 = 天生一次性 = 不记。
            ok(not any(_is_temp_path(x) for x in rec),
               "系统临时目录里的项目**不进**流水", [os.path.basename(x) for x in rec])
            ok(all(os.path.isdir(x) for x in rec), "流水里只留还存在的目录")
            ok(len(rec) <= 20, "流水有上限（最多 20 条），不会无限膨胀", len(rec))
            # 顺带直接验服务端那条判据本身
            import tempfile as _tf
            tmpdir = _tf.mkdtemp(prefix="urw_recent_")
            try:
                _srv._note_recent_project(tmpdir)
                ok(not any(os.path.normcase(x) == os.path.normcase(tmpdir)
                           for x in _srv.recent_projects()),
                   "临时目录即使被显式记一次，也不会留在流水里")
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            ok(False, "读「最近项目」失败：%s" % e)

        print("\n【8】切到**系统临时目录**里的项目：能用，但**不许记进 config.json**")
        # 守的坑（2026-09-24 实测踩到，代价很实在）：
        #   `_apitest.py` 第 7 步在一个临时项目上跑了一次 ⑤ 来验「回退也要过脱敏守卫」，
        #   而 `/api/run` → `set_project()` 会把当前项目**顺手写进 config.json**。
        #   那个临时目录随后被测试自己 `rmtree` 删掉 → 下次启动界面顶着「记着的项目不见了」、
        #   项目栏空着，**研究员原来在用的项目被静默挤掉了**，他还不知道为什么。
        #   临时项目天生一次性，记它没有意义：能切、能跑，但一个字都不写进配置。
        post("/api/project/open", {"root": a})          # 先落在一个正常值上
        cfg_before = json.load(open(CFG, encoding="utf-8")).get("project_root")
        tmp = tempfile.mkdtemp(prefix="urw_probe_")
        try:
            os.makedirs(os.path.join(tmp, "samples"), exist_ok=True)
            r = post("/api/project/open", {"root": tmp})
            ok(r.get("ok"), "临时项目能切过去（不是拒绝，只是不记）", r)
            eq(get("/api/state")["project"]["root"], tmp, "本次会话里它就是当前项目")
            cfg_after = json.load(open(CFG, encoding="utf-8")).get("project_root")
            eq(cfg_after, cfg_before,
               "config.json 里**没有被写进临时路径**（原来在用的项目没被挤掉）")
            ok(not paths.is_temp_path(cfg_after or ""),
               "配置里的当前项目仍然是一个正常路径：%s" % cfg_after)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        print("\n【收尾】恢复原来的项目设置，删掉两个临时项目")
        # ⚠ 恢复目标要按这个顺序找，**别只看 config 里的原值**：
        #   这个测试会验「清空之后真的是空的」，清完 config 里就是空的了；
        #   如果跑之前 config 本来就是空的（比如上一次测试留下的状态），
        #   收尾就只能恢复成"空"—— 而研究员**当时明明开着某个项目**，等于被测试弄丢了。
        #   （2026-09-24 实测踩到：api 自测随后就报"现在没有当前项目"。）
        #   所以：内存里正开着的 > 配置里的原值 > 「最近项目」流水。
        target = ""
        try:
            cur = get("/api/state").get("project") or {}
            if cur.get("root") and os.path.isdir(cur["root"]) \
                    and not cur["root"].startswith(pparent + os.sep + "_当前项目测试"):
                target = cur["root"]
        except Exception:
            pass
        if not target:
            target = original
        if not target:
            try:
                sys.path.insert(0, HERE)
                import server as _srv          # noqa: E402
                for r in _srv.recent_projects():
                    if not r.startswith(pparent + os.sep + "_当前项目测试"):
                        target = r
                        break
                if target:
                    print("  配置里本来就是空的 —— 从「最近项目」里找回：%s" % target)
            except Exception as e:
                print("  读「最近项目」失败：%s" % e)
        try:
            if target:
                write_cfg_root(target)
                post("/api/project/open", {"root": target})
                print("  已恢复：" + target)
            else:
                # 真的没有可恢复的项目 → 恢复成「空」，
                # 别在配置里留一个"不是项目的路径"，那会让界面顶着红条。
                post("/api/project/home", {"clear_project": True})
                print("  已恢复成「没选项目」（确实没有可恢复的项目）")
        except Exception as e:
            print("  恢复失败（请手动看一眼 config.json）：%s" % e)
        for p in (a, b):
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
        print("  两个临时项目已删")

    print("\n" + ("全部通过" if FAIL[0] == 0 else "有失败项") + "：%d 通过 / %d 失败\n"
          % (PASS[0], FAIL[0]))
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
