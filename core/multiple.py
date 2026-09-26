# -*- coding: utf-8 -*-
"""工作台 · 检验登记簿 + 多重比较

**为什么需要它**

    做了几个检验，就该知道"至少撞上一个假阳性"的概率有多大：
    1 个 = 5%，5 个 ≈ 23%，10 个 ≈ 40%（`1 - 0.95^n`）。
    这不是"作弊才会有的问题"——老老实实做 10 个检验就有四成概率至少一个是假的。

    但更常见的毛病是**根本不知道跑过几个**：研究员在界面上点了几次分析、
    每次里面又做了几件事，谁也没数。所以第一件事是**如实登记**，
    第二件事才是决定要不要校正。

**怎么用**

    from core import multiple

    multiple.register(project_root, [
        {"label": "H2 生活费→支出", "kind": "pearson", "p": 3.2e-09, "n": 539,
         "exploratory": False},
        {"label": "生活费 × 支出（Spearman）", "kind": "spearman", "p": 1.5e-91,
         "n": 539, "exploratory": False},
    ])
    led = multiple.load(project_root)
    corp = multiple.correct(led["entries"])
    multiple.reset(project_root)

**两个刻意的设计**

1. **只登记、不自动改结论。** 登记簿不会把某个 p 值"改掉"——它只告诉你
   "按这个门槛，哪几条会掉出显著"。改结论是研究员的判断。
2. **区分确认性 / 探索性。** 事先定好的假设（H1–H5）算**确认性**，
   不强制校正（防止把真效应压掉）；事后翻数据翻出来的组合算**探索性**，
   默认按 FDR 校正（探索本来就该更严）。
"""

import json
import os
import time

LEDGER_REL = "output/检验登记簿.json"

NOTE = ("这份登记簿 = 「这个项目一共跑过哪些检验」的流水。"
        "它不会被自动清掉（可复现性的一部分）；删掉它就重新开始计数。")


# --------------------------------------------------------------------------- #
# 存取
# --------------------------------------------------------------------------- #

def _path(project_root):
    return os.path.join(project_root, "output", "检验登记簿.json")


def load(project_root):
    """读登记簿。没有 / 读坏了都返回空结构（调用方不用判 None）。"""
    p = _path(project_root)
    if not os.path.exists(p):
        return {"entries": [], "note": NOTE}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
            return {"entries": [], "note": NOTE}
        d.setdefault("note", NOTE)
        return d
    except Exception:
        return {"entries": [], "note": NOTE}


