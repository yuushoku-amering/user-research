# -*- coding: utf-8 -*-
"""演示（`_demo.py`）的回归测试。

## 为什么要守

演示是**陌生人看到的第一样东西**，也是最容易被改坏而没人发现的东西 ——
它不在任何主链上，只有"有人真的双击了"才会暴露问题。
实测就出过两次：

  · `⑤` 的缺失表找错了名字（我按「缺失」找，实际叫「处理前后对比」）
    → 演示静默少一整块，不报错
  · SPSS 语法按 UTF-8 读，而它是**故意用 GBK 写的** → 屏幕上整片乱码

这两个都不是"崩了"，是"看起来正常但内容是错的/缺的" —— 最该被测试盯住的那一类。

## 守什么

1. 两个生成器能跑通，数据规模/分布对得上
2. **演示必须脱离服务器能跑完**（这是它存在的意义：不能让"没开服务"挡住陌生人）
3. 演示打印的内容里**必须出现关键几块**（意图复述、决策树、结果、SPSS 语法、邀请反馈）
4. **不许出现乱码特征**（`�`）—— 这一条就是冲着 SPSS 那个坑去的
5. 不该出现「没人应答」这种内部噪音
6. 冒烟：完整跑一遍，要求退出码 0、耗时别太离谱
"""
import io
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ⚠ 控制台是 GBK：这个脚本要打印 ✓ ✗，必须自己兜一下
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
except Exception as _e:
    print("[warn] stdout/stderr UTF-8 guard failed: %r" % (_e,))

PASS, FAIL = [], []


def ok(cond, label, extra=""):
    (PASS if cond else FAIL).append(label + ("" if cond else "  ← " + str(extra)))
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else "  ← " + str(extra)))


