# Investment Tools

單一 Streamlit 入口，整合四個工具：

- `K線型態分析`
- `權證計算機`
- `權證推薦`
- `主動ETF追蹤`

## 功能

- 首頁提供四個入口按鈕，可切換到不同工具
- `K線型態分析` 內含 K 線圖、技術指標、型態偵測與 AI 分析
- `權證計算機` 可手動輸入權證代號或名稱，再透過凱基 backend service 查詢
- 權證查到後會自動帶入標的物目標價、BIV、日期作為起始值
- 標的物目標價、BIV、日期都可自行修改
- 使用凱基 backend service 計算參考價格與敏感度矩陣
- 顯示 Delta / Gamma / Theta / Vega / Rho / 內含價值等欄位
- `權證推薦` 可依標的抓出認購權證，預設篩選 `360天以上`、`行使比例 >= 0.005`，並支援 `偏保守 / 偏均衡 / 偏積極 / 偏高流動性 / 自訂條件` 五種風格
- `主動ETF追蹤` 可新增或刪除台灣主動型 ETF 代號，抓取公開持股頁並比對前次快照的持股進出

## 建議環境

- `conda activate stock`

## 啟動方式

```bash
cd /Users/winer406/python/warrant
conda activate stock
streamlit run app.py
```

## Streamlit Cloud Google Sheets 設定

`主動ETF追蹤` 會優先使用 Google Sheets 儲存追蹤清單與每日快照。若未設定 Google Sheets secrets，會自動退回本機 `active_etf_state.json`。

1. 建立一份 Google Sheet，記下網址中的 spreadsheet id。
2. 建立 Google Cloud service account，下載 JSON key。
3. 將 Google Sheet 分享給 service account 的 `client_email`，權限給編輯者。
4. 在 Streamlit Community Cloud 的 App secrets 填入：

```toml
[active_etf]
spreadsheet_id = "你的 Google Sheet spreadsheet id"

[gcp_service_account]
type = "service_account"
project_id = "你的 project_id"
private_key_id = "你的 private_key_id"
private_key = "-----BEGIN PRIVATE KEY-----\n你的 private key\n-----END PRIVATE KEY-----\n"
client_email = "你的 service account email"
client_id = "你的 client_id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "你的 client_x509_cert_url"
universe_domain = "googleapis.com"
```

程式會自動建立三個工作表：

- `active_etf_watchlist`：目前追蹤的 ETF 代號
- `active_etf_snapshots`：每日 ETF 持股快照
- `active_etf_meta`：每檔 ETF 的最新快照摘要

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
