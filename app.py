# app.py
"""
台股 K 線圖分析（Streamlit Cloud 版）
功能：
1. 輸入台股代碼與查詢天數
2. 勾選：
   - 布林通道
   - 5/20/60 日均線
   - Morning Star
3. 顯示 K 線 + 成交量

需要套件：
pip install streamlit yfinance pandas plotly
"""

from dataclasses import dataclass
import datetime as dt

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
MA_WINDOWS = (5, 20, 60)


@dataclass
class ChartOptions:
    ticker: str
    display_days: int
    show_bollinger: bool
    show_moving_average: bool
    show_morning_star: bool


# -----------------------------
# 工具函式
# -----------------------------
def normalize_ticker(stock_id: str) -> str:
    """2330 -> 2330.TW"""
    ticker = stock_id.strip().upper()

    if not ticker:
        raise ValueError("股票代碼不可空白")

    if "." not in ticker:
        ticker = f"{ticker}.TW"

    return ticker


def detect_morning_star(data: pd.DataFrame) -> pd.Series:
    """簡化版 Morning Star"""
    signals = pd.Series(False, index=data.index)

    for i in range(2, len(data)):
        first = data.iloc[i - 2]
        second = data.iloc[i - 1]
        third = data.iloc[i]

        first_body = abs(first["Close"] - first["Open"])
        second_body = abs(second["Close"] - second["Open"])
        third_body = abs(third["Close"] - third["Open"])

        first_range = max(first["High"] - first["Low"], 1)
        third_range = max(third["High"] - third["Low"], 1)

        first_midpoint = (first["Open"] + first["Close"]) / 2

        first_is_long_bearish = (
            first["Close"] < first["Open"] and first_body >= first_range * 0.5
        )

        second_is_small_body = second_body <= first_body * 0.5

        third_is_strong_bullish = (
            third["Close"] > third["Open"]
            and third_body >= third_range * 0.4
            and third["Close"] >= first_midpoint
        )

        has_reversal_shape = (
            second["Low"] <= first["Close"]
            and third["Close"] > second["Close"]
        )

        signals.iloc[i] = (
            first_is_long_bearish
            and second_is_small_body
            and third_is_strong_bullish
            and has_reversal_shape
        )

    return signals


@st.cache_data(ttl=3600)
def get_stock_data(options: ChartOptions) -> pd.DataFrame:
    """抓取股價資料"""
    end_date = dt.datetime.today()
    max_window = max(MA_WINDOWS + (BOLLINGER_WINDOW,))
    fetch_days = max(options.display_days + max_window + 30, 160)

    start_date = end_date - dt.timedelta(days=fetch_days)

    data = yf.download(
        options.ticker,
        start=start_date,
        end=end_date + dt.timedelta(days=1),
        auto_adjust=False,
        progress=False,
    )

    if data.empty:
        raise ValueError(f"查無 {options.ticker} 的資料")

    # 若 yfinance 回傳 MultiIndex，轉單層
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data = data.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()

    # 均線
    for days in MA_WINDOWS:
        data[f"MA{days}"] = data["Close"].rolling(window=days).mean()

    # 布林通道
    data["STD20"] = data["Close"].rolling(window=BOLLINGER_WINDOW).std()
    data["Upper Band"] = data["MA20"] + (BOLLINGER_STD * data["STD20"])
    data["Lower Band"] = data["MA20"] - (BOLLINGER_STD * data["STD20"])

    # 成交量顏色
    data["Volume Color"] = data.apply(
        lambda row: "red" if row["Close"] >= row["Open"] else "green",
        axis=1,
    )

    # Morning Star
    data["Morning Star"] = detect_morning_star(data)

    return data.tail(options.display_days)


def get_non_trading_days(data: pd.DataFrame):
    """Plotly 跳過休市日"""
    all_days = pd.date_range(start=data.index[0], end=data.index[-1])

    trading_days = {day.strftime("%Y-%m-%d") for day in data.index}

    return [
        day.strftime("%Y-%m-%d")
        for day in all_days
        if day.strftime("%Y-%m-%d") not in trading_days
    ]