def main():
    print("=" * 74)
    print("演示（_demo.py / _demo_data.py）· 专项回归")
    print("=" * 74)

    py = sys.executable

    # ---------------- 1. 数据生成器 ----------------
    print("\n【1】合成问卷生成器")
    import _demo_data
    tmp = tempfile.mkdtemp(prefix="urw_demo_")
    try:
        path, df = _demo_data.build(tmp)
        ok(os.path.exists(path), "数据文件写出来了")
        ok(df.shape[0] == _demo_data.N, "行数 = %d" % _demo_data.N, df.shape)
        ok(df.shape[1] >= 15, "列数够（%d）" % df.shape[1], df.shape)

        for col in ("平台", "满意度", "崩溃频率", "是否愿意推荐"):
            if col == "满意度":
                continue
            ok(col in df.columns, "有变量「%s」" % col)

        sat = df[["Q7_1", "Q7_2", "Q7_3", "Q7_4", "Q7_5"]].mean(axis=1)
        a = sat[df.平台 == "Android"].mean()
        i = sat[df.平台 == "iOS"].mean()
        ok(i - a > 0.3, "埋的效应还在（iOS 比 Android 高 %.2f）" % (i - a),
           "Android %.2f / iOS %.2f" % (a, i))
        # ⚠ 效应**不能太大**：p 值到 1e-40 那种数量级本身就在喊"这数据是编的"，
        #   演示反而显得假。第一版就是 0.55 的惩罚项，跑出 p=3.2e-41。
        ok(i - a < 1.5, "效应没有大到失真（差 < 1.5 分）", "差 %.2f" % (i - a))

        n_missing = int(df.isna().sum().sum())
        ok(n_missing > 0, "故意留了缺失（%d 个单元格）" % n_missing)

        # ⚠ 空白开放题存下来是**空字符串**，不是 NaN —— 从 CSV 读回来 pandas 就当成有值。
        #   所以这里要同时看两种（第一版只看 isna，白红了一条）。
        blank_open = df["Q10_开放题"].isna() | (df["Q10_开放题"].astype(str).str.strip() == "")
        ok(blank_open.mean() > 0.1,
           "开放题像真的开放题（%.0f%% 的人没填）" % (blank_open.mean() * 100))

        op = df["Q10_开放题"].dropna()
        ok(op.str.contains("闪退|崩溃|卡").sum() > 0, "开放题里有可挖的抱怨")

        # 固定种子：两次生成必须一模一样
        p2, df2 = _demo_data.build(tempfile.mkdtemp(prefix="urw_demo2_"))
        ok(df.equals(df2), "固定种子 → 两次生成完全一致（演示最怕'你这数怎么和我不一样'）")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------------- 2. 完整跑一遍演示 ----------------
    print("\n【2】完整跑一遍（关键：**不依赖服务器**）")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([py, "-X", "utf8", os.path.join(HERE, "_demo.py")],
                       capture_output=True, env=env, cwd=HERE,
                       stdin=subprocess.DEVNULL, timeout=600)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")

    ok(p.returncode == 0, "退出码 0（演示跑完了）", "rc=%d\n%s" % (p.returncode, err[:400]))

    # 不许连服务：一旦它开始要 HTTP，这里就会看到端口相关字样
    ok("8765" not in out and "urlopen" not in out and "ConnectionRefused" not in out,
       "全程没碰本地服务（陌生人不需要先开服务）")

    # ---------------- 3. 关键内容都在 ----------------
    print("\n【3】该讲的东西讲到没有")
    # ⚠ 别拿**表名**当断言依据：演示的渲染器只打印我自己写的小标题，
    #   表名在结果 JSON 里、屏幕上不一定出现（第一版就因此在"找表名"上白红两条）。
    #   拿**真实的单元格内容**当依据才靠谱。
    must = [
        ("复述意图", "我理解你要问的是什么"),
        ("决策树", "决策树"),
        ("前提检验", "正态性"),
        ("方差齐性", "Levene"),
        ("为什么不用另一个", "为什么不用另一个"),
        ("各组描述统计（含 CI 那一列）", "均值的 95% CI"),
        ("检验结果（U 值）", "U："),
        ("检验结果（中位数对比）", "中位数："),
        ("置信区间", "95% CI"),
        ("效应量", "效应量"),
        ("结果解读的注", "比 p 值更值得先看"),
        ("SPSS 语法", "SPSS 语法"),
        ("读 SPSS 的中文（不是乱码）", "自动生成的 SPSS 语法"),
        ("产物清单", "分析报告"),
        ("邀请反馈", "issues"),
        ("说明这是合成数据", "假数据"),
        ("说清没做完", "早期阶段"),
        ("缺失没替人填", "缺失"),
        ("信度 α", "Cronbach α"),
    ]
    for label, needle in must:
        ok(needle in out, "讲了「%s」" % label, "找不到 %r" % needle)

    # ---------------- 4. 乱码与噪音 ----------------
    print("\n【4】不该出现的")
    bad = re.findall(r"[\ufffd]{1,}", out)
    ok(not bad, "没有乱码字符（U+FFFD）", "出现 %d 处" % len(bad))
    ok("����" not in out, "没有 GBK 错读的痕迹")
    ok("没人应答" not in out, "没有「没人应答」这种内部噪音")
    ok("Traceback" not in out and "Traceback" not in err, "没有异常堆栈")

    # ---------------- 5. 数值是真的算出来的 ----------------
    print("\n【5】数字得是真的（不能写死）")
    # ⚠ 取**结果区**那个 p，不是决策树里 Shapiro 的 p。
    #   决策树的 p 在前面会先被匹配到（0.0035），那不是我们要验的主结果。
    m = re.search(r"^\s*p：\s*([0-9.eE+-]+)", out, re.M)
    ok(bool(m), "结果区里有主 p 值", out[-600:] if not m else "")
    if m:
        try:
            pv = float(m.group(1))
            ok(0 < pv < 0.05, "主 p 值显著（%s）" % m.group(1))
            ok(pv > 1e-40, "p 没小到失真 —— 说明数据不是硬凑的（%s）" % m.group(1))
        except ValueError:
            ok(False, "p 值能解析成数字", m.group(1))
    ok("U：" in out, "报了 U 统计量")
    m = re.search(r"rank-biserial r：\s*([0-9.]+)", out)
    ok(bool(m), "有效应量", "")
    if m:
        r = float(m.group(1))
        ok(0.3 < r < 0.95, "效应量大小合理（r=%.3f）" % r)
    m = re.search(r"中位数：([0-9.]+) vs ([0-9.]+)", out)
    ok(bool(m), "报了两组中位数")
    if m:
        ok(float(m.group(2)) > float(m.group(1)), "中位数方向对（iOS 更高）", m.group(0))
    m = re.search(r"Levene p=([0-9.]+)", out)
    ok(bool(m), "报了方差齐性检验")
    m = re.search(r"Cronbach α[^\n]*?([0-9]\.[0-9]+)", out) or \
        re.search(r"\s(0\.8[0-9]{2})\s", out)
    ok(bool(m), "报了量表信度 α")

    # ---------------- 6. 冒烟：产物真的落盘了 ----------------
    print("\n【6】产物落盘")
    proj = os.path.join(HERE, "_jobs", "demo_project")
    ok(os.path.isdir(proj), "演示项目建出来了")
    outd = os.path.join(proj, "output")
    if os.path.isdir(outd):
        files = os.listdir(outd)
        ok(any(f.endswith(".sps") for f in files), "有 SPSS 语法")
        ok(any(f == "clean_data.csv" for f in files), "有 clean_data.csv")
        ok(any(f.startswith("分析报告") for f in files), "有分析报告")
        ok(any(f.endswith(".png") for f in files), "有图")
    # 演示不许污染仓库根
    ok(not os.path.isdir(os.path.join(HERE, "demo_project")),
       "演示项目**没有**建在仓库根下面（否则会被 git 看到）")

    print("\n" + "=" * 74)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("")
        for f in FAIL:
            print("  ❌ " + f)
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
