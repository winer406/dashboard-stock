# app.py
"""
台股 K 線圖分析（進階形態版）
功能：
1. 輸入台股代碼與查詢天數
2. 技術指標：布林通道、5/20/60/120 日均線、KD、RSI、MACD
3. K線形態偵測：Morning Star, Evening Star, Shooting Star、紅三兵、黑三鴉與多種吞噬/母子型態
4. 自動處理 Yahoo Finance 資料結構
5. 可切換 ChatGPT / Gemini 分析 K 線圖、成交量與布林通道

需要套件：
pip install streamlit yfinance pandas plotly
"""

from dataclasses import dataclass
import csv
import datetime as dt
import html as html_lib
import io
import json
import os
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

# -----------------------------
# 基本設定
# -----------------------------
BOLLINGER_WINDOW = 20
BOLLINGER_STD = 1.5
MA_WINDOWS = (5, 20, 60, 120)
KD_WINDOW = 9
RSI_WINDOW = 14
OPENAI_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
GEMINI_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
TPEX_OPENAPI_BASE = "https://www.tpex.org.tw/openapi/v1"
ENV_QUOTES = "\"'“”‘’"
KGI_SERVICE_URL = "https://warrant.kgi.com/EDWebService/WSInterfaceSwap.asmx/GetService"
KGI_LOCATION_PATH = "/EDWebSite/Views/WarrantCalculator/WarrantCalculator.aspx"
KGI_SEARCH_LOCATION_PATH = "/EDWebSite/Views/WarrantSearch/WarrantSearch.aspx"
KGI_USER_AGENT = "Mozilla/5.0"
KGI_NS = {"t": "http://tempuri.org/"}
ETFINFO_HOLDINGS_URL = "https://www.etfinfo.tw/etf/{code}/holdings"
ACTIVE_ETF_STATE_PATH = Path(__file__).with_name("active_etf_state.json")
ACTIVE_ETF_FALLBACK_STATE_PATH = Path.home() / ".warrant_app" / "active_etf_state.json"
ACTIVE_ETF_WATCHLIST_SHEET = "active_etf_watchlist"
ACTIVE_ETF_SNAPSHOTS_SHEET = "active_etf_snapshots"
ACTIVE_ETF_META_SHEET = "active_etf_meta"
ACTIVE_ETF_SNAPSHOT_COLUMNS = [
    "etf_code",
    "etf_name",
    "snapshot_date",
    "stock_code",
    "stock_name",
    "change_percent",
    "close_price",
    "weight_percent",
    "shares",
    "contribution_percent",
]
COMMON_STOCK_FALLBACKS = {
    "台積電": "2330.TW",
    "緯創": "3231.TW",
    "欣興": "3037.TW",
    "越峰": "8121.TWO",
}
PATTERN_SELECT_ALL = "全選"
PATTERN_CHOICES = (
    PATTERN_SELECT_ALL,
    "Red Candle (紅K/陽線)",
    "Black Candle (黑K/陰線)",
    "Doji (十字線)",
    "Morning Star (晨星)",
    "Evening Star (暮星)",
    "Shooting Star (射擊之星)",
    "Three White Soldiers (紅三兵)",
    "Three Black Crows (黑三鴉)",
    "Bullish Engulfing (多頭吞噬)",
    "Piercing Line (穿刺線)",
    "Hammer (槌子)",
    "Hanging Man (吊人線)",
    "Meteor (流星)",
    "Bullish Harami (多頭母子)",
    "Bullish Harami Cross (多頭母子十字)",
    "Sandwich (三明治)",
    "Ladder Bottom (梯底)",
    "Bearish Harami (空頭母子)",
    "Bearish Engulfing (陰吞噬)",
    "Dark Cloud Cover (烏雲罩頂)",
    "On Neck Line (頸上線)",
)
PATTERN_DEFINITIONS = [
    {"column": "Red Candle", "label": "紅K", "side": "neutral", "choice": "Red Candle (紅K/陽線)", "manual_only": True},
    {"column": "Black Candle", "label": "黑K", "side": "neutral", "choice": "Black Candle (黑K/陰線)", "manual_only": True},
    {"column": "Doji", "label": "十字線", "side": "neutral", "choice": "Doji (十字線)", "manual_only": True},
    {"column": "Morning Star", "label": "晨星", "side": "bullish", "choice": "Morning Star (晨星)"},
    {"column": "Three White Soldiers", "label": "紅三兵", "side": "bullish", "choice": "Three White Soldiers (紅三兵)"},
    {"column": "Bullish Engulfing", "label": "多頭吞噬", "side": "bullish", "choice": "Bullish Engulfing (多頭吞噬)"},
    {"column": "Piercing Line", "label": "穿刺線", "side": "bullish", "choice": "Piercing Line (穿刺線)"},
    {"column": "Hammer", "label": "槌子", "side": "bullish", "choice": "Hammer (槌子)"},
    {"column": "Bullish Harami", "label": "多頭母子", "side": "bullish", "choice": "Bullish Harami (多頭母子)"},
    {"column": "Bullish Harami Cross", "label": "多頭母子十字", "side": "bullish", "choice": "Bullish Harami Cross (多頭母子十字)"},
    {"column": "Sandwich", "label": "三明治", "side": "bullish", "choice": "Sandwich (三明治)"},
    {"column": "Ladder Bottom", "label": "梯底", "side": "bullish", "choice": "Ladder Bottom (梯底)"},
    {"column": "Evening Star", "label": "暮星", "side": "bearish", "choice": "Evening Star (暮星)"},
    {"column": "Shooting Star", "label": "射擊之星", "side": "bearish", "choice": "Shooting Star (射擊之星)"},
    {"column": "Three Black Crows", "label": "黑三鴉", "side": "bearish", "choice": "Three Black Crows (黑三鴉)"},
    {"column": "Hanging Man", "label": "吊人線", "side": "bearish", "choice": "Hanging Man (吊人線)"},
    {"column": "Meteor", "label": "流星", "side": "bearish", "choice": "Meteor (流星)"},
    {"column": "Bearish Harami", "label": "空頭母子", "side": "bearish", "choice": "Bearish Harami (空頭母子)"},
    {"column": "Bearish Engulfing", "label": "陰吞噬", "side": "bearish", "choice": "Bearish Engulfing (陰吞噬)"},
    {"column": "Dark Cloud Cover", "label": "烏雲罩頂", "side": "bearish", "choice": "Dark Cloud Cover (烏雲罩頂)"},
    {"column": "On Neck Line", "label": "頸上線", "side": "bearish", "choice": "On Neck Line (頸上線)"},
]

@dataclass
class ChartOptions:
    ticker: str
    display_days: int
    show_bollinger: bool
    selected_mas: tuple[int, ...]
    show_kd: bool
    show_rsi: bool
    show_macd: bool
    show_red_candle: bool
    show_black_candle: bool
    show_doji: bool
    show_morning_star: bool
    show_evening_star: bool
    show_shooting_star: bool
    show_three_white_soldiers: bool
    show_three_black_crows: bool
    show_bullish_engulfing: bool
    show_piercing_line: bool
    show_hammer: bool
    show_hanging_man: bool
    show_meteor: bool
    show_bullish_harami: bool
    show_bullish_harami_cross: bool
    show_sandwich: bool
    show_ladder_bottom: bool
    show_bearish_harami: bool
    show_bearish_engulfing: bool
    show_dark_cloud_cover: bool
    show_on_neck_line: bool


def safe_float(value, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

# -----------------------------
# 形態偵測函式
# -----------------------------
def candle_body(candle: pd.Series) -> float:
    return abs(candle["Close"] - candle["Open"])


def candle_range(candle: pd.Series) -> float:
    return max(candle["High"] - candle["Low"], 0.001)


def candle_mid_body(candle: pd.Series) -> float:
    return (candle["Open"] + candle["Close"]) / 2


def detect_red_candle(data: pd.DataFrame) -> pd.Series:
    """紅K / 陽線：收盤高於開盤。"""
    return data["Close"] > data["Open"]


def detect_black_candle(data: pd.DataFrame) -> pd.Series:
    """黑K / 陰線：收盤低於開盤。"""
    return data["Close"] < data["Open"]


def detect_doji(data: pd.DataFrame) -> pd.Series:
    """十字線：開盤與收盤接近，代表多空拉鋸。"""
    body = (data["Close"] - data["Open"]).abs()
    total_range = (data["High"] - data["Low"]).replace(0, pd.NA)
    return (body <= total_range * 0.1).fillna(False)


def detect_morning_star(data: pd.DataFrame) -> pd.Series:
    """晨星：看漲反轉（大陰、跳空小實體、大陽）"""
    signals = pd.Series(False, index=data.index)
    for i in range(2, len(data)):
        f, s, t = data.iloc[i-2], data.iloc[i-1], data.iloc[i]
        f_body = abs(f["Close"] - f["Open"])
        s_body = abs(s["Close"] - s["Open"])
        t_body = abs(t["Close"] - t["Open"])
        
        # 1. 第一根長黑，第二根小實體
        # 2. 第三根長紅且收盤超過第一根實體中值
        is_morning = (f["Close"] < f["Open"] and f_body > (f["High"]-f["Low"])*0.5 and
                      s_body < f_body * 0.5 and
                      t["Close"] > t["Open"] and t["Close"] > (f["Open"]+f["Close"])/2)
        signals.iloc[i] = is_morning
    return signals

def detect_evening_star(data: pd.DataFrame) -> pd.Series:
    """暮星：看跌反轉（大陽、跳空小實體、大陰）"""
    signals = pd.Series(False, index=data.index)
    for i in range(2, len(data)):
        f, s, t = data.iloc[i-2], data.iloc[i-1], data.iloc[i]
        f_body = abs(f["Close"] - f["Open"])
        s_body = abs(s["Close"] - s["Open"])
        
        # 1. 第一根長紅，第二根小實體
        # 2. 第三根長黑且收盤低於第一根實體中值
        is_evening = (f["Close"] > f["Open"] and f_body > (f["High"]-f["Low"])*0.5 and
                      s_body < f_body * 0.5 and
                      t["Close"] < t["Open"] and t["Close"] < (f["Open"]+f["Close"])/2)
        signals.iloc[i] = is_evening
    return signals

def detect_shooting_star(data: pd.DataFrame) -> pd.Series:
    """射擊之星：看跌訊號（長上影線、小實體）"""
    signals = pd.Series(False, index=data.index)
    for i in range(len(data)):
        curr = data.iloc[i]
        body = abs(curr["Close"] - curr["Open"])
        total_range = max(curr["High"] - curr["Low"], 0.001)
        upper_shadow = curr["High"] - max(curr["Open"], curr["Close"])
        lower_shadow = min(curr["Open"], curr["Close"]) - curr["Low"]
        
        # 上影線長度需為實體2倍以上，且下影線極短
        is_shooting = (upper_shadow >= body * 2) and (lower_shadow <= total_range * 0.1) and (body <= total_range * 0.3)
        signals.iloc[i] = is_shooting
    return signals


def detect_three_white_soldiers(data: pd.DataFrame) -> pd.Series:
    """紅三兵：連續三根陽線、收盤步步高升，且後兩根開盤落在前一根實體內。"""
    signals = pd.Series(False, index=data.index)
    for i in range(2, len(data)):
        first, second, third = data.iloc[i - 2], data.iloc[i - 1], data.iloc[i]
        candles = [first, second, third]
        if not all(candle["Close"] > candle["Open"] for candle in candles):
            continue

        closes_rising = first["Close"] < second["Close"] < third["Close"]
        opens_in_body = (
            min(first["Open"], first["Close"]) <= second["Open"] <= max(first["Open"], first["Close"])
            and min(second["Open"], second["Close"]) <= third["Open"] <= max(second["Open"], second["Close"])
        )
        body1 = abs(first["Close"] - first["Open"])
        body2 = abs(second["Close"] - second["Open"])
        body3 = abs(third["Close"] - third["Open"])
        bodies_non_decreasing = body2 >= body1 and body3 >= body2

        signals.iloc[i] = closes_rising and opens_in_body and bodies_non_decreasing
    return signals


def detect_three_black_crows(data: pd.DataFrame) -> pd.Series:
    """黑三鴉：連續三根陰線、收盤步步走低，且後兩根開盤落在前一根實體內。"""
    signals = pd.Series(False, index=data.index)
    for i in range(2, len(data)):
        first, second, third = data.iloc[i - 2], data.iloc[i - 1], data.iloc[i]
        candles = [first, second, third]
        if not all(candle["Close"] < candle["Open"] for candle in candles):
            continue

        closes_falling = first["Close"] > second["Close"] > third["Close"]
        opens_in_body = (
            min(first["Open"], first["Close"]) <= second["Open"] <= max(first["Open"], first["Close"])
            and min(second["Open"], second["Close"]) <= third["Open"] <= max(second["Open"], second["Close"])
        )
        closes_near_low = all(
            (candle["Close"] - candle["Low"]) <= max((candle["High"] - candle["Low"]) * 0.2, 0.001)
            for candle in candles
        )

        signals.iloc[i] = closes_falling and opens_in_body and closes_near_low
    return signals

def detect_bullish_engulfing(data: pd.DataFrame) -> pd.Series:
    """多頭吞噬：前黑後紅，且後一根實體吞噬前一根實體"""
    signals = pd.Series(False, index=data.index)
    for i in range(1, len(data)):
        prev, curr = data.iloc[i - 1], data.iloc[i]
        prev_bearish = prev["Close"] < prev["Open"]
        curr_bullish = curr["Close"] > curr["Open"]
        engulfs_body = curr["Open"] <= prev["Close"] and curr["Close"] >= prev["Open"]
        signals.iloc[i] = prev_bearish and curr_bullish and engulfs_body
    return signals

def detect_bearish_engulfing(data: pd.DataFrame) -> pd.Series:
    """陰吞噬：前紅後黑，且後一根黑 K 實體吞噬前一根紅 K 實體"""
    signals = pd.Series(False, index=data.index)
    for i in range(1, len(data)):
        prev, curr = data.iloc[i - 1], data.iloc[i]
        prev_bullish = prev["Close"] > prev["Open"]
        curr_bearish = curr["Close"] < curr["Open"]
        engulfs_body = curr["Open"] >= prev["Close"] and curr["Close"] <= prev["Open"]
        signals.iloc[i] = prev_bullish and curr_bearish and engulfs_body
    return signals


def detect_piercing_line(data: pd.DataFrame) -> pd.Series:
    """穿刺線：前長黑、後紅K收回前黑實體中線以上，偏多頭反轉。"""
    signals = pd.Series(False, index=data.index)
    for i in range(1, len(data)):
        prev, curr = data.iloc[i - 1], data.iloc[i]
        prev_body = candle_body(prev)
        prev_range = candle_range(prev)
        is_signal = (
            prev["Close"] < prev["Open"]
            and prev_body >= prev_range * 0.45
            and curr["Close"] > curr["Open"]
            and curr["Open"] <= prev["Close"] * 1.01
            and curr["Close"] > candle_mid_body(prev)
            and curr["Close"] < prev["Open"]
        )
        signals.iloc[i] = is_signal
    return signals


def detect_dark_cloud_cover(data: pd.DataFrame) -> pd.Series:
    """烏雲罩頂：前長紅、後黑K跌回前紅實體中線以下，偏空頭反轉。"""
    signals = pd.Series(False, index=data.index)
    for i in range(1, len(data)):
        prev, curr = data.iloc[i - 1], data.iloc[i]
        prev_body = candle_body(prev)
        prev_range = candle_range(prev)
        is_signal = (
            prev["Close"] > prev["Open"]
            and prev_body >= prev_range * 0.45
            and curr["Close"] < curr["Open"]
            and curr["Open"] >= prev["Close"] * 0.99
            and curr["Close"] < candle_mid_body(prev)
            and curr["Close"] > prev["Open"]
        )
        signals.iloc[i] = is_signal
    return signals


def is_body_inside_previous(prev: pd.Series, curr: pd.Series) -> bool:
    prev_body_low = min(prev["Open"], prev["Close"])
    prev_body_high = max(prev["Open"], prev["Close"])
    curr_body_low = min(curr["Open"], curr["Close"])
    curr_body_high = max(curr["Open"], curr["Close"])
    return curr_body_low >= prev_body_low and curr_body_high <= prev_body_high

def detect_bullish_harami(data: pd.DataFrame) -> pd.Series:
    """多頭母子：前長黑、後小紅，且後一根實體落在前一根實體內"""
    signals = pd.Series(False, index=data.index)
    for i in range(1, len(data)):
        prev, curr = data.iloc[i - 1], data.iloc[i]
        prev_body = abs(prev["Close"] - prev["Open"])
        curr_body = abs(curr["Close"] - curr["Open"])
        prev_range = max(prev["High"] - prev["Low"], 0.001)
        is_signal = (
            prev["Close"] < prev["Open"]
            and curr["Close"] > curr["Open"]
            and prev_body >= prev_range * 0.45
            and curr_body <= prev_body * 0.55
            and is_body_inside_previous(prev, curr)
        )
        signals.iloc[i] = is_signal
    return signals

def detect_bullish_harami_cross(data: pd.DataFrame) -> pd.Series:
    """多頭母子十字：前長黑、後十字線，且十字實體落在前一根實體內"""
    signals = pd.Series(False, index=data.index)
    for i in range(1, len(data)):
        prev, curr = data.iloc[i - 1], data.iloc[i]
        prev_body = abs(prev["Close"] - prev["Open"])
        curr_body = abs(curr["Close"] - curr["Open"])
        curr_range = max(curr["High"] - curr["Low"], 0.001)
        prev_range = max(prev["High"] - prev["Low"], 0.001)
        is_doji = curr_body <= curr_range * 0.12 or curr_body <= prev_body * 0.12
        is_signal = (
            prev["Close"] < prev["Open"]
            and prev_body >= prev_range * 0.45
            and is_doji
            and is_body_inside_previous(prev, curr)
        )
        signals.iloc[i] = is_signal
    return signals

def detect_bearish_harami(data: pd.DataFrame) -> pd.Series:
    """空頭母子：前長紅、後小黑，且後一根實體落在前一根實體內"""
    signals = pd.Series(False, index=data.index)
    for i in range(1, len(data)):
        prev, curr = data.iloc[i - 1], data.iloc[i]
        prev_body = abs(prev["Close"] - prev["Open"])
        curr_body = abs(curr["Close"] - curr["Open"])
        prev_range = max(prev["High"] - prev["Low"], 0.001)
        is_signal = (
            prev["Close"] > prev["Open"]
            and curr["Close"] < curr["Open"]
            and prev_body >= prev_range * 0.45
            and curr_body <= prev_body * 0.55
            and is_body_inside_previous(prev, curr)
        )
        signals.iloc[i] = is_signal
    return signals

def detect_lower_shadow_candle(data: pd.DataFrame) -> pd.Series:
    """小實體、長下影線、上影線短的單根 K 線外型"""
    signals = pd.Series(False, index=data.index)
    for i in range(len(data)):
        curr = data.iloc[i]
        body = abs(curr["Close"] - curr["Open"])
        total_range = max(curr["High"] - curr["Low"], 0.001)
        upper_shadow = curr["High"] - max(curr["Open"], curr["Close"])
        lower_shadow = min(curr["Open"], curr["Close"]) - curr["Low"]

        is_lower_shadow_candle = (
            body <= total_range * 0.35
            and lower_shadow >= body * 2
            and upper_shadow <= total_range * 0.25
        )
        signals.iloc[i] = is_lower_shadow_candle
    return signals

def detect_hammer(data: pd.DataFrame) -> pd.Series:
    """槌子：短線下跌後出現小實體、長下影線，偏看漲反轉"""
    signals = detect_lower_shadow_candle(data)
    trend_filter = data["Close"] < data["Close"].rolling(5).mean()
    return signals & trend_filter.fillna(False)

def detect_hanging_man(data: pd.DataFrame) -> pd.Series:
    """吊人線：形態接近槌子，但通常出現在短線上漲後，偏看跌警訊"""
    signals = detect_lower_shadow_candle(data)
    trend_filter = data["Close"] > data["Close"].rolling(5).mean()
    return signals & trend_filter.fillna(False)

def detect_meteor(data: pd.DataFrame) -> pd.Series:
    """流星：小實體、長上影線、下影線短，偏看跌警訊"""
    return detect_shooting_star(data)


def detect_sandwich(data: pd.DataFrame) -> pd.Series:
    """三明治：黑紅黑，前後黑K收盤接近，低檔支撐被反覆測試。"""
    signals = pd.Series(False, index=data.index)
    for i in range(2, len(data)):
        first, second, third = data.iloc[i - 2], data.iloc[i - 1], data.iloc[i]
        similar_close = abs(first["Close"] - third["Close"]) <= max(first["Close"] * 0.015, 0.01)
        is_signal = (
            first["Close"] < first["Open"]
            and second["Close"] > second["Open"]
            and third["Close"] < third["Open"]
            and similar_close
            and third["Close"] >= min(first["Low"], second["Low"]) * 0.995
        )
        signals.iloc[i] = is_signal
    return signals


def detect_ladder_bottom(data: pd.DataFrame) -> pd.Series:
    """梯底：連續下跌後低檔出現紅K反攻，偏多頭反轉。"""
    signals = pd.Series(False, index=data.index)
    for i in range(4, len(data)):
        c1, c2, c3, c4, c5 = data.iloc[i - 4], data.iloc[i - 3], data.iloc[i - 2], data.iloc[i - 1], data.iloc[i]
        first_three_bearish = all(candle["Close"] < candle["Open"] for candle in (c1, c2, c3))
        closes_falling = c1["Close"] > c2["Close"] > c3["Close"]
        fourth_stabilizes = c4["Low"] <= c3["Low"] and c4["Close"] >= c3["Close"] * 0.98
        fifth_reversal = c5["Close"] > c5["Open"] and c5["Close"] > max(c3["Open"], c4["High"])
        signals.iloc[i] = first_three_bearish and closes_falling and fourth_stabilizes and fifth_reversal
    return signals


def detect_on_neck_line(data: pd.DataFrame) -> pd.Series:
    """頸上線：下跌後小反彈僅收回前一根低檔附近，偏空頭延續。"""
    signals = pd.Series(False, index=data.index)
    for i in range(1, len(data)):
        prev, curr = data.iloc[i - 1], data.iloc[i]
        prev_body = candle_body(prev)
        prev_range = candle_range(prev)
        close_near_prev_close = abs(curr["Close"] - prev["Close"]) <= max(prev["Close"] * 0.015, 0.01)
        is_signal = (
            prev["Close"] < prev["Open"]
            and prev_body >= prev_range * 0.45
            and curr["Close"] > curr["Open"]
            and curr["Open"] < prev["Close"]
            and close_near_prev_close
            and curr["Close"] < candle_mid_body(prev)
        )
        signals.iloc[i] = is_signal
    return signals

# -----------------------------
# 資料處理
# -----------------------------
def normalize_stock_lookup_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper())


