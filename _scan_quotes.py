# -*- coding: utf-8 -*-
"""找出「引号冲突」这类**真会崩**的问题 —— 这个错我已经犯三次了，让它自动可见。

        python _scan_quotes.py [文件 ...]        # 默认扫 blocks/ 和 core/ 下的 .py

**判据很简单，也很准：先编译，编译不过才报，并把它定位到行。**

为什么不用正则去猜「中文中间夹了直引号」：那玩意儿在**文档字符串里是合法的**
（`\"\"\"...说\"这个\"...\"\"\"` 完全没问题），一猜就是上百条假警报，
真问题反而被淹掉（第一版就是这么吵的）。

顺带：这个脚本自己**不会被 _runall 收进回归**（名字不含 "test"），
它是给"改引擎代码时随手跑一下"用的。
"""
import os
import py_compile
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))


def targets_from_argv():
    t = [a for a in sys.argv[1:] if a]
    if t:
        return t
    # ⚠ 默认扫**整个 workbench 下的 .py**，不只是 blocks/ 和 core/。
    #   教训：这个扫描器原来只扫那两个目录，结果我在新建 `_multipletest.py` 时
    #   又犯了同一个引号错误、而"扫描通过"给了我一个假的安心。
    out = []
    # ⚠ 别忘了 `blocks/*/block.py` —— 它们是**声明文件**，一跑就 import，
    #   引号错了同样起不来。头两次加扫描时只扫了 engine.py / core，
    #   结果在 block.py 里又栽了一次（实测）。
    for cur, dirs, names in os.walk(os.path.join(HERE, "blocks")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "libs")]
        out += [os.path.join(cur, n) for n in names if n.endswith(".py")]
    for cur, dirs, names in os.walk(os.path.join(HERE, "core")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "libs")]
        out += [os.path.join(cur, n) for n in names if n.endswith(".py")]
    for cur, dirs, names in os.walk(HERE):
        dirs[:] = [d for d in dirs
                   if d not in ("__pycache__", "libs", "_jobs", "_history", "dsh-home",
                                "blocks", "core")]
        out += [os.path.join(cur, n) for n in names if n.endswith(".py")]
    return out


def main():
    # ⚠ `cfile=os.devnull` 在 Windows 上行不通：设备名叫 `nul`，
    #   py_compile 会抱怨「nul is a non-regular file」（实测 36 个文件全被误报）。
    #   所以老老实实写到一个临时文件里，用完删掉。
    import tempfile
    files = targets_from_argv()
    bad = 0
    tmpc = os.path.join(tempfile.gettempdir(), "_scan_quotes_%d.pyc" % os.getpid())
    for f in files:
        try:
            py_compile.compile(f, doraise=True, cfile=tmpc)
        except py_compile.PyCompileError as e:
            bad += 1
            msg = str(e)
            m = re.search(r"line (\d+)", msg)
            ln = int(m.group(1)) if m else 0
            print("❌ %s" % os.path.relpath(f, HERE))
            print("   第 %d 行：%s" % (ln, msg.strip().splitlines()[-1][:160]))
            # 把那一行原文也打出来，省得再打开文件
            try:
                with open(f, encoding="utf-8") as fh:
                    print("   原文：%s" % fh.readlines()[ln - 1].rstrip()[:140])
            except Exception:
                pass
        except Exception as e:
            bad += 1
            print("❌ %s：%s" % (os.path.relpath(f, HERE), e))
    try:
        os.remove(tmpc)
    except OSError:
        pass
    print("扫了 %d 个文件，编译不过的：%d 个" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
