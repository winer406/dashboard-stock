# app.py
"""
台股 K 線圖分析（進階形態版）
功能：
1. 輸入台股代碼與查詢天數
2. 技術指標：布林通道、5/20/60/120 日均線、KD、RSI、MACD
3. K線形態偵測：Morning Star, Evening Star, Shooting Star 與多種吞噬/母子型態
4. 自動處理 Yahoo Finance 資料結構
5. 可切換 ChatGPT / Gemini 分析 K 線圖、成交量與布林通道

需要套件：
pip install streamlit yfinance pandas plotly
"""

from dataclasses import dataclass
import datetime as dt
import json
import os
import urllib.error
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

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
ENV_QUOTES = "\"'“”‘’"
PATTERN_SELECT_ALL = "全選"
PATTERN_CHOICES = (
    PATTERN_SELECT_ALL,
    "Morning Star (晨星)",
    "Evening Star (暮星)",
    "Shooting Star (射擊之星)",
    "Bullish Engulfing (多頭吞噬)",
    "Hammer (槌子)",
    "Hanging Man (吊人線)",
    "Meteor (流星)",
    "Bullish Harami (多頭母子)",
    "Bullish Harami Cross (多頭母子十字)",
    "Bearish Harami (空頭母子)",
    "Bearish Engulfing (陰吞噬)",
)

@dataclass
class ChartOptions:
    ticker: str
    display_days: int
    show_bollinger: bool
    selected_mas: tuple[int, ...]
    show_kd: bool
    show_rsi: bool
    show_macd: bool
    show_morning_star: bool
    show_evening_star: bool
    show_shooting_star: bool
    show_bullish_engulfing: bool
    show_hammer: bool
    show_hanging_man: bool
    show_meteor: bool
    show_bullish_harami: bool
    show_bullish_harami_cross: bool
    show_bearish_harami: bool
    show_bearish_engulfing: bool
    show_bullish_harami: bool
    show_bullish_harami_cross: bool
    show_bearish_harami: bool
    show_bearish_engulfing: bool

# -----------------------------
# 形態偵測函式
# -----------------------------
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

# -----------------------------
# 資料處理
# -----------------------------
def normalize_ticker(stock_id: str) -> str:
    ticker = stock_id.strip().upper()
    if not ticker: raise ValueError("請輸入代碼")
    if ticker.endswith(".IO"):
        return f"{ticker[:-3]}.TWO"
    return f"{ticker}.TW" if "." not in ticker else ticker

def is_pattern_selected(selected_patterns: list[str], pattern_name: str) -> bool:
    return PATTERN_SELECT_ALL in selected_patterns or pattern_name in selected_patterns

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
    data["Morning Star"] = detect_morning_star(data)
    data["Evening Star"] = detect_evening_star(data)
    data["Shooting Star"] = detect_shooting_star(data)
    data["Bullish Engulfing"] = detect_bullish_engulfing(data)
    data["Hammer"] = detect_hammer(data)
    data["Hanging Man"] = detect_hanging_man(data)
    data["Meteor"] = detect_meteor(data)
    data["Bullish Harami"] = detect_bullish_harami(data)
    data["Bullish Harami Cross"] = detect_bullish_harami_cross(data)
    data["Bearish Harami"] = detect_bearish_harami(data)
    data["Bearish Engulfing"] = detect_bearish_engulfing(data)

    return data.tail(options.display_days)

def get_non_trading_days(data: pd.DataFrame) -> list[str]:
    all_days = pd.date_range(start=data.index[0], end=data.index[-1])
    trading_days = {day.strftime("%Y-%m-%d") for day in data.index}
    return [
        day.strftime("%Y-%m-%d")
        for day in all_days
        if day.strftime("%Y-%m-%d") not in trading_days
    ]

