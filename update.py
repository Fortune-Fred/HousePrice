# -*- coding: utf-8 -*-
"""一鍵更新：下載最新一季 -> 解析 -> 清洗 -> geocode（吃快取，只補新地址）-> 聚合。

用法：python update.py
冪等：已下載季度跳過、geocode 快取命中即不重打 API。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

STEPS = [
    ("下載最新季度", ["pipeline/download.py"]),
    ("解析合併", ["pipeline/parse.py"]),
    ("清洗過濾", ["pipeline/clean.py"]),
    ("村里界（若已存在則跳過）", ["pipeline/villages.py"]),
    ("行政區界（若已存在則跳過）", ["pipeline/towns.py"]),
    ("Geocode 與歸里（吃快取）", ["pipeline/geocode.py"]),
    ("聚合輸出 GeoJSON", ["pipeline/aggregate.py"]),
    ("供需風險分級", ["pipeline/risk.py"]),
]


def main():
    for name, args in STEPS:
        print(f"\n===== {name} =====", flush=True)
        r = subprocess.run([PY] + args, cwd=ROOT)
        if r.returncode != 0:
            print(f"[中止] {name} 失敗（exit {r.returncode}）", file=sys.stderr)
            sys.exit(r.returncode)
    print("\n全部完成。開啟 web/index.html（經 http server）檢視。")


if __name__ == "__main__":
    main()