@st.cache_data(ttl=86400, show_spinner=False)
def get_tw_stock_directory() -> list[dict]:
    rows = []
    sources = [
        ("TWSE", ".TW", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"),
        ("TPEX", ".TWO", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"),
    ]
    for market, suffix, url in sources:
        try:
            page = fetch_text(url)
        except Exception:
            continue

        table_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I)
        for row_html in table_rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S | re.I)
            if not cells:
                continue
            first_cell = strip_html(cells[0]).replace("\u3000", " ")
            match = re.match(r"^([0-9A-Z]{4,6})\s+(.+)$", first_cell)
            if not match:
                continue
            code, name = match.group(1).strip(), match.group(2).strip()
            if not code or not name or "有價證券" in name:
                continue
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "market": market,
                    "suffix": suffix,
                    "ticker": f"{code}{suffix}",
                    "code_key": normalize_stock_lookup_text(code),
                    "name_key": normalize_stock_lookup_text(name),
                }
            )
    return rows


def resolve_tw_stock(value: str) -> dict | None:
    query = normalize_stock_lookup_text(value)
    if not query:
        return None

    directory = get_tw_stock_directory()
    for item in directory:
        if query == item["code_key"]:
            return item
    for item in directory:
        if query == item["name_key"]:
            return item
    for item in directory:
        if item["name_key"].startswith(query):
            return item
    for item in directory:
        if query in item["name_key"]:
            return item
    return None


def resolve_stock_with_kgi(value: str) -> dict | None:
    try:
        matches = resolve_underlying_matches(value)
    except Exception:
        return None
    if not matches:
        return None

    text = str(matches[0].get("INSTR_STKID_NAME", "")).strip()
    match = re.match(r"^([0-9A-Z]{4,6})\s+(.+)$", text)
    if not match:
        return None

    code, name = match.group(1), match.group(2)
    listed_match = resolve_tw_stock(code)
    ticker = listed_match["ticker"] if listed_match else f"{code}.TW"
    return {"code": code, "name": name, "ticker": ticker}


def normalize_ticker(stock_id: str) -> str:
    raw = str(stock_id or "").strip()
    ticker = raw.upper()
    if not ticker:
        raise ValueError("請輸入股票代碼或名稱")
    if ticker.endswith(".TW") or ticker.endswith(".TWO"):
        return ticker

    resolved = resolve_tw_stock(raw)
    if resolved:
        return resolved["ticker"]

    fallback = COMMON_STOCK_FALLBACKS.get(normalize_stock_lookup_text(raw))
    if fallback:
        return fallback

    kgi_resolved = resolve_stock_with_kgi(raw)
    if kgi_resolved:
        return kgi_resolved["ticker"]

    if re.fullmatch(r"[0-9A-Z]{4,6}", ticker):
        return f"{ticker}.TW"
    raise ValueError(f"查無股票代碼或名稱：{raw}")

def is_pattern_selected(selected_patterns: list[str], pattern_name: str) -> bool:
    return PATTERN_SELECT_ALL in selected_patterns or pattern_name in selected_patterns


def selected_pattern_definitions(options: ChartOptions) -> list[dict]:
    selected = []
    for definition in PATTERN_DEFINITIONS:
        option_name = f"show_{definition['column'].lower().replace(' ', '_')}"
        if getattr(options, option_name, False):
            selected.append(definition)
    return selected


def build_pattern_summary_columns(data: pd.DataFrame, options: ChartOptions) -> pd.DataFrame:
    definitions = selected_pattern_definitions(options)
    summaries = []
    sides = []
    for _, row in data.iterrows():
        labels = [item["label"] for item in definitions if bool(row.get(item["column"], False))]
        side_set = {item["side"] for item in definitions if bool(row.get(item["column"], False))}
        summaries.append("、".join(labels) if labels else "無")
        if "bullish" in side_set:
            sides.append("bullish")
        elif "bearish" in side_set:
            sides.append("bearish")
        elif "neutral" in side_set:
            sides.append("neutral")
        else:
            sides.append("")
    result = data.copy()
    result["Pattern Summary"] = summaries
    result["Pattern Side"] = sides
    return result


def recent_pattern_signals(data: pd.DataFrame, options: ChartOptions, limit: int = 30) -> pd.DataFrame:
    definitions = selected_pattern_definitions(options)
    records = []
    side_labels = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}
    for date_value, row in data.iterrows():
        for item in definitions:
            if bool(row.get(item["column"], False)):
                records.append(
                    {
                        "日期": date_value.strftime("%Y-%m-%d") if hasattr(date_value, "strftime") else str(date_value),
                        "型態": item["label"],
                        "方向": side_labels.get(item["side"], ""),
                        "收盤": round(float(row["Close"]), 2),
                    }
                )
    if not records:
        return pd.DataFrame(columns=["日期", "型態", "方向", "收盤"])
    return pd.DataFrame(records).tail(limit).sort_values("日期", ascending=False).reset_index(drop=True)


def get_stock_code_and_market(ticker: str) -> tuple[str, str]:
    normalized = normalize_ticker(ticker)
    stock_code = normalized.split(".")[0]
    market = "TPEX" if normalized.endswith(".TWO") else "TWSE"
    return stock_code, market

def parse_int(value) -> int:
    if value is None or pd.isna(value):
        return 0
    cleaned = str(value).replace(",", "").replace("--", "0").strip()
    if cleaned in ("", "-"):
        return 0
    try:
        return int(float(cleaned))
    except ValueError:
        return 0

def format_roc_date(date_value: dt.date) -> str:
    return f"{date_value.year - 1911}/{date_value.month:02d}/{date_value.day:02d}"

def first_record_value(record: dict, names: list[str], fallback=0):
    for name in names:
        if name in record:
            return record[name]
    return fallback

def format_twse_date(date_code: str) -> str:
    digits = "".join(ch for ch in str(date_code) if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    if len(digits) == 7:
        year = int(digits[:3]) + 1911
        return f"{year}-{digits[3:5]}-{digits[5:]}"
    return str(date_code)

def fetch_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read()
    for encoding in ("utf-8-sig", "big5", "cp950"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")

def fetch_twse_institutional_trade(stock_code: str, trade_date: dt.date) -> dict | None:
    url = (
        "https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?date={trade_date.strftime('%Y%m%d')}&selectType=ALLBUT0999&response=json"
    )
    payload = fetch_json(url)
    columns = payload.get("fields") or payload.get("columns") or []
    rows = payload.get("data") or []
    for values in rows:
        row = dict(zip(columns, values))
        if str(row.get("證券代號", "")).strip() == stock_code:
            foreign = parse_int(
                first_record_value(
                    row,
                    [
                        "外陸資買賣超股數(不含外資自營商)",
                        "外資買賣超股數(不含外資自營商)",
                        "外陸資買賣超股數",
                        "外資買賣超股數",
                    ],
                )
            )
            investment = parse_int(first_record_value(row, ["投信買賣超股數"]))
            dealer = parse_int(first_record_value(row, ["自營商買賣超股數"]))
            total = parse_int(first_record_value(row, ["三大法人買賣超股數"], foreign + investment + dealer))
            return {
                "日期": format_twse_date(payload.get("date") or trade_date.strftime("%Y%m%d")),
                "外資買賣超": foreign,
                "投信買賣超": investment,
                "自營商買賣超": dealer,
                "三大法人合計": total,
            }
    return None

def parse_tpex_institutional_trade(row: dict) -> dict:
    foreign = parse_int(
        first_record_value(
            row,
            [
                "ForeignInvestorsInclude MainlandAreaInvestors-Difference",
                "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
                "ForeignInvestorsExcludingForeignDealers-Difference",
            ],
        )
    )
    investment = parse_int(first_record_value(row, ["SecuritiesInvestmentTrustCompanies-Difference"]))
    dealer = parse_int(first_record_value(row, ["Dealers-Difference"]))
    total = parse_int(first_record_value(row, ["TotalDifference"], foreign + investment + dealer))
    return {
        "日期": format_twse_date(str(row.get("Date", ""))),
        "外資買賣超": foreign,
        "投信買賣超": investment,
        "自營商買賣超": dealer,
        "三大法人合計": total,
    }

def fetch_tpex_institutional_trades(stock_code: str, trading_days: int = 10) -> pd.DataFrame:
    rows = fetch_json(f"{TPEX_OPENAPI_BASE}/tpex_3insti_daily_trading")
    if not isinstance(rows, list):
        return pd.DataFrame()

    records = [
        parse_tpex_institutional_trade(row)
        for row in rows
        if str(row.get("SecuritiesCompanyCode", "")).strip() == stock_code
    ]
    if not records:
        return pd.DataFrame()

    data = pd.DataFrame(records).sort_values("日期", ascending=False).head(trading_days)
    return data.reset_index(drop=True)

def fetch_tpex_institutional_trade(stock_code: str, trade_date: dt.date) -> dict | None:
    csv_url = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
        f"?l=zh-tw&o=csv&se=EW&t=D&d={format_roc_date(trade_date)}&s=0,asc"
    )
    csv_text = fetch_text(csv_url)
    lines = [
        row
        for row in csv.reader(io.StringIO(csv_text))
        if row and not row[0].startswith("=")
    ]
    if not lines:
        return None

    headers = lines[0]
    for values in lines[1:]:
        row = dict(zip(headers, values))
        if str(row.get("代號", row.get("證券代號", ""))).strip() != stock_code:
            continue

        foreign = parse_int(
            first_record_value(
                row,
                [
                    "外資及陸資(不含外資自營商)-買賣超股數",
                    "外資及陸資買賣超股數",
                    "外資買賣超股數",
                ],
            )
        )
        investment = parse_int(first_record_value(row, ["投信買賣超股數"]))
        dealer = parse_int(first_record_value(row, ["自營商買賣超股數"]))
        total = parse_int(first_record_value(row, ["三大法人買賣超股數"], foreign + investment + dealer))
        return {
            "日期": trade_date.strftime("%Y-%m-%d"),
            "外資買賣超": foreign,
            "投信買賣超": investment,
            "自營商買賣超": dealer,
            "三大法人合計": total,
        }
    return None

@st.cache_data(ttl=3600)
def get_institutional_trade_data(ticker: str, trading_days: int = 10) -> pd.DataFrame:
    stock_code, market = get_stock_code_and_market(ticker)
    if market == "TPEX":
        tpex_data = fetch_tpex_institutional_trades(stock_code, trading_days)
        if not tpex_data.empty:
            return tpex_data

    records = []
    today = dt.date.today()

    for day_offset in range(0, 45):
        if len(records) >= trading_days:
            break

        trade_date = today - dt.timedelta(days=day_offset)
        try:
            if market == "TPEX":
                record = fetch_tpex_institutional_trade(stock_code, trade_date)
            else:
                record = fetch_twse_institutional_trade(stock_code, trade_date)
        except Exception:
            continue

        if record:
            records.append(record)

    if not records:
        return pd.DataFrame()

    data = pd.DataFrame(records).sort_values("日期", ascending=False)
    return data.reset_index(drop=True)

def calculate_rsi(close: pd.Series, window: int = RSI_WINDOW) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))

