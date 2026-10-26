import requests
import pandas as pd
import yfinance as yf
import io
from datetime import datetime
import time
import pytz

# Apna Bot Token aur Chat ID yahan daal dein
BOT_TOKEN = "8855321186:AAE6pMGrgT5VS9DHip3z6otENLPwRYRM4lo"
CHAT_ID = "907465056"
LAST_UPDATE_ID = 0

TIMEFRAMES = {
    "1h":  {"interval": "1h",  "period": "1mo", "label": "1 Hour"},
    "1d":  {"interval": "1d",  "period": "3mo", "label": "1 Day"},
    "1wk": {"interval": "1wk", "period": "1y",  "label": "1 Week"}
}

COMMAND_MAP = {
    "/rsi60_1h": ("1h", "rsi60", "🟢 1 Hour RSI > 60"),
    "/rsi60_1d": ("1d", "rsi60", "🟢 1 Day RSI > 60"),
    "/rsi60_1w": ("1wk", "rsi60", "🟢 1 Week RSI > 60"),
    "/rsi30_1h": ("1h", "rsi30", "🔴 1 Hour RSI < 30"),
    "/rsi30_1d": ("1d", "rsi30", "🔴 1 Day RSI < 30"),
    "/rsi30_1w": ("1wk", "rsi30", "🔴 1 Week RSI < 30"),
    "/ema50_1h": ("1h", "ema50", "📈 1 Hour Price > 50 EMA"),
    "/ema50_1d": ("1d", "ema50", "📈 1 Day Price > 50 EMA"),
    "/ema50_1w": ("1wk", "ema50", "📈 1 Week Price > 50 EMA"),
}

def get_nifty_tickers():
    """Nifty tickers fetch karne ke liye safe function"""
    headers = {"User-Agent": "Mozilla/5.0"}
    urls = [
        "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
        "https://raw.githubusercontent.com/kprohith/nse-stock-analysis/master/ind_nifty50list.csv"
    ]
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                df = pd.read_csv(io.StringIO(res.text))
                tickers = [f"{str(s).strip()}.NS" for s in df['Symbol'].dropna().tolist()]
                if len(tickers) > 10:
                    return tickers
        except Exception:
            continue
    # Fallback default tickers agar NSE block kare
    return ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS"]

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ema(series, period=50):
    return series.ewm(span=period, adjust=False).mean()

def send_telegram_msg(text):
    global CHAT_ID
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    lines = text.split("\n")
    chunk, curr_len = [], 0
    for line in lines:
        if curr_len + len(line) + 1 > 3800:
            requests.post(url, json={"chat_id": CHAT_ID, "text": "\n".join(chunk), "parse_mode": "HTML"})
            chunk, curr_len = [line], len(line)
        else:
            chunk.append(line)
            curr_len += len(line) + 1
    if chunk:
        requests.post(url, json={"chat_id": CHAT_ID, "text": "\n".join(chunk), "parse_mode": "HTML"})

def get_close_series(data, ticker):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if ticker in data['Close']:
                return data['Close'][ticker].dropna()
        elif 'Close' in data:
            return data['Close'].dropna()
    except Exception:
        pass
    return pd.Series(dtype=float)

def run_specific_command_scan(tickers, tf_key
            
