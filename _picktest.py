# -*- coding: utf-8 -*-
"""选路径（📁 浏览）· 自检

**不会真的弹框**——弹出来会占用前辈的屏幕。这里只做两件能自动验的事：
  1. 服务端生成的 PowerShell 脚本**语法合法**（用 PS 自己的解析器查，不执行）
  2. 从项目外面挑来的文件，能被正确拷进项目（重名加序号）

    python _picktest.py       （需要工作台服务在跑）
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BASE = "http://127.0.0.1:8765"
TMP = os.path.join(HERE, "_jobs", "tmp_pick")
PASS, FAIL = [], []


def ok(cond, label, extra=""):
    (PASS if cond else FAIL).append(label + ("" if cond else "  ← " + str(extra)))
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else "  ← " + str(extra)))


def post(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def ps_syntax_ok(script):
    """让 PowerShell 自己解析一遍（ParseFile 只解析、不执行）。"""
    os.makedirs(TMP, exist_ok=True)
    f = os.path.join(TMP, "check.ps1")
    with open(f, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(script)
    cmd = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
           "'%s',[ref]$null,[ref]$e); if($e.Count){$e | ForEach-Object { $_.Message }; exit 1}"
           " else { 'OK' }" % f.replace("'", "''"))
    p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, timeout=60)
    return p.returncode == 0, (p.stdout or b"").decode("utf-8", "replace").strip(), \
        (p.stderr or b"").decode("utf-8", "replace").strip()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=" * 70)
    print("一、生成的 PowerShell 脚本语法合法")
    print("=" * 70)
    for kind, title in (("file", "选择数据文件"), ("dir", "选择文件夹")):
        j = post("/api/pick", {"dry_run": True, "kind": kind, "title": title,
                               "start": "F:\\try\\用户研究",
                               "filter": "CSV (*.csv)|*.csv|所有文件 (*.*)|*.*"})
        ok(j.get("ok") and j.get("script"), "%s：脚本生成出来了" % kind, j.get("error"))
        good, out, err = ps_syntax_ok(j.get("script") or "")
        ok(good, "%s：PowerShell 解析通过" % kind, (out + err)[:200])
        script = j.get("script") or ""
        ok(title in script, "%s：标题带进去了（中文没乱码）" % kind)
        ok("WriteLine" in script, "%s：有把结果打到标准输出" % kind)

    # 引号注入：路径里带单引号也不能把脚本搞坏
    j = post("/api/pick", {"dry_run": True, "kind": "file", "title": "带'引号'的",
                           "start": "C:\\a'b", "filter": "x'|y"})
    good, out, err = ps_syntax_ok(j.get("script") or "")
    ok(good, "路径 / 标题里带单引号也不会把脚本搞坏", (out + err)[:200])

    print("")
    print("=" * 70)
    print("一之二、服务所在的会话能不能弹窗（不弹，只探）")
    print("=" * 70)
    pr = post("/api/pick", {"probe": True})
    if pr.get("can_pick"):
        ok(True, "服务能创建窗口 → 原生选择框弹得出来")
    else:
        ok(False, "服务这个会话里弹不出窗口 —— 用 workbench\\启动工作台.bat 重启一次就行",
           pr.get("why"))

    print("")
    print("=" * 70)
    print("二、项目外面的文件能拷进来")
    print("=" * 70)
    st = urllib.request.urlopen(BASE + "/api/state", timeout=30)
    state = json.loads(st.read().decode("utf-8"))
    # ⚠ 不能假设「一定有个当前项目」——服务端允许空栏。
    #   有就用它；没有就自己建一个临时项目，别去动人家的项目。
    if state.get("project"):
        root = state["project"]["root"]
        made_root = ""
        print("   当前项目：%s" % state["project"]["name"])
    else:
        made = post("/api/project/create", {"name": "_picktest_临时项目"})
        if not made.get("ok"):
            ok(False, "没项目、也建不出临时项目：%s" % made.get("error"))
            return 1
        root = made["project"]["root"]
        made_root = root                     # 自己建的，收尾要自己删掉
        print("   本来没选项目，临时建了一个：%s" % root)

    os.makedirs(TMP, exist_ok=True)
    src = os.path.join(TMP, "外面挑来的问卷.csv")
    with open(src, "w", encoding="utf-8") as f:
        f.write("变量,n\n满意度,1\n")

    r1 = post("/api/file/import", {"src": src})
    ok(r1.get("ok"), "拷进项目：ok", r1.get("error"))
    ok((r1.get("rel") or "").startswith("data/"), "落在 data/ 下", r1.get("rel"))
    target = os.path.join(root, (r1.get("rel") or "").replace("/", os.sep))
    ok(os.path.exists(target), "文件真的在项目里")
    ok(open(target, encoding="utf-8").read().startswith("变量,n"), "内容没变")

    r2 = post("/api/file/import", {"src": src})
    ok(r2.get("rel") != r1.get("rel"), "同名再拷一次不会覆盖，加了序号", r2.get("rel"))
    ok("(2)" in (r2.get("rel") or ""), "序号长这样：%s" % r2.get("rel"))

    r3 = post("/api/file/import", {"src": os.path.join(TMP, "根本没有这个文件.csv")})
    ok(not r3.get("ok"), "源文件不存在时报错而不是崩", r3.get("error"))

    r4 = post("/api/file/import", {"src": src, "sub": "../../../Windows"})
    ok(r4.get("ok") and (r4.get("rel") or "").startswith("data/"),
       "乱填存放目录时会落回 data/（越不了界）", r4.get("rel"))

    # 收拾干净
    for rel in (r1.get("rel"), r2.get("rel"), r4.get("rel")):
        if rel:
            p = os.path.join(root, rel.replace("/", os.sep))
            if os.path.exists(p):
                os.remove(p)
    print("   （测试拷进来的文件已清掉）")
    if made_root:
        # 自己建的临时项目，别留在别人的项目列表里
        post("/api/project/home", {"clear_project": True})
        shutil.rmtree(made_root, ignore_errors=True)
        print("   （临时项目已删，当前项目恢复成「空」）")

    print("")
    print("=" * 70)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for x in FAIL:
        print("  ❌ " + x)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
