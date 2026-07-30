# -*- coding: utf-8 -*-
"""從村里界原始 SHP dissolve 出行政區界與標籤點，輸出 towns.geojson。

用原始（未簡化）幾何做 dissolve 再簡化，避免逐里簡化後聯集產生細縫。
"""
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from villages import download  # noqa: E402  （SHP 不在時自動下載）

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "villages"
OUT = ROOT / "data" / "processed" / "towns.geojson"
CITIES = ["臺北市", "新北市", "桃園市"]


def main():
    if OUT.exists() and "--force" not in sys.argv:
        print("[skip] towns.geojson 已存在（--force 可重產）")
        return
    shp = next(RAW.glob("*.shp"), None) or download()
    gdf = gpd.read_file(shp)
    county_col = next(c for c in gdf.columns if c.upper() in ("COUNTYNAME", "COUNTY"))
    town_col = next(c for c in gdf.columns if c.upper() in ("TOWNNAME", "TOWN"))
    gdf = gdf[gdf[county_col].isin(CITIES)].copy()
    gdf = gdf.rename(columns={county_col: "county", town_col: "town"})

    towns = gdf[["county", "town", "geometry"]].dissolve(
        by=["county", "town"], as_index=False)
    if towns.crs is None:
        towns = towns.set_crs(4326)
    else:
        towns = towns.to_crs(4326)

    # 標籤點取 representative_point（保證落在多邊形內）
    pts = towns.representative_point()
    towns["lab_lon"] = pts.x.round(5)
    towns["lab_lat"] = pts.y.round(5)

    towns["geometry"] = towns.simplify(0.0003, preserve_topology=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    towns.to_file(OUT, driver="GeoJSON")
    print(f"輸出 {len(towns)} 行政區 -> {OUT}（{OUT.stat().st_size/1e3:.0f} KB）")
    print(towns.groupby("county").size().to_string())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
