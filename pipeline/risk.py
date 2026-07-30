# -*- coding: utf-8 -*-
"""供需風險指標：聚合行政區級資料，輸出 risk_towns.json 與 reports/risk_report.md。

指標與來源（粒度皆為行政區）：
1. 空屋率＝低度使用(用電)住宅比率 — data/raw/risk/pip/DG3_{期別}_{縣市代碼}.csv
   來源：內政部不動產資訊平台 E1040（半年更新）。該站有 F5 反爬（TSPD），
   無法用 requests 自動下載；更新方式見 README「風險資料更新」。
2. 待售新成屋宅數 — 同目錄 DG4_{季}_{縣市代碼}.csv（季更新，來源同上）。
3. 戶數年增率 — 戶政司 RIS OpenData ODRP014（村里戶數，月更新；本腳本自動下載＋快取）。
4. 成交量動能 — data/processed/cleaned.parquet（近 4 季 vs 前 4 季筆數）。
5. 預售解約率 — data/processed/raw_merged.parquet（「解約情形」欄，近 8 季）。

紅黃綠分級（透明規則，詳 reports/risk_report.md）：
  旗標 vac    空屋率 ≥ 北北桃 54 區 P75
  旗標 unsold 每千戶待售新成屋 ≥ P75
  旗標 hh     戶數年增率 ≤ 0
  旗標 vol    成交量近 4 季較前 4 季 ≤ -20%
  旗標 cancel 預售解約率 ≥ P75（樣本 ≥ 100 件才計）
  旗標 pipe   每千戶建照宅數（近 12 季，未來供給管線）≥ P75
  紅 = ≥4 旗標；黃 = 2~3；綠 = ≤1（指標缺漏不計旗標，hover 顯示「—」）

第 6 項資料：data/raw/risk/pip/LIC_T17_permit.csv（建照）/ LIC_T21_usage.csv（使照），
來源同 pip 平台（E4041 主題下載區，行政區×季，098Q1 起）。
"""
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

import truststore

truststore.inject_into_ssl()
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
PIP_DIR = ROOT / "data" / "raw" / "risk" / "pip"
RIS_DIR = ROOT / "data" / "raw" / "risk"
OUT = ROOT / "data" / "processed" / "risk_towns.json"
REPORT = ROOT / "reports" / "risk_report.md"
CITIES = ["臺北市", "新北市", "桃園市"]
UA = {"User-Agent": "Mozilla/5.0"}


def norm_county(name: str) -> str:
    return name.replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南")


# ---------- 1&2. pip 快取 CSV（低度用電 / 待售新成屋） ----------

def period_key(p: str):
    """期別排序鍵：'098'<'109H1'<'109H2'<'110H1'…；季 '109Q1'<…"""
    m = re.match(r"(\d+)([HQ]?)(\d?)", p)
    return (int(m.group(1)), int(m.group(3) or 0))


def load_pip(prefix: str):
    """回傳 {期別: {(county, town): (宅數, 比率或None)}}"""
    out = {}
    for f in PIP_DIR.glob(f"{prefix}_*.csv"):
        period = f.stem.split("_")[1]
        rows = list(csv.reader(f.read_text(encoding="utf-8-sig").splitlines()))
        for r in rows[1:]:
            if len(r) < 3 or r[1] == "全區":
                continue
            county, town, n = norm_county(r[0]), r[1], float(r[2])
            rate = float(r[3]) if len(r) > 3 and r[3] not in ("", "-") else None
            out.setdefault(period, {})[(county, town)] = (n, rate)
    return out


def load_lic(fname: str, quarters: int = 12):
    """建照/使照 CSV → ({(county, town): 近 N 季宅數合計}, 窗口字串)。"""
    f = PIP_DIR / fname
    if not f.exists():
        return {}, None
    rows = list(csv.reader(f.read_text(encoding="utf-8-sig").splitlines()))
    periods = sorted({r[0] for r in rows[1:] if r}, key=period_key)[-quarters:]
    out = {}
    for r in rows[1:]:
        if not r or r[0] not in periods:
            continue
        site = norm_county(r[1])
        county, town = site[:3], site[3:]
        if county in CITIES and town:
            n = int(r[2].replace(",", "") or 0)
            out[(county, town)] = out.get((county, town), 0) + n
    return out, f"{periods[0]}~{periods[-1]}" if periods else None


# ---------- 3. RIS 戶數（村里 → 行政區） ----------

def ris_fetch(period: str):
    """下載 ODRP014 單期全部分頁（含快取），回傳 list[dict]。查無資料回傳 None。"""
    cache = RIS_DIR / f"ris_ODRP014_{period}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    rows, page = [], 1
    while True:
        r = requests.get(
            f"https://www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP014/{period}",
            params={"page": page}, timeout=120, headers=UA)
        j = r.json()
        if j.get("responseCode") != "OD-0101-S":
            return None
        rows += j.get("responseData", [])
        if page >= int(j.get("totalPage", 1)):
            break
        page += 1
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def latest_ris_period(today=None):
    """從當月往回找最新可用期別（RIS 發布約落後 1 個月）。"""
    today = today or date.today()
    y, m = today.year - 1911, today.month
    for _ in range(8):
        p = f"{y:03d}{m:02d}"
        if (RIS_DIR / f"ris_ODRP014_{p}.json").exists() or ris_fetch(p) is not None:
            return p
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    raise RuntimeError("找不到可用的 RIS 期別")


