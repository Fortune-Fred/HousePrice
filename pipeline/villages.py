# -*- coding: utf-8 -*-
"""下載村里界圖（TWD97 經緯度 SHP），過濾北北桃，簡化幾何，輸出 GeoJSON。

資料集：data.gov.tw dataset 7438（內政部國土測繪中心）
下載連結由 API 動態取得（檔名含版本日期，會變動）。
"""
import io
import sys
import zipfile
from pathlib import Path

import truststore

truststore.inject_into_ssl()
import geopandas as gpd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "villages"
OUT = ROOT / "data" / "processed" / "villages.geojson"
CITIES = ["臺北市", "新北市", "桃園市"]
UA = {"User-Agent": "Mozilla/5.0"}


def download() -> Path:
    if RAW.exists() and list(RAW.glob("*.shp")):
        print("[skip] 村里界 SHP 已存在")
        return next(RAW.glob("*.shp"))
    api = "https://data.gov.tw/api/v2/rest/dataset/7438"
    meta = requests.get(api, timeout=60, headers=UA).json()
    info = meta.get("result", meta)
    url = next(d["resourceDownloadUrl"] for d in info["distribution"]
               if d.get("resourceFormat") == "SHP")
    print("[get ]", url)
    r = requests.get(url, timeout=300, headers=UA)
    r.raise_for_status()
    RAW.mkdir(parents=True, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(RAW)
    return next(RAW.glob("*.shp"))


def main():
    shp = download()
    gdf = gpd.read_file(shp)
    print("欄位:", list(gdf.columns))
    print("全國村里數:", len(gdf))

    county_col = next(c for c in gdf.columns if c.upper() in ("COUNTYNAME", "COUNTY"))
    gdf = gdf[gdf[county_col].isin(CITIES)].copy()
    print("北北桃村里數:", len(gdf))

    # 統一欄位名
    ren = {}
    for c in gdf.columns:
        u = c.upper()
        if u == "COUNTYNAME":
            ren[c] = "county"
        elif u == "TOWNNAME":
            ren[c] = "town"
        elif u == "VILLNAME":
            ren[c] = "village"
        elif u == "VILLCODE":
            ren[c] = "villcode"
    gdf = gdf.rename(columns=ren)
    keep = [c for c in ("villcode", "county", "town", "village") if c in gdf.columns]
    gdf = gdf[keep + ["geometry"]]

    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    else:
        gdf = gdf.to_crs(4326)

    # 簡化幾何（保留拓撲），約 10 公尺容差
    gdf["geometry"] = gdf.simplify(0.0001, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OUT, driver="GeoJSON")
    print(f"輸出 {len(gdf)} 里 -> {OUT}（{OUT.stat().st_size/1e6:.1f} MB）")
    print(gdf.groupby("county").size().to_string())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
