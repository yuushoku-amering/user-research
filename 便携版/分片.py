# -*- coding: utf-8 -*-
"""把便携版 zip 切成几片，以及把几片合成回来。

为什么要切
------------------------------------------------------------------------------
便携版 zip 约 122 MB，撞两个上限：

  · **GitHub 单文件 100 MiB（硬限制）** —— 直接用 git 传会被服务端拒绝
  · **阿里云盘限制公开分享压缩包** —— 只给"快传"（有效期 1 天、1 人）

切成每片 45 MB 之后：
  · 每片都 < 100 MiB ⇒ 源码仓库、Release 附件、网盘**三条路都能走**
  · 用户下全几片、双击一个合并脚本就还原

用法
------------------------------------------------------------------------------
    # 切（默认每片 45MB，输出到 zip 旁边）
    python 便携版/分片.py split dist_便携版/岚苔Vesper-便携版.zip

    # 合并（双击生成的 .bat 也行）
    python 便携版/分片.py join dist_便携版/岚苔Vesper-便携版.zip

设计上注意的几点
------------------------------------------------------------------------------
1. **分片名要能自然排序**：`xxx.zip.001` / `.002` / `.003` —— 用户一眼就知道先后。
2. **合并脚本是纯 ASCII 的 .bat**：cmd 按 OEM 代码页解析，中文会被撕碎
   （这个坑在打包脚本里踩过两次）。中文说明写进**日志文件**，由 Python 写、UTF-8 编码。
3. **算个校验和**：合并出来跟原文件必须一模一样，不然用户装到一半才发现坏。
4. **合并脚本要能容忍"点错目录"**：找不到分片时说清楚它在找什么。
"""
import argparse
import hashlib
import os
import sys

DEFAULT_PART_MB = 45          # 留足余量：GitHub 上限 100 MiB，一片 45MB 很安全
MERGE_PY_NAME = "merge_parts.py"      # ⚠ 必须 ASCII —— .bat 里要**写出它的文件名**
MERGE_BAT_NAME = "merge-parts.bat"    # ⚠ 必须 ASCII：GitHub Release 的附件名只收 ASCII，中文会被降级成 default

MERGE_BAT = r"""@echo off
rem ===========================================================================
rem  LanTai Vesper - join the split parts back into one zip
rem
rem  Double-click this file. It joins every .001 .002 .003 ... that sits next
rem  to it back into the original zip, then prints the SHA256 so you can compare
rem  it with the value written in the .txt file next to it.
rem
rem  NO PYTHON NEEDED -- it uses Windows' own `copy /b` and `certutil`.
rem  (Using the bundled Python would be a chicken-and-egg problem: that Python
rem   is INSIDE the very zip we are trying to rebuild.)
rem
rem  PURE ASCII ON PURPOSE: a .bat is parsed with the OEM code page, so any
rem  Chinese byte inside it -- even in a comment -- gets shredded into garbage
rem  that then gets executed.  This was tripped over three times while writing
rem  these scripts, so the check is now automated in the build/split scripts.
rem ===========================================================================
setlocal enabledelayedexpansion
chcp 437 >nul 2>nul
cd /d "%~dp0"
title LanTai Vesper - join parts

rem ---- find the first part ----
set "FIRST="
for %%F in ("%~dp0*.zip.001") do set "FIRST=%%~fF"
if not defined FIRST goto :nopart

set "OUT=%FIRST:.001=%"
if exist "%OUT%" goto :exists

echo.
echo   Joining parts into:
echo     %OUT%
echo.

rem  NOTE: , : `copy /b "x.zip.???"`  `???`  cmd ****
rem     -- ,  0  () . 
rem      001..999 , . 
rem      ( !P!  %P%,  %P%  for/call . ) 
set /a N=1
:loop
call :pad3 %N%
set "PART=%FIRST:.001=.000%"
set "PART=!PART:.000=.%P%!"
if not exist "!PART!" goto :joined
if not exist "%OUT%" (
  copy /b "!PART!" "%OUT%" >nul
) else (
  copy /b "%OUT%" + "!PART!" "%OUT%" >nul
)
set /a N+=1
if %N% GTR 999 goto :joined
goto :loop

:joined
if not exist "%OUT%" goto :failed

for %%A in ("%OUT%") do set "SZ=%%~zA"
echo   Done.
echo     size: !SZ! bytes
echo.
echo   SHA256 of the joined file:
certutil -hashfile "%OUT%" SHA256
echo.
echo   Compare that with the SHA256 written in the .txt file next to this one.
echo   If they match, unpack the .zip and run start-portable.bat inside it.
echo.
goto :done

rem ---- helper: turn 1 into 001 ----
:pad3
set "P=00%~1"
set "P=!P:~-3!"
exit /b 0

:exists
echo.
echo   [!] This file already exists:
echo       %OUT%
echo       Delete it first if you want to join the parts again.
echo.
goto :done

:nopart
echo.
echo   [!] No ".zip.001" file next to this one.
echo.
echo       Put ALL the downloaded parts (.001 .002 .003 ...) in the SAME
echo       folder as this file, then double-click this file again.
echo.

:failed
echo.
echo   [!] The join produced nothing. Make sure all parts are there and that
echo       none of them was renamed.
echo.

:done
pause
endlocal
"""

