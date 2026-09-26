# -*- coding: utf-8 -*-
"""多重比较总账 · 专项自检

它守的是「**做多了检验，假阳性概率会涨**」这条，以及"别让它自己改结论"。

    python _multipletest.py

为什么要专门测它：多重比较最容易被做错的两个方向 ——
  · 校得太松：等于没校，报告里写"已校正"是假的
  · 校得太狠：把真效应也压掉，然后以为"没发现"
  · 还有一个更隐蔽的：**登记簿漏记**（跑了 10 个只记了 5 个）→ 总账算出来偏乐观
所以这里既验算法（拿教科书例子对）、也验"记全了没有"。
"""
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    # 理论上到不了这里：项目要求 Python 3.7+，那时 reconfigure 一定存在。
    # 真到了这里说明 Python 太老 —— UTF-8 保护**没生效**，必须让人知道，
    # 不能"静静跳过"（那等于假装有保护）。
    print("[warn] Python too old: sys.stdout.reconfigure missing, "
          "the UTF-8 guard did NOT take effect (needs Python 3.7+)")
except Exception as _e:
    # 别的失败是 bug（比如编码名写错），要叫出来，不许静默
    print("[warn] stdout/stderr UTF-8 guard failed: %r" % (_e,))

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import multiple as M          # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, label, extra=None):
    if cond:
        PASS[0] += 1
        print("  [OK] " + label)
    else:
        FAIL[0] += 1
        print("  [!!] " + label + ("" if extra is None else "  —— %s" % (extra,)))


def main():
    print("=" * 72)
    print("【1】BH 的 FDR：拿确定性的例子对一遍（不许「看起来差不多」）")
    print("=" * 72)
    # 手工算过一遍的例子：m=15，只有第 1 个 p 满足 p(i) <= i/m*0.05
    #   rank1: 0.0010 <= 0.00333 ✓ ｜ rank2: 0.0080 > 0.00667 ✗
    #   所以 BH 在这里只拒绝 1 个。**这正是 BH 比 Bonferroni 宽、但比"不校正"严的地方。**
    ps = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212,
          0.216, 0.222, 0.251, 0.269, 0.275, 0.34]
    r = M.fdr_bh(ps, 0.05)
    ok(len(r["reject"]) == 1, "BH 拒绝 1 个（rank1 通过、rank2 不通过）", len(r["reject"]))
    ok(r["reject"] == [0], "拒绝的正是最小的那个", r["reject"])
    # 全体 p 都很小 → 应该全部拒绝（不能出现"一个都不拒"）
    r2 = M.fdr_bh([0.0001] * 5, 0.05)
    ok(len(r2["reject"]) == 5, "5 个 p 都极小 → 全部拒绝", len(r2["reject"]))

    print("\n" + "=" * 72)
    print("【2】Bonferroni：门槛 = α/m")
    print("=" * 72)
    b = M.bonferroni([0.01, 0.02, 0.03, 0.04, 0.05], 0.05)
    ok(abs(b["thr"] - 0.01) < 1e-12, "5 个检验 → 门槛 0.01", b["thr"])
    ok(b["reject"] == [0], "只有 p=0.01 那条刚好通过（<=）", b["reject"])

    print("\n" + "=" * 72)
    print("【3】总账描述的是事实，**不做决定**")
    print("=" * 72)
    ents = [{"label": "A（确认性）", "p": 0.001, "kind": "t", "n": 100},
            {"label": "B（确认性）", "p": 0.03, "kind": "corr", "n": 100},
            {"label": "C（探索性）", "p": 0.04, "kind": "corr", "n": 100,
             "exploratory": True}]
    c = M.correct(ents, 0.05)
    ok(c["total"] == 3 and c["n_confirm"] == 2 and c["n_explore"] == 1,
       "确认性/探索性分得清", (c["total"], c["n_confirm"], c["n_explore"]))
    ok(abs(c["familywise"] - (1 - 0.95 ** 3)) < 1e-9,
       "家族错误率 = 1−0.95^n（不是简单相加）", c["familywise"])
    ok("B（确认性）" in c["dropped_by_bonf"], "点名了哪条会掉出（Bonferroni）",
       c["dropped_by_bonf"])
    ok(c["bonferroni"]["thr"] < 0.05 and c["fdr"]["thr"] <= 0.05,
       "两种门槛都在合理范围", (c["bonferroni"]["thr"], c["fdr"]["thr"]))
    # 关键：总账**不许改 p 值**
    ok(all(e["p"] == p for e, p in zip(ents, [0.001, 0.03, 0.04])),
       "**总账不改任何 p 值**（只作陈述）")

    print("\n" + "=" * 72)
    print("【4】登记簿：跨调用累计 + 只登记有 p 的 + 坏数据不炸")
    print("=" * 72)
    tmp = tempfile.mkdtemp(prefix="urw_multi_")
    try:
        n1 = M.register(tmp, [{"label": "x", "p": 0.01, "kind": "t", "n": 10}])
        n2 = M.register(tmp, [{"label": "y", "p": 0.02, "kind": "t", "n": 10},
                              {"label": "z", "p": 0.03, "kind": "t", "n": 10}])
        led = M.load(tmp)
        ok(n1 == 1 and n2 == 2, "两次登记分别 +1 / +2", (n1, n2))
        ok(len(led["entries"]) == 3, "跨调用**累计**（不是覆盖）", len(led["entries"]))
        # 没算出 p 的（描述统计）不该进登记簿
        n3 = M.register(tmp, [{"label": "描述统计", "p": None, "kind": "describe"}])
        ok(n3 == 0 and len(M.load(tmp)["entries"]) == 3,
           "没 p 值的检验不进登记簿（它不是假设检验）", n3)
        # 坏输入不能把分析弄崩
        n4 = M.register(tmp, [None, "字符串", {"label": "无 p"}])
        ok(n4 == 0, "坏条目被忽略、不抛异常", n4)
        # 空登记簿 / 不存在的项目：load 要干净地返回空结构
        empty = M.load(os.path.join(tmp, "不存在的项目"))
        ok(empty["entries"] == [], "读不到就返回空结构（调用方不用判 None）")
        # reset 要把旧的**存档**而不是删掉
        rr = M.reset(tmp)
        ok(rr.get("ok") and os.path.exists(os.path.join(tmp, rr["backup"])),
           "reset 把旧的存进 _history（不直接删）", rr)
        ok(M.load(tmp)["entries"] == [], "reset 之后是空的")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 72)
    print("【5】人话总结：不能只给数字，要说清「这意味着什么」")
    print("=" * 72)
    lines = M.summarize(M.correct(ents, 0.05))
    txt = " ".join(lines)
    ok("假阳性" in txt, "提到了假阳性概率")
    ok("Bonferroni" in txt and "FDR" in txt, "两种校正都说到")
    ok("研究员的判断" in txt or "不做决定" in txt,
       "明说「校正不替用户改结论」——这条是它的性格")
    ok(M.summarize({"total": 0}) == [], "没有检验时不给一段空话")

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
