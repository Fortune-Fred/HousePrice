# -*- coding: utf-8 -*-
"""合併所有原始 CSV -> data/processed/raw_merged.parquet。

- 跳過第二列英文欄名列
- 加欄位：city（台北市/新北市/桃園市）、season（如 114S4）、deal_type（中古/預售）
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "raw_merged.parquet"

CITY = {"a": "台北市", "f": "新北市", "h": "桃園市"}
DEAL = {"a": "中古", "b": "預售"}


def main():
    frames = []
    for csv in sorted(RAW_DIR.glob("*/[afh]_lvr_land_[ab].csv")):
        season = csv.parent.name
        city = CITY[csv.name[0]]
        deal = DEAL[csv.stem[-1]]
        # 少數列的欄位內含未引號逗號 -> 欄位數超出，將多餘欄位併回最後一欄
        bad = []

        def fix_line(line, _bad=bad, _f=csv.name):
            _bad.append(line)
            n = expected_cols[0]
            return line[: n - 1] + ["".join(line[n - 1 :])]

        header = pd.read_csv(csv, nrows=0)
        expected_cols = [len(header.columns)]
        df = pd.read_csv(
            csv, dtype=str, skiprows=[1], engine="python",
            on_bad_lines=fix_line,
        )
        if bad:
            print(f"  [warn] {csv.name}: {len(bad)} 列欄位數異常，已併回最後一欄")
        df["city"] = city
        df["season"] = season
        df["deal_type"] = deal
        df["source_file"] = f"{season}/{csv.name}"
        frames.append(df)
    merged = pd.concat(frames, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(OUT, index=False)

    print(f"總筆數: {len(merged)}")
    print(merged.groupby("city").size().to_string())
    print(merged.groupby("deal_type").size().to_string())
    print(f"季度數: {merged['season'].nunique()}")
    for c in ["台北市", "新北市", "桃園市"]:
        assert (merged["city"] == c).sum() > 0, f"{c} 筆數為 0"
    print("OK ->", OUT)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
