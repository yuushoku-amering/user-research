# -*- coding: utf-8 -*-
"""对照检查：registry 扫到的 vs server API 报的（绕开 server 进程缓存之类的疑点）"""
import json
import os
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import registry, paths          # noqa: E402

print("BLOCKS_DIR =", paths.BLOCKS_DIR)
print("目录：", sorted(d for d in os.listdir(paths.BLOCKS_DIR)
                       if os.path.isdir(os.path.join(paths.BLOCKS_DIR, d))))
print()
local = registry.load_blocks()
print("registry 扫到 %d 个：" % len(local))
for b in local:
    print("   order=%-4s id=%-18s name=%-22s engine=%s"
          % (b.get("order"), b.get("id"), b.get("name"), b.get("has_engine")))

print()
try:
    with urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=10) as r:
        st = json.loads(r.read().decode("utf-8"))
    print("API 报 %d 个（项目：%s）：" % (len(st["blocks"]), st["project"]["name"]))
    for b in st["blocks"]:
        print("   order=%-4s id=%-18s name=%-22s engine=%s"
              % (b.get("order"), b.get("id"), b.get("name"), b.get("has_engine")))
except Exception as e:
    print("API 查询失败：", e)