@st.cache_data(ttl=3600)
def get_stock_data(options: ChartOptions) -> pd.DataFrame:
    end_date = dt.datetime.today()
    start_date = end_date - dt.timedelta(days=options.display_days + 220)
    
    data = yf.download(options.ticker, start=start_date, end=end_date + dt.timedelta(days=1), progress=False)
    if data.empty: raise ValueError(f"查無 {options.ticker}")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data = data.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()

    # 計算指標
    for d in MA_WINDOWS: data[f"MA{d}"] = data["Close"].rolling(d).mean()
    data["STD20"] = data["Close"].rolling(BOLLINGER_WINDOW).std()
    data["Upper Band"] = data["MA20"] + (BOLLINGER_STD * data["STD20"])
    data["Lower Band"] = data["MA20"] - (BOLLINGER_STD * data["STD20"])
    data["VolColor"] = ["red" if c >= o else "green" for c, o in zip(data["Close"], data["Open"])]

    low_min = data["Low"].rolling(KD_WINDOW).min()
    high_max = data["High"].rolling(KD_WINDOW).max()
    data["RSV"] = ((data["Close"] - low_min) / (high_max - low_min).replace(0, pd.NA)) * 100
    data["K"] = data["RSV"].ewm(alpha=1 / 3, adjust=False).mean()
    data["D"] = data["K"].ewm(alpha=1 / 3, adjust=False).mean()
    data["RSI"] = calculate_rsi(data["Close"])
    data["MACD"] = data["Close"].ewm(span=12, adjust=False).mean() - data["Close"].ewm(span=26, adjust=False).mean()
    data["MACD Signal"] = data["MACD"].ewm(span=9, adjust=False).mean()
    data["MACD Histogram"] = data["MACD"] - data["MACD Signal"]
    
    # 偵測形態
    data["Red Candle"] = detect_red_candle(data)
    data["Black Candle"] = detect_black_candle(data)
    data["Doji"] = detect_doji(data)
    data["Morning Star"] = detect_morning_star(data)
    data["Evening Star"] = detect_evening_star(data)
    data["Shooting Star"] = detect_shooting_star(data)
    data["Three White Soldiers"] = detect_three_white_soldiers(data)
    data["Three Black Crows"] = detect_three_black_crows(data)
    data["Bullish Engulfing"] = detect_bullish_engulfing(data)
    data["Piercing Line"] = detect_piercing_line(data)
    data["Hammer"] = detect_hammer(data)
    data["Hanging Man"] = detect_hanging_man(data)
    data["Meteor"] = detect_meteor(data)
    data["Bullish Harami"] = detect_bullish_harami(data)
    data["Bullish Harami Cross"] = detect_bullish_harami_cross(data)
    data["Sandwich"] = detect_sandwich(data)
    data["Ladder Bottom"] = detect_ladder_bottom(data)
    data["Bearish Harami"] = detect_bearish_harami(data)
    data["Bearish Engulfing"] = detect_bearish_engulfing(data)
    data["Dark Cloud Cover"] = detect_dark_cloud_cover(data)
    data["On Neck Line"] = detect_on_neck_line(data)

    return data.tail(options.display_days)

def get_non_trading_days(data: pd.DataFrame) -> list[str]:
    all_days = pd.date_range(start=data.index[0], end=data.index[-1])
    trading_days = {day.strftime("%Y-%m-%d") for day in data.index}
    return [
        day.strftime("%Y-%m-%d")
        for day in all_days
        if day.strftime("%Y-%m-%d") not in trading_days
    ]

def draw_institutional_trade_chart(data: pd.DataFrame):
    chart_data = data.sort_values("日期").copy()
    fig = go.Figure()
    colors = {
        "外資買賣超": "#2563eb",
        "投信買賣超": "#f97316",
        "自營商買賣超": "#7c3aed",
        "三大法人合計": "#111827",
    }

    for column, color in colors.items():
        fig.add_trace(
            go.Bar(
                x=chart_data["日期"],
                y=chart_data[column],
                name=column,
                marker_color=color,
            )
        )

    fig.add_hline(y=0, line_color="#6b7280", line_width=1)
    fig.update_layout(
        height=360,
        template="plotly_white",
        barmode="group",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=20, r=20, t=45, b=20),
    )
    fig.update_xaxes(title_text="日期")
    fig.update_yaxes(title_text="買賣超股數", tickformat=",")
    return fig

