# -*- coding: utf-8 -*-
"""保值分析（行政區級，免 geocode）＋租金報酬率。

輸入：data/raw/{季}/[afh]_lvr_land_a.csv（101S3 起的買賣）
     data/raw/{季}/[afh]_lvr_land_c.csv（近 12 季租賃）
輸出：data/processed/value_towns.json、reports/value_report.md

方法（沿用 clean.py 主要清洗規則，時間粒度＝半年）：
- 買賣：交易標的含房地、住宅五型態、剔除備註特殊關係、車位拆算、
  單價界線 5~350 萬/坪；各行政區×半年單價中位數（樣本 ≥30 才採計）。
- cagr10 / cagr5：最近半年 vs 10 / 5 年前同半年（缺值往前一半年遞補）的年化漲幅。
- dd2223 修正期抗跌：min(111H2~112H2) ÷ max(110H2~111H2) − 1（升息修正期回檔幅度）。
- 租金：近 12 季 _c 檔住宅租賃，車位拆算後月租單價中位數（樣本 ≥30）；
  年化租金報酬率 = 月租單價×12 ÷ 最近半年買賣單價。
- 另輸出 unit_now / total_now / n4（近 4 季），供前端行政區概覽上色。
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "value_towns.json"
REPORT = ROOT / "reports" / "value_report.md"
CITY = {"a": "臺北市", "f": "新北市", "h": "桃園市"}
TYPES = ("公寓", "住宅大樓", "華廈", "透天厝", "套房")
BAD_NOTE = re.compile("親友|特殊關係|債務|急買急賣")
PING = 0.3025  # 平方公尺 → 坪


def col(df, *names):
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series(pd.NA, index=df.index)


def num(s):
    return pd.to_numeric(s, errors="coerce")


def half_of(datestr):
    """民國 yyymmdd → '112H1'；無法解析回傳 None。"""
    s = str(datestr)
    if not s or len(s) < 6 or not s[:3].isdigit():
        return None
    y, m = int(s[:3]), int(s[3:5])
    if not 1 <= m <= 12 or not 100 <= y <= 120:  # 夾掉亂填的年份
        return None
    return f"{y:03d}H{1 if m <= 6 else 2}"


def half_key(h):
    return (int(h[:3]), int(h[-1]))


def seasons_on_disk():
    return sorted((d.name for d in RAW.iterdir()
                   if re.fullmatch(r"\d{3}S\d", d.name)),
                  key=lambda s: (int(s[:3]), int(s[-1])))


def load_sales():
    frames = []
    for season in seasons_on_disk():
        for letter, county in CITY.items():
            f = RAW / season / f"{letter}_lvr_land_a.csv"
            if not f.exists():
                continue
            df = pd.read_csv(f, skiprows=[1], dtype=str, low_memory=False)
            keep = pd.DataFrame({
                "county": county,
                "town": df["鄉鎮市區"],
                "target": df["交易標的"].fillna(""),
                "btype": df["建物型態"].fillna(""),
                "note": col(df, "備註").fillna(""),
                "half": df["交易年月日"].map(half_of),
                "price": num(df["總價元"]),
                "area": num(df["建物移轉總面積平方公尺"]),
                "car_price": num(col(df, "車位總價元")).fillna(0),
                "car_area": num(col(df, "車位移轉總面積平方公尺",
                                    "車位移轉總面積(平方公尺)")).fillna(0),
            })
            frames.append(keep)
    df = pd.concat(frames, ignore_index=True)
    df = df[df["target"].str.contains("房地")
            & df["btype"].str.contains("|".join(TYPES))
            & ~df["note"].str.contains(BAD_NOTE)
            & df["half"].notna() & (df["price"] > 0) & (df["area"] > 0)]
    # 車位拆算（拆算後面積需為正，否則保留原值）
    adj_p = df["price"] - df["car_price"]
    adj_a = df["area"] - df["car_area"]
    ok = (df["car_price"] > 0) & (adj_a > 0) & (adj_p > 0)
    df["u"] = df["price"] / (df["area"] * PING)
    df.loc[ok, "u"] = adj_p[ok] / (adj_a[ok] * PING)
    df = df[(df["u"] >= 5e4) & (df["u"] <= 350e4)]
    return df


def load_rents(n_seasons=12):
    frames = []
    for season in seasons_on_disk()[-n_seasons:]:
        for letter, county in CITY.items():
            f = RAW / season / f"{letter}_lvr_land_c.csv"
            if not f.exists():
                continue
            df = pd.read_csv(f, skiprows=[1], dtype=str, low_memory=False)
            keep = pd.DataFrame({
                "county": county,
                "town": df["鄉鎮市區"],
                "target": df["交易標的"].fillna(""),
                "btype": df["建物型態"].fillna(""),
                "rent": num(col(df, "總額元")),
                "area": num(col(df, "建物總面積平方公尺")),
                "car_rent": num(col(df, "車位總額元")).fillna(0),
                "car_area": num(col(df, "車位面積平方公尺")).fillna(0),
            })
            frames.append(keep)
    df = pd.concat(frames, ignore_index=True)
    df = df[df["target"].str.contains("租賃房屋")
            & df["btype"].str.contains("|".join(TYPES))
            & (df["rent"] > 0) & (df["area"] > 0)]
    adj_r, adj_a = df["rent"] - df["car_rent"], df["area"] - df["car_area"]
    ok = (df["car_rent"] > 0) & (adj_a > 0) & (adj_r > 0)
    df["ru"] = df["rent"] / (df["area"] * PING)
    df.loc[ok, "ru"] = adj_r[ok] / (adj_a[ok] * PING)
    return df[(df["ru"] >= 100) & (df["ru"] <= 10000)]


def med_at(series_by_half, target, max_back=2):
    """取 target 半年的中位數；缺值往前遞補至多 max_back 個半年。回傳 (值, 實際半年)。"""
    y, h = half_key(target)
    for _ in range(max_back + 1):
        key = f"{y:03d}H{h}"
        if key in series_by_half:
            return series_by_half[key], key
        h -= 1
        if h == 0:
            y, h = y - 1, 2
    return None, None


def main():
    sales = load_sales()
    print(f"買賣樣本 {len(sales):,} 筆（{sales['half'].min()}~{sales['half'].max()}）")
    g = sales.groupby(["county", "town", "half"])["u"]
    med = g.median()
    cnt = g.size()
    med = med[cnt >= 30]

    half_n = sales.groupby("half").size()
    halves_all = sorted((h for h in half_n.index if half_n[h] >= 1000),
                        key=half_key)  # 樣本充足的半年才算「最新」
    latest = halves_all[-1]
    ly, lh = half_key(latest)

    rents = load_rents()
    rg = rents.groupby(["county", "town"])["ru"]
    rent_med = rg.median()[rg.size() >= 30]

    last4 = seasons_on_disk()[-4:]
    towns = {}
    for (county, town), sub in med.groupby(level=[0, 1]):
        s = {h: v for (_, _, h), v in sub.items()}
        now, now_h = med_at(s, latest)
        b10, b10_h = med_at(s, f"{ly - 10:03d}H{lh}")
        b5, b5_h = med_at(s, f"{ly - 5:03d}H{lh}")
        peak = max((s.get(h) for h in ("110H2", "111H1", "111H2")
                    if s.get(h)), default=None)
        trough = min((s.get(h) for h in ("111H2", "112H1", "112H2")
                      if s.get(h)), default=None)
        r = rent_med.get((county, town))
        rec = {
            "unit_now": round(now / 1e4, 1) if now else None,
            "now_half": now_h,
            "unit_10y": round(b10 / 1e4, 1) if b10 else None,
            "cagr10": round(((now / b10) ** 0.1 - 1) * 100, 1)
                      if now and b10 else None,
            "cagr5": round(((now / b5) ** 0.2 - 1) * 100, 1)
                     if now and b5 else None,
            "dd2223": round((trough / peak - 1) * 100, 1)
                      if peak and trough else None,
            "rent_unit": round(r, 0) if r else None,
            "yield": round(r * 12 / now * 100, 2) if r and now else None,
            "halves": {h: round(v / 1e4, 1) for h, v in s.items()},
        }
        towns[f"{county}|{town}"] = rec

    # 近 4 季行政區概覽指標（縮放連動用）：單價/總價中位數與筆數
    recent = sales[sales["half"].isin(halves_all[-2:])]  # 近 2 半年 ≈ 近 4 季
    for (county, town), sub in recent.groupby(["county", "town"]):
        key = f"{county}|{town}"
        if key in towns and len(sub) >= 30:
            towns[key]["total_now"] = round(sub["price"].median() / 1e4, 0)
            towns[key]["n4"] = int(len(sub))

    meta = {
        "latest_half": latest, "seasons": [seasons_on_disk()[0],
                                           seasons_on_disk()[-1]],
        "rent_window": f"{seasons_on_disk()[-12]}~{seasons_on_disk()[-1]}",
        "dd_windows": "峰 110H2~111H2 / 谷 111H2~112H2",
        "generated": date.today().isoformat(),
    }
    OUT.write_text(json.dumps({"meta": meta, "towns": towns},
                              ensure_ascii=False), encoding="utf-8")

    rank = sorted(((k, v) for k, v in towns.items() if v["cagr10"] is not None),
                  key=lambda kv: kv[1]["cagr10"], reverse=True)
    dd = sorted(((k, v) for k, v in towns.items() if v["dd2223"] is not None),
                key=lambda kv: kv[1]["dd2223"])
    fmt = lambda kv: f"{kv[0].replace('|', '')} {kv[1]['cagr10']}%/年"
    fmt_dd = lambda kv: f"{kv[0].replace('|', '')} {kv[1]['dd2223']}%"
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(
        f"""# 保值分析報告（行政區級）

