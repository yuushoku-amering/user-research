# -*- coding: utf-8 -*-
"""SPSS 串联 · 自检

**不假设 SPSS 在这台机器上一定能跑起来**（能不能跑取决于工作台是从哪个会话启动的：
受限权限的程序拉起来的会话里，SPSS 写不了注册表，会直接退出）。
这里验的是「机器部分」：

  · 走**生产作业**（`-production` + .spj）—— SPSS 专门为自动化设计的那条路
  · .spj 的取值照它自己的 `production-1.4.xsd`：batch / continue / html / png
  · 语法按 UTF-8 写（配合作业里的 `unicode="true"`），老 GBK 语法也能正确读进来
  · 开关表里没有 `-b` / `-f` 那种会让 SPSS 弹「未知的开关」的短写
  · 报错能翻译成人话

    python _spsstest.py
"""
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import paths, spss          # noqa: E402

TMP = os.path.join(HERE, "_jobs", "tmp_spss")
PASS, FAIL = [], []


def ok(cond, label, extra=""):
    (PASS if cond else FAIL).append(label + ("" if cond else "  ← " + str(extra)))
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else "  ← " + str(extra)))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(os.path.join(TMP, "output"), exist_ok=True)

    print("=" * 70)
    print("一、开关：只走 SPSS 真认的路")
    print("=" * 70)
    ok("-production" in str(spss.CANDIDATES), "首选是生产作业 -production（跑完自己退出）")
    ok(all(x not in spss.BAD_FORMS for x in
           [a for c in spss.CANDIDATES for a in c[1] if not a.startswith("{")]),
       "候选里没有 -b / -f 那种会让 SPSS 弹「未知的开关」的短写", spss.CANDIDATES)
    ok(all(x in spss.BAD_FORMS for x in ("-b", "-f", "-o")), "错误短写被列进 BAD_FORMS 了")
    cfg0 = paths.load_config()
    if isinstance(cfg0.get("spss_args"), list):
        ok(all(x not in spss.BAD_FORMS for x in cfg0["spss_args"]),
           "config.json 里没留旧的错误开关", cfg0.get("spss_args"))
    else:
        ok(True, "config.json 里没留旧的错误开关")

    print("")
    print("=" * 70)
    print("二、生产作业文件（.spj）")
    print("=" * 70)
    spj = spss.job_xml(r"D:\某处\语法.sps", r"D:\某处\输出.html")
    ok(spss.PROD_NS in spj, "命名空间对（照 production-1.4.xsd）")
    ok('syntaxFormat="batch"' in spj, "syntaxFormat=batch（批处理）")
    ok('syntaxErrorHandling="continue"' in spj, "出错也继续")
    ok('unicode="true"' in spj, "unicode=true（SPSS 的 Unicode 模式）")
    ok(r'syntaxPath="D:\某处\语法.sps"' in spj, "语法路径写对了")
    ok('outputFormat="html"' in spj and r'outputPath="D:\某处\输出.html"' in spj,
       "输出格式和路径直接写在作业里（连 OUTPUT EXPORT 都不用）")
    ok('imageFormat="png"' in spj, "图片格式指定成 png")
    try:
        ET.fromstring(spj)
        ok(True, "生成的 XML 能被解析")
    except Exception as e:
        ok(False, "生成的 XML 能被解析", e)
    try:
        ET.fromstring(spss.job_xml(r"D:\a&b\<语法>.sps", r"D:\a&b\<输出>.html"))
        ok(True, "路径里有 & < > 也不会把 XML 搞坏")
    except Exception as e:
        ok(False, "路径里有 & < > 也不会把 XML 搞坏", e)
    ok(' out_format="html"' not in spj, "注释里的 Python 参数名没漏进 XML")

    print("")
    print("=" * 70)
    print("三、编码：语法要写成 SPSS 读得懂的")
    print("=" * 70)
    print("   当前编码：%s" % spss.syntax_encoding())
    ok(spss.syntax_encoding().lower() in ("gbk", "cp936", "gb18030"),
       "默认按 GBK 写 —— 实测 SPSS 就是按本机代码页读语法文件的"
       "（`unicode=true` 和 `* Encoding: UTF-8.` 都不管用）")
    p = os.path.join(TMP, "enc.sps")
    body = "* 中文注释：玩具购买意愿\nFREQUENCIES VARIABLES=玩具购买意愿.\n"
    spss.write_syntax(p, body)
    ok(spss.read_syntax(p) == body, "按同一套编码读回来一模一样")
    gbk_file = os.path.join(TMP, "old_gbk.sps")
    with open(gbk_file, "wb") as f:
        f.write(body.encode("gbk"))
    ok(spss.read_syntax(gbk_file) == body,
       "老版本留下的 GBK 语法也能正确读进来（会被自动迁成 UTF-8）")

    cleaned = spss.drop_encoding_header("* Encoding: UTF-8.\n* 正文\n")
    ok("Encoding" not in cleaned.lower(), "旧的 * Encoding: UTF-8. 头会被清掉", cleaned[:30])
    ok("* 正文" in cleaned, "清头的时候不伤正文")
    ok(spss.drop_encoding_header("* 没有头\n* 正文\n").startswith("* 没有头"),
       "没头的语法原样返回")

    print("")
    print("=" * 70)
    print("四、语法加工：导出路径 / 全 ASCII 运行目录")
    print("=" * 70)
    d = spss.ascii_run_dir("urw_spss_test")
    ok(all(ord(c) < 128 for c in d), "运行目录是全 ASCII 的", d)
    txt = spss.set_export_target("FREQUENCIES VARIABLES=x.\n",
                                 r"C:\Users\SELORIS\AppData\Local\Temp\urw\out.html")
    ok("OUTPUT EXPORT" in txt, "没有导出尾巴时会补一条")
    ok(r"C:\Users\SELORIS\AppData\Local\Temp\urw\out.html" in txt,
       "导出路径写进去了（含反斜杠，没踩 bad escape）")
    ok(spss.set_export_target(txt, r"C:\别的\地方\out2.html").count("OUTPUT EXPORT") == 1,
       "已有导出尾巴时是替换而不是追加")
    shutil.rmtree(d, ignore_errors=True)

    print("")
    print("=" * 70)
    print("五、报错翻译成人话")
    print("=" * 70)
    reg = ("java.lang.SecurityException: Could not open windows registry node "
           "Software\\JavaSoft\\Prefs at root 0x80000001: Access denied\n"
           "\tat com.spss.java_client.core.common.Driver.main(Unknown Source)")
    msg = spss.explain(reg)
    ok("权限" in msg and "启动工作台.bat" in msg, "注册表被拒 → 说清原因 + 给出办法")
    ok("许可" in spss.explain("Error: license expired"), "许可问题另说一套")
    ok(spss.explain("") != "", "空报错也有兜底文案")

    print("")
    print("=" * 70)
    print("五之二、SPSS 失败时会产出 HTML —— 得认出那是报错不是结果")
    print("=" * 70)
    err_html = ("<p>&gt;错误号 237<BR>&gt;SPSS Statistics 读取了一行语法，"
                "其中包含一个或多个在当前语言环境中无效的字符。<BR>&gt;无法访问文件。</p>")
    d = spss.html_diagnosis(err_html)
    ok("没有产出结果表" in d, "认出这是报错（不是结果表）", d[:40])
    ok("编码" in d, "还顺手点出可能的病根（编码）", d[:60])
    ok(spss.html_diagnosis("<table><tr><td>Mann-Whitney U</td></tr></table>") == "",
       "正常结果表不会被误判成报错")
    ok("没有表格" in spss.html_diagnosis("<p>hello</p>"),
       "既没表也没明确报错时，也给一句提示")

    print("")
    print("=" * 70)
    print("六、环境")
    print("=" * 70)
    cfg = paths.load_config()
    exe = spss.find_exe()
    print("   config 里的 spss_exe：%s（存在=%s）" % (cfg.get("spss_exe"), bool(exe)))
    ok(True, "现在开着 %d 个 SPSS" % spss.stats_running())

    bad = dict(cfg)
    bad["spss_exe"] = os.path.join(TMP, "并不存在的stats.exe")
    paths.save_config(bad)
    r = spss.run_production(TMP, "不存在的.sps", "out.html")
    ok(not r.get("ok"), "SPSS 路径不对时报错而不是崩", (r.get("error") or "")[:60])
    paths.save_config(cfg)

    print("")
    print("=" * 70)
    print("七、生成的 SPSS 语法里，字符串变量不能直接进数字命令")
    print("=" * 70)
    # ⚠ 踩过：SPSS 的 REGRESSION 只吃数字自变量、T-TEST/NPAR TESTS 的分组变量也必须数字化。
    #   以前直接把「无/有」「5000～10000 元」这种字符串写进去，SPSS 报
    #   「在仅允许数字变量的位置使用了字符串变量」然后整个命令停掉，
    #   导出的 HTML 里只有一句报错、没有结果表。
    try:
        sys.path.insert(0, os.path.join(HERE, "libs"))
        import pandas as pd
        from blocks.b5_stats import engine as E
        from core import kit

        d = pd.DataFrame({
            "满意度": [3.5, 4.0, 2.5, 4.5, 3.0, 5.0, 2.0, 4.0, 3.5, 4.5],
            "有无孩子": ["有", "无", "有", "无", "有", "无", "有", "无", "有", "无"],
            "收入档": ["低", "中", "高", "低", "中", "高", "低", "中", "高", "低"],
        })
        kinds = {c: kit.infer_kind(d[c]) for c in d.columns}
        ok(kinds["有无孩子"] == "categorical", "「有无孩子」被认成分类变量", kinds["有无孩子"])

        # 分组变量 → 数字码 + 值标签
        gname, lines = E._sps_code_var(d, "有无孩子", ["有", "无"])
        ok(gname.endswith("_码"), "分组变量换成了数字码变量", gname)
        ok(any(l.startswith("RECODE") for l in lines), "生成了 RECODE", lines[:1])
        ok(any(l.startswith("VALUE LABELS") for l in lines),
           "生成了 VALUE LABELS（输出的表里还显示「有/无」）")
        ok(any(l == "EXECUTE." for l in lines), "带了 EXECUTE")
        ok(E._sps_code_var(d, "满意度", None)[1] == [], "本来就是数字的变量不动它")

        # 分类自变量 → 哑变量（去掉第一类）
        pre, names = E._sps_cat_prelude(d, ["收入档"], kinds)
        ok(len(names) == 2, "3 个类别 → 2 个哑变量（去掉第一个当参照）", names)
        ok(all(n.startswith("收入档_") for n in names), "哑变量命名清楚", names)
        ok(any("COMPUTE" in l for l in pre) and any("EXECUTE." == l for l in pre),
           "生成了 COMPUTE + EXECUTE")
        ok(any("VARIABLE LABELS" in l for l in pre), "哑变量挂了标签，报告里看得懂")

        # 整份语法里：数字命令引用的都是数字变量
        sps = E._build_sps(d, r"C:\x\data.csv",
                           ["REGRESSION\n  /DEPENDENT 满意度\n  /METHOD=ENTER 收入档_2 收入档_3."],
                           "CSV", 0.05, prelude=pre)
        ok("SET PRINTBACK=OFF." in sps, "关掉了语法回显（不然输出的前半页全是日志）")
        ok("GET DATA" in sps, "还是会把数据读进来")
        ok("/METHOD=ENTER 收入档_2 收入档_3." in sps, "回归用的是哑变量，不是原始字符串")
    except Exception as e:
        ok(False, "生成语法的自检能跑通", e)

    print("")
    print("=" * 70)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for x in FAIL:
        print("  ❌ " + x)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
