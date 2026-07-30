# 北北桃房價地圖 v1

規格與進度見 [SPEC.md](SPEC.md)。**所有程式已寫完**；唯一未完成的是全量
geocode（純資料工作，不需要 AI，照下面指令跑完即可）。

## 收尾流程（依序執行，全部可中斷重跑）

```
:: 1. 全量 geocode（約 13 萬唯一地址，4 執行緒約 9–12 小時，可中斷續跑）
.venv\Scripts\python.exe pipeline\geocode.py

:: 2. 重新聚合出地圖資料
.venv\Scripts\python.exe pipeline\aggregate.py

:: 3. 自動化驗收（步驟 8/9/13 的檢查，產出 reports/final_qa.md）
.venv\Scripts\python.exe pipeline\qa.py

:: 4. 看地圖
.venv\Scripts\python.exe -m http.server 8642
:: 瀏覽 http://localhost:8642/web/
```

- geocode 快取：`data/processed/geocode_cache.jsonl`（append-only，勿手動編輯）。
  中斷後重跑第 1 步會從斷點接續，已完成的不會重打 API。
- `qa.py` 若有 FAIL 項，代表數據與常識矛盾，需查明是 bug 還是市場事實，
  結論補進 `reports/final_qa.md` 的說明區。
- 一鍵更新（之後每季跑一次）：`.venv\Scripts\python.exe update.py`
  （下載新季 → 清洗 → geocode 只補新地址 → 重新聚合）。

## 目錄

- `pipeline/` 下載、解析、清洗、geocode、聚合腳本
- `data/raw/` 原始 CSV（gitignore）；`data/processed/` parquet 與 GeoJSON
- `reports/` 清洗、geocode 評估與歸里報告
- `web/` MapLibre 靜態地圖（單價/總價/成交量/蛋黃蛋白四視圖、預售/中古切換、
  總價滑桿、3D、行政區界與區名、桃園軌道站點含到北車時間、地標、
  「她家基準」相對價比較；`overlays.js` 為站點地標靜態資料）
  - 網址加 `?rafshim=1` 可在無 rAF 的環境（如 Claude 瀏覽器面板）強制渲染，供自動化驗證
