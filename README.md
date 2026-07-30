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
- `web/` MapLibre 靜態地圖（單價/總價/成交量/蛋黃蛋白/供需風險/保值六視圖、
  預售/中古切換、總價滑桿、3D、行政區界與區名、桃園軌道站點含到北車時間、地標、
  「她家基準」相對價比較、行政區/里搜尋框、縮放連動粒度（遠看行政區、近看里）；
  `overlays.js` 為站點地標靜態資料）
  - 網址加 `?rafshim=1` 可在無 rAF 的環境（如 Claude 瀏覽器面板）強制渲染，供自動化驗證

## 風險資料更新（供需風險視圖）

`pipeline/risk.py` 產出 `data/processed/risk_towns.json` 與 `reports/risk_report.md`，
五指標中三個全自動（戶數＝戶政司 API、量能與解約率＝自有實價登錄）；
**空屋率與待售新成屋**來自內政部不動產資訊平台（pip.moi.gov.tw），該站有
F5 反爬（TSPD），`requests`/`curl` 會被擋，只能經真實瀏覽器下載：

1. 瀏覽器開 https://pip.moi.gov.tw/Publicize/Info/E1040 後按 F12 開 Console，執行：
   ```js
   for (const [dg, p] of [["DataGroup3","115H1"], ["DataGroup4","115Q2"]])  // 換成新期別
     for (const c of ["63000","65000","68000"])
       fetch("/Publicize/Info/E1040", { method: "POST",
         headers: { "Content-Type": "application/x-www-form-urlencoded" },
         body: new URLSearchParams({ F01: dg, F02: p, F03: c }) })
         .then(r => r.blob()).then(b => {
           const a = document.createElement("a");
           a.href = URL.createObjectURL(b);
           a.download = `${dg === "DataGroup3" ? "DG3" : "DG4"}_${p}_${c}.csv`; a.click();
         });
   ```
2. 下載的檔案放進 `data/raw/risk/pip/`，重跑 `python pipeline/risk.py`。
3. 建照/使照（第六旗標）同站主題下載區，同樣需經瀏覽器：
   `/Publicize/Info/E4041?m=csv&k=K02&n=T17`（建照）與 `n=T21`（使照），
   存成 `LIC_T17_permit.csv` / `LIC_T21_usage.csv`（北北桃列即可）放同目錄。
4. 更新頻率：低度用電每半年（2月/7月出刊）、待售新成屋與建照使照每季；
   沒更新也能跑，risk.py 自動取目錄內最新期別。

## 保值分析（保值視圖）

`pipeline/value.py` 使用 `data/raw/{季}/` 全部季度（101S3 起，`download.py --range
101S3:115S2` 可補齊）計算行政區級 10/5 年年化漲幅、2022–23 修正期回檔與租金報酬率
（租賃 `_c` 檔近 12 季），輸出 `value_towns.json` 與 `reports/value_report.md`。
每季 update.py 會自動重算；歷史季度檔勿刪（gitignore，但保值分析依賴它們）。