def draw_chart(data: pd.DataFrame, options: ChartOptions):
    """繪圖"""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.72, 0.28],
    )

    # K線
    fig.add_trace(
        go.Candlestick(
            x=data.index,
            open=data["Open"],
            high=data["High"],
            low=data["Low"],
            close=data["Close"],
            increasing_line_color="red",
            decreasing_line_color="green",
            increasing_fillcolor="red",
            decreasing_fillcolor="green",
            name="K線",
        ),
        row=1,
        col=1,
    )

    # 布林通道
    if options.show_bollinger:
        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=data["Upper Band"],
                mode="lines",
                line=dict(color="orange", dash="dash"),
                name="布林上軌",
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=data["Lower Band"],
                mode="lines",
                line=dict(color="orange", dash="dash"),
                name="布林下軌",
            ),
            row=1,
            col=1,
        )

    # 均線
    if options.show_moving_average:
        ma_styles = {
            "MA5": ("5日均線", "purple"),
            "MA20": ("20日均線", "blue"),
            "MA60": ("60日均線", "teal"),
        }

        for column, (label, color) in ma_styles.items():
            fig.add_trace(
                go.Scatter(
                    x=data.index,
                    y=data[column],
                    mode="lines",
                    line=dict(color=color, width=1.5),
                    name=label,
                ),
                row=1,
                col=1,
            )

    # Morning Star
    if options.show_morning_star:
        signals = data[data["Morning Star"]]

        if not signals.empty:
            fig.add_trace(
                go.Scatter(
                    x=signals.index,
                    y=signals["Low"] * 0.98,
                    mode="markers",
                    marker=dict(
                        color="gold",
                        size=14,
                        symbol="star",
                    ),
                    name="Morning Star",
                ),
                row=1,
                col=1,
            )

    # 成交量
    fig.add_trace(
        go.Bar(
            x=data.index,
            y=data["Volume"],
            marker_color=data["Volume Color"],
            name="成交量",
        ),
        row=2,
        col=1,
    )

    fig.update_xaxes(
        rangebreaks=[dict(values=get_non_trading_days(data))]
    )

    fig.update_layout(
        title=f"{options.ticker} 近 {options.display_days} 日 K線分析",
        template="plotly_white",
        height=850,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
    )

    return fig


# -----------------------------
# Streamlit UI
# -----------------------------
def main():
    st.set_page_config(
        page_title="台股技術分析平台",
        layout="wide",
    )

    st.title("📈 台股技術分析平台")
    st.caption("支援 K 線 / 布林通道 / 均線 / Morning Star")

    # Sidebar
    with st.sidebar:
        st.header("參數設定")

        stock_id = st.text_input(
            "台股代碼",
            value="2330",
            help="例如：2330、2317、0050",
        )

        display_days = st.slider(
            "查詢天數",
            min_value=30,
            max_value=365,
            value=120,
            step=10,
        )

        show_bollinger = st.checkbox("布林通道", value=True)
        show_moving_average = st.checkbox("5/20/60 日均線", value=True)
        show_morning_star = st.checkbox("Morning Star", value=True)

        run_button = st.button("開始分析", use_container_width=True)

    if run_button:
        try:
            options = ChartOptions(
                ticker=normalize_ticker(stock_id),
                display_days=display_days,
                show_bollinger=show_bollinger,
                show_moving_average=show_moving_average,
                show_morning_star=show_morning_star,
            )

            with st.spinner("抓取股價資料中..."):
                data = get_stock_data(options)

            # 最新資料
            latest = data.iloc[-1]

            col1, col2, col3, col4 = st.columns(4)

            col1.metric("最新收盤價", f"{latest['Close']:.2f}")
            col2.metric("最高價", f"{latest['High']:.2f}")
            col3.metric("最低價", f"{latest['Low']:.2f}")
            col4.metric("成交量", f"{int(latest['Volume']):,}")

            fig = draw_chart(data, options)
            st.plotly_chart(fig, use_container_width=True)

            # Morning Star 訊號表
            if show_morning_star:
                signals = data[data["Morning Star"]]

                if not signals.empty:
                    st.subheader("⭐ Morning Star 訊號")
                    st.dataframe(
                        signals[["Open", "High", "Low", "Close", "Volume"]].sort_index(
                            ascending=False
                        )
                    )
                else:
                    st.info("近期未偵測到 Morning Star")

        except Exception as e:
            st.error(f"發生錯誤：{e}")


if __name__ == "__main__":
    main()
