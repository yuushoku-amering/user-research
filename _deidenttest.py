# -*- coding: utf-8 -*-
"""脱敏的「表格式 / 花名册 / JSON / 二进制」专项自检

守的坑（都是实测踩出来的，用一份「广东海洋大学受访者信息表」当素材）：

  1. **裸姓名列抓不到** —— 表格里姓名是独立单元格，前面没有「姓名：」这种上下文，
     6 条姓名规则一条都不命中 → **12 个真名原样留着**。
  2. **表格里的学号抓不到** —— 那些规则要「学号」这个词紧挨着数字。
  3. **二进制文件静默无效** —— .xlsx 按文本读是乱码，"替换 0 处"，
     而人以为已经脱敏了。这个最危险。

跑法：  python _deidenttest.py
失败项同时写到 _jobs/deident_fail.txt（控制台被噪声搅了也看得见）。
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import importlib.util                                # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import paths                                  # noqa: E402

# 姓氏表要直接验（漏一个字的代价是一整类人的真名留在稿子里）
_spec = importlib.util.spec_from_file_location(
    "de_engine", os.path.join(HERE, "blocks", "b9_deident", "engine.py"))
_de = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_de)
SURNAME = _de.SURNAME
# 格式说明的文件名（跟引擎里 layout.REL 一致，别在两处各写一遍字符串）
import core.layout as _LAY                                # noqa: E402
_de_LAYOUT_MD = _LAY.REL

PASS = []
FAIL = []

COLS = ["编号", "姓名", "性别", "年龄", "年级", "学院", "专业", "学号", "手机", "邮箱", "生源地"]
ROWS = [
    ["R01", "陈嘉怡", "女", "19", "大二", "水产学院", "水产养殖学", "2023114501",
     "13800138001", "chenjiayi@stu.gdou.edu.cn", "广东湛江"],
    ["R02", "林俊杰", "男", "20", "大三", "海洋与气象学院", "海洋科学", "2022113205",
     "13900139002", "linjunjie@stu.gdou.edu.cn", "广东汕头"],
    ["R03", "黄思远", "男", "21", "大三", "机械与动力工程学院", "能源与动力工程", "2022112807",
     "13700137003", "huangsiyuan@stu.gdou.edu.cn", "广西南宁"],
]
NAMES = ["陈嘉怡", "林俊杰", "黄思远"]


def ok(cond, label, extra=""):
    if cond:
        PASS.append(label)
        print("  [OK] " + str(label))
    else:
        FAIL.append(label)
        print("  [FAIL] " + str(label) + (("  -- " + str(extra)) if extra else ""))


def run_block(root, params, block="b9_deident"):
    job = dict(params)
    job["project_root"] = root
    job["block_dir"] = os.path.join(HERE, "blocks", block)
    job["block_id"] = block
    jf = os.path.join(root, "_job.json")
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([paths.engine_python(), os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE, stdin=subprocess.DEVNULL)
    out = p.stdout.decode("utf-8", "replace")
    res, err = None, ""
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("t") == "result":
            res = m.get("data")
        elif m.get("t") == "error":
            err = m.get("msg", "")
    return {"result": res, "error": err}


def run_block_logs(root, params, block="b9_deident"):
    """跟 run_block 一样跑一次，但把**日志文字**也带回来。

    为什么需要：有些事只写在日志里（比如「你的确认和程序一致，所以输出没变化」）。
    提醒/产物里都看不出来，可研究员就是靠这句话才知道"选项没坏"。
    """
    job = dict(params)
    job["project_root"] = root
    job["block_dir"] = os.path.join(HERE, "blocks", block)
    job["block_id"] = block
    jf = os.path.join(root, "_job_logs.json")
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([paths.engine_python(), os.path.join(HERE, "runner.py"), jf],
                       capture_output=True, env=env, cwd=HERE, stdin=subprocess.DEVNULL)
    out = p.stdout.decode("utf-8", "replace")
    res, err, logs = None, "", []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("t") == "result":
            res = m.get("data")
        elif m.get("t") == "error":
            err = m.get("msg", "")
        elif m.get("t") == "log":
            logs.append(str(m.get("msg") or ""))
    return {"result": res, "error": err, "logs": logs}


def read_out(root, name):
    p = os.path.join(root, "output", name)
    if not os.path.exists(p):
        return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return open(p, encoding=enc).read()
        except UnicodeDecodeError:
            continue
    return ""


def write(root, rel, text, enc="utf-8"):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding=enc, newline="") as f:
        f.write(text)


def main():
    root = tempfile.mkdtemp(prefix="urw_de_")
    try:
        os.makedirs(os.path.join(root, "samples"), exist_ok=True)
        os.makedirs(os.path.join(root, "output"), exist_ok=True)

        print("\n【1】CSV：姓名是独立单元格（这块原来是全漏的）")
        write(root, "samples/信息表.csv",
              ",".join(COLS) + "\n" + "\n".join(",".join(r) for r in ROWS) + "\n", enc="utf-8-sig")
        r = run_block(root, {"file": "samples/信息表.csv", "keep_mapping": ["mapping"]})
        ok(not r["error"], "跑通", (r["error"] or "")[:80])
        out = read_out(root, "脱敏_信息表.csv")
        for nm in NAMES:
            ok(nm not in out, "姓名「%s」没了" % nm)
        for ph in ("13800138001", "2023114501", "chenjiayi@"):
            ok(ph not in out, "「%s」没了" % ph)
        ok("[姓名" in out, "换成了姓名占位")
        ok(("水产学院" in out) or ("水产养殖学" in out), "数据列没被误伤（学院/专业还在）")

        print("\n【2】TSV 和 Markdown 表格同样处理")
        write(root, "samples/信息表.tsv",
              "\t".join(COLS) + "\n" + "\n".join("\t".join(r) for r in ROWS) + "\n")
        run_block(root, {"file": "samples/信息表.tsv", "keep_mapping": ["mapping"]})
        ok("林俊杰" not in read_out(root, "脱敏_信息表.tsv"), "TSV 里姓名没了")

        write(root, "samples/信息表.md",
              "# 信息表\n\n| " + " | ".join(COLS) + " |\n|" + "---|" * len(COLS) + "\n"
              + "\n".join("| " + " | ".join(r) + " |" for r in ROWS) + "\n")
        run_block(root, {"file": "samples/信息表.md", "keep_mapping": ["mapping"]})
        ok("黄思远" not in read_out(root, "脱敏_信息表.md"), "Markdown 表格里姓名没了")

        print("\n【3】登记式「姓名：xxx」（规则里原来没有这个标签）")
        reg = "受访者信息登记\n\n"
        for r2 in ROWS:
            reg += "【%s】\n" % r2[0]
            for k, v in zip(COLS[1:], r2[1:]):
                reg += "%s：%s\n" % (k, v)
            reg += "\n"
        write(root, "samples/登记.txt", reg)
        run_block(root, {"file": "samples/登记.txt", "keep_mapping": ["mapping"]})
        out4 = read_out(root, "脱敏_登记.txt")
        ok("陈嘉怡" not in out4, "「姓名：陈嘉怡」被处理掉了")
        ok("[姓名" in out4, "换成了占位符")

        print("\n【4】一行一人「R01 陈嘉怡 女 19岁 …」（名字在中间）")
        one = "广东海洋大学 受访者信息表\n\n"
        for r2 in ROWS:
            one += "%s %s %s %s岁 %s %s %s 学号%s 手机%s 邮箱%s %s\n" % (
                r2[0], r2[1], r2[2], r2[3], r2[4], r2[5], r2[6], r2[7], r2[8], r2[9], r2[10])
        write(root, "samples/一行一人.txt", one)
        run_block(root, {"file": "samples/一行一人.txt", "keep_mapping": ["mapping"]})
        out5 = read_out(root, "脱敏_一行一人.txt")
        ok("林俊杰" not in out5, "名字在中间也被抓到了")
        ok("广东海洋大学" in out5, "学校名留着（准标识符，只提示不自动改）")

        print("\n【5】JSON：按字段名替换")
        j = {"school": "某大学", "subjects": [dict(zip(COLS, r2)) for r2 in ROWS]}
        write(root, "samples/信息.json", json.dumps(j, ensure_ascii=False, indent=2))
        run_block(root, {"file": "samples/信息.json", "keep_mapping": ["mapping"]})
        out6 = read_out(root, "脱敏_信息.json")
        ok("林俊杰" not in out6, "JSON 里姓名没了")
        ok("2023114501" not in out6, "JSON 里学号没了")
        ok('"school"' in out6, "不该动的字段留着")

        print("\n【6】二进制文件必须明确拒绝，不能静默无效")
        p6 = os.path.join(root, "samples", "信息表.xlsx")
        with open(p6, "wb") as f:
            f.write(b"PK\x03\x04" + b"\x00" * 64 + b"fake xlsx")
        r6 = run_block(root, {"file": "samples/信息表.xlsx", "keep_mapping": ["mapping"]})
        ok(bool(r6["error"]), "xlsx 被拒绝（不是安静地输出乱码）")
        ok("二进制" in str(r6["error"]), "理由说的是「二进制格式」")
        ok(("CSV" in str(r6["error"])) or ("txt" in str(r6["error"])),
           "并且告诉你怎么转（另存为 CSV/txt）")
        ok(not os.path.exists(os.path.join(root, "output", "脱敏_信息表.xlsx")),
           "没有生成那个假脱敏文件")

        print("\n【7】图片（手机截图）—— 明确说清楚为什么不读，以及该怎么办")
        # 手机记事簿截图是很自然的素材来源，但图片没有文字层。
        # 工作台**故意不接 OCR**：装几百 MB 破坏零依赖，而且为了读姓名手机号
        # 把整张图发云端，跟「先过 🔒 再分析」是矛盾的。
        png = bytes.fromhex("89504e470d0a1a0a") + b"\xff\xd8\xff" + "截图".encode("utf-8")
        with open(os.path.join(root, "samples", "记事簿截图.png"), "wb") as f:
            f.write(png)
        r7 = run_block(root, {"file": "samples/记事簿截图.png", "keep_mapping": ["mapping"]})
        ok(bool(r7["error"]), "图片被拒绝（不是安静地输出乱码）")
        msg = str(r7["error"])
        ok("图片" in msg, "说了「这是一张图片」")
        ok("OCR" in msg, "说明了为什么不接 OCR")
        ok("提取文字" in msg or "识屏" in msg, "告诉他怎么自己提取文字（手机自带能力）")
        ok("云端" in msg or "上传" in msg, "把隐私代价说明白了")
        ok(not os.path.exists(os.path.join(root, "output", "脱敏_记事簿截图.png")),
           "**没有生成那个假脱敏文件**")

        print("\n【8】不许误伤：普通文本不该被当成姓名列换掉")
        write(root, "samples/笔记.txt",
              "研究笔记\n\n今天访谈很顺利，学生普遍谈到经济压力。\n恋爱中的花销主要由男生承担。\n")
        run_block(root, {"file": "samples/笔记.txt", "keep_mapping": ["mapping"]})
        out8 = read_out(root, "脱敏_笔记.txt")
        ok(("经济压力" in out8) and ("恋爱中" in out8), "普通句子没被动（没把「恋爱中」当人名）")

        print("\n【9】姓氏表：漏一个字就是一类人的真名留在稿子里")
        ok(len(SURNAME) == len(set(SURNAME)), "姓氏表没有重复（原来是 177 字里 39 个重复）")
        TOP100 = ("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾"
                  "肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏"
                  "韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴"
                  "莫孔向汤")
        miss = [c for c in TOP100 if c not in SURNAME]
        ok(not miss, "全国前 100 大姓一个不缺", "".join(miss))
        for c in ("刘", "徐", "胡", "肖", "付", "闫", "龙", "林"):
            ok(c in SURNAME, "「%s」在姓氏表里" % c)

        print("\n【10】记事簿随手写（无表头、名字后面接手机号）")
        # 现场：她自己在记事簿写了 4 组，两个姓名没认出来。
        # 根因：原来的姓名规则要求名字后面紧跟「男/女/N岁」，而这里接的是手机号；
        #       而且「刘」不在姓氏表里。
        nb = ("张伟 男 13812345678\n"
              "李娜 女 18900001111 QQ 33445566\n"
              "王芳 15912345678 微信 wangfang_88\n"
              "陈晨 男 17788889999 邮箱 chenchen@qq.com\n"
              "刘洋 13611112222\n"
              "孙磊 18833334444 电话 18955556666\n")
        write(root, "samples/记事簿.txt", nb)
        run_block(root, {"file": "samples/记事簿.txt", "keep_mapping": ["mapping"]})
        out10 = read_out(root, "脱敏_记事簿.txt")
        for nm in ("张伟", "李娜", "王芳", "陈晨", "刘洋", "孙磊"):
            ok(nm not in out10, "随手记里的姓名「%s」被处理掉了" % nm)
        for ph in ("13812345678", "18900001111", "15912345678", "17788889999",
                   "13611112222", "18833334444", "18955556666"):
            ok(ph not in out10, "手机「%s」被处理掉了" % ph)
        ok("33445566" not in out10, "QQ 号也处理掉了")
        ok("wangfang_88" not in out10, "微信号也处理掉了")

        print("\n【11】数字串有歧义时要提醒，但**不能乱报**")
        r11 = run_block(root, {"file": "samples/记事簿.txt", "keep_mapping": ["mapping"]})
        al = ((r11.get("result") or {}).get("alerts") or [])
        amb = [a for a in al if "歧义" in str(a.get("msg"))]
        ok(bool(amb), "同行既有 QQ 又有 11 位数字 → 给出歧义提醒（%d 条）" % len(amb))
        # 单独一行的手机号不该被报成歧义（第一版按 ±30 字符取上下文，会跨行，误报一片）
        nb2 = "张伟 男 13812345678\n李娜 女 13900002222\n"
        write(root, "samples/纯手机.txt", nb2)
        r11b = run_block(root, {"file": "samples/纯手机.txt", "keep_mapping": ["mapping"]})
        amb2 = [a for a in ((r11b.get("result") or {}).get("alerts") or [])
                if "歧义" in str(a.get("msg"))]
        ok(not amb2, "没有 QQ/微信字眼时**不报**歧义（不跨行乱猜）", amb2)
        print("\n【12】编号绝不撞车（撞号 = 把两个人合并成一个人）")
        # 现场：上下文规则把「陈云」发成 [姓名1]，按格式那步**另起计数器**又把
        # 「晓晓」发成 [姓名1] —— 两个人同号。读稿的人会以为只有 3 个受访者。
        nb3 = ("陈云 男 14658167618 恋爱中\n\n"
               "晓晓 女 17676494856 已分手\n\n"
               "杜翔 男 16795819494 恋爱中\n\n"
               "红红 女 16792816434 恋爱中\n")
        write(root, "samples/昵称.txt", nb3)
        run_block(root, {"file": "samples/昵称.txt", "out_name": "脱敏_昵称.txt",
                         "extra_rules": "晓晓 = [受访者B]", "keep_mapping": ["mapping"]})
        out12 = read_out(root, "脱敏_昵称.txt")
        nums = re.findall(r"\[姓名(\d+)\]|\[受访者(\w+)\]", out12)
        got = [a or b for a, b in nums]
        ok(len(got) == len(set(got)), "四个人的标记都不一样（实际 %s）" % got, got)
        ok("晓晓" not in out12, "自定义替换里的「晓晓」被换掉了")
        mp = read_out(root, "编号对照表.csv")
        ok(mp.count("[姓名1]") == 1, "对照表里 [姓名1] 只出现一次（没撞号）")

        print("\n【13】格式识别：看出一行一条 / 空行分隔，拿不准要说出来")
        sys.path.insert(0, HERE)
        from core import layout as LAY
        i13 = LAY.detect(nb3, sample_n=3)
        ok(i13.get("style") == "line", "四个对象被认成「一行一条」", i13.get("style"))
        ok(i13.get("records") == 4, "认出 4 条记录", i13.get("records"))
        kinds13 = [c["kind"] for c in i13.get("columns") or []]
        ok("姓名" in kinds13, "认出姓名那一列")
        ok("手机" in kinds13, "认出手机那一列")
        ok("恋爱中" not in "".join(kinds13), "**没把「恋爱中」当姓名**（位置推断原来就错在这）")
        un13 = " ".join(i13.get("uncertain") or [])
        ok("晓晓" in un13 or "红红" in un13 or "没被认出来" in un13,
           "把「没认出来的词」报出来了（而不是说「没问题」）")
        # 空行分隔 + 标签式
        blk = ("姓名：张伟\n性别：男\n手机：13812345678\n\n"
               "姓名：李娜\n性别：女\n手机：13900002222\n")
        i13b = LAY.detect(blk, sample_n=3)
        ok(i13b.get("style") == "block", "标签式被认成「空行分隔」", i13b.get("style"))
        kinds13b = [f["kind"] for f in i13b.get("fields") or []]
        ok("姓名" in kinds13b and "手机" in kinds13b, "块式里认出姓名和手机")
        # 生成的说明文件要能看懂
        md13 = LAY.to_markdown(i13, "samples/昵称.txt")
        ok("拿不准的地方" in md13, "说明文件里有「拿不准的地方」那一节")
        ok("一行一条" in md13, "说明文件里写清了切法")
        print("\n【14】特征标记优先（前辈提的：邮箱有 @，那就是判据）")
        # 现场：原来靠"按顺序猜哪个更像"，结果手机号被认成学号、10 位学号被认成 QQ。
        # 改成：**先看有没有特征标记，再谈形状**。@ 是最硬的那个证据。
        from core import layout as LAY2
        for v, want in (("chenjiayi@stu.gdou.edu.cn", "邮箱"),
                        ("wangfang_88@qq.com", "邮箱"),
                        ("a@b.cn", "邮箱"),
                        ("13812345678", "手机"),
                        ("14658167618", "手机"),
                        ("15912345678", "手机"),
                        ("33445566", "QQ"),
                        ("11855001", "QQ"),
                        ("123456789", "QQ"),
                        ("jy_chen1998", "微信"),
                        ("wangfang_88", "微信"),
                        ("2023114501", "学号"),
                        ("2021110233", "学号"),
                        ("陈云", "姓名"),
                        ("杜翔", "姓名"),
                        ("刘洋", "姓名"),
                        ("恋爱中", ""),
                        ("男", ""),
                        ("晓晓", ""),
                        ("大二", ""),
                        ("广东湛江", ""),
                        ("广州天河", ""),
                        ("湖南衡阳", "")):
            got = LAY2.marker_kind(v)
            ok(got == want, "「%s」→ %s" % (v, got or "(不是标识符)"),
               "期望 %s，实际 %s" % (want or "(不是标识符)", got or "(不是标识符)"))
        print("\n【15】提醒里说的路径，和文件真实位置必须一致")
        # 现场：ctx.save_text 是按给的相对路径直接写（不是自动进 output/）。
        #   漏了 `output/` 前缀 → md 落在项目根目录，而提醒写的是 `output/脱敏格式.md`，
        #   人一点就"文件不存在" —— 看着像功能坏了，其实只是路径自己跟自己对不上。
        nb15 = ("陈云 男 14658167618 恋爱中\n\n晓晓 女 17676494856 已分手\n\n"
                "广东莞 男 13800138000 恋爱中\n\n红红 女 16792816434 恋爱中\n")
        write(root, "samples/路径.txt", nb15)
        r15 = run_block(root, {"file": "samples/路径.txt", "out_name": "脱敏_路径.txt",
                               "keep_mapping": ["mapping"]})
        ok(not r15["error"], "跑通", (r15["error"] or "")[:60])
        ok(os.path.exists(os.path.join(root, "output", _de_LAYOUT_MD)),
           "格式说明落在 output/ 里（%s）" % _de_LAYOUT_MD)
        ok(not os.path.exists(os.path.join(root, _de_LAYOUT_MD)),
           "**没有**落在项目根目录（那是路径漏了 output/ 的旧毛病）")
        # 提醒里提到的路径，必须真的存在
        al15 = ((r15.get("result") or {}).get("alerts") or [])
        for a in al15:
            rel = a.get("rel") or ""
            if rel:
                ok(os.path.exists(os.path.join(root, rel.replace("/", os.sep))),
                   "提醒里指的 `%s` 真的存在" % rel)
        # ⚠ 光看 `rel` 不够：**提醒的正文里**还会自己写一句"看完整说明：output/xxx"。
        #   文件名从 `脱敏格式.md` 改成 `格式说明.md` 那次，`rel` 跟着改了，
        #   但正文那句是硬编码的，漏改了 —— 人点那句还是会去找一个不存在的文件。
        #   所以正文里提到的每一个 output/文件 都得真的在。
        for a in al15:
            blob = (a.get("msg") or "") + " " + (a.get("fix") or "")
            for m in re.finditer(r"output/([^\s，。；、）)`\"']+)", blob):
                fn = m.group(1).strip()
                ok(os.path.exists(os.path.join(root, "output", fn)),
                   "提醒正文里写的 `output/%s` 真的存在" % fn)

        print("\n【16】记事簿式材料：格式说明不能自相矛盾，选项不能拿整条记录开刀")
        # 研究员报的两条：
        #   「他提醒的部分和他已经处理了的部分有重合啊」
        #     → 因为格式说明把**整条记录**报成"没认出来的词"，而那条记录里的手机号
        #       早被换成了占位符，这个"整条"其实已经不存在；点一下还会把整条记录换成代号。
        #   「问题表述配合操作有点复杂」「第三个位置是具体指哪里呢」
        #     → 因为一条记录占好几行时，按「第 N 行」报的字段跟材料对不上号。
        nb16 = ("陈云 男 14658167618 恋爱中\n晓晓 女 17676494856 已分手\n"
                "杜翔 男 QQ 13177778888 单身\n\n"
                "林嘉怡 女 2023114501 恋爱中\n红红 女 15900001111 单身\n"
                "广东莞 男 13700002222 恋爱中\n")
        write(root, "samples/记事簿.txt", nb16)
        r16 = run_block(root, {"file": "samples/记事簿.txt", "out_name": "脱敏_记事簿.txt"})
        ok(not r16["error"], "跑通", (r16["error"] or "")[:80])
        md16 = read_out(root, "格式说明.md")
        ok("行内各段" in md16, "按「一行里的第几段」说明，而不是含糊的「第 N 行」")
        ok("占 3 行" in md16, "说清了一条记录占几行（%s）"
           % ("占 3 行" if "占 3 行" in md16 else "没说清"))
        ok("第 5 段" not in md16, "没有把「每人 3 行」摊成一列 9 个值（冒出假的第 5 段）")
        al16 = ((r16.get("result") or {}).get("alerts") or [])
        # 选项里的"原文"绝不能带空格（带空格 = 整条记录 = 会把一行资料整段换掉）
        bad = []
        for a in al16:
            for o in a.get("options") or []:
                src = o.get("src") or ""
                if src and re.search(r"\s", src):
                    bad.append(src)
                line = o.get("line") or ""
                if line and re.search(r"^\S*\s+\S+\s+\S+\s*=", line):
                    bad.append(line)
        ok(not bad, "选项里没有「整条记录」当原文（那会把一行资料整段换掉）", bad[:3])        # 「没被认出来的词」选项必须是**词**，不能是字段值
        vals16 = [o.get("src") for a in al16 for o in (a.get("options") or [])
                  if "没认出来" in str(a.get("msg"))]
        ok("恋爱中" not in vals16 and "单身" not in vals16 and "已分手" not in vals16,
           "没把「恋爱中/单身/已分手」这种字段值当成人名给你换", vals16)
        # 「确认判断」的选项要真的能改结果
        for cmd, want in (("!这是手机 13700002222 = ", "[手机"),
                          ("!这是QQ 13700002222 = ", "[QQ"),
                          ("!不用管 13700002222 = ", None)):
            r16b = run_block(root, {"file": "samples/记事簿.txt",
                                    "out_name": "脱敏_确认.txt", "extra_rules": cmd})
            o16 = read_out(root, "脱敏_确认.txt")
            if want:
                ok(want in o16, "`%s` 真的改变了输出（要出现 %s）" % (cmd.strip(), want), o16[:120])
            else:
                ok("[保留" not in o16, "「不用管」不会再凭空造一个 `[保留N]` 出来", o16[:120])

        print("\n【17】手机号的写法变体：带分隔符 / 全角，都要认，而且不能撞号")
        # 现场：`130-1234-5678`、`１５５００００２２２２` 原来整条漏掉（只给一句提醒），
        #   而放宽之后又踩了两个坑：
        #     ① rep.map 存原文、取号用归一化串 → 同一个号被当成两个人，发两个号；
        #     ② 全角/半角拆成两条规则 → 全角那条先跑，先拿走最小号，
        #        于是第 12 条的全角手机拿到了 `[手机1]`（在文档里它不是第一个）。
        for form in ("130-1234-5678", "13012345678",
                     "１５５００００２２２２", "15500002222",
                     "130 1234 5678"):
            r17 = run_block(root, {"file": "samples/记事簿.txt",
                                   "out_name": "脱敏_写法.txt",
                                   "extra_rules": "%s = [写法占位]" % form})
            o17 = read_out(root, "脱敏_写法.txt")
            ok(form not in o17, "`%s` 被处理掉了（不留原样）" % form, o17[:120])

        # 同一个号的两种写法 → 必须并成**一个**实体、一个号
        dup = ("李雷 男 13012345678 恋爱中\n\n韩梅梅 女 130-1234-5678 单身\n")
        write(root, "samples/同号.txt", dup)
        r17b = run_block(root, {"file": "samples/同号.txt", "out_name": "脱敏_同号.txt",
                                "keep_mapping": ["mapping"]})
        o17b = read_out(root, "脱敏_同号.txt")
        phones17 = re.findall(r"\[手机(\d+)\]", o17b)
        ok(len(phones17) == 2 and len(set(phones17)) == 1,
           "同一个号的两种写法并成一个实体、共用一个号", phones17)

        # 号段顺序：编号要按**在文档里的先后**发，不能按规则的先后
        seq = ("甲一 男 15500002222 恋爱中\n\n乙二 男 13012345678 单身\n")
        write(root, "samples/序.txt", seq)
        r17c = run_block(root, {"file": "samples/序.txt", "out_name": "脱敏_序.txt"})
        o17c = read_out(root, "脱敏_序.txt")
        ok(o17c.find("[手机1]") < o17c.find("[手机2]") and o17c.count("[手机1]") == 1,
           "第一个出现的人拿 [手机1]（顺序按文档，不按规则）", o17c.replace("\n", " / "))

        # 「我看着像但没处理」不能和「我已经处理了」打架。
        # ⚠ 只看**那一类**提醒：段位提醒里会正当地把这一段的实际值列出来当例子
        #   （`实际写的是「13012345678、130-1234-5678」`），那不是"没处理"，是"长这样"。
        r17d = run_block(root, {"file": "samples/同号.txt", "out_name": "脱敏_同号2.txt"})
        al17 = " ".join(str(a.get("msg") or "")
                        for a in ((r17d.get("result") or {}).get("alerts") or [])
                        if "没被处理" in str(a.get("msg")))
        ok("130-1234-5678" not in al17 and "13012345678" not in al17,
           "已经处理掉的写法，不会再报一句「看着像标识符但没处理」", al17[:120])

        print("\n【18】编号按**原文出现顺序**发（研究员拍板的第 1 条）")
        # 他原话：「我就是很担心顺序这个东西，怕用户需要自己改的时候不知道这是几号，
        #   又担心遗漏或者多编了一行什么的导致顺序大乱」。
        # 踩过：`晓晓` 在文档第 2 条、却拿到 `[姓名18]`（因为姓名通道是"认出来就发号"）。
        ordr = ("陈云 男 14658167618 恋爱中\n\n"
                "晓晓 女 17676494856 已分手\n\n"
                "杜翔 男 16795819494 恋爱中\n\n"
                "李明 男 13800138001 单身\n")
        write(root, "samples/顺序.txt", ordr)
        r18 = run_block(root, {"file": "samples/顺序.txt", "out_name": "脱敏_顺序.txt",
                               "keep_mapping": ["mapping"]})
        o18 = read_out(root, "脱敏_顺序.txt")
        # 姓名/手机各自都要 1、2、3、4，且按文档先后
        for pre in ("姓名", "手机"):
            got = re.findall(r"\[%s(\d+)\]" % pre, o18)
            ok(got == ["1", "2", "3", "4"], "%s编号按文档顺序连号 1-4（实际 %s）" % (pre, got))
        ok(o18.find("[姓名1]") < o18.find("[姓名2]") < o18.find("[姓名3]"),
           "第一个人就是 [姓名1]（不再跳到 18 号）", o18.replace("\n", " / ")[:140])
        # 对照表要能跟原文逐行对
        mp18 = read_out(root, "编号对照表.csv")
        ok("原文第几行" in mp18, "对照表带上了「原文第几行」")
        ok("[姓名1],陈云,姓名（上下文）,1" in mp18.replace(" ", ""),
           "对照表第一行就是原文第 1 行的陈云对应 [姓名1]", mp18.splitlines()[1] if mp18 else "")
        # 交换编号也不能踩踏（1→2、2→1 那种）
        swap = "甲一 男 15500002222 恋爱中\n\n乙二 男 13012345678 单身\n"
        write(root, "samples/交换.txt", swap)
        r18b = run_block(root, {"file": "samples/交换.txt", "out_name": "脱敏_交换.txt"})
        o18b = read_out(root, "脱敏_交换.txt")
        ok(o18b.count("[手机1]") == 1 and o18b.count("[手机2]") == 1
           and o18b.find("[手机1]") < o18b.find("[手机2]"),
           "重排时不会把改好的又改回去（1→2、2→1 那种交换）", o18b.replace("\n", " / "))

        print("\n【19】「第 N 段是什么」——**段位判断只用说一次**")
        # 研究员的原话：「我想要告诉她是手机，但是每一行原文都不一样我怎么填呢，
        #   同时也没有选项给我直接告诉她是手机」。
        # 所以：① 那种提醒必须带能点的选项 ② 选项写的是**段位**不是某个值
        #      ③ 确认之后整份材料照办（不用逐行填）
        seg = ("甲一 男 zhangsan_88 恋爱中\n"
               "乙二 女 lisi_99 单身\n"
               "丙三 男 wangwu_77 恋爱中\n")
        write(root, "samples/段位.txt", seg)
        # ① 选项：先造一个**真的拿不准**的段（这一格前几条里出现过手机和学号两种）
        mixed = ("甲一 男 14658167618 恋爱中\n"
                 "乙二 女 20231145 单身\n"
                 "丙三 男 15900001111 恋爱中\n")
        write(root, "samples/段位混.txt", mixed)
        r19x = run_block(root, {"file": "samples/段位混.txt", "out_name": "脱敏_段位混.txt"})
        al19x = ((r19x.get("result") or {}).get("alerts") or [])
        seg_al = [a for a in al19x if re.search(r"第\s*3\s*段", str(a.get("msg")))]
        opts19 = [o.get("label") for a in seg_al for o in (a.get("options") or [])]
        ok(bool(seg_al), "「一行里第 N 段拿不准」这条提醒真的会发出来",
           [a.get("msg", "")[:50] for a in al19x])
        ok(any("是手机号" in (x or "") for x in opts19),
           "它带了「这一段是手机号」这种**能点的选项**（以前一个选项都没有）", opts19[:6])
        ok(any("不是标识符" in (x or "") for x in opts19), "也给了「不是标识符，别管它」")
        lines19 = [o.get("line") for a in seg_al for o in (a.get("options") or [])]
        ok(any((x or "").startswith("!第") and "段是" in (x or "") for x in lines19),
           "选项的写法是**段位判断**（`!第3段是手机`），不是某一个具体值", lines19[:4])
        # ② 一个都认不出来的段，也得给"它其实是手机/微信号"这种出路
        r19y = run_block(root, {"file": "samples/段位.txt", "out_name": "脱敏_段位y.txt"})
        al19y = ((r19y.get("result") or {}).get("alerts") or [])
        seg_y = [a for a in al19y if re.search(r"第\s*[13]\s*段", str(a.get("msg")))]
        opts_y = [o.get("label") for a in seg_y for o in (a.get("options") or [])]
        ok(any("是微信号" in (x or "") for x in opts_y),
           "「一个都没认出来」的段也有「这一段是微信号」这种选项", opts_y[:8])
        # ③ 确认之后整份材料照办
        r19b = run_block(root, {"file": "samples/段位.txt", "out_name": "脱敏_段位2.txt",
                                "extra_rules": "!第3段是微信"})
        o19 = read_out(root, "脱敏_段位2.txt")
        ok("zhangsan_88" not in o19 and "lisi_99" not in o19 and "wangwu_77" not in o19,
           "**只说一次**，三行的第 3 段全被处理了（不用逐行填）", o19.replace("\n", " / "))
        # ④ 人说「这一段别管」时，**程序就别再拿它来问**
        r19c = run_block(root, {"file": "samples/段位混.txt", "out_name": "脱敏_段位3.txt",
                                "extra_rules": "!第3段不用管"})
        al19c = " ".join(str(a.get("msg") or "")
                         for a in ((r19c.get("result") or {}).get("alerts") or []))
        ok(not re.search(r"第\s*3\s*段", al19c),
           "说了「第 3 段不用管」之后，不再拿它来问（位置推断那一路不碰它了）", al19c[:120])

        print("\n【20】提醒要带**位置**（点一下就翻到原文那一行）")
        # 研究员原话：「给问题加一个跳转到原文档对应位置直接查看的功能，
        #   自己翻原文档一行行找太要命了」。
        # 用一个**带 QQ 字眼**的材料验行号（歧义提醒只在"同一行出现 QQ/微信 + 11 位数"时才发）
        loc_src = ("甲一 男 14658167618 恋爱中\n"
                   "乙二 女 20231145 单身\n"
                   "丙三 男 QQ 13177778888 单身\n")
        write(root, "samples/定位.txt", loc_src)
        r20 = run_block(root, {"file": "samples/定位.txt", "out_name": "脱敏_定位.txt"})
        al20 = ((r20.get("result") or {}).get("alerts") or [])
        ok(bool(al20), "有提醒可查")
        with_loc = [a for a in al20 if a.get("locate")]
        ok(len(with_loc) == len(al20), "每条提醒都带了 locate（原文在哪一行）",
           [(a.get("msg", "")[:20], a.get("locate")) for a in al20 if not a.get("locate")])
        for a in with_loc:
            loc = a["locate"]
            ok(loc.get("file") == "samples/定位.txt",
               "locate 指的是**源材料**（不是产物）", loc)
            ok(isinstance(loc.get("line"), int) and loc["line"] >= 1,
               "行号是正整数", loc)
        # 歧义那条的行号必须真的指到那个号码所在的行
        amb20 = [a for a in al20 if "歧义" in str(a.get("msg"))]
        ok(bool(amb20), "歧义提醒在")
        if amb20:
            ln20 = amb20[0]["locate"]["line"]
            src20 = loc_src.split("\n")
            ok(0 < ln20 <= len(src20) and "13177778888" in src20[ln20 - 1],
               "行号对得上（第 %d 行确实是那个号）" % ln20,
               src20[ln20 - 1] if 0 < ln20 <= len(src20) else "")
        # 「第 N 段」那类没有具体值时，也要落到"第一段所在的那一行"，而不是瞎猜一行
        seg20 = [a for a in al20 if re.search(r"第\s*3\s*段", str(a.get("msg")))]
        if seg20:
            ln_s = seg20[0]["locate"]["line"]
            ok(0 < ln_s <= len(loc_src.split("\n")),
               "段位提示的行号落在材料范围内", ln_s)

        print("\n【22】「这条不用再问」的名单：存项目里、读得回来")
        # 研究员提的：「防止有如『没被认出来的词』这种复杂情况…加一个选项来跳过或者无视这一提醒」
        # 有些提醒根本没有逐条回答的办法（它把一批杂七杂八的东西混在一起），
        # 那就得允许他说"这条我看过了，别再显示"。名单存**项目里**（换机器/打包带走还在）。
        import server as SRV

        class _P(object):
            def __init__(self, root):
                self.root = root

            def safe(self, rel):
                return os.path.join(self.root, rel.replace("/", os.sep))

        proj22 = _P(root)
        ok(SRV._load_ignored(proj22) == [], "没有名单时读出空（不是崩）")
        SRV._save_ignored(proj22, ["a1", "a2", "a1"])
        got22 = SRV._load_ignored(proj22)
        ok(got22 == ["a1", "a2"], "存进去、读回来，并且**自动去重**", got22)
        ok(os.path.exists(os.path.join(root, SRV.IGNORED_REL)),
           "名单落在项目里（%s）—— 跟着项目走，不是浏览器" % SRV.IGNORED_REL)
        # 坏文件不能炸
        with open(os.path.join(root, SRV.IGNORED_REL), "w", encoding="utf-8") as f:
            f.write("{不是 json")
        ok(SRV._load_ignored(proj22) == [], "名单文件坏了也只是读出空（不崩）")

        print("\n【23】两套编号方式：按出现顺序 / 按序号（研究员拍板的第 2 套）")
        # 他原话：「这个 qq 不是所有人都有记录，我们上次说按出现的顺序记录，我觉得是一个解法，
        #   同时我想补充第二种编码方式供选择：如果用户提供了序号，就把电话和 qq 都按前面的
        #   序号匹配；如果没有序号，我们就按行数来默认添加一个前置的序号，再做匹配。」
        nosq = ("陈云 男 14658167618 恋爱中\n\n"
                "晓晓 女 17676494856 已分手\n\n"
                "杜翔 男 QQ 13177778888 单身\n")
        write(root, "samples/无序号.txt", nosq)
        # ① 默认档：还是按出现顺序（不能把老行为改坏）
        r23a = run_block(root, {"file": "samples/无序号.txt", "out_name": "脱敏_序a.txt"})
        o23a = read_out(root, "脱敏_序a.txt")
        ok("[姓名1]" in o23a and "[姓名2]" in o23a and "[手机1]" in o23a,
           "默认仍是「按出现顺序」连号", o23a.replace("\n", " / "))
        # ② 按序号 + 没给序号列 → 用**行号**，并且带 `#`（跟"第几个"分得开）
        r23b = run_block(root, {"file": "samples/无序号.txt", "out_name": "脱敏_序b.txt",
                                "numbering": "seq"})
        o23b = read_out(root, "脱敏_序b.txt")
        ok("[姓名#1]" in o23b and "[姓名#3]" in o23b and "[手机#5]" not in o23b,
           "没序号列时用行号当序号（第 1、3、5 行），带 `#` 前缀", o23b.replace("\n", " / "))
        ok("[姓名#1]" in o23b and "[姓名#3]" in o23b,
           "同一行里的姓名和手机拿到**同一个序号**（一眼看出是同一条记录）",
           o23b.replace("\n", " / "))
        # ③ 有用户自己的序号列 → 按它匹配
        withsq = ("R07 陈云 男 14658167618 恋爱中\n\n"
                  "R11 晓晓 女 17676494856 已分手\n\n"
                  "R23 杜翔 男 QQ 13177778888 单身\n")
        write(root, "samples/有序号.txt", withsq)
        r23c = run_block(root, {"file": "samples/有序号.txt", "out_name": "脱敏_序c.txt",
                                "numbering": "seq", "seq_col": "第1段"})
        o23c = read_out(root, "脱敏_序c.txt")
        ok("[姓名R07]" in o23c and "[手机R11]" in o23c and "[QQR23]" in o23c,
           "给了序号列就按它匹配（[姓名R07]、[手机R11]、[QQR23]）",
           o23c.replace("\n", " / "))
        ok("R07 [姓名R07]" in o23c, "用户的序号列本身留着不动，占位符对得上它",
           o23c.split("\n")[0])
        # ④ 说了按序号但序号列找不到 → 老实退回行号（不报错、不留空号）
        r23d = run_block(root, {"file": "samples/有序号.txt", "out_name": "脱敏_序d.txt",
                                "numbering": "seq", "seq_col": "序号"})
        o23d = read_out(root, "脱敏_序d.txt")
        ok("[姓名#1]" in o23d, "序号列找不到时退回行号（不炸、不空）", o23d.replace("\n", " / "))
        # ⑤ 同一条记录里同一种东西出现两次 → 不能撞号
        dup2 = "R07 沈括 男 18900001111 备注：备用号 13500002222\n"
        write(root, "samples/两条号.txt", dup2)
        r23e = run_block(root, {"file": "samples/两条号.txt", "out_name": "脱敏_序e.txt",
                                "numbering": "seq", "seq_col": "第1段"})
        o23e = read_out(root, "脱敏_序e.txt")
        phones23 = re.findall(r"\[手机([^\]]+)\]", o23e)
        ok(len(phones23) == 2 and len(set(phones23)) == 2,
           "同一条记录里两个手机号不撞号（加 a/b 后缀）", phones23)

        print("\n【21】「一列里只有一部分要处理」和「选了没效果」的反馈")
        # 研究员报的两条：
        #   ① 选了「这是 QQ/微信号」之后自定义里的呈现有问题（指令被拼上了 `= `，工程师那边匹配不上）
        #   ② 选了「第 3 段是手机号」看着没效果 —— 其实生效了，只是**和程序判断一致**，
        #      输出当然一模一样。这种"没效果"必须主动说清楚，不然永远查不出来。
        # 指令**原样存**（不带 `=`）也要能被引擎认出来
        qq = "刘洋 男 16000000001 QQ 16000000001\n"
        write(root, "samples/指令.txt", qq)
        for rule, want in (("!这是QQ 16000000001", "[QQ"),
                           ("!这是手机 16000000001", "[手机")):
            r21 = run_block(root, {"file": "samples/指令.txt", "out_name": "脱敏_指令.txt",
                                   "extra_rules": rule})
            o21 = read_out(root, "脱敏_指令.txt")
            ok(want in o21, "指令 `%s`（不带 =）真的生效（要出现 %s）" % (rule, want),
               o21.replace("\n", " / "))
        # 一致时要有明确反馈
        r21b = run_block_logs(root, {"file": "samples/定位.txt", "out_name": "脱敏_一致.txt",
                                     "extra_rules": "!第3段是手机"})
        logs21 = " ".join(r21b.get("logs") or [])
        ok("一致" in logs21 or "本来" in logs21,
           "确认和自动判断一致时，明说「没东西可改」（不是默默没反应）", logs21[:160])
        # 确认过的段，不该再问第二遍
        al21 = " ".join(str(a.get("msg") or "")
                        for a in ((r21b.get("result") or {}).get("alerts") or []))
        ok(not re.search(r"第\s*3\s*段", al21),
           "确认过「第 3 段是手机」之后，不再拿这一段来问", al21[:120])

        print("\n【24】姓氏表里的常用字**不许把正文当成名字换掉**（真名照旧要抓到）")
        # 现场（2026-09-24，拿一份新写的访谈转写稿跑 🔒 才暴露）：
        #   姓氏表里混着一大堆常用字（时/都/基/本/长/方/于/明/全/成/段/白…），
        #   于是「一个两字词的前半截」只要以这些字开头就被当成人名。三处误伤：
        #     `时长：41 分钟`   → `[姓名4]：41 分钟`（那是"访谈时长"的登记项，一个真名都没有）
        #     `他爸妈都是老师`   → `他爸妈[姓名5]老师`
        #     `这种基本都是他`   → `这种基本[姓名5]他`
        #   **把正文改坏比漏一个名字严重得多** —— 漏了他能自己补，改坏了他未必发现。
        transcript = (
            "访谈对象：周然\n"
            "访谈时间：2026年4月3日 下午 2:00\n"
            "访谈者：李明\n"
            "时长：41 分钟\n"
            "\n"
            "---\n"
            "\n"
            "李明：先随便聊聊，你家里是什么情况？\n"
            "周然：我爸妈都是老师，家里挺规矩的。\n"
            "周然：平时吃饭看电影这种基本都是他。\n"
            "周然：我长期住校，周末才回去。\n"
            "周然：方便的话可以加我，手机 13700001111。\n"
        )
        write(root, "samples/转写稿_误伤.txt", transcript)
        r24 = run_block(root, {"file": "samples/转写稿_误伤.txt", "out_name": "脱敏_误伤.txt"})
        o24 = read_out(root, "脱敏_误伤.txt")
        ok("时长：41 分钟" in o24, "「时长：41 分钟」原样留着（不当说话人、不当人名）",
           o24.replace("\n", " / ")[:160])
        ok("我爸妈都是老师" in o24, "「我爸妈都是老师」不被切成「他爸妈[姓名]老师」",
           [l for l in o24.split("\n") if "老师" in l][:2])
        ok("这种基本都是他" in o24, "「这种基本都是他」不被切成「基本[姓名]他」",
           [l for l in o24.split("\n") if "基本" in l][:2])
        ok("[姓名" in o24 and "周然" not in o24, "真名「周然」照样被换掉（没因为收紧而漏）",
           [l for l in o24.split("\n") if "姓名" in l][:3])
        ok("李明" not in o24, "访谈者的名字也照样换掉")
        ok("[手机" in o24, "手机号照样被换掉")
        # 直接验函数：这两句里的碎片绝不能再出现在候选里
        cands24 = _de.find_names_in_contact_lines(transcript)
        ok("时长" not in cands24, "候选里没有「时长」", cands24)
        ok("都是" not in cands24, "候选里没有「都是」", cands24)
        ok("基本" not in cands24, "候选里没有「基本」", cands24)
        ok(not _de._is_sentence_word("王芳", "王芳 15912345678 微信 wf_88", 0),
           "正常的「王芳 手机号」不算句子碎片（该抓的还得抓）")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + ("全部通过" if not FAIL else "有失败项")
          + "：%d 通过 / %d 失败\n" % (len(PASS), len(FAIL)))
    try:
        os.makedirs(os.path.join(HERE, "_jobs"), exist_ok=True)
        with open(os.path.join(HERE, "_jobs", "deident_fail.txt"), "w", encoding="utf-8") as f:
            for x in FAIL:
                f.write("[FAIL] " + str(x) + "\n")
            if not FAIL:
                f.write("(no failures)\n")
    except OSError:
        pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
