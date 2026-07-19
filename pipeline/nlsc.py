# -*- coding: utf-8 -*-
"""NLSC TextQueryMap 共用工具：地址正規化與查詢。"""
import re

import truststore

truststore.inject_into_ssl()
import requests

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


def query(addr: str, session=None, timeout=20):
    """回傳 (lon, lat, matched_content) 或 None。候選須與查詢的路街+號吻合。"""
    sess = session or requests
    r = sess.get("https://api.nlsc.gov.tw/idc/TextQueryMap/" + addr,
                 timeout=timeout, headers=HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    items = re.findall(
        r"<CONTENT>(.*?)</CONTENT>.*?<LOCATION>([\d.]+),([\d.]+)</LOCATION>",
        r.text, re.S)
    if not items:
        return None
    m = re.search(r"([^\s區市縣]{2,}?(?:路|街|大道)[^號]*?\d+號)", addr)
    key = m.group(1) if m else None
    for content, lon, lat in items:
        c = content.translate(FW)
        if key is None or key in c:
            return float(lon), float(lat), content
    return None