產出：{date.today().isoformat()}（pipeline/value.py）
資料：{meta['seasons'][0]}~{meta['seasons'][1]} 買賣（樣本 {len(sales):,}）；
租賃 {meta['rent_window']}（樣本 {len(rents):,}）。時間粒度＝半年，行政區×半年樣本 ≥30 才採計。

## 10 年年化漲幅（{latest} vs 10 年前）
- 前 10：{'；'.join(fmt(kv) for kv in rank[:10])}
- 後 10：{'；'.join(fmt(kv) for kv in rank[-10:])}

## 2022–23 修正期回檔（{meta['dd_windows']}）
- 跌最深 10 區：{'；'.join(fmt_dd(kv) for kv in dd[:10])}
- 最抗跌 10 區：{'；'.join(fmt_dd(kv) for kv in dd[-10:])}

## 注意
- 行政區級中位數會被產品結構改變影響（新重劃區大量新案會拉高中位數，
  漲幅≠同一間房子的漲幅）；里級版本需全量歷史 geocode，列 v3。
- 修正期回檔以半年中位數計，樣本少的區波動大，參考旗標而非精確值。
- 租金樣本在郊區稀疏（樣本 <30 不採計），報酬率缺值屬正常。
""", encoding="utf-8")
    print(f"輸出 {OUT.name}（{len(towns)} 區）；報告 {REPORT.name}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
