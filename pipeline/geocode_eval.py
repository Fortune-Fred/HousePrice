# -*- coding: utf-8 -*-
"""步驟 7：Geocoding 方案評估 — 抽樣 1,000 筆地址實測 NLSC TextQueryMap。

輸出 reports/geocode_eval.md。
"""
import re
import sys
import time
from pathlib import Path

import truststore

truststore.inject_into_ssl()
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "geocode_eval.md"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://maps.nlsc.gov.tw/"}
FW = str.maketrans("０１２３４５６７８９", "0123456789")


def normalize(addr: str) -> str:
    """全形轉半形、去樓層資訊、門牌區間取中點。"""
    a = addr.translate(FW)
    a = re.sub(r"[一二三四五六七八九十]+樓(之\d+)?$", "", a)
    a = re.sub(r"之\d+$", "", a)
    m = re.search(r"(\d+)~(\d+)號", a)
    if m:
        mid = (int(m.group(1)) + int(m.group(2))) // 2
        a = re.sub(r"\d+~\d+號", f"{mid}號", a)
    return a.strip()


def query(addr: str):
    """回傳 (lon, lat, matched_content) 或 None。要求候選結果與查詢的路街+號吻合。"""
    r = requests.get("https://api.nlsc.gov.tw/idc/TextQueryMap/" + addr,
                     timeout=20, headers=HEADERS)
    if r.status_code != 200:
        return None
    items = re.findall(
        r"<CONTENT>(.*?)</CONTENT>.*?<LOCATION>([\d.]+),([\d.]+)</LOCATION>",
        r.text, re.S)
    if not items:
        return None
    # 取查詢字串的「路街巷弄+號」做吻合檢查，避免模糊配對（39號 -> 139號）
    m = re.search(r"([^\s區市縣]{2,}?(?:路|街|大道)[^號]*?\d+號)", addr)
    key = m.group(1) if m else None
    for content, lon, lat in items:
        c = content.translate(FW)
        if key is None or key in c:
            return float(lon), float(lat), content
    return None


def main():
    df = pd.read_parquet(ROOT / "data" / "processed" / "cleaned.parquet")
    sample = df.sample(1000, random_state=42)
    results = []
    t0 = time.time()
    for i, (_, row) in enumerate(sample.iterrows(), 1):
        raw = row["土地位置建物門牌"]
        if not isinstance(raw, str) or not raw:
            results.append((row["deal_type"], raw, False))
            continue
        try:
            hit = query(normalize(raw))
        except Exception:
            hit = None
        results.append((row["deal_type"], raw, hit is not None))
        if i % 100 == 0:
            ok = sum(r[2] for r in results)
            print(f"{i}/1000 成功率 {ok/i:.1%} 累計 {time.time()-t0:.0f}s", flush=True)
        time.sleep(0.1)  # 溫和限速

    res = pd.DataFrame(results, columns=["deal_type", "addr", "ok"])
    elapsed = time.time() - t0
    overall = res["ok"].mean()
    by_type = res.groupby("deal_type")["ok"].agg(["mean", "count"])

    lines = [
        "# Geocoding 方案評估（步驟 7）",
        "",
        f"- 評估時間：{pd.Timestamp.now():%Y-%m-%d %H:%M}；抽樣 1,000 筆（random_state=42）",
        "",
        "## 候選方案",
        "",
        "| 方案 | 帳號需求 | 實測 |",
        "|---|---|---|",
        "| NLSC TextQueryMap（api.nlsc.gov.tw/idc/TextQueryMap）| 不需帳號（需帶 Referer: maps.nlsc.gov.tw）| 本報告主測 |",
        "| TGOS 全國門牌地址定位 | 需申請帳號/金鑰 | 未測（備援；若 NLSC 成功率不足再請使用者申請）|",
        "",
        "## NLSC 實測結果",
        "",
        f"- 總成功率：**{overall:.1%}**（{int(res['ok'].sum())}/1000）",
        f"- 平均速度：{elapsed/1000:.2f} 秒/筆（含 0.1s 限速）",
        "",
        "依物件類別：",
        "",
        "```",
        by_type.to_string(),
        "```",
        "",
        "## 匹配策略與已知失敗型態",
        "",
        "- 前處理：全形數字轉半形、去樓層、門牌區間（1~30號）取中點。",
        "- 候選驗證：回傳結果須含查詢的「路街+號」，避免模糊配對錯置（實測發現 39號 會配到 139號）。",
        "- 失敗主因：預售屋地址常為「XX路與XX街交叉路口」或地號描述，無法門牌定位。",
        "- 加分項：NLSC 回應的 CONTENT 直接含**里名**（如「福音里」），步驟 8 可同時用",
        "  座標 point-in-polygon 與回應里名交叉驗證。",
        "",
        "## 失敗樣本（前 20 筆）",
        "",
        "```",
        "\n".join(res[~res.ok]["addr"].head(20).astype(str)),
        "```",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n總成功率 {overall:.1%} -> {REPORT}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
