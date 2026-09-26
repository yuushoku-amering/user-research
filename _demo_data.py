# -*- coding: utf-8 -*-
"""5 分钟演示用的合成问卷数据 —— **现场造，不进版本库**。

## 为什么是一份"埋了结构"的数据

随便造一堆随机数，跑出来全是「不显著」，演示就成了劝退。
所以这份数据**故意埋了一条真实的因果链**，让整条链跑出来是有话可说的：

    平台（Android / iOS）
        └─→ 崩溃频率（Android 因为兼容问题崩得多）
                └─→ 体验满意度（Q7_1~Q7_5 五题量表，崩得多就低）
                        └─→ 是否愿意推荐

埋的效应：Android 的满意度比 iOS 低约 **0.9 分**（5 点量表）。
所以 ⑥ 跑组间差异时，会稳定地报出「显著 + 中等偏大的效应量」，
而不是一句「没有显著差异」。

## 为什么和 `_fixtures.py` 里的那份不一样

`_fixtures.py` 那份是给**回归测试**用的（要喂给 `_selftest.py` 那 11 条用例）。
这份是给**人**看的：变量名更贴近"校园服务满意度"这个场景，
而且刻意做成"一份刚回收的问卷"该有的样子（有缺失、有开放题、有注意力检验题）。

⚠ 固定随机种子 —— 谁跑、什么时候跑，结果都一样。
   演示最怕的就是"我这个数怎么和你那个不一样"。
"""
import os

SEED = 20260927
N = 412


def build(out_dir):
    """造一份问卷数据写到 out_dir/sim_survey.csv，返回路径。"""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(SEED)

    # ---------- 背景变量 ----------
    platform = rng.choice(["Android", "iOS"], N, p=[0.52, 0.48])
    gender = rng.choice(["男", "女"], N, p=[0.44, 0.56])
    grade = rng.choice(["大一", "大二", "大三", "大四", "研究生"], N,
                       p=[0.22, 0.27, 0.24, 0.19, 0.08])
    # 每周使用次数：轻度和重度都有，右偏（真实的用量分布就长这样）
    uses = np.clip(rng.gamma(2.0, 1.6, N), 0, 20).round().astype(int)

    # ---------- 埋结构：Android 崩溃多 → 满意度低 ----------
    # 崩溃频率：0=从不 1=偶尔 2=经常 3=几乎每次
    crash = np.where(
        platform == "Android",
        rng.choice([0, 1, 2, 3], N, p=[0.06, 0.24, 0.44, 0.26]),
        rng.choice([0, 1, 2, 3], N, p=[0.58, 0.33, 0.08, 0.01]))

    # 满意度（5 题 5 点量表）：平台 + 崩溃频率 一起压
    # ⚠ 效应大小是**调过**的。第一版埋了 0.55 + 0.22×崩溃，
    #   跑出来 p=3.2e-41 —— 那个数量级本身就在喊"这数据是编的"。
    #   真实回收的问卷里，0.9 分的组间差在 n=200 上下会给出 p 到 1e-20 左右，
    #   已经够显著了。所以压到 0.42 + 0.16，让它看起来像真数据。
    sat_center = (3.85
                  - np.where(platform == "Android", 0.42, 0.0)
                  - crash * 0.16
                  + rng.normal(0, 0.46, N))
    common = rng.normal(0, 0.30, N)
    q7 = {}
    for i in range(1, 6):
        v = sat_center + rng.normal(0, 0.48, N) + common * 0.35
        q7["Q7_%d" % i] = np.clip(np.round(v), 1, 5).astype(int)

    # 继续使用意愿（3 题）：跟满意度正相关，但没那么强
    will_center = 2.75 + (sat_center - 3.0) * 0.62 + rng.normal(0, 0.62, N)
    q8 = {}
    for i in range(1, 4):
        v = will_center + rng.normal(0, 0.55, N)
        q8["Q8_%d" % i] = np.clip(np.round(v), 1, 5).astype(int)

    # 是否愿意推荐：由意愿决定
    recommend = np.where(will_center + rng.normal(0, 0.72, N) >= 3.2, "是", "否")

    # 注意力检验题：绝大多数人答对
    attention = np.where(rng.random(N) < 0.92, "非常同意", "非常不同意")

    # 开放题：按平台分两个语料库（Android 抱怨崩溃，iOS 聊功能）
    open_bank = {
        "Android": ["更新之后老是闪退，根本用不下去",
                    "安卓这边优化太差了，同样的手机以前不卡",
                    "希望先把崩溃修好再上新功能",
                    "进详情页经常卡住，只能杀掉重开",
                    "体验越来越差，已经很少打开了"],
        "iOS": ["整体还不错，就是有些功能找不到",
                "希望能加个夜间模式",
                "界面挺清爽的，继续加油",
                "有些页面加载有点慢，别的都好",
                "希望多出点内容，功能本身没问题"],
    }
    open_text = []
    for i in range(N):
        if rng.random() < 0.24:
            open_text.append("")          # 开放题天生就有很多人不填
        else:
            bank = open_bank[platform[i]]
            open_text.append(bank[rng.integers(0, len(bank))])

    df = pd.DataFrame({
        "受访者编号": ["P%03d" % (i + 1) for i in range(N)],
        "平台": platform,
        "性别": gender,
        "年级": grade,
        "周使用次数": uses,
        "崩溃频率": crash,
        "Q7_1": q7["Q7_1"], "Q7_2": q7["Q7_2"], "Q7_3": q7["Q7_3"],
        "Q7_4": q7["Q7_4"], "Q7_5": q7["Q7_5"],
        "Q8_1": q8["Q8_1"], "Q8_2": q8["Q8_2"], "Q8_3": q8["Q8_3"],
        "是否愿意推荐": recommend,
        "注意力检验": attention,
        "Q10_开放题": open_text,
    })

    # 撒一点缺失 —— 让 ⑤ 预处理那一步真的有活干
    # （真实的回收问卷一定是有缺失的，一份干干净净的数据反而不像真的）
    for col in ("周使用次数", "崩溃频率", "Q7_3", "Q8_2", "Q10_开放题"):
        idx = rng.choice(N, size=int(N * 0.03), replace=False)
        df.loc[idx, col] = np.nan

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "sim_survey.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")

    return path, df


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p, d = build(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_jobs", "demo_data"))
    print("写好了：%s" % p)
    print("规模：%d 行 × %d 列" % d.shape)
    print("平台分布：%s" % d["平台"].value_counts().to_dict())
    sat = d[["Q7_1", "Q7_2", "Q7_3", "Q7_4", "Q7_5"]].mean(axis=1)
    print("满意度均值：Android %.2f  vs  iOS %.2f"
          % (sat[d.平台 == "Android"].mean(), sat[d.平台 == "iOS"].mean()))
