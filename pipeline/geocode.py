# -*- coding: utf-8 -*-
"""步驟 8：全量 geocode（NLSC，併發 4）＋歸里。

- 快取：data/processed/geocode_cache.jsonl（append-only，中斷可續跑）
- 完成後 point-in-polygon 歸里，輸出 data/processed/geocoded.parquet
  與 reports/geocode_report.md
"""
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nlsc import normalize, query  # noqa: E402

import requests  # noqa: E402  (truststore 已於 nlsc 注入)

ROOT = Path(__file__).resolve().parent.parent
CLEANED = ROOT / "data" / "processed" / "cleaned.parquet"
CACHE = ROOT / "data" / "processed" / "geocode_cache.jsonl"
OUT = ROOT / "data" / "processed" / "geocoded.parquet"
REPORT = ROOT / "reports" / "geocode_report.md"
WORKERS = 4

_lock = threading.Lock()
_slowdown = threading.Event()


def load_cache() -> dict:
    cache = {}
    if CACHE.exists():
        with CACHE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    cache[rec["addr"]] = rec
                except json.JSONDecodeError:
                    continue  # 中斷時的殘缺行
    return cache


def worker(addr: str, fh):
    sess = requests.Session()
    rec = {"addr": addr, "ok": False}
    for attempt in range(3):
        if _slowdown.is_set():
            time.sleep(5)
        try:
            hit = query(addr, session=sess)
            if hit:
                rec.update(ok=True, lon=hit[0], lat=hit[1], content=hit[2])
            break
        except Exception:
            _slowdown.set()
            time.sleep(2 ** attempt * 2)
    _slowdown.clear()
    with _lock:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
    time.sleep(0.05)
    return rec


def geocode_all():
    df = pd.read_parquet(CLEANED)
    addrs = df["土地位置建物門牌"].dropna().map(normalize)
    uniq = sorted(set(addrs))
    cache = load_cache()
    todo = [a for a in uniq if a not in cache]
    print(f"唯一地址 {len(uniq):,}，快取已有 {len(uniq)-len(todo):,}，待處理 {len(todo):,}",
          flush=True)
    if todo:
        t0 = time.time()
        done = [0]
        with CACHE.open("a", encoding="utf-8") as fh, \
             ThreadPoolExecutor(WORKERS) as ex:
            def run(a):
                r = worker(a, fh)
                done[0] += 1
                if done[0] % 1000 == 0:
                    rate = done[0] / (time.time() - t0)
                    eta = (len(todo) - done[0]) / rate / 3600
                    print(f"{done[0]:,}/{len(todo):,} "
                          f"{rate:.1f} 筆/s ETA {eta:.1f}h", flush=True)
                return r
            list(ex.map(run, todo))
    return load_cache()


def assign_villages(cache: dict):
    import geopandas as gpd
    from shapely.geometry import Point

    df = pd.read_parquet(CLEANED)
    df["norm_addr"] = df["土地位置建物門牌"].fillna("").map(
        lambda a: normalize(a) if a else "")
    cdf = pd.DataFrame([c for c in cache.values() if c.get("ok")])
    df = df.merge(cdf[["addr", "lon", "lat", "content"]],
                  left_on="norm_addr", right_on="addr", how="left")

    geocoded = df["lon"].notna()
    pts = gpd.GeoDataFrame(
        df[geocoded],
        geometry=[Point(xy) for xy in zip(df.loc[geocoded, "lon"],
                                          df.loc[geocoded, "lat"])],
        crs=4326)
    villages = gpd.read_file(ROOT / "data" / "processed" / "villages.geojson")
    joined = gpd.sjoin(pts, villages, how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]  # 邊界點可能落兩里
    for col in ("villcode", "county", "town", "village"):
        df[col] = joined[col]

    # 交叉驗證：NLSC 回應 CONTENT 內的里名 vs polygon 歸里
    from nlsc import FW
    resp_vill = (df["content"].fillna("").str.translate(FW)
                 .str.extract(r"(?:區|鎮|鄉|市)([一-鿿]{1,4}(?:里|村))\d*鄰")[0])
    both = df["village"].notna() & resp_vill.notna()
    agree = (df.loc[both, "village"] == resp_vill[both]).mean() if both.any() else float("nan")

    df = df.drop(columns=["addr"])
    df.to_parquet(OUT, index=False)

    n = len(df)
    n_geo = int(geocoded.sum())
    n_vill = int(df["villcode"].notna().sum())
    lines = [
        "# Geocode 與歸里報告（步驟 8）",
        "",
        f"- 產出時間：{pd.Timestamp.now():%Y-%m-%d %H:%M}",
        f"- 交易筆數：{n:,}",
        f"- 取得座標：{n_geo:,}（{n_geo/n:.1%}）",
        f"- 成功歸里：{n_vill:,}（**{n_vill/n:.1%}**）",
        f"- NLSC 回應里名 vs polygon 歸里一致率：{agree:.1%}（樣本 {int(both.sum()):,}）",
        "",
        "## 各縣市歸里成功率",
        "",
        "```",
        df.assign(ok=df["villcode"].notna()).groupby("city")["ok"]
          .agg(["mean", "count"]).to_string(),
        "```",
        "",
        "## 各類別歸里成功率",
        "",
        "```",
        df.assign(ok=df["villcode"].notna()).groupby("deal_type")["ok"]
          .agg(["mean", "count"]).to_string(),
        "```",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"歸里成功率 {n_vill/n:.1%}，一致率 {agree:.1%} -> {REPORT}", flush=True)


def main():
    cache = geocode_all()
    assign_villages(cache)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
