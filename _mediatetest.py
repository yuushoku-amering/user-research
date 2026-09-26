# -*- coding: utf-8 -*-
"""中介 / 调节 · 专项自检（第 3 批）

    python _mediatetest.py

守四件事：

  1. **中介的间接效应 a×b 要和真值对得上**（用"真值已知"的数据生成）
  2. **中介必须用 bootstrap**：a×b 的分布不正态，Sobel 的 p 和 CI 都偏
  3. **调节的交互项要先对中**：不对中的话 X 的系数变成"W=0 时的作用"，不可解释
  4. **Johnson-Neyman 的转折点要真的对应显著性的翻转**（拿数据逐点验）
"""
import importlib.util
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
from core import mediate as MD               # noqa: E402
from core import method_pick as mp           # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, label, extra=None):
    if cond:
        PASS[0] += 1
        print("  [OK] " + label)
    else:
        FAIL[0] += 1
        print("  [!!] " + label + ("" if extra is None else "  —— %s" % (extra,)))


def load_engine(block):
    spec = importlib.util.spec_from_file_location(
        "eng_" + block, os.path.join(HERE, "blocks", block, "engine.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Ctx(object):
    def __init__(self, params=None, project_root=""):
        self.params = dict(params or {})
        self.project_root = project_root
        self.steps, self.logs, self.alerts, self.outputs = [], [], [], []

    def get(self, k, d=None):
        v = self.params.get(k, d)
        return d if v is None else v

    def log(self, m, level="info"):
        self.logs.append("[%s] %s" % (level, m))

    def warn(self, m):
        self.logs.append("[warn] %s" % m)

    def alert(self, msg, *a, **k):
        self.alerts.append(msg)

    def alerts_from(self, items):
        pass

    def step(self, sid, title, detail=None, rows=None, columns=None):
        self.steps.append((sid, title, detail))

    def path(self, *p):
        return os.path.join(self.project_root, *p)

    def out_path(self, *p):
        return os.path.join(self.project_root, "output", *p)

    def made(self, path):
        self.outputs.append(path)

    def save_text(self, rel, text, encoding="utf-8"):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
        self.outputs.append(rel)
        return rel

    def save_table(self, name, rows, columns=None):
        import pandas as pd
        p = self.out_path(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        pd.DataFrame(list(rows), columns=columns).to_csv(p, index=False,
                                                         encoding="utf-8-sig")
        self.outputs.append(name)
        return name

    def ask(self, sid, title, detail=None, options=None, default=None,
            rows=None, columns=None):
        return default if default is not None else (options[0]["value"] if options else "ok")


def main():
    import numpy as np
    import pandas as pd

    print("=" * 72)
    print("【1】中介：真值 a=0.6, b=0.5, c′=0.3 → 间接效应应当是 0.30")
    print("=" * 72)
    rng = np.random.default_rng(99)
    n = 500
    x = rng.normal(0, 1, n)
    m = 0.6 * x + rng.normal(0, 1, n)                 # a = 0.6
    y = 0.5 * m + 0.3 * x + rng.normal(0, 1, n)       # b = 0.5, c′ = 0.3
    d = pd.DataFrame({"X": x, "M": m, "Y": y})
    r = MD.mediation(d, "X", "M", "Y", n_boot=2000)
    ok(abs(r["a"] - 0.6) < 0.12, "a 路径 ≈ 0.6（%.3f）" % r["a"], r["a"])
    ok(abs(r["b"] - 0.5) < 0.12, "b 路径 ≈ 0.5（%.3f）" % r["b"], r["b"])
    ok(abs(r["c_prime"] - 0.3) < 0.12, "直接效应 c′ ≈ 0.3（%.3f）" % r["c_prime"], r["c_prime"])
    ok(abs(r["indirect"] - 0.30) < 0.08,
       "**间接效应 a×b ≈ 0.30**（%.3f）" % r["indirect"], r["indirect"])
    ok(abs(r["indirect"] - r["a"] * r["b"]) < 1e-9,
       "间接效应**严格等于** a×b（不是分别取整再乘）")
    lo, hi = r["boot_ci"]
    ok(lo < r["indirect"] < hi, "bootstrap 区间包含点估计（[%.3f, %.3f]）" % (lo, hi), r["boot_ci"])
    ok(not (lo <= 0 <= hi), "区间**不跨 0** → 判定为有中介", r["boot_ci"])
    ok("部分中介" in r["kind"], "直接效应仍显著 → 判成部分中介", r["kind"])

    print("\n" + "=" * 72)
    print("【2】没有中介时不能报有中介（M 与 X 无关）")
    print("=" * 72)
    m0 = rng.normal(0, 1, n)                          # a ≈ 0
    y0 = 0.5 * m0 + 0.3 * x + rng.normal(0, 1, n)
    r0 = MD.mediation(pd.DataFrame({"X": x, "M": m0, "Y": y0}), "X", "M", "Y", n_boot=2000)
    lo0, hi0 = r0["boot_ci"]
    ok(lo0 <= 0 <= hi0, "间接效应的区间**跨 0**（[%.3f, %.3f]）" % (lo0, hi0), r0["boot_ci"])
    ok(not r0["significant"], "判定为**没有中介**", r0["significant"])
    ok("不显著" in r0["kind"], "结论里写明「间接效应不显著」", r0["kind"])

    print("\n" + "=" * 72)
    print("【3】中介的可复现性：固定种子 → 两次跑出同一个区间")
    print("=" * 72)
    r_a = MD.mediation(d, "X", "M", "Y", n_boot=1000)
    r_b = MD.mediation(d, "X", "M", "Y", n_boot=1000)
    ok(r_a["boot_ci"] == r_b["boot_ci"],
       "**同一份数据两次 bootstrap 区间完全一样**（固定种子）",
       (r_a["boot_ci"], r_b["boot_ci"]))

    print("\n" + "=" * 72)
    print("【4】调节：真交互 0.4 → 交互项系数要对上，且要先对中")
    print("=" * 72)
    wv = rng.normal(0, 1, n)
    yy = 0.5 * x + 0.2 * wv + 0.4 * x * wv + rng.normal(0, 1, n)
    r3 = MD.moderation(pd.DataFrame({"X": x, "W": wv, "Y": yy}), "X", "W", "Y")
    ok(abs(r3["b_int"] - 0.4) < 0.10,
       "**交互项 ≈ 0.4**（%.3f）" % r3["b_int"], r3["b_int"])
    ok(r3["significant"], "交互项显著 → 有调节作用")
    ok(abs(r3["b_x"] - 0.5) < 0.12,
       "X 主效应的解释是「W 在平均值上 X 的作用」≈ 0.5（%.3f）" % r3["b_x"], r3["b_x"])
    # 对中：W_centered=0 处的斜率应当等于 b_x
    mid = r3["slopes"][1]
    ok(abs(mid["w_centered"]) < 0.15, "中间那个简单斜率取在 W 的均值附近",
       mid["w_centered"])
    ok(abs(mid["slope"] - r3["b_x"]) < 1e-6,
       "W=均值处的斜率 == X 主效应（对中的直接后果）",
       (mid["slope"], r3["b_x"]))
    # 斜率随 W 单调
    ok(r3["slopes"][0]["slope"] < mid["slope"] < r3["slopes"][2]["slope"],
       "简单斜率随 W 单调上升（低 < 中 < 高）",
       [s["slope"] for s in r3["slopes"]])

    print("\n" + "=" * 72)
    print("【5】Johnson-Neyman 的转折点要真的对应显著性翻转")
    print("=" * 72)
    roots = r3["jn_roots"]
    ok(len(roots) >= 1, "解出了转折点：%s" % ["%.2f" % v for v in roots], roots)
    # 在两个转折点中间取一点 → 应当不显著；两点外侧各取一点 → 应当显著
    from scipy import stats as st
    fit = r3["fit"]
    dof, rr = r3["dof"], float(fit["resid"] @ fit["resid"]) / r3["dof"]
    v1 = fit["XtX_inv"][1, 1] * rr
    v3 = fit["XtX_inv"][3, 3] * rr
    c13 = fit["XtX_inv"][1, 3] * rr

    def p_at(w_actual):
        wc = w_actual - r3["w_mean"]
        est = r3["b_x"] + r3["b_int"] * wc
        se = np.sqrt(max(v1 + wc ** 2 * v3 + 2 * wc * c13, 0))
        t = est / se
        return 2 * (1 - st.t.cdf(abs(t), dof))

    if len(roots) == 2:
        inside = (roots[0] + roots[1]) / 2
        p_in = p_at(inside)
        p_out_lo = p_at(roots[0] - 1.5)
        p_out_hi = p_at(roots[1] + 1.5)
        ok(p_in > 0.05, "两转折点**中间**（W=%.2f）不显著（p=%.3f）" % (inside, p_in), p_in)
        ok(p_out_lo < 0.05 and p_out_hi < 0.05,
           "两转折点**外侧**显著（p=%.4f / %.4f）" % (p_out_lo, p_out_hi))

    print("\n" + "=" * 72)
    print("【6】没有交互时不能报有调节")
    print("=" * 72)
    yy2 = 0.5 * x + 0.2 * wv + rng.normal(0, 1, n)
    r4 = MD.moderation(pd.DataFrame({"X": x, "W": wv, "Y": yy2}), "X", "W", "Y")
    ok(not r4["significant"], "交互项不显著 → 判成**没有调节**（p=%.2f）" % r4["p_int"])

    print("\n" + "=" * 72)
    print("【7】方法判定 + 端到端（含「填了中介变量自动走 causal」）")
    print("=" * 72)
    ok(mp.pick_mediated(True, False)[0]["method"] == "mediation", "填中介 → mediation")
    ok(mp.pick_mediated(False, True)[0]["method"] == "moderation", "填调节 → moderation")
    ok(len(mp.pick_mediated(True, True)) == 2, "两个都填 → 两个都做")
    ok(mp.pick_mediated(False, False) is None, "都没填 → 不走这一支")
    why = " ".join(mp.pick_mediated(True, False)[0]["why_not"])
    ok("Sobel" in why, "明说**为什么不用 Sobel**（a×b 的分布不正态）", why[:60])
    why2 = " ".join(mp.pick_mediated(False, True)[0]["why_not"])
    ok("对中" in why2, "明说**交互项要先对中**", why2[:60])

    e = load_engine("b5_stats")
    tmp = tempfile.mkdtemp(prefix="urw_med_")
    try:
        pd.DataFrame({"X": x[:400].round(3), "M": m[:400].round(3),
                      "W": wv[:400].round(3), "Y": yy[:400].round(3)}).to_csv(
            os.path.join(tmp, "c.csv"), index=False, encoding="utf-8-sig")
        ctx = Ctx({"file": "c.csv", "question": "auto", "dv": "Y", "ivs": ["X"],
                   "mediator": "M", "moderator": "W", "alpha": 0.05,
                   "gen_sps": ["fig"]}, project_root=tmp)
        res = e.run(ctx)
        names = [t["name"] for t in (res.get("tables") or [])]
        ok(any("中介分析" in n_ for n_ in names), "端到端出了中介表", names)
        ok(any("调节分析" in n_ for n_ in names), "端到端出了调节表", names)
        ok(any("Johnson-Neyman" in n_ for n_ in names), "出了 JN 区间表", names)
        figs = [f["rel"] for f in (res.get("figures") or [])]
        ok(any("调节" in f for f in figs), "出了简单斜率图", figs)
        for f in figs:
            p = os.path.join(tmp, *f.split("/"))
            ok(os.path.exists(p), "图确实落盘：%s" % f)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