MERGE_PY = r'''# -*- coding: utf-8 -*-
"""把 `*.zip.001/.002/...` 合成回一个 zip（由合并脚本调用，也可以自己跑）。

用法： python merge_parts.py <第一个分片的路径>
"""
import glob
import hashlib
import os
import sys


def merge(first):
    first = os.path.abspath(first)
    base = first[:-4]                      # 去掉 ".001"
    # 收集同前缀的分片，按序号排
    parts = sorted(glob.glob(base + ".*"))
    parts = [p for p in parts if p[-3:].isdigit()]
    if not parts:
        print("找不到分片：%s.*" % base)
        return 1
    out = base
    if os.path.exists(out):
        print("目标已存在，先删掉它再合并：%s" % out)
        return 1

    total = sum(os.path.getsize(p) for p in parts)
    print("找到 %d 个分片，共 %.1f MB" % (len(parts), total / 1048576.0))
    h = hashlib.sha256()
    with open(out, "wb") as w:
        for i, p in enumerate(parts, 1):
            with open(p, "rb") as r:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    w.write(chunk)
                    h.update(chunk)
            print("  已合入 %s" % os.path.basename(p))

    size = os.path.getsize(out)
    print("")
    print("合并完成：%s" % out)
    print("  大小   ：%.1f MB" % (size / 1048576.0))
    print("  SHA256 ：%s" % h.hexdigest())
    print("")
    print("如果旁边有个 分片.txt 写着期望的 SHA256，对一下上面这行 —— 一样就说明没坏。")
    print("然后就可以解压这个 zip 了（解压完双击 start-portable.bat 启动）。")

    # 顺带把中文说明落成文件，避免控制台乱码看不清
    try:
        with open(os.path.join(os.path.dirname(out), "合并结果.txt"),
                  "w", encoding="utf-8") as f:
            f.write("合并结果\n")
            f.write("========\n\n")
            f.write("合并出的文件：%s\n" % os.path.basename(out))
            f.write("大小：%.1f MB\n" % (size / 1048576.0))
            f.write("SHA256：%s\n\n" % h.hexdigest())
            f.write("下一步：解压它，然后双击里面的 start-portable.bat。\n")
    except Exception as e:
        print("[warn] 写 合并结果.txt 失败：%s" % e)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    return merge(sys.argv[1])


if __name__ == "__main__":
    sys.exit(main())
'''


def sha256_of(path, limit=None):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
            if limit and n >= limit:
                break
    return h.hexdigest()


