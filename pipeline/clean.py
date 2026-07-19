# -*- coding: utf-8 -*-
"""清洗過濾 + 車位拆算 + 單價重算（SPEC 第 4 節規則 1–6）。

輸出：data/processed/cleaned.parquet、reports/cleaning_report.md
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "processed" / "raw_merged.parquet"
OUT = ROOT / "data" / "processed" / "cleaned.parquet"
REPORT = ROOT / "reports" / "cleaning_report.md"

ALLOWED_TARGET = ["房地(土地+建物)", "房地(土地+建物)+車位"]
ALLOWED_TYPE_PREFIX = ("公寓", "住宅大樓", "華廈", "透天厝", "套房")
REMARK_KEYWORDS = ["親友", "特殊關係", "債務", "急買急賣"]
PING = 0.3025  # 平方公尺 -> 坪
PRICE_MIN, PRICE_MAX = 5e4, 350e4  # 每坪 sanity 界線


def num(s):
    return pd.to_numeric(s, errors="coerce")


def main():
    df = pd.read_parquet(SRC)
    steps = []  # (規則, 說明, 剔除筆數, 剔除後剩餘)

    def drop(mask, rule, desc):
        nonlocal df
        n = int(mask.sum())
        df = df[~mask]
        steps.append((rule, desc, n, len(df)))

    total0 = len(df)

    # 規則 1：只留含建物之房地交易
    drop(~df["交易標的"].isin(ALLOWED_TARGET), "規則1",
         "交易標的非「房地(土地+建物)」或「房地(土地+建物)+車位」（純土地、純車位、純建物）")

    # 規則 2：建物型態白名單
    drop(~df["建物型態"].fillna("").str.startswith(ALLOWED_TYPE_PREFIX), "規則2",
         "建物型態非 公寓/住宅大樓/華廈/透天厝/套房")

    # 規格外：預售解約交易（非真實成交，剔除並標明供使用者複核）
    drop(df["解約情形"].notna() & (df["解約情形"].astype(str).str.strip() != ""),
         "規格外", "預售屋解約交易（解約情形欄非空；規格未涵蓋，執行者判斷剔除）")

    # 規則 4：備註關鍵字
    remark = df["備註"].fillna("")
    drop(remark.str.contains("|".join(REMARK_KEYWORDS)), "規則4",
         f"備註含 {'/'.join(REMARK_KEYWORDS)}")

    # --- 規則 3 + 6：車位拆算與每坪單價重算 ---
    total = num(df["總價元"])
    bldg_m2 = num(df["建物移轉總面積平方公尺"])
    park_price = num(df["車位總價元"]).fillna(0)
    park_m2 = num(df["車位移轉總面積平方公尺"]).fillna(0)
    has_park = df["交易標的"].str.contains("車位")

    # 可拆算：含車位且車位價與車位面積皆 > 0 且拆算後面積為正
    deductible = has_park & (park_price > 0) & (park_m2 > 0) & (bldg_m2 - park_m2 > 0)
    adj_total = np.where(deductible, total - park_price, total)
    adj_m2 = np.where(deductible, bldg_m2 - park_m2, bldg_m2)
    df = df.assign(
        adj_total_price=adj_total,
        adj_area_ping=adj_m2 * PING,
        park_flag=(has_park & ~deductible),  # 含車位但無法拆算
    )
    df["unit_price_ping"] = df["adj_total_price"] / df["adj_area_ping"]
    n_flag = int(df["park_flag"].sum())

    # 無效值：總價或面積缺漏/非正 -> 無法算單價
    drop(~(num(df["adj_total_price"]) > 0) | ~(df["adj_area_ping"] > 0), "規則6附帶",
         "總價或建物面積缺漏/非正，無法計算單價")

    # 規則 5a：每坪 < 5 萬或 > 350 萬
    drop((df["unit_price_ping"] < PRICE_MIN) | (df["unit_price_ping"] > PRICE_MAX),
         "規則5a", "每坪單價 < 5 萬或 > 350 萬")

    # 規則 5b：各行政區 P1/P99 之外
    lo = df.groupby(["city", "鄉鎮市區"])["unit_price_ping"].transform(lambda s: s.quantile(0.01))
    hi = df.groupby(["city", "鄉鎮市區"])["unit_price_ping"].transform(lambda s: s.quantile(0.99))
    drop((df["unit_price_ping"] < lo) | (df["unit_price_ping"] > hi),
         "規則5b", "單價低於該行政區 P1 或高於 P99")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)

    # --- 報告 ---
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 清洗報告（cleaning_report.md）",
        "",
        f"- 產出時間：{pd.Timestamp.now():%Y-%m-%d %H:%M}",
        f"- 輸入筆數：{total0:,}",
        "",
        "| 規則 | 說明 | 剔除筆數 | 剩餘筆數 |",
        "|---|---|---:|---:|",
    ]
    for rule, desc, n, rest in steps:
        lines.append(f"| {rule} | {desc} | {n:,} | {rest:,} |")
    lines += [
        "",
        f"- 最終筆數：{len(df):,}（保留率 {len(df)/total0:.1%}）",
        f"- 規則3 車位拆算：含車位交易中 **{n_flag:,} 筆**車位資訊不全無法拆算，"
        "已標記 `park_flag=True` 保留（單價含車位、略被低估）。",
        "",
        "## 建物型態分布（清洗後）",
        "",
        "```",
        df["建物型態"].value_counts().to_string(),
        "```",
        "",
        "## 單價分布（每坪，萬元）",
        "",
        "```",
        (df.groupby("city")["unit_price_ping"]
           .quantile([0.05, 0.5, 0.95]).div(1e4).round(1).unstack().to_string()),
        "```",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"最終筆數 {len(df):,} / {total0:,}")
    print("報告 ->", REPORT)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