def households_by_town(rows):
    """村里列 → {(county, town): 戶數}"""
    out = {}
    for r in rows:
        site = norm_county(r["site_id"])
        county, town = site[:3], site[3:]
        if county in CITIES:
            out[(county, town)] = out.get((county, town), 0) + int(r["household_no"])
    return out


# ---------- 4&5. 自有資料（量能 / 解約率） ----------

def season_sorted(seasons):
    return sorted(seasons, key=lambda s: (int(s[:3]), int(s[-1])))


def own_metrics():
    df = pd.read_parquet(ROOT / "data" / "processed" / "cleaned.parquet",
                         columns=["city", "season", "鄉鎮市區"])
    df["county"] = df["city"].map(norm_county)
    seasons = season_sorted(df["season"].unique())
    recent, prior = seasons[-4:], seasons[-8:-4]
    g = df.groupby(["county", "鄉鎮市區", "season"]).size()
    vol = {}
    for (county, town), sub in g.groupby(level=[0, 1]):
        s = sub.droplevel([0, 1])
        r, p = s.reindex(recent).fillna(0).sum(), s.reindex(prior).fillna(0).sum()
        vol[(county, town)] = {
            "vol_recent": int(r), "vol_prior": int(p),
            "vol_chg": round((r - p) / p * 100, 1) if p >= 30 else None,
        }

    raw = pd.read_parquet(ROOT / "data" / "processed" / "raw_merged.parquet",
                          columns=["city", "season", "鄉鎮市區", "deal_type", "解約情形"])
    raw = raw[raw["deal_type"] == "預售"]
    last8 = season_sorted(raw["season"].unique())[-8:]
    raw = raw[raw["season"].isin(last8)]
    raw["county"] = raw["city"].map(norm_county)
    raw["cancel"] = raw["解約情形"].fillna("").str.contains("解約")
    cx = {}
    for (county, town), sub in raw.groupby(["county", "鄉鎮市區"]):
        n, c = len(sub), int(sub["cancel"].sum())
        cx[(county, town)] = {
            "presale_n": n, "cancel_n": c,
            "cancel_rate": round(c / n * 100, 2) if n >= 100 else None,
        }
    return vol, cx, {"recent": recent, "prior": prior, "cancel_window": last8}


# ---------- 分級 ----------

def p75(vals):
    vals = sorted(v for v in vals if v is not None)
    return vals[int(len(vals) * 0.75)] if vals else None