def do_split(src, part_mb):
    src = os.path.abspath(src)
    if not os.path.isfile(src):
        print("[FAIL] 找不到文件：%s" % src)
        return 1
    size = os.path.getsize(src)
    part = int(part_mb * 1024 * 1024)
    n = (size + part - 1) // part
    out_dir = os.path.dirname(src)
    name = os.path.basename(src)

    # 先清掉旧分片，免得新旧混在一起被合并成错的
    for old in sorted(os.listdir(out_dir)):
        if old.startswith(name + ".") and old[-3:].isdigit():
            os.remove(os.path.join(out_dir, old))

    print("源文件：%s（%.1f MB）" % (name, size / 1048576.0))
    print("切成 %d 片，每片 %.0f MB" % (n, part_mb))
    h = hashlib.sha256()
    written = 0
    with open(src, "rb") as f:
        for i in range(1, n + 1):
            p = os.path.join(out_dir, "%s.%03d" % (name, i))
            got = 0
            with open(p, "wb") as w:
                while got < part:
                    chunk = f.read(min(1 << 20, part - got))
                    if not chunk:
                        break
                    w.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    written += len(chunk)
            print("  %s  %.1f MB" % (os.path.basename(p), got / 1048576.0))
    digest = h.hexdigest()

    # 合并脚本 + 说明，跟分片放一起
    bat = os.path.join(out_dir, MERGE_BAT_NAME)
    # ⚠ 这个坑踩了三次：.bat 里**任何**中文字节（**连注释和要写的文件名都算**）
    #   都会被 cmd 按 OEM 代码页撕碎 → 写入时就 UnicodeEncodeError。
    #   ⇒ 写之前先断言，并把出问题的位置打出来（不然只看到一句 codec 报错）。
    _bad = next((i for i, ch in enumerate(MERGE_BAT) if ord(ch) > 127), None)
    if _bad is not None:
        raise SystemExit("❌ %s 里有非 ASCII 字符：位置 %d 是 %r —— .bat 必须纯 ASCII"
                         % (MERGE_BAT_NAME, _bad, MERGE_BAT[_bad]))
    with open(bat, "w", encoding="ascii", newline="\r\n") as f:
        f.write(MERGE_BAT)
    # 校验和让用户能自己核
    with open(os.path.join(out_dir, "part-info.txt"), "w", encoding="utf-8") as f:
        f.write("这个压缩包被切成了 %d 片（每片约 %.0f MB），\n"
                "因为原文件 %.1f MB，超过了部分下载渠道的单文件上限。\n\n"
                % (n, part_mb, size / 1048576.0))
        f.write("怎么还原（不用装任何东西）：\n")
        f.write("  1. 把所有 .001 .002 .003 … 和 %s 放在**同一个文件夹**里\n" % MERGE_BAT_NAME)
        f.write("  2. 双击 `%s`\n" % MERGE_BAT_NAME)
        f.write("  3. 它会合成出 %s，并打印它的 SHA256\n" % name)
        f.write("  4. 和下面的 SHA256 对一下 —— 一样就说明没坏\n")
        f.write("  5. 解压它，然后双击里面的 start-portable.bat 启动\n\n")
        f.write("（文件名用英文：GitHub Release 的附件名只收 ASCII，\n"
                "  中文名会被它降级成 default，反而看不出这是什么。）\n\n")
        f.write("原文件大小：%d 字节（%.1f MB）\n" % (size, size / 1048576.0))
        f.write("原文件 SHA256：%s\n" % digest)
        f.write("\n（这一步只是核对，不做也能用；但网盘下载偶有损坏，核一下最稳。）\n")

    print("")
    print("原文件 SHA256：%s" % digest)
    print("校验和与说明写进了：part-info.txt")
    print("合并脚本：%s（纯 ASCII，双击即可，**不需要 Python**）" % MERGE_BAT_NAME)
    return 0


def do_join(first):
    """命令行合并（等价于双击那个 .bat；这里用 Python 实现，方便在非 Windows 上验证）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ns = {}
    exec(compile(MERGE_PY, "merge_parts.py", "exec"), ns)
    return ns["merge"](first)


def main():
    ap = argparse.ArgumentParser(description="便携版 zip 的分片工具")
    ap.add_argument("action", choices=["split", "join"])
    ap.add_argument("target", help="split: 源 zip；join: 第一个分片(.001)")
    ap.add_argument("--part-mb", type=float, default=DEFAULT_PART_MB,
                    help="每片多少 MB（默认 %.0f；GitHub 上限 100 MiB，建议别超过 90）"
                         % DEFAULT_PART_MB)
    args = ap.parse_args()
    if args.action == "split":
        return do_split(args.target, args.part_mb)
    return do_join(args.target)


if __name__ == "__main__":
    sys.exit(main())
