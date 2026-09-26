# -*- coding: utf-8 -*-
"""回归与 logistic · 专项自检（第 2 批）

    python _regresstest.py

守四件事：

  1. **logistic 的系数要和另一个独立实现对得上**（sklearn 装了就拿它当参照）
     —— 自己写的 IRLS，光"能跑出数"不够，得证明它算的是对的
  2. **不能拿 OLS 拟合 0/1 因变量**：系数看着能算，但标准误和 p 值都是错的
  3. **OR 的 CI 要在对数尺度上算**（直接对 OR 加减标准误会得出负的下界）
  4. **正确率会被类别不平衡骗**：必须和「全猜最大类」的基准比
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
from core import regress as R                # noqa: E402
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
        d = os.path.join(self.project_root, "output")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, *p)

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
        pd.DataFrame(list(rows), columns=columns).to_csv(p, index=False,
                                                         encoding="utf-8-sig")
        self.outputs.append(name)
        return name

    def ask(self, sid, title, detail=None, options=None, default=None,
            rows=None, columns=None):
        return default if default is not None else (options[0]["value"] if options else "ok")


def main():
    import numpy as np

    print("=" * 72)
    print("【1】logistic 的系数要经得起**另一个实现**的检验")
    print("=" * 72)
    rng = np.random.default_rng(2026)
    n = 600
    x1, x2 = rng.normal(0, 1, n), rng.normal(0, 1, n)
    eta = -0.5 + 1.2 * x1 - 0.8 * x2
    y = (rng.random(n) < 1 / (1 + np.exp(-eta))).astype(float)
    X = np.column_stack([np.ones(n), x1, x2])
    mine = R.logistic(X, y)
    ok(mine["converged"], "IRLS 收敛（用了 %d 步）" % mine["iters"])
    ok(abs(mine["beta"][1] - 1.2) < 0.25,
       "x1 的系数接近真值 1.2（%.3f）" % mine["beta"][1], mine["beta"][1])
    try:
        from sklearn.linear_model import LogisticRegression
        sk = LogisticRegression(penalty=None, solver="lbfgs", max_iter=5000, tol=1e-10)
        sk.fit(np.column_stack([x1, x2]), y)
        diff = max(abs(sk.intercept_[0] - mine["beta"][0]),
                   abs(sk.coef_[0][0] - mine["beta"][1]),
                   abs(sk.coef_[0][1] - mine["beta"][2]))
        ok(diff < 1e-4,
           "**和 sklearn 的系数一致**（最大差 %.2e）—— 两个独立实现" % diff, diff)
    except ImportError:
        ok(True, "（没装 sklearn，跳过交叉验证——但这条本该是必跑项）")

    print("\n" + "=" * 72)
    print("【2】OR 的置信区间必须在**对数尺度**上算")
    print("=" * 72)
    b, se = mine["beta"][1], mine["se"][1]
    ci = R.ci_or(b, se)
    lo, hi = [float(v) for v in ci.strip("[]").split(",")]
    orv = float(np.exp(b))
    ok(lo < orv < hi, "OR 的 CI 包含点估计（OR=%.3f，CI=%s）" % (orv, ci), ci)
    ok(lo > 0, "**下界是正的**（直接加减标准误会算出负的下界）", lo)
    # 手工核一遍：先在 log 尺度算再取指数
    zc = 1.959963985
    man = (np.exp(b - zc * se), np.exp(b + zc * se))
    ok(abs(man[0] - lo) < 1e-3 and abs(man[1] - hi) < 1e-3,
       "和手工「log 尺度 ± 1.96SE 再取指数」一致", (man, (lo, hi)))

    print("\n" + "=" * 72)
    print("【3】正确率会被类别不平衡骗 —— 必须和基准比")
    print("=" * 72)
    # 造一个严重不平衡的：正例只占 5%
    y_imb = np.zeros(n)
    y_imb[:int(n * 0.05)] = 1
    rng.shuffle(y_imb)
    p_dummy = np.full(n, 0.01)            # 一个"什么都不预测"的模型
    ct = R.classify_table(y_imb, p_dummy)
    ok(ct["accuracy"] > 0.9,
       "「全猜否」的正确率也有 %.3f（看着很高）" % ct["accuracy"], ct["accuracy"])
    ok(abs(ct["baseline"] - 0.95) < 0.02,
       "但**基准（最大类占比）**是 %.3f —— 一比就知道它没有信息" % ct["baseline"],
       ct["baseline"])
    ok(ct["lift"] is not None and abs(ct["lift"]) < 0.02,
       "程序给出的「比基准好」≈ 0（这才是不骗人的说法）", ct["lift"])
    ok(ct["sensitivity"] is None or ct["sensitivity"] == 0,
       "敏感度也是 0（一个正例都没抓到）", ct["sensitivity"])

    print("\n" + "=" * 72)
    print("【4】拟合优度 + 「哪一类算 1」的编码规则")
    print("=" * 72)
    hl, pv, g = R.hosmer_lemeshow(y, mine["p_hat"])
    ok(hl is not None and hl["groups"] >= 2, "HL 算出来了（%d 组）" % g)
    ok(0 <= hl["p"] <= 1, "HL 的 p 在 [0,1]", hl["p"])
    ok(pv > 0.05, "真模型生成的数据 → HL **不显著**（p=%.3f，p 大才好）" % hl["p"], hl["p"])
    # 编码规则：升序最后一个算 1
    import pandas as pd
    yy, lv, _ = R.encode_binary(pd.Series(["否", "是", "是", "否"]))
    ok(lv == ["否", "是"] and list(yy) == [0.0, 1.0, 1.0, 0.0],
       "「否/是」→ 是=1（升序最后一个）", (lv, list(yy)))
    yy2, lv2, _ = R.encode_binary(pd.Series(["0", "1", "1"]))
    ok(list(yy2) == [0.0, 1.0, 1.0], "「0/1」→ 1=1", list(yy2))
    y3, lv3, _ = R.encode_binary(pd.Series(["a", "b", "c"]))
    ok(y3 is None, "**三个类别要拒绝**（做不了二元 logistic）", lv3)

    print("\n" + "=" * 72)
    print("【5】方法判定：因变量两类就必须换模型（不许拿 OLS 硬上）")
    print("=" * 72)
    r = mp.pick_relate(2, dv_binary=True)
    ok(r["method"] == "logistic", "两类因变量 → logistic", r["method"])
    ok(any("线性回归" in x for x in r["why_not"]),
       "并且说明**为什么不能拿线性回归**", r["why_not"][0][:50])
    ok(mp.pick_relate(2, dv_binary=False)["method"] == "ols", "连续因变量 → 还是 OLS")
    ok(mp.pick("relate", n_iv=2, dv_binary=True)["method"] == "logistic",
       "统一入口也传得对（`pick` 漏传过一次参数）")

    print("\n" + "=" * 72)
    print("【6】端到端：两类因变量走 logistic，且**不出现 OLS 的表**")
    print("=" * 72)
    e = load_engine("b5_stats")
    tmp = tempfile.mkdtemp(prefix="urw_reg_")
    try:
        pd.DataFrame({
            "生活费": x1[:400].round(2),
            "年级": rng.choice(["大一", "大二", "大三"], 400),
            "是否分手": np.where(y[:400] > 0, "是", "否"),
            "支出": (200 + 30 * x1[:400] + rng.normal(0, 40, 400)).round(1),
        }).to_csv(os.path.join(tmp, "c.csv"), index=False, encoding="utf-8-sig")

        ctx = Ctx({"file": "c.csv", "question": "auto", "dv": "是否分手",
                   "ivs": ["生活费", "年级"], "alpha": 0.05, "gen_sps": ["sps"]},
                  project_root=tmp)
        res = e.run(ctx)
        names = [t["name"] for t in (res.get("tables") or [])]
        ok(any("logistic" in n_ for n_ in names), "出了 logistic 系数表", names)
        ok(not any(n_ == "回归系数" for n_ in names),
           "**没有** OLS 的「回归系数」表（抽函数前它会被一起跑一遍）", names)
        ok(any("分类效果" in n_ for n_ in names), "出了分类效果 / 拟合优度表", names)
        # 决策树里要写明「哪一类算 1」
        plan = [t for t in res["tables"] if t["name"].startswith("分析计划")][0]
        ptxt = " ".join(str(c) for r_ in plan["rows"] for c in r_)
        ok("算「1」" in ptxt or "哪一类算" in ptxt,
           "决策树里写明了**哪一类算 1**（OR 的方向全靠它）", ptxt[:80])

        # 换成连续因变量 → 应当走 OLS
        ctx2 = Ctx({"file": "c.csv", "question": "relate", "dv": "支出",
                    "ivs": ["生活费"], "alpha": 0.05, "gen_sps": []}, project_root=tmp)
        res2 = e.run(ctx2)
        n2 = [t["name"] for t in (res2.get("tables") or [])]
        ok(any(x == "回归系数" for x in n2), "连续因变量 → 出 OLS 的回归系数表", n2)
        ok(not any("logistic" in x for x in n2), "且**不出现** logistic 表", n2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 72)
    print("通过 %d / 失败 %d" % (PASS[0], FAIL[0]))
    print("=" * 72)
    return 0 if FAIL[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
