# -*- coding: utf-8 -*-
"""下載實價登錄歷史季度批次資料（北北桃、中古 _a / 預售 _b）。

用法：python pipeline/download.py [--seasons N]
已存在的季度自動跳過，可重跑。
"""
import argparse
import io
import sys
import zipfile
from pathlib import Path

import truststore

truststore.inject_into_ssl()  # 政府網站憑證鏈缺 SKI，改用系統憑證庫驗證
import requests

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
URL_TMPL = "https://plvr.land.moi.gov.tw/DownloadSeason?season={season}&type=zip&fileName=lvr_landcsv.zip"
# A=台北市 F=新北市 H=桃園市；_a=中古買賣、_b=預售屋
WANTED = [f"{c}_lvr_land_{t}.csv" for c in "afh" for t in "ab"]


def season_candidates(n: int) -> list[str]:
    """由新到舊列出候選季度（民國年），多列幾個以防最新季尚未釋出。"""
    import datetime

    today = datetime.date.today()
    roc_year = today.year - 1911
    quarter = (today.month - 1) // 3 + 1
    out = []
    y, q = roc_year, quarter
    for _ in range(n + 3):  # 多 3 個候選
        out.append(f"{y}S{q}")
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out


def download_season(season: str) -> bool:
    """下載一季並解出北北桃檔案。回傳是否成功。"""
    dest = RAW_DIR / season
    if dest.exists() and any(dest.glob("*.csv")):
        print(f"[skip] {season} 已存在")
        return True
    url = URL_TMPL.format(season=season)
    print(f"[get ] {season} <- {url}")
    r = requests.get(url, timeout=120)
    if r.status_code != 200 or len(r.content) < 1000:
        print(f"[fail] {season} status={r.status_code} size={len(r.content)}")
        return False
    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        print(f"[fail] {season} 非 zip（可能該季不存在）")
        return False
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in zf.namelist():
        if name.lower() in WANTED:
            (dest / name.lower()).write_bytes(zf.read(name))
            n += 1
    print(f"[ ok ] {season} 解出 {n} 檔")
    return n > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, default=12)
    args = ap.parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    got = []
    for s in season_candidates(args.seasons):
        if len(got) >= args.seasons:
            break
        if download_season(s):
            got.append(s)
    print(f"\n完成：{len(got)} 季 -> {', '.join(got)}")
    if len(got) < args.seasons:
        print("警告：季數不足", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
