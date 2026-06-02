# Investment Tools

單一 Streamlit 入口，整合三個工具：

- `K線型態分析`
- `權證計算機`
- `權證推薦`

## 功能

- 首頁提供三個入口按鈕，可切換到不同工具
- `K線型態分析` 內含 K 線圖、技術指標、型態偵測與 AI 分析
- `權證計算機` 可手動輸入權證代號或名稱，再透過凱基 backend service 查詢
- 權證查到後會自動帶入標的物目標價、BIV、日期作為起始值
- 標的物目標價、BIV、日期都可自行修改
- 使用凱基 backend service 計算參考價格與敏感度矩陣
- 顯示 Delta / Gamma / Theta / Vega / Rho / 內含價值等欄位
- `權證推薦` 可依標的抓出認購權證，預設篩選 `360天以上`、`行使比例 >= 0.005`，並支援 `偏保守 / 偏均衡 / 偏積極 / 偏高流動性 / 自訂條件` 五種風格

## 建議環境

- `conda activate stock`

## 啟動方式

```bash
cd /Users/winer406/python/warrant
conda activate stock
streamlit run app.py
```

## 說明

- 目前 `app.py` 已經是單一檔案，適合直接推到 GitHub 與部署到 Streamlit Community Cloud
- 權證工具主要依賴凱基權證網 backend service：
  - `S0600013_GetWarrantList`
  - `S0600013_GetWarrant`
  - `S0600013_GetWarrants`
  - `S0600017_GetUnderlyingList`
  - `S0600017_GetUnderlyingByWarrant`
  - `S0600018_GetTheoreticalPrice`
  - `S0600018_SensitivityAnalysis`
- 若凱基之後調整 serviceId、欄位名或參數格式，權證工具需跟著更新