def draw_chart(data: pd.DataFrame, options: ChartOptions):
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

    # K線
    fig.add_trace(go.Candlestick(
        x=data.index, open=data["Open"], high=data["High"], low=data["Low"], close=data["Close"],
        increasing_line_color="red", decreasing_line_color="green", name="K線"
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

    # 形態標記
    pattern_configs = [
        (options.show_morning_star, "Morning Star", "gold", "star", "Low", 0.97),
        (options.show_evening_star, "Evening Star", "violet", "star-diamond", "High", 1.03),
        (options.show_shooting_star, "Shooting Star", "cyan", "triangle-down", "High", 1.02)
    ]
    
    for show, col, color, symbol, pos, offset in pattern_configs:
        if show:
            sigs = data[data[col]]
            if not sigs.empty:
                fig.add_trace(go.Scatter(
                    x=sigs.index, y=sigs[pos] * offset, mode="markers",
                    marker=dict(color=color, size=12, symbol=symbol), name=col
                ), row=1, col=1)

    label_pattern_configs = [
        (options.show_bullish_engulfing, "Bullish Engulfing", "多頭吞噬", "Low", 0.965, "red", "white", "top"),
        (options.show_hammer, "Hammer", "槌子", "Low", 0.955, "red", "white", "top"),
        (options.show_hanging_man, "Hanging Man", "吊人線", "High", 1.045, "green", "black", "bottom"),
        (options.show_meteor, "Meteor", "流星", "High", 1.035, "green", "black", "bottom"),
        (options.show_bullish_harami, "Bullish Harami", "多頭母子", "Low", 0.945, "red", "white", "top"),
        (options.show_bullish_harami_cross, "Bullish Harami Cross", "多頭母子十字", "Low", 0.935, "red", "white", "top"),
        (options.show_bearish_harami, "Bearish Harami", "空頭母子", "High", 1.055, "green", "black", "bottom"),
        (options.show_bearish_engulfing, "Bearish Engulfing", "陰吞噬", "High", 1.065, "green", "black", "bottom"),
    ]
    for show, col, label, pos, offset, bg_color, font_color, yanchor in label_pattern_configs:
        if show:
            sigs = data[data[col]]
            for x_value, row in sigs.iterrows():
                fig.add_annotation(
                    x=x_value,
                    y=row[pos] * offset,
                    text=label,
                    showarrow=False,
                    bgcolor=bg_color,
                    bordercolor=bg_color,
                    borderpad=3,
                    font=dict(color=font_color, size=11),
                    yanchor=yanchor,
                    xref="x",
                    yref="y",
                )

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
# 主介面
# -----------------------------
def main():
    st.set_page_config(page_title="台股形態分析", layout="wide")
    st.title("📈 台股技術形態分析平台")

    with st.sidebar:
        st.header("設定")
        sid = st.text_input(
            "股票代碼",
            "2330.TW",
            help="上市請輸入 xxxx.TW，例如 2330.TW；上櫃請輸入 xxxx.TWO，例如 6208.TWO。",
        )
        st.caption("上市請輸入 xxxx.TW；上櫃請輸入 xxxx.TWO。")
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
            help="選擇全選會顯示所有 K 線型態標記。",
        )
        ms_on = is_pattern_selected(selected_patterns, "Morning Star (晨星)")
        es_on = is_pattern_selected(selected_patterns, "Evening Star (暮星)")
        ss_on = is_pattern_selected(selected_patterns, "Shooting Star (射擊之星)")
        be_on = is_pattern_selected(selected_patterns, "Bullish Engulfing (多頭吞噬)")
        hammer_on = is_pattern_selected(selected_patterns, "Hammer (槌子)")
        hanging_on = is_pattern_selected(selected_patterns, "Hanging Man (吊人線)")
        meteor_on = is_pattern_selected(selected_patterns, "Meteor (流星)")
        bullish_harami_on = is_pattern_selected(selected_patterns, "Bullish Harami (多頭母子)")
        bullish_harami_cross_on = is_pattern_selected(selected_patterns, "Bullish Harami Cross (多頭母子十字)")
        bearish_harami_on = is_pattern_selected(selected_patterns, "Bearish Harami (空頭母子)")
        bearish_engulfing_on = is_pattern_selected(selected_patterns, "Bearish Engulfing (陰吞噬)")

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
                ms_on,
                es_on,
                ss_on,
                be_on,
                hammer_on,
                hanging_on,
                meteor_on,
                bullish_harami_on,
                bullish_harami_cross_on,
                bearish_harami_on,
                bearish_engulfing_on,
            )
            data = get_stock_data(opts)
            st.session_state["stock_data"] = data
            st.session_state["chart_options"] = opts
            st.session_state.pop("ai_analysis", None)
            st.session_state.pop("ai_analysis_provider", None)

        except Exception as e:
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

        # 顯示訊號列表
        for name, flag in [
            ("Morning Star", opts.show_morning_star),
            ("Evening Star", opts.show_evening_star),
            ("Shooting Star", opts.show_shooting_star),
            ("Bullish Engulfing", opts.show_bullish_engulfing),
            ("Hammer", opts.show_hammer),
            ("Hanging Man", opts.show_hanging_man),
            ("Meteor", opts.show_meteor),
            ("Bullish Harami", opts.show_bullish_harami),
            ("Bullish Harami Cross", opts.show_bullish_harami_cross),
            ("Bearish Harami", opts.show_bearish_harami),
            ("Bearish Engulfing", opts.show_bearish_engulfing),
        ]:
            if flag:
                sigs = data[data[name]]
                if not sigs.empty:
                    st.write(f"✅ 近期 {name} 訊號：")
                    st.dataframe(sigs[["Open", "High", "Low", "Close", "Volume"]].sort_index(ascending=False))

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


if __name__ == "__main__":
    main()
