# -*- coding: utf-8 -*-
"""優先 geocode：先跑步驟 13 驗收走查涉及的關鍵行政區（每區抽樣上限），
讓 QA 腳本能在全量 geocode 完成前先驗證程式路徑。

共用 geocode.py 的快取與 worker，跑完自動歸里。
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geocode as G  # noqa: E402
from nlsc import normalize  # noqa: E402

# (city 欄位值, 鄉鎮市區) -> 每區抽樣上限
KEY_DISTRICTS = {
    ("台北市", "大安區"): 600,
    ("台北市", "信義區"): 600,
    ("台北市", "萬華區"): 600,
    ("台北市", "士林區"): 600,   # 含陽明山地帶
    ("台北市", "北投區"): 600,   # 含竹子湖/湖田里
    ("新北市", "板橋區"): 600,
    ("新北市", "林口區"): 600,
    ("新北市", "烏來區"): 600,   # 山區，預期灰色
    ("桃園市", "中壢區"): 800,   # 含青埔
    ("桃園市", "復興區"): 600,   # 偏鄉，預期灰色或低
    ("桃園市", "大園區"): 600,   # 郊區對照組
}


def main():
    df = pd.read_parquet(G.CLEANED)
    cache = G.load_cache()
    todo = []
    for (city, town), cap in KEY_DISTRICTS.items():
        sub = df[(df["city"] == city) & (df["鄉鎮市區"] == town)]
        addrs = sorted(set(sub["土地位置建物門牌"].dropna().map(normalize)))
        pending = [a for a in addrs if a not in cache]
        if len(pending) > cap:
            pending = pd.Series(pending).sample(cap, random_state=42).tolist()
        todo += pending
        print(f"{city}{town}: 唯一 {len(addrs):,}，待跑 {len(pending):,}", flush=True)
    print(f"合計待跑 {len(todo):,}", flush=True)

    if todo:
        t0 = time.time()
        done = [0]
        with G.CACHE.open("a", encoding="utf-8") as fh, \
             ThreadPoolExecutor(G.WORKERS) as ex:
            def run(a):
                r = G.worker(a, fh)
                done[0] += 1
                if done[0] % 500 == 0:
                    rate = done[0] / (time.time() - t0)
                    print(f"{done[0]:,}/{len(todo):,} {rate:.1f} 筆/s", flush=True)
                return r
            list(ex.map(run, todo))
    G.assign_villages(G.load_cache())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