def main():
    towns_gj = json.loads(
        (ROOT / "data" / "processed" / "towns.geojson").read_text(encoding="utf-8"))
    all_towns = [(f["properties"]["county"], f["properties"]["town"])
                 for f in towns_gj["features"]]

    dg3, dg4 = load_pip("DG3"), load_pip("DG4")
    vac_p = max(dg3, key=period_key)
    vac_prev_p = max((p for p in dg3 if p != vac_p), key=period_key)
    uns_p = max(dg4, key=period_key)
    uns_prev_candidates = [p for p in dg4 if period_key(p)[0] == period_key(uns_p)[0] - 1
                           and period_key(p)[1] == period_key(uns_p)[1]]
    uns_yoy_p = uns_prev_candidates[0] if uns_prev_candidates else None

    hh_p = latest_ris_period()
    hh_prev_p = f"{int(hh_p[:3]) - 1:03d}{hh_p[3:]}"
    hh_now = households_by_town(ris_fetch(hh_p))
    hh_prev = households_by_town(ris_fetch(hh_prev_p) or [])

    vol, cx, windows = own_metrics()
    permits, lic_window = load_lic("LIC_T17_permit.csv")
    usages, _ = load_lic("LIC_T21_usage.csv")

    rows = {}
    for key in all_towns:
        county, town = key
        vac = dg3.get(vac_p, {}).get(key)
        vac_prev = dg3.get(vac_prev_p, {}).get(key)
        uns = dg4.get(uns_p, {}).get(key)
        uns_yoy = dg4.get(uns_yoy_p, {}).get(key) if uns_yoy_p else None
        hh = hh_now.get(key)
        hhp = hh_prev.get(key)
        rows[key] = {
            "vac": vac[1] if vac else None,
            "vac_prev": vac_prev[1] if vac_prev else None,
            "unsold": int(uns[0]) if uns else None,
            "unsold_yoy": int(uns[0] - uns_yoy[0]) if uns and uns_yoy else None,
            "unsold1k": round(uns[0] / hh * 1000, 2) if uns and hh else None,
            "hh": hh,
            "hh_yoy": round((hh - hhp) / hhp * 100, 2) if hh and hhp else None,
            "permit3y": permits.get(key),
            "permit1k": round(permits[key] / hh * 1000, 1)
                        if key in permits and hh else None,
            "usage3y": usages.get(key),
            **vol.get(key, {"vol_recent": 0, "vol_prior": 0, "vol_chg": None}),
            **cx.get(key, {"presale_n": 0, "cancel_n": 0, "cancel_rate": None}),
        }

    th = {
        "vac_p75": p75([r["vac"] for r in rows.values()]),
        "unsold1k_p75": p75([r["unsold1k"] for r in rows.values()]),
        "cancel_p75": p75([r["cancel_rate"] for r in rows.values()]),
        "permit1k_p75": p75([r["permit1k"] for r in rows.values()]),
    }
    for r in rows.values():
        flags = []
        if r["vac"] is not None and r["vac"] >= th["vac_p75"]:
            flags.append("vac")
        if r["unsold1k"] is not None and r["unsold1k"] >= th["unsold1k_p75"]:
            flags.append("unsold")
        if r["hh_yoy"] is not None and r["hh_yoy"] <= 0:
            flags.append("hh")
        if r["vol_chg"] is not None and r["vol_chg"] <= -20:
            flags.append("vol")
        if r["cancel_rate"] is not None and r["cancel_rate"] >= th["cancel_p75"]:
            flags.append("cancel")
        if r["permit1k"] is not None and th["permit1k_p75"] is not None \
                and r["permit1k"] >= th["permit1k_p75"]:
            flags.append("pipe")
        r["flags"] = flags
        r["level"] = ("red" if len(flags) >= 4
                      else "yellow" if len(flags) >= 2 else "green")

    out = {
        "meta": {
            "vac_period": vac_p, "vac_prev_period": vac_prev_p,
            "unsold_period": uns_p, "unsold_yoy_period": uns_yoy_p,
            "hh_period": hh_p, "hh_prev_period": hh_prev_p,
            "vol_recent": windows["recent"], "vol_prior": windows["prior"],
            "cancel_window": windows["cancel_window"],
            "lic_window": lic_window,
            "generated": date.today().isoformat(),
        },
        "thresholds": th,
        "towns": {f"{c}|{t}": r for (c, t), r in rows.items()},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    levels = {"red": [], "yellow": [], "green": []}
    for (c, t), r in rows.items():
        levels[r["level"]].append(f"{c}{t}（{'、'.join(r['flags']) or '無旗標'}）")
    flag_names = {"vac": "空屋率高", "unsold": "餘屋壓力大", "hh": "戶數負成長",
                  "vol": "量縮逾兩成", "cancel": "解約率高", "pipe": "供給管線大"}
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(
        f"""# 供需風險分級報告

產出：{date.today().isoformat()}（pipeline/risk.py）

## 資料時點
| 指標 | 期別 | 來源 |
|---|---|---|
| 空屋率（低度用電） | {vac_p}（上期 {vac_prev_p}） | 內政部不動產資訊平台 E1040 |
| 待售新成屋 | {uns_p}（年比 {uns_yoy_p}） | 同上 |
| 戶數年增率 | {hh_p} vs {hh_prev_p} | 戶政司 ODRP014 |
| 成交量動能 | 近4季 {windows['recent']} vs 前4季 {windows['prior']} | 自有實價登錄 |
| 預售解約率 | {windows['cancel_window'][0]}~{windows['cancel_window'][-1]} | 自有實價登錄（解約情形欄） |
| 建照宅數（供給管線） | {lic_window} | pip E4041 主題下載區 |

## 分級規則
六旗標：空屋率≥P75（{th['vac_p75']}%）、每千戶餘屋≥P75（{th['unsold1k_p75']}）、
戶數年增率≤0、量縮≤-20%、解約率≥P75（{th['cancel_p75']}%，樣本≥100）、
每千戶建照≥P75（{th['permit1k_p75']}）。
紅=≥4旗標、黃=2~3、綠=≤1。旗標名稱：{flag_names}。

## 結果
- 紅（{len(levels['red'])}）：{'；'.join(levels['red']) or '無'}
- 黃（{len(levels['yellow'])}）：{'；'.join(levels['yellow']) or '無'}
- 綠：{len(levels['green'])} 區

## 判讀注意
- 空屋率高但戶數強成長的區（如青埔所在的中壢/大園交屋潮），旗標制自然不會誤判為紅。
- 低度用電是代理指標，山區/度假屋多的區（如萬里、復興）天然偏高。
- 待售新成屋為建商壓力指標，郊區小基期區（如觀音、新屋）看每千戶正規化值。
""", encoding="utf-8")
    print(f"輸出 {OUT.name}：紅 {len(levels['red'])} 黃 {len(levels['yellow'])} "
          f"綠 {len(levels['green'])}；報告 {REPORT}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
