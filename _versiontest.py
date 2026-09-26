# -*- coding: utf-8 -*-
"""版本对比 · 专项自检

守的坑：历史版本一直在存（`_history/`），但**从来没人看得见**。
所以这里既要验"能列出来"，也要验"差异说得准"，还要验"打标签不动历史文件"。

跑法：  python _versiontest.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import versioning as V                     # noqa: E402
from core.project import Project                     # noqa: E402

PASS = [0]
FAIL = [0]


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


MD_V1 = """# 访谈提纲

## 1. 暖场
聊聊你今天怎么来的。

## 2. 主问题
### 2.1 使用习惯
你平时怎么用这个 App？

## 4. 收尾
还有什么想说的吗？
"""

MD_V2 = """# 访谈提纲

## 1. 暖场
聊聊你今天怎么来的。

## 2. 主问题
### 2.1 使用习惯
你平时怎么用这个 App？
追问：能说一次你具体这么做的时候吗？

### 2.2 价格敏感度
你上次为这个花过钱是什么时候？

## 4. 收尾
还有什么想说的吗？
"""

CSV_V1 = "变量名,角色,测量层次\n付费意愿,因变量,定序\n功能认知,自变量,定类\n"
CSV_V2 = "变量名,角色,测量层次\n付费意愿,因变量,定序\n价格敏感度,自变量,定序\n"


def mk_hist(proj, rel, text, stamp):
    """手工造一个历史版本（照 runner 的命名法）。"""
    hdir = proj.safe("_history")
    os.makedirs(hdir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(rel))
    name = "%s_%s%s" % (stem, stamp, ext)
    with open(os.path.join(hdir, name), "w", encoding="utf-8") as f:
        f.write(text)
    return name


def main():
    root = tempfile.mkdtemp(prefix="urw_ver_")
    try:
        proj = Project(root)
        proj.ensure()
        os.makedirs(proj.safe("contracts"), exist_ok=True)
        md_rel = "contracts/interview_guide.md"
        csv_rel = "contracts/变量表.csv"

        print("\n【1】列版本：当前版 + 历史，新的在前")
        n1 = mk_hist(proj, md_rel, MD_V1, "20260920_100000")
        time.sleep(1.1)
        n2 = mk_hist(proj, md_rel, MD_V2, "20260921_100000")
        proj.write_text(md_rel, MD_V2)
        # 造一个别的文件的版本，确认不会混进来
        mk_hist(proj, "contracts/研究简报.md", "# 别的文件\n", "20260921_110000")

        vs = V.list_versions(proj, md_rel)
        names = [v["name"] for v in vs]
        ok(len(vs) == 3, "当前版 + 2 个历史（%d 个）" % len(vs), names)
        eq(vs[0]["kind"], "current", "当前版排在最前")
        eq(names[0], "interview_guide.md", "第一个是当前版")
        ok("研究简报" not in json.dumps(names, ensure_ascii=False),
           "别的文件的历史没混进来", names)
        ok(vs[0]["at"] and vs[-1]["at"], "每个版本都有时间")
        ok(vs[-1]["lines"] > 0, "记了行数")

        print("\n【2】md 差异：按小节对齐，说清增/删/改")
        d = V.diff_versions(proj, md_rel, n1, n2)      # 旧的 → 新的
        ok(d.get("ok"), "对比能出结果", d.get("error"))
        eq(d["kind"], "md", "md 文件走小节粒度")
        st = {s["title"]: s["status"] for s in d["sections"]}
        ok("### 2.2 价格敏感度" in st, "认出了新增的小节", list(st.keys()))
        eq(st.get("### 2.2 价格敏感度"), "新增", "2.2 是新增")
        eq(st.get("### 2.1 使用习惯"), "改动", "2.1 被改了")
        ok(st.get("## 1. 暖场") is None, "没动的小节不该出现（不啰嗦）")
        eq(d["summary"]["added"], 1, "新增小节数对")
        eq(d["summary"]["changed"], 1, "改动小节数对")

        print("\n【3】表格差异：按行（变量）比对")
        mk_hist(proj, csv_rel, CSV_V1, "20260920_100000")
        proj.write_text(csv_rel, CSV_V2)
        t = V.diff_versions(proj, csv_rel, "变量表_20260920_100000.csv", "变量表.csv")
        eq(t["kind"], "table", "csv 文件走行粒度")
        eq(t["added"], ["价格敏感度"], "新增的变量认出来了")
        eq(t["removed"], ["功能认知"], "删掉的变量认出来了")

        print("\n【4】方向不能反：旧→新 和 新→旧 要不一样")
        back = V.diff_versions(proj, md_rel, n2, n1)
        bst = {s["title"]: s["status"] for s in back["sections"]}
        eq(bst.get("### 2.2 价格敏感度"), "删除", "反过来看，2.2 就是删掉的")

        print("\n【5】打标签：只写旁挂 json，历史文件本身不动")
        before = open(proj.safe("_history/" + n2), encoding="utf-8").read()
        before_mt = os.path.getmtime(proj.safe("_history/" + n2))
        r = V.set_label(proj, n2, label="第 2 轮：加了价格敏感度", note="第 3 位受访者提到定价")
        ok(r.get("ok"), "标签打上了", r)
        after = open(proj.safe("_history/" + n2), encoding="utf-8").read()
        eq(after, before, "历史文件内容一字节没变")
        eq(os.path.getmtime(proj.safe("_history/" + n2)), before_mt, "历史文件的修改时间也没变")
        vs2 = V.list_versions(proj, md_rel)
        hit = [v for v in vs2 if v["name"] == n2][0]
        eq(hit["label"], "第 2 轮：加了价格敏感度", "列表里能看到标签")
        eq(hit["note"], "第 3 位受访者提到定价", "备注也带出来了")
        ok(os.path.exists(proj.safe(V.LABELS_REL)), "标签存在 _history/版本说明.json")

        print("\n【6】没打标签时，程序给个事实型的默认说法")
        vs3 = V.list_versions(proj, md_rel)
        cur = vs3[0]
        eq(cur["label"], "当前版本", "当前版的默认标签")
        ok([v for v in vs3 if v["kind"] == "history"][0]["at"], "历史版至少有时间，不是空白")

        print("\n【7】导出成 markdown：能直接写「这一轮为什么改」")
        md = V.diff_to_markdown(md_rel, d)
        ok("版本对比" in md and "新的" in md, "导出的标题和版本信息在")
        ok("新增 1 个小节" in md, "摘要写的是小节级（不是行级噪音）", md[:300])
        ok("这一轮为什么改" in md, "留了「为什么改」的位置给人写")
        ok("价格敏感度" in md, "具体改了什么都列出来了")

        print("\n【8】边界：找不到的版本、不存在的文件")
        bad = V.diff_versions(proj, md_rel, "不存在.md", n1)
        ok(not bad.get("ok"), "版本找不到时说清，不炸", bad.get("error"))
        eq(V.list_versions(proj, "contracts/没有这个文件.md"), [], "文件不存在 → 空列表，不炸")
        eq(V.set_label(proj, "不存在的历史.md", "x").get("ok"), False, "给不存在的版本打标签 → 拒绝")

        print("\n【9】历史很长时也要稳（50 个版本）")
        for i in range(50):
            mk_hist(proj, md_rel, MD_V1 + "\n<!-- %d -->\n" % i, "202601%02d_120000" % (i + 1))
        vs4 = V.list_versions(proj, md_rel)
        ok(len(vs4) >= 50, "50+ 个版本都列得出来（%d）" % len(vs4))
        ok(vs4[0]["kind"] == "current", "加了这么多历史，当前版仍在最前")

        print("\n【10】同一秒里连改两次：两版都要留得下来（不能撞名）")
        # 现场：在界面上手改产物、连点两下保存 —— 备份名用秒级时间戳，
        # 两个备份撞名，后一个把前一个覆盖了，中间那一版永久丢了。
        from core.project import unique_hist_name
        hdir = proj.safe("_history")
        os.makedirs(hdir, exist_ok=True)
        n1 = unique_hist_name(hdir, "output/脱敏_测试.txt")
        with open(os.path.join(hdir, n1), "w", encoding="utf-8") as f:
            f.write("第一版\n")
        n2 = unique_hist_name(hdir, "output/脱敏_测试.txt")
        ok(n2 != n1, "同一秒里第二个名字不一样（%s vs %s）" % (n1, n2), n2)
        ok(n2.endswith(".txt"), "后缀还在：%s" % n2)
        # 名字还得能被版本解析认出来，否则列不进版本列表（这个也踩过）
        ok(V._pair(n2, "脱敏_测试.txt")[0] == "脱敏_测试.txt",
           "带防撞号的名字仍然解析得出原文件名", V._pair(n2, "脱敏_测试.txt"))
        ok(bool(V._pair(n2, "脱敏_测试.txt")[1]), "也解析得出时间戳")
    finally:
        shutil.rmtree(root, ignore_errors=True)

        print("\n【11】接口必须听 `project` 参数（真环境，需要服务在跑）")
        # 守的坑：新加的项目级接口直接用了「当前项目」，于是 ?project=别的项目 被无视，
        # 永远读当前那个 —— 返回 ok、数据却是另一个项目的，**静默答错**。
        try:
            import urllib.request

            def _get(p):
                with urllib.request.urlopen("http://127.0.0.1:8765" + p, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))

            st = _get("/api/state")
            # ⚠ 别假设「一定有当前项目」—— 服务端允许空栏（没选项目是合法状态）。
            #   没选就用列表里的第一个项目来比；连一个项目都没有就没法验这条。
            allp = [p["root"] for p in (st.get("projects") or [])]
            if st.get("project"):
                cur = st["project"]["root"]
            elif allp:
                cur = allp[0]
                print("     （当前没选项目，拿列表里第一个来比：%s）" % os.path.basename(cur))
            else:
                ok(False, "一个项目都没有，验不了这条")
                return 0
            others = [r for r in allp if r != cur]
            if not others:
                ok(False, "需要至少两个项目才能验这条（现在只有一个）")
            else:
                # ⚠ 别随手挑一份文件就比 —— 项目一多，随手挑到的可能两边都没历史，
                #   「1 vs 1」就看不出接口听不听参数（第一版这么写，误报过一次）。
                #   先扫出「在这份文件上两个项目确实不同」，再拿它断言。
                def count(root, rel):
                    j = _get("/api/versions?rel=" + urllib.parse.quote(rel)
                             + "&project=" + urllib.parse.quote(root))
                    return len(j.get("versions") or []) if j.get("ok") else -1

                probe = ["contracts/coded_transcript.md", "contracts/research_brief.md",
                         "output/编码汇总.md", "contracts/interview_guide.md",
                         "contracts/survey_design.md"]
                ok(all(count(cur, r) >= 0 for r in probe), "两个项目都问得出结果（接口是通的）")
                found = None
                for rel in probe:
                    a, b = count(cur, rel), count(others[0], rel)
                    if a != b:
                        found = (rel, a, b)
                        break
                if found:
                    rel, a, b = found
                    ok(True, "换 project 参数 → 结果跟着换（%s：%d vs %d），没有无视参数"
                       % (rel.split("/")[-1], a, b))
                else:
                    ok(False, "候选文件在两个项目里的版本数全一样，这条断言区分不出"
                              "「接口对」和「接口无视参数」——换个项目再跑")
                ghost = urllib.parse.quote("contracts/没有这个文件.md")
                j2 = _get("/api/versions?rel=" + ghost + "&project="
                          + urllib.parse.quote(others[0]))
                ok(j2.get("ok") and j2.get("versions") == [], "不存在的文件 → 空列表，不报错")
        except Exception as e:
            ok(False, "接口测试需要工作台在跑（%s）" % e)

    print("\n" + ("全部通过" if FAIL[0] == 0 else "有失败项") + "：%d 通过 / %d 失败\n"
          % (PASS[0], FAIL[0]))
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
