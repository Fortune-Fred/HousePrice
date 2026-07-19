# -*- coding: utf-8 -*-
"""步驟 8/9/13 驗收自動化 -> reports/final_qa.md。

用法：python pipeline/qa.py [--partial]
--partial：資料尚未全量 geocode 時，僅驗證程式路徑，
           成功率/比例類門檻不計為 FAIL（標記 PARTIAL）。
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "final_qa.md"

results = []  # (檢查項, 狀態, 說明)


def check(name, ok, detail, partial_mode=False, threshold_check=False):
    if ok:
        status = "PASS"
    elif partial_mode and threshold_check:
        status = "PARTIAL"  # 資料不足，非程式錯誤
    else:
        status = "FAIL"
    results.append((name, status, detail))
    print(f"[{status:^7}] {name}: {detail}")


def vill(gdf, town, village):
    r = gdf[(gdf["town"] == town) & (gdf["village"] == village)]
    return r.iloc[0] if len(r) else None


def town_median(gdf, town, col):
    s = gdf[gdf["town"] == town][col].dropna()
    return s.median() if len(s) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partial", action="store_true")
    args = ap.parse_args()
    P = args.partial

    df = pd.read_parquet(ROOT / "data" / "processed" / "geocoded.parquet")
    gdf = gpd.read_file(ROOT / "data" / "processed" / "map_data.geojson")

    # ---- 步驟 8：歸里成功率 ----
    rate = df["villcode"].notna().mean()
    check("步驟8 歸里成功率 ≥ 80%", rate >= 0.8,
          f"{rate:.1%}（geocode 未全量時偏低屬預期）", P, True)

    # ---- 步驟 9 ----
    ins_rate = gdf["all_insufficient"].mean()
    check("步驟9 insufficient 比例 < 40%", ins_rate < 0.4,
          f"{ins_rate:.1%}", P, True)
    daan = gdf[(gdf["town"] == "大安區") & gdf["all_unit"].notna()]["all_unit"]
    rural = gdf[(gdf["town"].isin(["大園區", "復興區", "觀音區", "新屋區"]))
                & gdf["all_unit"].notna()]["all_unit"]
    ok = len(daan) > 0 and (len(rural) == 0 or daan.max() > rural.min())
    check("步驟9 大安區里單價 > 桃園郊區里單價",
          ok and len(daan) > 0,
          f"大安區有值里 {len(daan)}（max {daan.max()/1e4:.0f} 萬/坪）vs "
          f"桃園郊區有值里 {len(rural)}"
          + (f"（min {rural.min()/1e4:.0f} 萬/坪）" if len(rural) else "（無，視同通過）"),
          P, True)

    # ---- 步驟 13：常識走查 ----
    med_all = gdf["all_unit"].dropna().median()

    d = town_median(gdf, "大安區", "all_unit")
    check("13-1 大安區單價高（> 全體里中位數 1.3 倍）",
          d is not None and d > med_all * 1.3,
          f"大安區里單價中位 {d/1e4:.1f} 萬/坪 vs 全體 {med_all/1e4:.1f}" if d else "無資料", P, True)

    x = town_median(gdf, "信義區", "all_total")
    mt = gdf["all_total"].dropna().median()
    check("13-2 信義區總價高（> 全體 1.3 倍）",
          x is not None and x > mt * 1.3,
          f"信義區總價中位 {x/1e4:.0f} 萬 vs 全體 {mt/1e4:.0f} 萬" if x else "無資料", P, True)

    w = town_median(gdf, "萬華區", "all_unit")
    check("13-3 萬華單價 < 大安", w is not None and d is not None and w < d,
          f"萬華 {w/1e4:.1f} vs 大安 {d/1e4:.1f} 萬/坪" if w and d else "無資料", P, True)

    jc = vill(gdf, "板橋區", "江翠里")
    check("13-4 板橋江翠有值且中高",
          jc is not None and jc["all_unit"] is not None
          and not pd.isna(jc["all_unit"]) and jc["all_unit"] > med_all * 0.8,
          f"江翠里 {jc['all_unit']/1e4:.1f} 萬/坪" if jc is not None
          and not pd.isna(jc["all_unit"]) else "無資料", P, True)

    for town in ("林口區", "中壢區"):
        pu = town_median(gdf, town, "presale_unit")
        uu = town_median(gdf, town, "used_unit")
        check(f"13-5 {town} 預售單價 > 中古",
              pu is not None and uu is not None and pu > uu,
              f"預售 {pu/1e4:.1f} vs 中古 {uu/1e4:.1f} 萬/坪" if pu and uu else "資料不足", P, True)

    wl = gdf[gdf["town"] == "烏來區"]
    check("13-6 烏來全區灰色（insufficient）",
          len(wl) > 0 and wl["all_insufficient"].all(),
          f"烏來 {len(wl)} 里，灰色 {int(wl['all_insufficient'].sum())} 里")

    ht = vill(gdf, "北投區", "湖田里")  # 陽明山竹子湖
    check("13-7 陽明山（北投湖田里）灰色",
          ht is not None and bool(ht["all_insufficient"]),
          "湖田里 insufficient" if ht is not None else "找不到湖田里")

    fx = gdf[gdf["town"] == "復興區"]
    fx_units = fx["all_unit"].dropna()
    check("13-8 桃園復興區灰色或低價",
          len(fx) > 0 and (fx["all_insufficient"].all()
                           or (len(fx_units) and fx_units.median() < med_all * 0.5)),
          f"復興區 {len(fx)} 里，灰色 {int(fx['all_insufficient'].sum())}，"
          f"有值里單價中位 {fx_units.median()/1e4:.1f} 萬/坪" if len(fx_units)
          else f"復興區 {len(fx)} 里全灰")

    # ---- 報告 ----
    n_pass = sum(1 for _, s, _ in results if s == "PASS")
    n_fail = sum(1 for _, s, _ in results if s == "FAIL")
    lines = [
        "# 驗收走查報告（final_qa.md）",
        "",
        f"- 產出時間：{pd.Timestamp.now():%Y-%m-%d %H:%M}",
        f"- 模式：{'PARTIAL（資料未全量，門檻類檢查不計 FAIL）' if P else '完整驗收'}",
        f"- 結果：PASS {n_pass} / FAIL {n_fail} / 其他 {len(results)-n_pass-n_fail}",
        "",
        "| 檢查項 | 狀態 | 數據 |",
        "|---|---|---|",
    ]
    for name, status, detail in results:
        lines.append(f"| {name} | {status} | {detail} |")
    lines += [
        "",
        "## 矛盾項說明（FAIL 時人工補充：是 bug 還是市場事實）",
        "",
        "（無 FAIL 免填）" if n_fail == 0 else "（待補：逐項查明原因）",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n-> {REPORT}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