def register(project_root, entries, source=""):
    """把本次跑过的检验登进去。`entries` 是 list[dict]。

    ⚠ 登记失败**不能**把分析弄崩 —— 这一步是"记录"，不是"计算"。
      所以整个函数包在 try 里，异常只往 stdout 说一句。
    """
    try:
        led = load(project_root)
        stamp = time.strftime("%Y-%m-%d %H:%M")
        added = 0
        for e in (entries or []):
            if not isinstance(e, dict):
                continue
            if e.get("p") is None:
                continue          # 没算出 p 的（描述统计之类）不进登记簿
            rec = {
                "at": stamp,
                "source": source or e.get("source") or "",
                "label": str(e.get("label") or "")[:120],
                "kind": str(e.get("kind") or "")[:40],
                "p": float(e["p"]),
                "n": int(e["n"]) if e.get("n") is not None else None,
                "exploratory": bool(e.get("exploratory")),
            }
            led["entries"].append(rec)
            added += 1
        if not added:
            return 0
        led["note"] = NOTE
        p = _path(project_root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(led, f, ensure_ascii=False, indent=2)
        return added
    except Exception as e:
        print("[warn] 检验登记没写成（不影响本次分析）：%s" % e)
        return 0


def reset(project_root):
    """清空登记簿（换研究问题 / 重新开始计数时用）。

    ⚠ 旧的那份**不删**，挪去 `_history` —— 它属于"跑过什么"的证据。
    """
    p = _path(project_root)
    if not os.path.exists(p):
        return {"ok": False, "error": "还没有登记簿"}
    try:
        hdir = os.path.join(project_root, "_history")
        os.makedirs(hdir, exist_ok=True)
        back = os.path.join(hdir, "检验登记簿_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
        os.replace(p, back)
        return {"ok": True, "backup": os.path.relpath(back, project_root).replace("\\", "/")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------- #
# 多重比较
# --------------------------------------------------------------------------- #

def bonferroni(pvals, alpha=0.05):
    """Bonferroni：门槛 = α/m。最保守，检验数少时用。"""
    m = len(pvals)
    if m == 0:
        return {"method": "bonferroni", "m": 0, "thr": alpha, "reject": []}
    thr = alpha / m
    return {"method": "bonferroni", "m": m, "thr": thr,
            "reject": [i for i, p in enumerate(pvals) if p <= thr]}


def fdr_bh(pvals, alpha=0.05):
    """Benjamini-Hochberg 的 FDR（控制"显著结果里假阳性的比例"）。

    步骤：p 值升序排 → 找最大的 i 使 `p(i) <= i/m * α` → 它和它前面全部算显著。
    比 Bonferroni 宽松得多（检验多的时候尤其明显），代价是允许一定比例的假阳性。

    ⚠ 返回的是**下标**（对应传进来的顺序），不是排过序的顺序。
    """
    m = len(pvals)
    if m == 0:
        return {"method": "fdr_bh", "m": 0, "thr": alpha, "reject": []}
    order = sorted(range(m), key=lambda i: pvals[i])
    kmax, thr_at_kmax = 0, 0.0
    for rank, i in enumerate(order, start=1):
        crit = rank / float(m) * alpha
        if pvals[i] <= crit:
            kmax, thr_at_kmax = rank, crit
    reject = order[:kmax]
    return {"method": "fdr_bh", "m": m, "thr": thr_at_kmax, "reject": reject,
            "sorted": order}


def correct(entries, alpha=0.05):
    """对一批检验做总账。返回一个**只描述事实**的 dict。

    这里刻意**不做任何自动决定**：不算"哪个方法是主结果"、不改任何 p 值。
    它只回答：「共几个检验、按 Bonferroni / FDR 各是什么门槛、哪几条会掉出去」。
    """
    ents = [e for e in (entries or []) if isinstance(e, dict) and e.get("p") is not None]
    conf = [e for e in ents if not e.get("exploratory")]
    expl = [e for e in ents if e.get("exploratory")]

    out = {
        "total": len(ents), "n_confirm": len(conf), "n_explore": len(expl),
        "alpha": alpha,
        "familywise": 1 - (1 - alpha) ** len(ents) if ents else 0.0,
        "bonferroni": bonferroni([e["p"] for e in ents], alpha),
        "fdr": fdr_bh([e["p"] for e in ents], alpha),
        "dropped_by_bonf": [], "dropped_by_fdr": [],
    }
    bon_set = set(out["bonferroni"]["reject"])
    fdr_set = set(out["fdr"]["reject"])
    naively_sig = [i for i, e in enumerate(ents) if e["p"] <= alpha]
    for i in naively_sig:
        if i not in bon_set:
            out["dropped_by_bonf"].append(ents[i].get("label"))
        if i not in fdr_set:
            out["dropped_by_fdr"].append(ents[i].get("label"))
    return out


def summarize(corp, entries=None):
    """把总账写成几句人话（报告和界面都用它）。"""
    if not corp or not corp.get("total"):
        return []
    L = []
    L.append("本次共登记 **%d 个检验**（确认性 %d、探索性 %d）。"
             % (corp["total"], corp["n_confirm"], corp["n_explore"]))
    L.append("按 α=%.2f：**至少有一个是假阳性**的概率约 **%.0f%%**（`1−0.95^n`）——"
             "这不需要作弊，做够多个检验就有。"
             % (corp["alpha"], corp["familywise"] * 100))
    L.append("Bonferroni 门槛 = α/m = **%.5f**；FDR(BH) 门槛 = **%.5f**。"
             % (corp["bonferroni"]["thr"], corp["fdr"]["thr"]))
    if corp["n_explore"]:
        L.append("里面 %d 个是**探索性**的（不是事先定好的假设）——"
                 "这几个默认按 FDR 看，别和确认性假设混在一张表里报。"
                 % corp["n_explore"])
    if corp["dropped_by_bonf"]:
        L.append("⚠ 按 Bonferroni，这 **%d 条**会掉出显著：%s"
                 % (len(corp["dropped_by_bonf"]),
                    "、".join(corp["dropped_by_bonf"][:6])))
    if corp["dropped_by_fdr"]:
        L.append("⚠ 按 FDR，这 **%d 条**会掉出显著：%s"
                 % (len(corp["dropped_by_fdr"]),
                    "、".join(corp["dropped_by_fdr"][:6])))
    if not corp["dropped_by_bonf"] and not corp["dropped_by_fdr"]:
        L.append("现有结论在两种校正下都站得住（没有谁掉出去）——"
                 "这比「p<.05」本身更有说服力。")
    L.append("**校正只告诉你「哪几条会掉」，不做决定**：主结果用不用校正、"
             "哪些算确认性，是研究员的判断。写进报告时至少要说清"
             "「共 N 个检验、是否校正」。")
    return L