def draw_chart(data: pd.DataFrame, options: ChartOptions):
    data = build_pattern_summary_columns(data, options)
    extra_panels = []
    if options.show_kd:
        extra_panels.append("kd")
    if options.show_rsi:
        extra_panels.append("rsi")
    if options.show_macd:
        extra_panels.append("macd")

    rows = 2 + len(extra_panels)
    row_heights = [0.56, 0.18] + [0.16] * len(extra_panels)
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=row_heights,
    )

    hover_data = pd.DataFrame(
        {
            "Volume": data["Volume"].fillna(0).round(0),
            "MA5": data["MA5"].round(2),
            "MA20": data["MA20"].round(2),
            "MA60": data["MA60"].round(2),
            "MA120": data["MA120"].round(2),
            "Upper Band": data["Upper Band"].round(2),
            "Lower Band": data["Lower Band"].round(2),
            "K": data["K"].round(2),
            "D": data["D"].round(2),
            "RSI": data["RSI"].round(2),
            "MACD": data["MACD"].round(2),
            "MACD Signal": data["MACD Signal"].round(2),
            "Pattern Summary": data["Pattern Summary"],
        },
        index=data.index,
    )

    # K線
    fig.add_trace(go.Candlestick(
        x=data.index, open=data["Open"], high=data["High"], low=data["Low"], close=data["Close"],
        increasing_line_color="red",
        decreasing_line_color="green",
        name="K線",
        customdata=hover_data,
        hovertemplate=(
            "日期：%{x|%Y-%m-%d}<br>"
            "開：%{open:.2f}<br>"
            "高：%{high:.2f}<br>"
            "低：%{low:.2f}<br>"
            "收：%{close:.2f}<br>"
            "成交量：%{customdata[0]:,.0f}<br>"
            "MA5：%{customdata[1]}<br>"
            "MA20：%{customdata[2]}<br>"
            "MA60：%{customdata[3]}<br>"
            "MA120：%{customdata[4]}<br>"
            "布林上軌：%{customdata[5]}<br>"
            "布林下軌：%{customdata[6]}<br>"
            "K/D：%{customdata[7]} / %{customdata[8]}<br>"
            "RSI：%{customdata[9]}<br>"
            "MACD / Signal：%{customdata[10]} / %{customdata[11]}<br>"
            "K線型態：%{customdata[12]}<extra></extra>"
        ),
    ), row=1, col=1)

    # 均線與布林
    ma_colors = {5: "purple", 20: "blue", 60: "teal", 120: "brown"}
    for ma_days in options.selected_mas:
        ma = f"MA{ma_days}"
        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=data[ma],
                name=f"{ma_days}日均線",
                line=dict(color=ma_colors[ma_days], width=1.2),
            ),
            row=1,
            col=1,
        )
    
    if options.show_bollinger:
        fig.add_trace(go.Scatter(x=data.index, y=data["Upper Band"], name="布林上軌", line=dict(color="orange", dash="dash")), row=1, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data["Lower Band"], name="布林下軌", line=dict(color="orange", dash="dash")), row=1, col=1)

    # 成交量
    fig.add_trace(go.Bar(x=data.index, y=data["Volume"], marker_color=data["VolColor"], name="成交量"), row=2, col=1)

    current_row = 3
    if options.show_kd:
        fig.add_trace(go.Scatter(x=data.index, y=data["K"], name="K值", line=dict(color="#2563eb", width=1.2)), row=current_row, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data["D"], name="D值", line=dict(color="#f97316", width=1.2)), row=current_row, col=1)
        fig.add_hline(y=80, line_dash="dot", line_color="gray", row=current_row, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="gray", row=current_row, col=1)
        fig.update_yaxes(title_text="KD", range=[0, 100], row=current_row, col=1)
        current_row += 1

    if options.show_rsi:
        fig.add_trace(go.Scatter(x=data.index, y=data["RSI"], name="RSI", line=dict(color="#7c3aed", width=1.2)), row=current_row, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="gray", row=current_row, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="gray", row=current_row, col=1)
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=current_row, col=1)
        current_row += 1

    if options.show_macd:
        macd_colors = ["red" if value >= 0 else "green" for value in data["MACD Histogram"]]
        fig.add_trace(go.Bar(x=data.index, y=data["MACD Histogram"], marker_color=macd_colors, name="MACD柱狀圖"), row=current_row, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data["MACD"], name="MACD", line=dict(color="#2563eb", width=1.2)), row=current_row, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=data["MACD Signal"], name="Signal", line=dict(color="#f97316", width=1.2)), row=current_row, col=1)
        fig.update_yaxes(title_text="MACD", row=current_row, col=1)

    fig.update_layout(
        height=820 + len(extra_panels) * 150,
        template="plotly_white",
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=20, r=20, t=70, b=60),
    )
    fig.update_yaxes(title_text="價格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)
    fig.update_xaxes(rangebreaks=[dict(values=get_non_trading_days(data))])
    return fig

# -----------------------------
# ChatGPT 分析
# -----------------------------
def clean_key(value: str | None) -> str:
    if value is None:
        return ""

    return value.strip().strip(ENV_QUOTES).strip()

def get_secret_value(name: str) -> str:
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""

def get_openai_api_key() -> str:
    return (
        clean_key(os.getenv("OPENAI_API_KEY"))
        or clean_key(get_secret_value("OPENAI_API_KEY"))
    )

def get_gemini_api_key() -> str:
    return (
        clean_key(os.getenv("GEMINI_API_KEY"))
        or clean_key(get_secret_value("GEMINI_API_KEY"))
    )

def find_non_ascii_chars(value: str) -> str:
    chars = []
    for char in value:
        if ord(char) > 127 and char not in chars:
            chars.append(char)

    return "".join(chars)

def build_analysis_prompt(data: pd.DataFrame, options: ChartOptions) -> str:
    latest = data.iloc[-1]
    previous = data.iloc[-2] if len(data) >= 2 else latest
    change = latest["Close"] - previous["Close"]
    change_percent = (change / previous["Close"]) * 100 if previous["Close"] else 0

    analysis_data = data[
        [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "MA5",
            "MA20",
            "MA60",
            "MA120",
            "Upper Band",
            "Lower Band",
            "K",
            "D",
            "RSI",
            "MACD",
            "MACD Signal",
            "MACD Histogram",
        ]
    ].tail(min(options.display_days, 60))
    analysis_data = analysis_data.round(2)
    analysis_data.index = analysis_data.index.strftime("%Y-%m-%d")

    return f"""
請用繁體中文分析這支台股的 K 線圖、成交量與布林通道，但不要保證漲跌，也不要直接給絕對買賣建議。

股票代碼：{options.ticker}
分析期間：近 {options.display_days} 個交易日
最新收盤價：{latest["Close"]:.2f}
最新漲跌：{change:.2f}，{change_percent:.2f}%
最新成交量：{int(latest["Volume"])}
最新 5 日均線：{latest["MA5"]:.2f}
最新 20 日均線：{latest["MA20"]:.2f}
最新 60 日均線：{latest["MA60"]:.2f}
最新 120 日均線：{latest["MA120"]:.2f}
最新布林上軌：{latest["Upper Band"]:.2f}
最新布林下軌：{latest["Lower Band"]:.2f}
最新 K 值：{latest["K"]:.2f}
最新 D 值：{latest["D"]:.2f}
最新 RSI：{latest["RSI"]:.2f}
最新 MACD：{latest["MACD"]:.2f}
最新 MACD Signal：{latest["MACD Signal"]:.2f}

請說明：
1. K 線目前偏多、偏空或盤整
2. 價格在布林通道的位置代表什麼
3. 成交量是否支持目前走勢
4. 5/20/60/120 日均線排列透露的趨勢
5. KD、RSI、MACD 是否支持或背離目前趨勢
6. 可能的支撐與壓力區
7. 後續 3 到 5 個交易日可以觀察的重點
8. 風險提醒

以下是圖表使用的原始資料：
{analysis_data.to_csv()}
""".strip()

def extract_openai_text(result: dict) -> str:
    if result.get("output_text"):
        return result["output_text"]

    texts = []
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                texts.append(content.get("text", ""))
    return "\n".join(texts).strip()

def extract_gemini_text(result: dict) -> str:
    texts = []
    for candidate in result.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if part.get("text"):
                texts.append(part["text"])

    return "\n".join(texts).strip()

def parse_error_message(message: str, provider: str) -> str:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return message

    error = payload.get("error", {})
    code = error.get("code", "")
    detail = error.get("message", message)
    if provider == "ChatGPT" and code == "insufficient_quota":
        return "OpenAI API 額度不足或 billing 未啟用。請檢查 OpenAI 帳號額度，或切換到 Gemini 分析。"

    return detail

def analyze_with_chatgpt(data: pd.DataFrame, options: ChartOptions) -> str:
    api_key = get_openai_api_key()
    model = clean_key(os.getenv("OPENAI_MODEL")) or clean_key(get_secret_value("OPENAI_MODEL")) or DEFAULT_OPENAI_MODEL
    if not api_key:
        return "尚未設定 OPENAI_API_KEY。請用環境變數或 Streamlit secrets 設定 OPENAI_API_KEY。"

    if "你的" in api_key or "OpenAI API key" in api_key:
        return "OPENAI_API_KEY 目前看起來還是範例文字，請設定真正的 OpenAI API key。"

    non_ascii_chars = find_non_ascii_chars(api_key)
    if non_ascii_chars:
        return f"OPENAI_API_KEY 內含不應出現在 API key 裡的字元：{non_ascii_chars}"

    payload = {
        "model": model,
        "instructions": "你是謹慎的台股技術分析助理，只能根據使用者提供的資料分析，不提供保證獲利承諾。",
        "input": build_analysis_prompt(data, options),
        "temperature": 0.3,
    }
    request = urllib.request.Request(
        OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        return f"OpenAI API 回傳錯誤：HTTP {error.code}\n{parse_error_message(message, 'ChatGPT')}"
    except urllib.error.URLError as error:
        return f"連線 OpenAI API 失敗：{error.reason}"

    analysis = extract_openai_text(result)
    if not analysis:
        return f"OpenAI API 已回應，但沒有解析到文字內容：\n{json.dumps(result, ensure_ascii=False, indent=2)}"

    return analysis

def analyze_with_gemini(data: pd.DataFrame, options: ChartOptions) -> str:
    api_key = get_gemini_api_key()
    model = clean_key(os.getenv("GEMINI_MODEL")) or clean_key(get_secret_value("GEMINI_MODEL")) or DEFAULT_GEMINI_MODEL
    if not api_key:
        return "尚未設定 GEMINI_API_KEY。請用環境變數或 Streamlit secrets 設定 GEMINI_API_KEY。"

    if "你的" in api_key or "Gemini API key" in api_key:
        return "GEMINI_API_KEY 目前看起來還是範例文字，請設定真正的 Gemini API key。"

    non_ascii_chars = find_non_ascii_chars(api_key)
    if non_ascii_chars:
        return f"GEMINI_API_KEY 內含不應出現在 API key 裡的字元：{non_ascii_chars}"

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": "你是謹慎的台股技術分析助理，只能根據使用者提供的資料分析，不提供保證獲利承諾。"
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": build_analysis_prompt(data, options)}],
            }
        ],
        "generationConfig": {"temperature": 0.3},
    }
    request = urllib.request.Request(
        GEMINI_API_URL_TEMPLATE.format(model=model),
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        return f"Gemini API 回傳錯誤：HTTP {error.code}\n{parse_error_message(message, 'Gemini')}"
    except urllib.error.URLError as error:
        return f"連線 Gemini API 失敗：{error.reason}"

    analysis = extract_gemini_text(result)
    if not analysis:
        return f"Gemini API 已回應，但沒有解析到文字內容：\n{json.dumps(result, ensure_ascii=False, indent=2)}"

    return analysis

def analyze_with_provider(provider: str, data: pd.DataFrame, options: ChartOptions) -> str:
    if provider == "Gemini":
        return analyze_with_gemini(data, options)

    return analyze_with_chatgpt(data, options)

# -----------------------------
# 權證工具
# -----------------------------
@st.cache_data(show_spinner=False)
def kgi_service(service_id: str, parameters: dict, location_path: str = KGI_LOCATION_PATH) -> object:
    payload = {
        "serviceId": service_id,
        "parametersOfJson": json.dumps(
            {**parameters, "LocationPathName": location_path},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    request = urllib.request.Request(
        KGI_SERVICE_URL,
        data=urllib.parse.urlencode(payload).encode(),
        headers={"User-Agent": KGI_USER_AGENT},
    )
    context = ssl._create_unverified_context()
    raw = urllib.request.urlopen(request, timeout=20, context=context).read().decode("utf-8", "ignore")
    root = ET.fromstring(raw)
    result = root.findtext("t:Result", namespaces=KGI_NS)
    if result != "true":
        message = root.findtext("t:Message", namespaces=KGI_NS) or "Unknown service error"
        raise RuntimeError(f"{service_id} failed: {message}")
    value = root.findtext("t:ValueOfJson", namespaces=KGI_NS) or ""
    return json.loads(value) if value else ""


@st.cache_data(show_spinner=False)
def get_warrant_list() -> list[dict]:
    return kgi_service("S0600013_GetWarrantList", {})


@st.cache_data(show_spinner=False)
def get_underlying_list() -> list[dict]:
    return kgi_service("S0600017_GetUnderlyingList", {}, location_path=KGI_SEARCH_LOCATION_PATH)


def resolve_matches(query: str) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    warrants = get_warrant_list()
    exact_code = [item for item in warrants if str(item.get("TEXT", "")).split(" ", 1)[0].lower() == q]
    if exact_code:
        return exact_code[:20]
    exact_prefix = [item for item in warrants if str(item.get("TEXT", "")).lower().startswith(q)]
    if exact_prefix:
        return exact_prefix[:20]
    contains = [item for item in warrants if q in str(item.get("TEXT", "")).lower()]
    return contains[:20]


def resolve_underlying_matches(query: str) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    underlyings = get_underlying_list()
    exact_code = [item for item in underlyings if str(item.get("INSTR_STKID_NAME", "")).split(" ", 1)[0].lower() == q]
    if exact_code:
        return exact_code[:20]
    exact_prefix = [item for item in underlyings if str(item.get("INSTR_STKID_NAME", "")).lower().startswith(q)]
    if exact_prefix:
        return exact_prefix[:20]
    contains = [item for item in underlyings if q in str(item.get("INSTR_STKID_NAME", "")).lower()]
    return contains[:20]


def load_warrant_payload(insnbr: int) -> tuple[dict, dict]:
    warrant = kgi_service("S0600013_GetWarrant", {"INSTR_INSNBR": insnbr})[0]
    underlying = kgi_service("S0600017_GetUnderlyingByWarrant", {"INSTR_INSNBR": insnbr})[0]
    return warrant, underlying


def default_underlying_target(warrant: dict, underlying: dict) -> float:
    stock_type = warrant.get("INSWRT_STOCKTYPE")
    cp = warrant.get("INSWRT_CP")
    if stock_type == "DI":
        return max(safe_float(underlying.get("DEAL")), 1.0)
    if cp == "認購":
        return max(safe_float(underlying.get("BID1")), safe_float(underlying.get("DEAL")), 1.0)
    return max(safe_float(underlying.get("ASK1")), safe_float(underlying.get("DEAL")), 1.0)


def theoretical_price(insnbr: int, process_date: int, vol: float, underlying_price: float) -> float:
    return float(
        kgi_service(
            "S0600018_GetTheoreticalPrice",
            {
                "INSTR_INSNBR": insnbr,
                "PROCESS_DATE": process_date,
                "VOL": vol,
                "UNDERLYING_PRICE": underlying_price,
            },
        )
    )


def sensitivity_analysis(insnbr: int, process_date: int, vol: float, underlying_price: float) -> dict:
    return kgi_service(
        "S0600018_SensitivityAnalysis",
        {
            "INSTR_INSNBR": insnbr,
            "PROCESS_DATE": process_date,
            "VOL": vol,
            "UNDERLYING_PRICE": underlying_price,
        },
    )


def fetch_underlying_warrants(
    underlying_insnbr: int,
    cp: str = "認購",
    last_days_from: int = 360,
    execrate_min: float = 0.005,
    leverage_min: float = 0.0,
    volume_min: float = 0.0,
) -> list[dict]:
    params = {
        "NORMAL_OR_CATTLE_BEAR": 0,
        "INSWRT_ISSUER_NAME": "ALL",
        "STRIKE_FROM": -1,
        "STRIKE_TO": -1,
        "VOLUME": -1,
        "UND_INSTR_INSNBR": underlying_insnbr,
        "LAST_DAYS_FROM": last_days_from,
        "LAST_DAYS_TO": -1,
        "IMP_VOL": -1,
        "CP": cp,
        "IN_OUT_PERCENT_FROM": -1,
        "IN_OUT_PERCENT_TO": -1,
        "BID_ASK_SPREAD_PERCENT": -1,
        "LEVERAGE": -1,
        "EXECRATE": -1,
        "OUTSTANDING_PERCENT": -1,
        "BARRIER_DEAL_PERCENT": -1,
    }
    rows = kgi_service("S0600013_GetWarrants", params, location_path=KGI_SEARCH_LOCATION_PATH)
    return [
        row
        for row in rows
        if safe_float(row.get("INSWRT_EXECRATE")) >= execrate_min
        and safe_float(row.get("LEVERAGE")) >= leverage_min
        and safe_float(row.get("VOLUME")) >= volume_min
    ]


def to_process_date(value: dt.date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def format_compact_date(value: object) -> str:
    raw = str(int(safe_float(value))) if safe_float(value) else ""
    if len(raw) == 8:
        return f"{raw[:4]}/{raw[4:6]}/{raw[6:]}"
    return raw


def normalize_etf_code(value: str) -> str:
    return (value or "").strip().upper()


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_numeric_text(value: object, default: float = 0.0) -> float:
    text = str(value or "").replace(",", "").replace("%", "").replace("+", "").strip()
    if text in ("", "-", "--", "N/A"):
        return default
    try:
        return float(text)
    except ValueError:
        return default


def parse_int_text(value: object, default: int = 0) -> int:
    return int(round(parse_numeric_text(value, float(default))))


def exception_message(exc: Exception) -> str:
    text = str(exc).strip()
    return text or repr(exc) or exc.__class__.__name__


def get_secret_section(name: str) -> dict:
    try:
        section = st.secrets.get(name, {})
    except (FileNotFoundError, KeyError, AttributeError):
        return {}
    return dict(section) if hasattr(section, "items") else {}


def active_etf_google_sheet_id() -> str:
    return str(get_secret_section("active_etf").get("spreadsheet_id", "")).strip()


def active_etf_uses_google_sheets() -> bool:
    return bool(active_etf_google_sheet_id() and get_secret_section("gcp_service_account") and gspread and Credentials)


def active_etf_storage_label() -> str:
    if active_etf_uses_google_sheets():
        return "Google Sheets"
    if active_etf_google_sheet_id() and not get_secret_section("gcp_service_account"):
        return "本機 JSON（尚未讀到 gcp_service_account）"
    if active_etf_google_sheet_id() and (not gspread or not Credentials):
        return "本機 JSON（尚未安裝 gspread/google-auth）"
    return "本機 JSON"


def active_etf_storage_diagnostics() -> list[str]:
    diagnostics = []
    service_account_info = get_secret_section("gcp_service_account")
    if not active_etf_google_sheet_id():
        diagnostics.append("尚未讀到 st.secrets['active_etf']['spreadsheet_id']")
    if not service_account_info:
        diagnostics.append("尚未讀到 st.secrets['gcp_service_account']")
    elif service_account_info.get("client_email"):
        diagnostics.append(f"請確認 Google Sheet 已分享給：{service_account_info.get('client_email')}，權限需為編輯者")
    if not gspread:
        diagnostics.append("尚未安裝 gspread")
    if not Credentials:
        diagnostics.append("尚未安裝 google-auth")
    if not diagnostics:
        diagnostics.append("Google Sheets 設定已讀取，若仍寫入失敗，請檢查 Sheet 是否已分享給 service account 並給編輯權限。")
    if not active_etf_uses_google_sheets():
        diagnostics.append(f"本機 JSON 主要路徑：{ACTIVE_ETF_STATE_PATH}")
        diagnostics.append(f"本機 JSON 備援路徑：{ACTIVE_ETF_FALLBACK_STATE_PATH}")
    return diagnostics


def local_active_etf_state_paths() -> list[Path]:
    return [ACTIVE_ETF_STATE_PATH, ACTIVE_ETF_FALLBACK_STATE_PATH]


@st.cache_resource(show_spinner=False)
def get_active_etf_spreadsheet(spreadsheet_id: str):
    if not gspread or not Credentials:
        raise RuntimeError("缺少 gspread 或 google-auth 套件，無法使用 Google Sheets 儲存。")
    service_account_info = get_secret_section("gcp_service_account")
    if not service_account_info:
        raise RuntimeError("尚未設定 st.secrets['gcp_service_account']。")
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    client = gspread.authorize(credentials)
    return client.open_by_key(spreadsheet_id)


@st.cache_resource(show_spinner=False)
def get_active_etf_worksheets(spreadsheet_id: str):
    spreadsheet = get_active_etf_spreadsheet(spreadsheet_id)
    return {
        ACTIVE_ETF_WATCHLIST_SHEET: get_or_create_worksheet(spreadsheet, ACTIVE_ETF_WATCHLIST_SHEET, rows=200, cols=2),
        ACTIVE_ETF_SNAPSHOTS_SHEET: get_or_create_worksheet(spreadsheet, ACTIVE_ETF_SNAPSHOTS_SHEET, rows=5000, cols=12),
        ACTIVE_ETF_META_SHEET: get_or_create_worksheet(spreadsheet, ACTIVE_ETF_META_SHEET, rows=200, cols=5),
    }


def get_or_create_worksheet(spreadsheet, title: str, rows: int = 1000, cols: int = 20):
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def worksheet_records(worksheet) -> list[dict]:
    rows = worksheet.get_all_records()
    return rows if isinstance(rows, list) else []


@st.cache_data(ttl=60, show_spinner=False)
def load_active_etf_state_from_google_sheets_cached(spreadsheet_id: str) -> dict:
    return load_active_etf_state_from_google_sheets_uncached(spreadsheet_id)


def load_active_etf_state_from_google_sheets() -> dict:
    return load_active_etf_state_from_google_sheets_cached(active_etf_google_sheet_id())


def load_active_etf_state_from_google_sheets_uncached(spreadsheet_id: str) -> dict:
    worksheets = get_active_etf_worksheets(spreadsheet_id)
    watchlist_sheet = worksheets[ACTIVE_ETF_WATCHLIST_SHEET]
    snapshot_sheet = worksheets[ACTIVE_ETF_SNAPSHOTS_SHEET]

    watchlist_rows = worksheet_records(watchlist_sheet)
    if watchlist_rows:
        watchlist = [
            normalize_etf_code(row.get("etf_code"))
            for row in watchlist_rows
            if normalize_etf_code(row.get("etf_code"))
        ]
    else:
        raw_values = watchlist_sheet.get_all_values()
        watchlist = [
            normalize_etf_code(row[0])
            for row in raw_values[1:]
            if row and normalize_etf_code(row[0])
        ]

    history: dict[str, list[dict]] = {}
    for row in worksheet_records(snapshot_sheet):
        etf_code = normalize_etf_code(row.get("etf_code"))
        snapshot_date = str(row.get("snapshot_date", "")).strip()
        if not etf_code or not snapshot_date:
            continue

        snapshots = history.setdefault(etf_code, [])
        snapshot = next((item for item in snapshots if item.get("date") == snapshot_date), None)
        if snapshot is None:
            snapshot = {
                "code": etf_code,
                "name": str(row.get("etf_name", "")).strip() or etf_code,
                "date": snapshot_date,
                "holdings": [],
            }
            snapshots.append(snapshot)

        snapshot["holdings"].append(
            {
                "stock_code": str(row.get("stock_code", "")).strip(),
                "stock_name": str(row.get("stock_name", "")).strip(),
                "change_percent": parse_numeric_text(row.get("change_percent")),
                "close_price": parse_numeric_text(row.get("close_price")),
                "weight_percent": parse_numeric_text(row.get("weight_percent")),
                "shares": parse_int_text(row.get("shares")),
                "contribution_percent": parse_numeric_text(row.get("contribution_percent")),
            }
        )

    for snapshots in history.values():
        snapshots.sort(key=lambda item: item.get("date", ""))

    return {"watchlist": sorted(set(watchlist)), "history": history}


def save_active_etf_state_to_google_sheets(state: dict) -> tuple[bool, str]:
    try:
        worksheets = get_active_etf_worksheets(active_etf_google_sheet_id())
        watchlist_sheet = worksheets[ACTIVE_ETF_WATCHLIST_SHEET]
        snapshot_sheet = worksheets[ACTIVE_ETF_SNAPSHOTS_SHEET]
        meta_sheet = worksheets[ACTIVE_ETF_META_SHEET]

        watchlist_values = [["etf_code", "updated_at"]]
        updated_at = dt.datetime.now().isoformat(timespec="seconds")
        for code in sorted(set(state.get("watchlist", []))):
            watchlist_values.append([code, updated_at])
        watchlist_sheet.clear()
        watchlist_sheet.update(values=watchlist_values, range_name="A1")

        snapshot_values = [ACTIVE_ETF_SNAPSHOT_COLUMNS]
        meta_values = [["etf_code", "etf_name", "latest_snapshot_date", "snapshot_count", "holding_count"]]
        for etf_code, snapshots in sorted(state.get("history", {}).items()):
            clean_snapshots = sorted(snapshots, key=lambda item: item.get("date", ""))[-30:]
            for snapshot in clean_snapshots:
                for holding in snapshot.get("holdings", []):
                    snapshot_values.append(
                        [
                            snapshot.get("code", etf_code),
                            snapshot.get("name", ""),
                            snapshot.get("date", ""),
                            holding.get("stock_code", ""),
                            holding.get("stock_name", ""),
                            holding.get("change_percent", 0.0),
                            holding.get("close_price", 0.0),
                            holding.get("weight_percent", 0.0),
                            holding.get("shares", 0),
                            holding.get("contribution_percent", 0.0),
                        ]
                    )
            if clean_snapshots:
                latest = clean_snapshots[-1]
                meta_values.append(
                    [
                        etf_code,
                        latest.get("name", ""),
                        latest.get("date", ""),
                        len(clean_snapshots),
                        len(latest.get("holdings", [])),
                    ]
                )

        snapshot_sheet.clear()
        snapshot_sheet.update(values=snapshot_values, range_name="A1")
        meta_sheet.clear()
        meta_sheet.update(values=meta_values, range_name="A1")
        load_active_etf_state_from_google_sheets_cached.clear()
        return True, ""
    except PermissionError as exc:
        return False, (
            f"PermissionError: {exception_message(exc)}。"
            "請確認 Google Sheet 已分享給 service account 的 client_email，且權限為編輯者。"
        )
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exception_message(exc)}"


def load_active_etf_state() -> dict:
    default_state = {"watchlist": [], "history": {}}
    if active_etf_uses_google_sheets():
        try:
            return load_active_etf_state_from_google_sheets()
        except Exception:
            return default_state

    data = None
    for path in local_active_etf_state_paths():
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            break
        except (OSError, json.JSONDecodeError):
            continue
    if data is None:
        return default_state

    watchlist = [normalize_etf_code(code) for code in data.get("watchlist", []) if normalize_etf_code(code)]
    history = data.get("history", {})
    if not isinstance(history, dict):
        history = {}
    return {"watchlist": watchlist, "history": history}


def save_active_etf_state(state: dict) -> tuple[bool, str]:
    if active_etf_uses_google_sheets():
        return save_active_etf_state_to_google_sheets(state)

    errors = []
    for path in local_active_etf_state_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as file:
                json.dump(state, file, ensure_ascii=False, indent=2)
            return True, ""
        except OSError as exc:
            errors.append(f"{path}: {exc.__class__.__name__}: {exception_message(exc)}")

    return False, "；".join(errors)


def fetch_etfinfo_html(etf_code: str) -> str:
    url = ETFINFO_HOLDINGS_URL.format(code=urllib.parse.quote(normalize_etf_code(etf_code)))
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": KGI_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=20, context=context) as response:
        return response.read().decode("utf-8", errors="ignore")


def parse_etf_holdings_html(etf_code: str, page_html: str) -> dict:
    code = normalize_etf_code(etf_code)
    title_match = re.search(r"<title>(.*?)</title>", page_html, re.S)
    title_text = strip_html(title_match.group(1)) if title_match else ""
    name_match = re.search(rf"{re.escape(code)}\s+(.+?)\s+成分股", title_text)
    etf_name = name_match.group(1).strip() if name_match else code

    date_match = re.search(r"快照\s*(\d{4}-\d{2}-\d{2})", page_html)
    if not date_match:
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", title_text)
    snapshot_date = date_match.group(1) if date_match else dt.date.today().isoformat()

    holdings = []
    rows = re.findall(r'<tr[^>]*class="[^"]*\bholding-row\b[^"]*"[^>]*>(.*?)</tr>', page_html, re.S)
    for row_html in rows:
        stock_code_match = re.search(r'class="stock-code-link"[^>]*>(.*?)</a>', row_html, re.S)
        stock_name_match = re.search(r'class="stock-name-sub"[^>]*>(.*?)</span>', row_html, re.S)
        if not stock_code_match:
            continue

        cells = re.findall(r"<td([^>]*)>(.*?)</td>", row_html, re.S)
        desktop_values = []
        contribution = 0.0
        for attrs, inner in cells:
            class_match = re.search(r'class="([^"]*)"', attrs)
            class_text = class_match.group(1) if class_match else ""
            clean_value = strip_html(inner)
            if "hide-mobile" in class_text and "hide-desktop" not in class_text:
                desktop_values.append(clean_value)
            elif "cell-number" in class_text and "hide-mobile" not in class_text and "hide-desktop" not in class_text:
                contribution = parse_numeric_text(clean_value)

        change_pct = parse_numeric_text(desktop_values[0]) if len(desktop_values) > 0 else 0.0
        close_price = parse_numeric_text(desktop_values[1]) if len(desktop_values) > 1 else 0.0
        weight_pct = parse_numeric_text(desktop_values[2]) if len(desktop_values) > 2 else 0.0
        shares = parse_int_text(desktop_values[3]) if len(desktop_values) > 3 else 0

        holdings.append(
            {
                "stock_code": strip_html(stock_code_match.group(1)),
                "stock_name": strip_html(stock_name_match.group(1)) if stock_name_match else "",
                "change_percent": change_pct,
                "close_price": close_price,
                "weight_percent": weight_pct,
                "shares": shares,
                "contribution_percent": contribution,
            }
        )

    if not holdings:
        raise ValueError("抓到頁面但解析不到持股表格，可能是資料來源版型已變更。")

    return {"code": code, "name": etf_name, "date": snapshot_date, "holdings": holdings}


def fetch_etf_holdings_snapshot(etf_code: str) -> dict:
    page_html = fetch_etfinfo_html(etf_code)
    return parse_etf_holdings_html(etf_code, page_html)


def upsert_etf_snapshot(state: dict, snapshot: dict) -> None:
    code = snapshot["code"]
    history = state.setdefault("history", {}).setdefault(code, [])
    history = [item for item in history if item.get("date") != snapshot.get("date")]
    history.append(snapshot)
    history.sort(key=lambda item: item.get("date", ""))
    state["history"][code] = history[-30:]


def previous_etf_snapshot(state: dict, etf_code: str, current_date: str) -> dict | None:
    history = state.get("history", {}).get(normalize_etf_code(etf_code), [])
    previous_items = [item for item in history if item.get("date", "") < current_date]
    if previous_items:
        return sorted(previous_items, key=lambda item: item.get("date", ""))[-1]
    return None


def build_etf_change_rows(current_snapshot: dict, previous_snapshot: dict | None) -> list[dict]:
    current_map = {item["stock_code"]: item for item in current_snapshot.get("holdings", [])}
    previous_map = {
        item["stock_code"]: item
        for item in (previous_snapshot or {}).get("holdings", [])
    }
    rows = []

    for stock_code, current in current_map.items():
        previous = previous_map.get(stock_code, {})
        current_shares = int(current.get("shares", 0))
        previous_shares = int(previous.get("shares", 0))
        delta = current_shares - previous_shares
        if not previous:
            action = "新增"
        elif delta > 0:
            action = "加碼"
        elif delta < 0:
            action = "減碼"
        else:
            action = "持平"

        rows.append(
            {
                "ETF": f"{current_snapshot['code']} {current_snapshot.get('name', '')}",
                "快照日": current_snapshot.get("date", ""),
                "動作": action,
                "股票代號": stock_code,
                "名稱": current.get("stock_name", ""),
                "股數變化": delta,
                "目前股數": current_shares,
                "前次股數": previous_shares,
                "權重%": round(float(current.get("weight_percent", 0.0)), 2),
                "收盤價": round(float(current.get("close_price", 0.0)), 2),
                "漲跌幅%": round(float(current.get("change_percent", 0.0)), 2),
            }
        )

    for stock_code, previous in previous_map.items():
        if stock_code in current_map:
            continue
        previous_shares = int(previous.get("shares", 0))
        rows.append(
            {
                "ETF": f"{current_snapshot['code']} {current_snapshot.get('name', '')}",
                "快照日": current_snapshot.get("date", ""),
                "動作": "刪除",
                "股票代號": stock_code,
                "名稱": previous.get("stock_name", ""),
                "股數變化": -previous_shares,
                "目前股數": 0,
                "前次股數": previous_shares,
                "權重%": 0.0,
                "收盤價": round(float(previous.get("close_price", 0.0)), 2),
                "漲跌幅%": round(float(previous.get("change_percent", 0.0)), 2),
            }
        )

    action_order = {"新增": 0, "加碼": 1, "減碼": 2, "刪除": 3, "持平": 4}
    return sorted(rows, key=lambda item: (action_order.get(item["動作"], 9), -abs(item["股數變化"])))


def etf_holdings_dataframe(snapshot: dict) -> pd.DataFrame:
    rows = []
    for item in snapshot.get("holdings", []):
        rows.append(
            {
                "股票代號": item.get("stock_code", ""),
                "名稱": item.get("stock_name", ""),
                "持股張數": round(parse_numeric_text(item.get("shares")) / 1000, 2),
                "持股股數": int(item.get("shares", 0)),
                "權重%": round(float(item.get("weight_percent", 0.0)), 2),
                "收盤價": round(float(item.get("close_price", 0.0)), 2),
                "漲跌幅%": round(float(item.get("change_percent", 0.0)), 2),
            }
        )
    return pd.DataFrame(rows)


def init_home_state() -> None:
    st.session_state.setdefault("app_section", "home")
    st.session_state.setdefault("query_text", "")
    st.session_state.setdefault("match_options", [])
    st.session_state.setdefault("loaded_warrant", None)
    st.session_state.setdefault("loaded_underlying", None)
    st.session_state.setdefault("calc_underlying_price", None)
    st.session_state.setdefault("calc_biv", None)
    st.session_state.setdefault("calc_date", None)
    st.session_state.setdefault("recommend_query_text", "")
    st.session_state.setdefault("recommend_matches", [])
    st.session_state.setdefault("recommend_underlying", None)
    st.session_state.setdefault("recommend_rows", None)
    st.session_state.setdefault("recommend_style", "偏均衡")
    st.session_state.setdefault("recommend_custom_days", 360)
    st.session_state.setdefault("recommend_custom_execrate", 0.005)
    st.session_state.setdefault("recommend_custom_leverage", 2.0)
    st.session_state.setdefault("recommend_custom_volume", 100.0)
    if "active_etf_state" not in st.session_state:
        st.session_state["active_etf_state"] = load_active_etf_state()
    st.session_state.setdefault("active_etf_new_code", "")
    st.session_state.setdefault("active_etf_latest_changes", None)
    st.session_state.setdefault("active_etf_last_errors", [])


def clear_loaded_warrant() -> None:
    st.session_state["loaded_warrant"] = None
    st.session_state["loaded_underlying"] = None
    st.session_state["calc_underlying_price"] = None
    st.session_state["calc_biv"] = None
    st.session_state["calc_date"] = None


def clear_recommendation_state() -> None:
    st.session_state["recommend_matches"] = []
    st.session_state["recommend_underlying"] = None
    st.session_state["recommend_rows"] = None


def load_selected_warrant(selected_item: dict) -> None:
    insnbr = int(float(selected_item["INSTR_INSNBR"]))
    warrant, underlying = load_warrant_payload(insnbr)
    st.session_state["loaded_warrant"] = warrant
    st.session_state["loaded_underlying"] = underlying
    st.session_state["calc_underlying_price"] = default_underlying_target(warrant, underlying)
    st.session_state["calc_biv"] = safe_float(warrant.get("MTM_BID_VOL"), safe_float(warrant.get("BID_IMP_VOL"), 0.0))
    st.session_state["calc_date"] = dt.date.today()


def render_match_selector() -> None:
    matches: list[dict] = st.session_state["match_options"]
    if not matches:
        return
    options = {item["TEXT"]: item for item in matches}
    selected_label = st.selectbox("找到多筆符合資料，請選擇", list(options.keys()), index=0)
    col1, col2 = st.columns([0.35, 0.65])
    with col1:
        if st.button("載入權證", type="primary"):
            load_selected_warrant(options[selected_label])
    with col2:
        st.caption("輸入代號時會優先抓精確代碼；輸入名稱時則依前綴與包含關係找最相近結果。")


def render_underlying_match_selector() -> None:
    matches: list[dict] = st.session_state["recommend_matches"]
    if not matches:
        return
    options = {item["INSTR_STKID_NAME"]: item for item in matches}
    selected_label = st.selectbox("找到多筆標的，請選擇", list(options.keys()), index=0)
    col1, col2 = st.columns([0.35, 0.65])
    with col1:
        if st.button("載入標的並推薦", type="primary"):
            item = options[selected_label]
            st.session_state["recommend_underlying"] = item
            thresholds = recommendation_thresholds(st.session_state.get("recommend_style", "偏均衡"))
            rows = fetch_underlying_warrants(int(float(item["INSTR_INSNBR"])), **thresholds)
            st.session_state["recommend_rows"] = rows
    with col2:
        st.caption("輸入標的代號時會優先抓精確代碼；輸入名稱時則依前綴與包含關係找最相近結果。")


def build_reference_dataframe(result: dict) -> pd.DataFrame:
    header = result["ANALYSIS_HEADER"][0]
    col_headers = [f"{header[f'COL{i}']:.2f}" for i in range(1, 8)]
    rows = []
    for item in result["ANALYSIS"]:
        row = {"BIV/標的價格": f"{item['UNDERLYING_PRICE']:,.2f} ({int(item['ROWINDEX']):+d}%)"}
        for idx, key in enumerate(range(1, 8), start=0):
            row[col_headers[idx]] = item[f"COL{key}"]
        rows.append(row)
    return pd.DataFrame(rows)


def score_recommendation(row: dict, style: str) -> float:
    leverage = safe_float(row.get("LEVERAGE"))
    execrate = safe_float(row.get("INSWRT_EXECRATE"))
    volume = safe_float(row.get("VOLUME"))
    spread = safe_float(row.get("BID_ASK_SPREAD_PERCENT"))
    siv = safe_float(row.get("ASK_IMP_VOL"))
    biv = safe_float(row.get("BID_IMP_VOL"))
    gap = max(siv - biv, 0.0)
    last_days = safe_float(row.get("LAST_DAYS"))
    in_out_abs = abs(safe_float(row.get("IN_OUT_PERCENT")))
    outstanding = safe_float(row.get("OUTSTANDING_PERCENT"))
    price = safe_float(row.get("DEAL"))

    if style == "偏高流動性":
        score = 0.0
        score += min(volume, 8000.0) / 12
        score += min(last_days, 720.0) / 15
        score += min(leverage, 8.0) * 8
        score += min(execrate, 0.02) * 2200
        score -= spread * 18
        score -= gap * 9
        score -= max(siv - 105.0, 0.0) * 1.1
        score -= max(in_out_abs - 10.0, 0.0) * 1.5
        score -= max(outstanding - 75.0, 0.0) * 0.5
        if price <= 0:
            score -= 50
        return score

    if style == "偏積極":
        score = 0.0
        score += min(leverage, 12.0) * 18
        score += min(execrate, 0.02) * 3600
        score += min(volume, 5000.0) / 35
        score += min(last_days, 720.0) / 18
        score -= spread * 7
        score -= gap * 4
        score -= max(siv - 120.0, 0.0) * 0.5
        score -= max(in_out_abs - 18.0, 0.0) * 0.8
        score -= max(outstanding - 90.0, 0.0) * 0.2
        if price <= 0:
            score -= 50
        return score

    if style == "偏均衡":
        score = 0.0
        score += min(leverage, 10.0) * 13
        score += min(execrate, 0.02) * 3200
        score += min(volume, 6000.0) / 22
        score += min(last_days, 720.0) / 14
        score -= spread * 10
        score -= gap * 6
        score -= max(siv - 108.0, 0.0) * 0.9
        score -= max(in_out_abs - 14.0, 0.0) * 1.1
        score -= max(outstanding - 82.0, 0.0) * 0.35
        if price <= 0:
            score -= 50
        return score

    score = 0.0
    score += min(leverage, 10.0) * 12
    score += min(execrate, 0.02) * 3000
    score += min(volume, 5000.0) / 25
    score += min(last_days, 720.0) / 12
    score -= spread * 9
    score -= gap * 5
    score -= max(siv - 110.0, 0.0) * 0.8
    score -= max(in_out_abs - 12.0, 0.0) * 1.5
    score -= max(outstanding - 80.0, 0.0) * 0.4
    if price <= 0:
        score -= 50
    return score


def recommendation_reason(row: dict, style: str) -> str:
    notes = []
    if safe_float(row.get("LEVERAGE")) >= 4:
        notes.append("槓桿較高")
    if safe_float(row.get("BID_ASK_SPREAD_PERCENT")) <= 3:
        notes.append("價差比偏佳")
    if safe_float(row.get("VOLUME")) >= 500:
        notes.append("成交量相對足")
    if safe_float(row.get("ASK_IMP_VOL")) and safe_float(row.get("ASK_IMP_VOL")) - safe_float(row.get("BID_IMP_VOL")) <= 8:
        notes.append("BIV/SIV gap 不大")
    if safe_float(row.get("INSWRT_EXECRATE")) >= 0.007:
        notes.append("行使比例偏高")
    if style == "偏保守":
        notes.append("保守排序")
    elif style == "偏積極":
        notes.append("積極排序")
    elif style == "偏高流動性":
        notes.append("流動性排序")
    else:
        notes.append("均衡排序")
    return "、".join(notes) if notes else "條件均衡"


def build_recommendation_dataframe(rows: list[dict], style: str) -> pd.DataFrame:
    filtered = []
    for row in rows:
        if safe_float(row.get("DEAL")) <= 0:
            continue
        if safe_float(row.get("ASK1_PRICE")) <= 0 and safe_float(row.get("ASK1")) <= 0:
            continue
        filtered.append(row)

    ranked = sorted(filtered, key=lambda row: score_recommendation(row, style), reverse=True)
    top_rows = ranked[:10]
    records = []
    for idx, row in enumerate(top_rows, start=1):
        biv = safe_float(row.get("BID_IMP_VOL"))
        siv = safe_float(row.get("ASK_IMP_VOL"))
        records.append(
            {
                "名次": idx,
                "權證代碼": row.get("INSTR_STKID", ""),
                "權證名稱": row.get("INSTR_NAME", ""),
                "成交價": round(safe_float(row.get("DEAL")), 3),
                "成交量": int(safe_float(row.get("VOLUME"))),
                "買賣價差比%": round(safe_float(row.get("BID_ASK_SPREAD_PERCENT")), 2),
                "BIV": round(biv, 2),
                "SIV": round(siv, 2),
                "BIV-SIV gap": round(siv - biv, 2),
                "履約價": round(safe_float(row.get("INSWRT_STRIKE")), 2),
                "行使比例": round(safe_float(row.get("INSWRT_EXECRATE")), 6),
                "價內外%": round(safe_float(row.get("IN_OUT_PERCENT")), 2),
                "剩餘天數": int(safe_float(row.get("LAST_DAYS"))),
                "實質槓桿": round(safe_float(row.get("LEVERAGE")), 2),
                "流通在外%": round(safe_float(row.get("OUTSTANDING_PERCENT")), 2),
                "推薦理由": recommendation_reason(row, style),
            }
        )
    return pd.DataFrame(records)


def recommendation_thresholds(style: str) -> dict:
    if style == "自訂條件":
        return {
            "last_days_from": int(st.session_state.get("recommend_custom_days", 360)),
            "execrate_min": float(st.session_state.get("recommend_custom_execrate", 0.005)),
            "leverage_min": float(st.session_state.get("recommend_custom_leverage", 2.0)),
            "volume_min": float(st.session_state.get("recommend_custom_volume", 100.0)),
        }
    return {
        "last_days_from": 360,
        "execrate_min": 0.005,
        "leverage_min": 0.0,
        "volume_min": 0.0,
    }


def go_to(section: str) -> None:
    st.session_state["app_section"] = section
    st.rerun()


def candle_pattern_library() -> dict[str, list[dict]]:
    return {
        "基礎線型": [
            {
                "name": "紅K / 陽線",
                "bias": "多方",
                "candles": [(100, 112, 96, 110)],
                "summary": "收盤高於開盤，代表這段時間買方取得優勢。",
                "watch": "實體越長，表示多方推升越果斷；若搭配放量，訊號更有力。",
                "confirm": "觀察下一根是否續強，或是否站上壓力區。",
                "trap": "單根紅K若剛好出現在壓力區，仍可能只是反彈，不宜只看顏色判斷。",
                "steps": ["開盤後買盤推升，收盤高於開盤，形成紅K實體。"],
            },
            {
                "name": "黑K / 陰線",
                "bias": "空方",
                "candles": [(110, 114, 98, 101)],
                "summary": "收盤低於開盤，代表這段時間賣方取得優勢。",
                "watch": "實體越長，表示賣壓越明確；若跌破支撐，空方訊號更強。",
                "confirm": "觀察下一根是否續弱，或反彈是否無法站回支撐。",
                "trap": "黑K不一定代表當日大跌，仍要看位置、成交量與趨勢。",
                "steps": ["開盤後賣壓主導，收盤低於開盤，形成黑K實體。"],
            },
            {
                "name": "十字線",
                "bias": "中性",
                "candles": [(105, 113, 97, 105.3)],
                "summary": "開盤與收盤接近，代表多空拉鋸，常出現在轉折前。",
                "watch": "十字線本身不是買賣訊號，位置比形狀重要。",
                "confirm": "高檔十字線後跌破低點偏弱，低檔十字線後突破高點偏強。",
                "trap": "盤整區大量十字線很常見，單獨看容易過度解讀。",
                "steps": ["價格上下震盪，但收盤回到開盤附近，表示多空暫時平衡。"],
            },
        ],
        "多頭型態": [
            {
                "name": "槌子",
                "bias": "多頭反轉",
                "candles": [(112, 114, 104, 108), (108, 110, 96, 106), (103, 107, 88, 105)],
                "summary": "下跌後出現長下影，表示低檔有買盤承接。",
                "watch": "下影線越長、實體越小，低檔承接意味越明顯。",
                "confirm": "下一根紅K站上槌子高點，反轉可信度較高。",
                "trap": "若隔日跌破槌子低點，表示承接失敗。",
                "steps": ["先有下跌背景。", "盤中被打低，但低檔買盤開始出現。", "收盤拉回實體附近，留下長下影。"],
            },
            {
                "name": "多頭吞噬",
                "bias": "多頭反轉",
                "candles": [(112, 113, 105, 107), (106, 116, 104, 115)],
                "summary": "前一根黑K後，後一根紅K實體吞噬前一根實體，代表買方反攻。",
                "watch": "吞噬幅度越完整，反轉力道越強。",
                "confirm": "隔日不跌回吞噬紅K中段以下，較有延續性。",
                "trap": "若發生在長期高檔，可能只是震盪，不一定是低檔反轉。",
                "steps": ["第一根黑K延續弱勢。", "第二根開低走高，紅K實體吃掉前一根黑K實體。"],
            },
            {
                "name": "多頭母子",
                "bias": "多頭反轉",
                "candles": [(112, 114, 100, 102), (103, 108, 101, 107)],
                "summary": "大黑K後出現小紅K，且小紅K落在前一根實體內，代表賣壓放緩。",
                "watch": "它是止跌訊號，不是強烈攻擊訊號。",
                "confirm": "後續突破母線高點，才較像反轉啟動。",
                "trap": "若只是小反彈後再破低，母子型態會失效。",
                "steps": ["第一根大黑K顯示賣壓。", "第二根小紅K縮在前一根實體內，賣壓暫緩。"],
            },
            {
                "name": "穿刺線",
                "bias": "多頭反轉",
                "candles": [(114, 116, 102, 104), (101, 113, 100, 112)],
                "summary": "下跌後隔日開低，但收盤拉回前一根黑K實體中線以上。",
                "watch": "收盤越接近前一根開盤，多方反攻越強。",
                "confirm": "隔日續紅或站上前高，訊號更完整。",
                "trap": "若只拉回一點點，沒有越過黑K中線，力道不足。",
                "steps": ["第一根黑K延續下跌。", "第二根開低後買盤拉升，收在黑K實體中線以上。"],
            },
            {
                "name": "晨星",
                "bias": "多頭反轉",
                "candles": [(116, 118, 104, 105), (103, 106, 100, 104), (106, 116, 105, 115)],
                "summary": "大黑K、小實體、再接大紅K，是典型低檔轉強結構。",
                "watch": "第三根紅K收越高，反轉意味越強。",
                "confirm": "第三根最好收回第一根黑K實體中線以上。",
                "trap": "若第三根紅K量縮且無法突破壓力，容易變成弱反彈。",
                "steps": ["第一根大黑K代表空方主導。", "第二根小實體代表賣壓猶豫。", "第三根大紅K代表買方重新掌控。"],
            },
            {
                "name": "紅三兵 / 三陽開泰",
                "bias": "多頭延續",
                "candles": [(100, 108, 98, 106), (104, 113, 103, 111), (109, 120, 108, 118)],
                "summary": "連續三根陽線，收盤逐日墊高，代表買盤穩定推進。",
                "watch": "開盤落在前一根實體內、收盤創高，是較漂亮的型態。",
                "confirm": "第三根後不要立刻爆大量長上影，否則可能短線過熱。",
                "trap": "漲太快且離均線太遠時，紅三兵也可能成為追高風險。",
                "steps": ["第一根紅K扭轉短線氣氛。", "第二根續攻並收高。", "第三根再收高，形成步步高升。"],
            },
            {
                "name": "三明治",
                "bias": "多頭反轉",
                "candles": [(112, 114, 102, 104), (105, 112, 103, 111), (113, 114, 102, 104.2)],
                "summary": "兩根黑K夾一根紅K，且兩根黑K收盤接近，低檔支撐被反覆測試。",
                "watch": "重點不是中間紅K，而是低點附近賣壓無法再壓低。",
                "confirm": "後續突破中間紅K高點，多方才更明確。",
                "trap": "若第三根黑K直接跌破前低，型態失效。",
                "steps": ["第一根黑K測出支撐。", "第二根紅K反彈。", "第三根再壓回但收在相近支撐，顯示低檔有守。"],
            },
            {
                "name": "梯底",
                "bias": "多頭反轉",
                "candles": [(115, 116, 108, 109), (109, 110, 102, 103), (103, 104, 97, 98), (98, 104, 96, 103), (103, 112, 102, 111)],
                "summary": "連續下跌後，低檔出現止跌與反攻，像從階梯底部轉上。",
                "watch": "最後一根紅K是否重新站回短線壓力，是重點。",
                "confirm": "突破前面黑K高點或站回均線，較有反轉可信度。",
                "trap": "弱勢趨勢中容易只是一日反彈，仍要等確認。",
                "steps": ["價格連續走低。", "跌勢放慢。", "低檔買盤試圖守住。", "紅K反攻。", "突破短線壓力，型態完成。"],
            },
        ],
        "空頭型態": [
            {
                "name": "吊人",
                "bias": "空頭反轉",
                "candles": [(100, 108, 98, 107), (108, 116, 107, 115), (116, 118, 103, 114)],
                "summary": "上漲後出現長下影小實體，代表高檔曾被大幅賣壓打低。",
                "watch": "位置在高檔才有空頭反轉意義。",
                "confirm": "隔日跌破吊人低點或收黑，訊號較完整。",
                "trap": "若隔日續創新高，吊人訊號失效。",
                "steps": ["先有上漲背景。", "高檔盤中被賣壓打低。", "雖拉回收盤，但留下警訊。"],
            },
            {
                "name": "射擊之星 / 流星",
                "bias": "空頭反轉",
                "candles": [(100, 108, 98, 107), (108, 116, 106, 115), (116, 128, 114, 117)],
                "summary": "上漲後出現長上影小實體，代表追價買盤被賣壓打回。",
                "watch": "上影線越長，表示上方賣壓越重。",
                "confirm": "下一根跌破流星低點，空方訊號較強。",
                "trap": "若隔日直接突破上影高點，表示賣壓被消化。",
                "steps": ["先有上漲背景。", "盤中衝高。", "收盤被壓回，留下長上影。"],
            },
            {
                "name": "空頭吞噬",
                "bias": "空頭反轉",
                "candles": [(104, 114, 103, 112), (113, 115, 101, 102)],
                "summary": "前一根紅K後，後一根黑K實體吞噬前一根實體，代表賣方反攻。",
                "watch": "吞噬越完整，空方力道越明確。",
                "confirm": "隔日無法站回黑K中段以上，偏弱。",
                "trap": "若發生在低檔，可能只是震盪洗盤，不一定續跌。",
                "steps": ["第一根紅K延續強勢。", "第二根開高走低，黑K實體吃掉前一根紅K。"],
            },
            {
                "name": "空頭母子",
                "bias": "空頭反轉",
                "candles": [(100, 114, 99, 112), (111, 113, 106, 107)],
                "summary": "大紅K後出現小黑K，且小黑K落在前一根實體內，代表買盤轉弱。",
                "watch": "它偏向警訊，通常需要後續跌破確認。",
                "confirm": "跌破母線低點，空方訊號較完整。",
                "trap": "強勢多頭中常見休息小黑K，不一定反轉。",
                "steps": ["第一根大紅K推升。", "第二根小黑K縮在前一根實體內，買盤猶豫。"],
            },
            {
                "name": "烏雲罩頂",
                "bias": "空頭反轉",
                "candles": [(100, 114, 99, 113), (116, 117, 104, 106)],
                "summary": "上漲後隔日開高，但收盤跌回前一根紅K實體中線以下。",
                "watch": "收盤越低，空方反撲越強。",
                "confirm": "隔日續跌或跌破前低，訊號更完整。",
                "trap": "若只跌回一點點，沒有跌破紅K中線，力道不足。",
                "steps": ["第一根紅K延續強勢。", "第二根開高後賣壓湧出，收在紅K中線以下。"],
            },
            {
                "name": "夜星",
                "bias": "空頭反轉",
                "candles": [(100, 113, 99, 112), (114, 117, 112, 115), (113, 114, 102, 103)],
                "summary": "大紅K、小實體、再接大黑K，是典型高檔轉弱結構。",
                "watch": "第三根黑K收越低，反轉意味越強。",
                "confirm": "第三根最好跌破第一根紅K實體中線。",
                "trap": "若第三根沒有量或沒有跌破關鍵支撐，可能只是拉回。",
                "steps": ["第一根大紅K代表多方主導。", "第二根小實體代表追價猶豫。", "第三根大黑K代表賣方重新掌控。"],
            },
            {
                "name": "黑三鴉 / 三隻烏鴉",
                "bias": "空頭延續",
                "candles": [(118, 120, 110, 112), (113, 114, 105, 106), (107, 108, 98, 100)],
                "summary": "連續三根陰線，收盤逐日走低，代表賣壓穩定釋放。",
                "watch": "開盤落在前一根實體內、收盤接近低點，是較典型的型態。",
                "confirm": "若跌破支撐或均線轉弱，空方訊號更強。",
                "trap": "短線急跌後才出現黑三鴉，可能已有過度恐慌，追空要小心。",
                "steps": ["第一根黑K轉弱。", "第二根續跌並收低。", "第三根再收低，形成步步下壓。"],
            },
            {
                "name": "頸上線",
                "bias": "空頭延續",
                "candles": [(116, 117, 104, 105), (103, 108, 101, 105.5)],
                "summary": "下跌後隔日開低反彈，但只收回前一根低點附近，反彈力道不足。",
                "watch": "反彈無法站回黑K實體內部，代表買盤弱。",
                "confirm": "後續跌破第二根低點，續跌機率提高。",
                "trap": "若隔日強攻站回黑K中線，空方延續訊號失效。",
                "steps": ["第一根大黑K下跌。", "第二根開低反彈，但只回到前低附近。"],
            },
        ],
    }


def teaching_candles_dataframe(pattern: dict, visible_count: int) -> pd.DataFrame:
    candles = pattern["candles"][:visible_count]
    return pd.DataFrame(
        [
            {"Date": f"第 {idx} 根", "Open": o, "High": h, "Low": l, "Close": c}
            for idx, (o, h, l, c) in enumerate(candles, start=1)
        ]
    )


def draw_teaching_candles(pattern: dict, visible_count: int) -> go.Figure:
    data = teaching_candles_dataframe(pattern, visible_count)
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=data["Date"],
            open=data["Open"],
            high=data["High"],
            low=data["Low"],
            close=data["Close"],
            increasing_line_color="#e53935",
            increasing_fillcolor="#ff4d4f",
            decreasing_line_color="#128c4a",
            decreasing_fillcolor="#18c66a",
            name=pattern["name"],
        )
    )
    if not data.empty:
        last = data.iloc[-1]
        color = "#e53935" if "多頭" in pattern["bias"] or pattern["bias"] == "多方" else "#128c4a"
        fig.add_annotation(
            x=last["Date"],
            y=last["High"] + 4,
            text=pattern["name"],
            showarrow=False,
            font={"size": 18, "color": color},
            bgcolor="rgba(255,255,255,0.86)",
            bordercolor=color,
            borderwidth=1,
        )
    fig.update_layout(
        height=430,
        margin={"l": 20, "r": 20, "t": 42, "b": 20},
        xaxis_rangeslider_visible=False,
        plot_bgcolor="#fffaf2",
        paper_bgcolor="#fffaf2",
        yaxis_title="示意價格",
        title=f"{pattern['name']}：逐步形成示意",
    )
    return fig


def render_candlestick_teaching() -> None:
    st.title("K線型態教學")
    st.caption("用示意 K 線理解型態背後的多空心理。反轉型態不是保證反轉，通常仍要搭配位置、成交量、均線與隔日確認。")

    st.markdown(
        """
        <style>
        .teaching-card {
            border: 1px solid #ead9c2;
            background: linear-gradient(135deg, #fffaf2 0%, #fff4e4 100%);
            border-radius: 16px;
            padding: 16px 18px;
            margin-bottom: 12px;
        }
        .bull-badge {
            color: #b71c1c;
            background: #ffe5e5;
            border-radius: 999px;
            padding: 4px 10px;
            font-weight: 700;
        }
        .bear-badge {
            color: #0b6b37;
            background: #ddf7e7;
            border-radius: 999px;
            padding: 4px 10px;
            font-weight: 700;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    library = candle_pattern_library()
    category = st.radio("型態分類", list(library.keys()), horizontal=True)
    patterns = library[category]
    selected_name = st.selectbox("選擇型態", [item["name"] for item in patterns])
    pattern = next(item for item in patterns if item["name"] == selected_name)

    max_step = len(pattern["candles"])
    use_steps = st.toggle("逐步動畫模式", value=True, help="用 slider 一根一根看型態如何形成。")
    step = st.slider("形成步驟", 1, max_step, max_step) if use_steps and max_step > 1 else max_step

    chart_col, text_col = st.columns([0.58, 0.42])
    with chart_col:
        st.plotly_chart(draw_teaching_candles(pattern, step), use_container_width=True)
    with text_col:
        badge_class = "bull-badge" if "多" in pattern["bias"] or pattern["bias"] == "多方" else "bear-badge"
        if pattern["bias"] == "中性":
            badge_class = "bull-badge"
        st.markdown(
            f"<div class='teaching-card'><span class='{badge_class}'>{pattern['bias']}</span>"
            f"<h3>{pattern['name']}</h3><p>{pattern['summary']}</p></div>",
            unsafe_allow_html=True,
        )
        st.markdown("#### 目前步驟")
        steps = pattern.get("steps", [])
        current_step_text = steps[min(step - 1, len(steps) - 1)] if steps else pattern["summary"]
        st.write(current_step_text)
        st.markdown("#### 判讀重點")
        st.write(pattern["watch"])
        st.markdown("#### 確認方式")
        st.write(pattern["confirm"])
        st.markdown("#### 常見陷阱")
        st.write(pattern["trap"])

    st.divider()
    st.subheader("快速索引")
    cols = st.columns(3)
    for idx, (group_name, group_patterns) in enumerate(library.items()):
        with cols[idx]:
            st.markdown(f"#### {group_name}")
            for item in group_patterns:
                st.write(f"- {item['name']}：{item['bias']}")

    st.info(
        "教學圖是型態示意，不是即時訊號。實戰上請先看趨勢位置，再看型態，最後用成交量、支撐壓力與隔日K線確認。"
    )


def render_home() -> None:
    st.title("投資工具首頁")
    st.caption("這支程式同時包含 K 線型態分析、K 線型態教學、權證計算機、權證推薦與主動 ETF 持股追蹤，之後可直接部署到 GitHub 與 Streamlit Community Cloud。")
    kline_left, kline_right = st.columns(2)
    with kline_left:
        st.markdown("### K線型態分析")
        st.write("查看台股 K 線、技術指標、型態訊號與 AI 分析。")
        if st.button("前往 K線型態分析", type="primary", use_container_width=True):
            go_to("stock2")
    with kline_right:
        st.markdown("### K線型態教學")
        st.write("用 Plotly 示意圖與逐步動畫理解多頭、空頭型態。")
        if st.button("前往 K線型態教學", type="primary", use_container_width=True):
            go_to("candlestick_teaching")

    st.divider()
    warrant_left, warrant_right = st.columns(2)
    with warrant_left:
        st.markdown("### 權證計算機")
        st.write("使用凱基 backend service 查詢權證資料與試算參考價格。")
        if st.button("前往 權證計算機", type="primary", use_container_width=True):
            go_to("warrant")
    with warrant_right:
        st.markdown("### 權證推薦")
        st.write("依標的篩選認購權證，優先找長天期、較高行使比例與較佳交易條件。")
        if st.button("前往 權證推薦", type="primary", use_container_width=True):
            go_to("recommend")

    st.divider()
    etf_left, etf_right = st.columns([0.5, 0.5])
    with etf_left:
        st.markdown("### 主動ETF追蹤")
        st.write("新增台灣主動型 ETF，盤後追蹤每日持股進出與股數變化。")
        if st.button("前往 主動ETF追蹤", type="primary", use_container_width=True):
            go_to("active_etf")
    with etf_right:
        st.write("")


def render_warrant_calculator() -> None:
    st.title("權證計算機")
    st.caption("先輸入權證代號或名稱，再透過凱基 backend service 載入資料。載入後可自行修改標的目標價、BIV 與日期。")

    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            border: 1px solid #dbe5f1;
            padding: 12px 14px;
            border-radius: 10px;
            background: #f7fbff;
        }
        .result-box {
            border: 2px solid #1f5fbf;
            border-radius: 12px;
            background: #fff3eb;
            padding: 18px 20px;
            min-height: 170px;
        }
        .result-box h3 {
            color: #ff5a00;
            margin: 0 0 12px 0;
            font-size: 1.9rem;
        }
        .note-box {
            border-left: 4px solid #ff5a00;
            padding-left: 12px;
            color: #4b5563;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    query_col, button_col, clear_col = st.columns([0.7, 0.15, 0.15])
    with query_col:
        query_text = st.text_input(
            "請輸入權證代號或名稱",
            value=st.session_state["query_text"],
            placeholder="例如：057525 或 欣興統一66購02",
        )
    with button_col:
        fetch_clicked = st.button("從凱基抓取", type="primary")
    with clear_col:
        clear_clicked = st.button("清空")

    if clear_clicked:
        st.session_state["query_text"] = ""
        st.session_state["match_options"] = []
        clear_loaded_warrant()
        st.rerun()

    if fetch_clicked:
        st.session_state["query_text"] = query_text
        clear_loaded_warrant()
        matches = resolve_matches(query_text)
        st.session_state["match_options"] = matches
        if not matches:
            st.warning("查無符合的權證，請再換一個代號或名稱。")
        elif len(matches) == 1:
            load_selected_warrant(matches[0])
        else:
            st.info(f"找到 {len(matches)} 筆符合資料，請從下方選一檔載入。")

    render_match_selector()

    warrant = st.session_state.get("loaded_warrant")
    underlying = st.session_state.get("loaded_underlying")
    if not warrant or not underlying:
        st.info("目前左側試算欄位保持空白。請先輸入權證代號或名稱，再按「從凱基抓取」。")
        return

    calc_underlying_default = safe_float(st.session_state.get("calc_underlying_price"))
    calc_biv_default = safe_float(st.session_state.get("calc_biv"))
    calc_date_default = st.session_state.get("calc_date") or dt.date.today()

    st.subheader(f"{warrant['INSTR_STKID']} {warrant['INSTR_NAME']} ({warrant['UND_INSTR_STKID']})")
    summary_left, summary_right = st.columns([1.12, 0.88])

    with summary_left:
        quote_df = pd.DataFrame(
            [
                {
                    "代碼": warrant["INSTR_STKID"],
                    "名稱": warrant["INSTR_NAME"],
                    "委買量": safe_float(warrant["BID1VOLUME"]),
                    "最佳買價": safe_float(warrant["BID1"]),
                    "最佳賣價": safe_float(warrant["ASK1"]),
                    "委賣量": safe_float(warrant["ASK1VOLUME"]),
                    "成交價": safe_float(warrant["DEAL"]),
                    "成交量": safe_float(warrant["VOLUME"]),
                    "漲跌": safe_float(warrant["CHANGE"]),
                    "漲跌幅%": safe_float(warrant["CHANGE_PERCENT"]),
                    "今日最高": safe_float(warrant["HIGH"]),
                    "今日最低": safe_float(warrant["LOW"]),
                },
                {
                    "代碼": underlying["INSTR_STKID"],
                    "名稱": underlying["INSTR_NAME"],
                    "委買量": safe_float(underlying["BID1VOLUME"]),
                    "最佳買價": safe_float(underlying["BID1"]),
                    "最佳賣價": safe_float(underlying["ASK1"]),
                    "委賣量": safe_float(underlying["ASK1VOLUME"]),
                    "成交價": safe_float(underlying["DEAL"]),
                    "成交量": safe_float(underlying["VOLUME"]),
                    "漲跌": safe_float(underlying["CHANGE"]),
                    "漲跌幅%": safe_float(underlying["CHANGE_PERCENT"]),
                    "今日最高": safe_float(underlying["HIGH"]),
                    "今日最低": safe_float(underlying["LOW"]),
                },
            ]
        )
        st.dataframe(quote_df, use_container_width=True, hide_index=True)

    with summary_right:
        input_left, _, input_right = st.columns([0.48, 0.02, 0.50])
        with input_left:
            target_price = st.number_input("標的物目標價", min_value=0.0, value=calc_underlying_default, step=1.0, format="%.2f")
            biv_pct = st.number_input("BIV(%)", min_value=0.0, value=calc_biv_default, step=0.1, format="%.2f")
            process_date = st.date_input("日期", value=calc_date_default)
        with input_right:
            st.markdown("<div class='note-box'>載入後的三個值只是凱基當前資料的起始值，你可以自行覆蓋再試算。</div>", unsafe_allow_html=True)
            run_calc = st.button("開始計算", type="primary")

    if not run_calc:
        st.info("請先調整標的物目標價、BIV 或日期，再按「開始計算」。")
        return

    process_date_int = to_process_date(process_date)
    insnbr = int(float(warrant["INSTR_INSNBR"]))
    theo_price = theoretical_price(insnbr, process_date_int, biv_pct, target_price)
    analysis = sensitivity_analysis(insnbr, process_date_int, biv_pct, target_price)

    result_text = (
        f"{process_date:%Y/%m/%d}，當標的的價格為 {target_price:,.2f} 元，且波動率為 {biv_pct:.2f}% 時，"
        f"此權證參考價格為 {theo_price:.2f} 元。"
    )
    st.markdown(
        f"<div class='result-box'><h3>試算結果</h3><p style='font-size:1.45rem;line-height:1.7'>{result_text}</p></div>",
        unsafe_allow_html=True,
    )

    greeks_df = pd.DataFrame(
        [
            {
                "權證類型": warrant.get("INSWRT_AE", ""),
                "實質槓桿": round(safe_float(warrant.get("LEVERAGE")), 4),
                "價內外程度%": round(safe_float(warrant.get("IN_OUT_PERCENT")), 2),
                "履約價": round(safe_float(warrant.get("INSWRT_STRIKE")), 4),
                "行使比例": round(safe_float(warrant.get("INSWRT_EXECRATE")), 6),
                "到期日": format_compact_date(warrant.get("INSWRT_EXPIRED_DATE")),
                "Delta": round(safe_float(warrant.get("DELTA")), 6),
                "Theta": round(safe_float(warrant.get("THETA")), 6),
                "Gamma": round(safe_float(warrant.get("GAMMA")), 6),
                "Vega": round(safe_float(warrant.get("VEGA")), 6),
                "Rho": round(safe_float(warrant.get("RHO")), 6),
                "內含價值": round(safe_float(warrant.get("INCLUDE_VALUE")), 6),
                "三個月歷史波動率": round(safe_float(warrant.get("THREE_MONTH_HISTORY_VOLAILITY")), 4),
            }
        ]
    )
    st.subheader("各項相關係數")
    st.dataframe(greeks_df, use_container_width=True, hide_index=True)

    st.subheader("參考價格")
    st.caption("這張矩陣直接使用凱基 `S0600018_SensitivityAnalysis` 回傳結果。")
    st.dataframe(build_reference_dataframe(analysis), use_container_width=True, hide_index=True)

    st.markdown(
        """
        <div class="note-box">
        目前權證選單與試算結果都直接來自凱基 backend service。若凱基未來調整 serviceId、欄位名或參數格式，這支工具也要跟著更新。
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_warrant_recommendation() -> None:
    st.title("權證推薦")
    st.caption("先輸入標的代號或名稱，再用凱基 backend service 抓出符合條件的認購權證。預設條件：剩餘天數 >= 360、行使比例 >= 0.005。")

    style = st.radio(
        "推薦風格",
        ["偏保守", "偏均衡", "偏積極", "偏高流動性", "自訂條件"],
        index=["偏保守", "偏均衡", "偏積極", "偏高流動性", "自訂條件"].index(
            st.session_state.get("recommend_style", "偏均衡")
        ),
        horizontal=True,
        help="偏保守重視成本與風險，偏均衡平衡槓桿與流動性，偏積極強調槓桿與行使比例，偏高流動性則優先看量與價差，自訂條件可自設最低門檻。",
    )
    st.session_state["recommend_style"] = style

    if style == "自訂條件":
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.session_state["recommend_custom_days"] = st.number_input(
                "最低剩餘天數",
                min_value=1,
                value=int(st.session_state.get("recommend_custom_days", 360)),
                step=30,
            )
        with c2:
            st.session_state["recommend_custom_execrate"] = st.number_input(
                "最低行使比例",
                min_value=0.0,
                value=float(st.session_state.get("recommend_custom_execrate", 0.005)),
                step=0.001,
                format="%.3f",
            )
        with c3:
            st.session_state["recommend_custom_leverage"] = st.number_input(
                "最低實質槓桿",
                min_value=0.0,
                value=float(st.session_state.get("recommend_custom_leverage", 2.0)),
                step=0.5,
                format="%.1f",
            )
        with c4:
            st.session_state["recommend_custom_volume"] = st.number_input(
                "最低成交量",
                min_value=0.0,
                value=float(st.session_state.get("recommend_custom_volume", 100.0)),
                step=50.0,
                format="%.0f",
            )

    query_col, button_col, clear_col = st.columns([0.7, 0.15, 0.15])
    with query_col:
        query_text = st.text_input(
            "請輸入標的代號或名稱",
            value=st.session_state["recommend_query_text"],
            placeholder="例如：3037 或 欣興",
            key="recommend_input",
        )
    with button_col:
        fetch_clicked = st.button("抓取候選", type="primary")
    with clear_col:
        clear_clicked = st.button("清空推薦")

    if clear_clicked:
        st.session_state["recommend_query_text"] = ""
        clear_recommendation_state()
        st.rerun()

    if fetch_clicked:
        st.session_state["recommend_query_text"] = query_text
        clear_recommendation_state()
        matches = resolve_underlying_matches(query_text)
        st.session_state["recommend_matches"] = matches
        if not matches:
            st.warning("查無符合的標的，請再換一個代號或名稱。")
        elif len(matches) == 1:
            item = matches[0]
            st.session_state["recommend_underlying"] = item
            thresholds = recommendation_thresholds(style)
            rows = fetch_underlying_warrants(int(float(item["INSTR_INSNBR"])), **thresholds)
            st.session_state["recommend_rows"] = rows
        else:
            st.info(f"找到 {len(matches)} 筆符合標的，請從下方選一檔載入。")

    render_underlying_match_selector()

    underlying = st.session_state.get("recommend_underlying")
    rows = st.session_state.get("recommend_rows")
    if not underlying or rows is None:
        st.info("請先輸入標的代號或名稱，再按「抓取候選」。")
        return

    st.subheader(f"標的：{underlying.get('INSTR_STKID_NAME', '')}")
    if style == "偏保守":
        st.write("目前使用保守排序：更重視成交量、買賣價差比、BIV/SIV gap 與 SIV 成本，仍保留對槓桿與行使比例的要求。")
    elif style == "偏均衡":
        st.write("目前使用均衡排序：在槓桿、行使比例、成交量、買賣價差比與 BIV/SIV gap 之間做平衡。")
    elif style == "偏高流動性":
        st.write("目前使用高流動性排序：優先看成交量、買賣價差比與較小的 BIV/SIV gap，降低進出場摩擦。")
    elif style == "自訂條件":
        st.write(
            "目前使用自訂條件："
            f"剩餘天數 >= {int(st.session_state.get('recommend_custom_days', 360))}、"
            f"行使比例 >= {float(st.session_state.get('recommend_custom_execrate', 0.005)):.3f}、"
            f"實質槓桿 >= {float(st.session_state.get('recommend_custom_leverage', 2.0)):.1f}、"
            f"成交量 >= {int(float(st.session_state.get('recommend_custom_volume', 100.0)))}。"
        )
    else:
        st.write("目前使用積極排序：更重視實質槓桿與行使比例，對價差與波動成本的容忍度會高一些。")

    if not rows:
        st.warning("這個標的目前查無符合條件的權證。")
        return

    summary_cols = st.columns(4)
    summary_cols[0].metric("候選總數", f"{len(rows)}")
    thresholds = recommendation_thresholds(style)
    summary_cols[1].metric("條件", f"認購 / {int(thresholds['last_days_from'])}天+")
    summary_cols[2].metric("最低行使比例", f"{float(thresholds['execrate_min']):.3f}")
    summary_cols[3].metric("最低槓桿 / 量", f"{float(thresholds['leverage_min']):.1f} / {int(thresholds['volume_min'])}")

    ranking_style = "偏均衡" if style == "自訂條件" else style
    recommend_df = build_recommendation_dataframe(rows, ranking_style)
    if recommend_df.empty:
        st.warning("目前符合基本條件的資料中，沒有可用於推薦排序的有效報價。")
        return

    st.subheader("建議先看")
    st.dataframe(recommend_df.head(5), use_container_width=True, hide_index=True)

    st.subheader("前 10 檔候選")
    st.dataframe(recommend_df, use_container_width=True, hide_index=True)


def render_active_etf_tracker() -> None:
    st.title("台灣主動型 ETF 持股追蹤")
    st.caption("新增要追蹤的主動型 ETF 代號，盤後按「更新全部」即可抓取最新持股，並與前一次快照比對股數進出。")
    st.caption(f"目前儲存位置：{active_etf_storage_label()}")
    with st.expander("儲存設定檢查", expanded=False):
        for item in active_etf_storage_diagnostics():
            st.write(f"- {item}")

    if "active_etf_state" not in st.session_state:
        st.session_state["active_etf_state"] = load_active_etf_state()
    state = st.session_state["active_etf_state"]
    state.setdefault("watchlist", [])
    state.setdefault("history", {})

    with st.container(border=True):
        st.subheader("追蹤清單")
        add_col, add_button_col = st.columns([0.75, 0.25])
        with add_col:
            new_code = st.text_input(
                "新增 ETF 代號",
                placeholder="例如：00403A",
                key="active_etf_new_code",
            )
        with add_button_col:
            st.write("")
            st.write("")
            if st.button("新增ETF", type="primary", use_container_width=True):
                code = normalize_etf_code(new_code)
                if not code:
                    st.warning("請先輸入 ETF 代號。")
                elif code in state["watchlist"]:
                    st.info(f"{code} 已在追蹤清單中。")
                else:
                    state["watchlist"].append(code)
                    state["watchlist"] = sorted(set(state["watchlist"]))
                    ok, message = save_active_etf_state(state)
                    if not ok:
                        st.warning(f"清單已加入本次 session，但寫入狀態檔失敗：{message}")
                    st.session_state["active_etf_state"] = state
                    st.rerun()

        if state["watchlist"]:
            st.write("目前追蹤：")
            st.dataframe(pd.DataFrame({"ETF代號": state["watchlist"]}), use_container_width=True, hide_index=True)
            remove_codes = st.multiselect("選擇要刪除的 ETF", options=state["watchlist"])
            if st.button("刪除選取", use_container_width=True):
                if not remove_codes:
                    st.info("請先選擇要刪除的 ETF。")
                else:
                    state["watchlist"] = [code for code in state["watchlist"] if code not in remove_codes]
                    ok, message = save_active_etf_state(state)
                    if not ok:
                        st.warning(f"已從本次 session 移除，但寫入狀態檔失敗：{message}")
                    st.session_state["active_etf_state"] = state
                    st.rerun()
        else:
            st.info("目前尚未加入 ETF。請先輸入代號，例如 00403A。")

    if not state["watchlist"]:
        return

    refresh_col, info_col = st.columns([0.25, 0.75])
    with refresh_col:
        refresh_clicked = st.button("更新全部並比對", type="primary", use_container_width=True)
    with info_col:
        st.caption("資料來源為 ETF 資訊網公開持股頁。若當天資料尚未更新，會抓到來源網站目前最新快照日。")

    if refresh_clicked:
        all_change_rows = []
        errors = []
        with st.spinner("正在抓取 ETF 持股並比對前次快照..."):
            for etf_code in state["watchlist"]:
                try:
                    snapshot = fetch_etf_holdings_snapshot(etf_code)
                    previous = previous_etf_snapshot(state, etf_code, snapshot["date"])
                    change_rows = build_etf_change_rows(snapshot, previous)
                    if previous:
                        all_change_rows.extend([row for row in change_rows if row["動作"] != "持平"])
                    else:
                        all_change_rows.extend(change_rows)
                    upsert_etf_snapshot(state, snapshot)
                except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                    errors.append(f"{etf_code}: {exc}")

        ok, message = save_active_etf_state(state)
        if not ok:
            errors.append(f"狀態檔寫入失敗：{message}")
        st.session_state["active_etf_state"] = state
        st.session_state["active_etf_latest_changes"] = all_change_rows
        st.session_state["active_etf_last_errors"] = errors

    errors = st.session_state.get("active_etf_last_errors") or []
    if errors:
        st.error("部分 ETF 更新失敗：\n\n" + "\n".join(f"- {message}" for message in errors))

    latest_changes = st.session_state.get("active_etf_latest_changes")
    if latest_changes is not None:
        st.subheader("本次持股變化總覽")
        if latest_changes:
            changes_df = pd.DataFrame(latest_changes)
            st.dataframe(
                changes_df,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("本次更新沒有偵測到持股股數變化。")

    st.subheader("最新持股快照")
    for etf_code in state["watchlist"]:
        history = state.get("history", {}).get(etf_code, [])
        if not history:
            with st.expander(f"{etf_code} 尚未更新"):
                st.info("按「更新全部並比對」後，這裡會顯示最新持股。")
            continue

        latest_snapshot = sorted(history, key=lambda item: item.get("date", ""))[-1]
        label = f"{etf_code} {latest_snapshot.get('name', '')} / 快照日 {latest_snapshot.get('date', '')}"
        with st.expander(label, expanded=False):
            holdings_df = etf_holdings_dataframe(latest_snapshot)
            metric_cols = st.columns(3)
            metric_cols[0].metric("持股檔數", f"{len(holdings_df)}")
            metric_cols[1].metric("最大權重", f"{holdings_df['權重%'].max():.2f}%" if not holdings_df.empty else "-")
            metric_cols[2].metric("歷史快照數", f"{len(history)}")
            st.dataframe(holdings_df, use_container_width=True, hide_index=True)

# -----------------------------
# 主介面
# -----------------------------
def render_stock2_tool():
    st.title("📈 台股技術形態分析平台")

    with st.sidebar:
        st.header("設定")
        sid = st.text_input(
            "股票代碼或名稱",
            "2330",
            help="可輸入代碼或名稱，例如 2330、8121、台積電、越峰。系統會自動判斷上市 .TW 或上櫃 .TWO。",
        )
        st.caption("可直接輸入上市/上櫃代碼或股票名稱，不需要加 .TW / .TWO。")
        days = st.slider("查詢天數", 30, 365, 120)
        
        st.subheader("指標顯示")
        selected_mas = st.multiselect(
            "移動平均線",
            options=list(MA_WINDOWS),
            default=[5, 20, 60],
            format_func=lambda value: f"{value}日均線",
        )
        bb_on = st.checkbox("布林通道", True)
        kd_on = st.checkbox("KD", False)
        rsi_on = st.checkbox("RSI", False)
        macd_on = st.checkbox("MACD", False)
        
        st.subheader("形態偵測")
        selected_patterns = st.multiselect(
            "K線型態",
            options=list(PATTERN_CHOICES),
            default=[PATTERN_SELECT_ALL],
            help="選擇全選會顯示多空組合型態；紅K、黑K、十字線需手動勾選，避免圖上標籤過多。",
        )
        red_candle_on = "Red Candle (紅K/陽線)" in selected_patterns
        black_candle_on = "Black Candle (黑K/陰線)" in selected_patterns
        doji_on = "Doji (十字線)" in selected_patterns
        ms_on = is_pattern_selected(selected_patterns, "Morning Star (晨星)")
        es_on = is_pattern_selected(selected_patterns, "Evening Star (暮星)")
        ss_on = is_pattern_selected(selected_patterns, "Shooting Star (射擊之星)")
        tws_on = is_pattern_selected(selected_patterns, "Three White Soldiers (紅三兵)")
        tbc_on = is_pattern_selected(selected_patterns, "Three Black Crows (黑三鴉)")
        be_on = is_pattern_selected(selected_patterns, "Bullish Engulfing (多頭吞噬)")
        piercing_on = is_pattern_selected(selected_patterns, "Piercing Line (穿刺線)")
        hammer_on = is_pattern_selected(selected_patterns, "Hammer (槌子)")
        hanging_on = is_pattern_selected(selected_patterns, "Hanging Man (吊人線)")
        meteor_on = is_pattern_selected(selected_patterns, "Meteor (流星)")
        bullish_harami_on = is_pattern_selected(selected_patterns, "Bullish Harami (多頭母子)")
        bullish_harami_cross_on = is_pattern_selected(selected_patterns, "Bullish Harami Cross (多頭母子十字)")
        sandwich_on = is_pattern_selected(selected_patterns, "Sandwich (三明治)")
        ladder_bottom_on = is_pattern_selected(selected_patterns, "Ladder Bottom (梯底)")
        bearish_harami_on = is_pattern_selected(selected_patterns, "Bearish Harami (空頭母子)")
        bearish_engulfing_on = is_pattern_selected(selected_patterns, "Bearish Engulfing (陰吞噬)")
        dark_cloud_cover_on = is_pattern_selected(selected_patterns, "Dark Cloud Cover (烏雲罩頂)")
        on_neck_line_on = is_pattern_selected(selected_patterns, "On Neck Line (頸上線)")

        st.subheader("AI 分析")
        ai_provider = st.radio(
            "分析模型",
            ["ChatGPT", "Gemini"],
            horizontal=True,
        )
        
        run = st.button("開始分析", use_container_width=True)

    if run:
        try:
            opts = ChartOptions(
                normalize_ticker(sid),
                days,
                bb_on,
                tuple(selected_mas),
                kd_on,
                rsi_on,
                macd_on,
                red_candle_on,
                black_candle_on,
                doji_on,
                ms_on,
                es_on,
                ss_on,
                tws_on,
                tbc_on,
                be_on,
                piercing_on,
                hammer_on,
                hanging_on,
                meteor_on,
                bullish_harami_on,
                bullish_harami_cross_on,
                sandwich_on,
                ladder_bottom_on,
                bearish_harami_on,
                bearish_engulfing_on,
                dark_cloud_cover_on,
                on_neck_line_on,
            )
            data = get_stock_data(opts)
            st.session_state["stock_data"] = data
            st.session_state["chart_options"] = opts
            st.session_state.pop("ai_analysis", None)
            st.session_state.pop("ai_analysis_provider", None)

        except Exception as e:
            st.session_state.pop("stock_data", None)
            st.session_state.pop("chart_options", None)
            st.session_state.pop("ai_analysis", None)
            st.session_state.pop("ai_analysis_provider", None)
            st.error(f"錯誤：{e}")

    if "stock_data" in st.session_state and "chart_options" in st.session_state:
        data = st.session_state["stock_data"]
        opts = st.session_state["chart_options"]

        # 儀表板數據
        l = data.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("收盤", f"{l['Close']:.2f}")
        c2.metric("高", f"{l['High']:.2f}")
        c3.metric("低", f"{l['Low']:.2f}")
        c4.metric("成交量", f"{int(l['Volume']):,}")

        st.plotly_chart(draw_chart(data, opts), use_container_width=True)

        st.subheader("最近 K線型態訊號")
        signal_df = recent_pattern_signals(data, opts)
        if signal_df.empty:
            st.info("目前查詢區間內沒有偵測到已勾選的 K 線型態。")
        else:
            st.dataframe(signal_df, use_container_width=True, hide_index=True)

        st.subheader("近 10 個交易日三大法人買賣超")
        st.caption("單位：股；正數為買超，負數為賣超。資料來源：TWSE / TPEx 公開資料。")
        institutional_data = get_institutional_trade_data(opts.ticker)
        if institutional_data.empty:
            st.info("目前查無此個股近 10 個交易日三大法人資料，可能是資料來源尚未更新或代碼市場別不符。")
        else:
            st.plotly_chart(
                draw_institutional_trade_chart(institutional_data),
                use_container_width=True,
            )
            display_data = institutional_data.copy()
            for column in ["外資買賣超", "投信買賣超", "自營商買賣超", "三大法人合計"]:
                display_data[column] = display_data[column].map(lambda value: f"{value:,}")
            st.dataframe(display_data, use_container_width=True, hide_index=True)

        st.subheader("AI 分析說明")
        provider = ai_provider
        st.caption(f"目前使用 {provider} 分析 K 線、成交量、布林通道、均線、KD、RSI 與 MACD；內容僅供研究參考。")
        if st.button(f"使用 {provider} 分析目前圖表", use_container_width=True):
            with st.spinner(f"{provider} 正在分析 K 線圖、成交量與技術指標..."):
                st.session_state["ai_analysis"] = analyze_with_provider(provider, data, opts)
                st.session_state["ai_analysis_provider"] = provider

        if (
            st.session_state.get("ai_analysis")
            and st.session_state.get("ai_analysis_provider") == provider
        ):
            st.markdown(st.session_state["ai_analysis"])


def main():
    init_home_state()
    st.set_page_config(page_title="投資工具首頁", page_icon="📈", layout="wide")

    current = st.session_state.get("app_section", "home")
    if current != "home":
        with st.sidebar:
            if st.button("回首頁", use_container_width=True):
                go_to("home")

    if current == "stock2":
        render_stock2_tool()
    elif current == "candlestick_teaching":
        render_candlestick_teaching()
    elif current == "warrant":
        render_warrant_calculator()
    elif current == "recommend":
        render_warrant_recommendation()
    elif current == "active_etf":
        render_active_etf_tracker()
    else:
        render_home()


if __name__ == "__main__":
    main()
