# -*- coding: utf-8 -*-
"""步驟 9：聚合計算（SPEC 第 5 節）-> data/processed/map_data.geojson。

- 分組：里 × 類別（all=全部 / used=中古 / presale=預售）
- 指標：單價中位數(unit，元/坪)、總價中位數(total，元)、成交筆數(n)
- 窗口：近 8 季；筆數 < 10 擴到近 12 季；仍 < 10 -> insufficient
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "processed" / "geocoded.parquet"
VILLAGES = ROOT / "data" / "processed" / "villages.geojson"
OUT = ROOT / "data" / "processed" / "map_data.geojson"

MIN_N = 10
CATS = {"all": None, "used": "中古", "presale": "預售"}


def stats(sub: pd.DataFrame) -> pd.DataFrame:
    return sub.groupby("villcode").agg(
        unit=("unit_price_ping", "median"),
        total=("total_num", "median"),
        n=("villcode", "size"),
    )


def main():
    df = pd.read_parquet(SRC)
    df = df[df["villcode"].notna()].copy()
    df["total_num"] = pd.to_numeric(df["總價元"], errors="coerce")
    seasons = sorted(df["season"].unique(),
                     key=lambda s: (int(s.split("S")[0]), int(s.split("S")[1])))
    win8 = set(seasons[-8:])
    win12 = set(seasons[-12:])
    print(f"歸里資料 {len(df):,} 筆；近8季窗口 = {sorted(win8)}")

    villages = gpd.read_file(VILLAGES)
    for cat, deal in CATS.items():
        sub = df if deal is None else df[df["deal_type"] == deal]
        s8 = stats(sub[sub["season"].isin(win8)])
        s12 = stats(sub[sub["season"].isin(win12)])
        use12 = s8[s8["n"] < MIN_N].index
        merged = pd.concat([s8.drop(index=use12),
                            s12[s12.index.isin(use12)]])
        merged.loc[merged["n"] < MIN_N, ["unit", "total"]] = None
        merged["insufficient"] = merged["n"] < MIN_N

        villages[f"{cat}_unit"] = villages["villcode"].map(merged["unit"]).round(0)
        villages[f"{cat}_total"] = villages["villcode"].map(merged["total"]).round(0)
        villages[f"{cat}_n"] = villages["villcode"].map(merged["n"]).fillna(0).astype(int)
        ins = villages["villcode"].map(merged["insufficient"])
        villages[f"{cat}_insufficient"] = ins.fillna(True).astype(bool)

        n_ins = int(villages[f"{cat}_insufficient"].sum())
        print(f"[{cat}] 有資料里 {len(merged):,}；insufficient（含無資料）"
              f"{n_ins}/{len(villages)}（{n_ins/len(villages):.1%}）")

    villages.to_file(OUT, driver="GeoJSON")
    print("->", OUT, f"({OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
