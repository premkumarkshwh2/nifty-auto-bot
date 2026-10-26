import requests
import pandas as pd
import yfinance as yf
import io
from datetime import datetime
import time
import pytz

# Apna Telegram Bot Token aur Chat ID yahan daal dein
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

def get_nifty500_tickers():
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
    urls = [
        "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "https://raw.githubusercontent.com/kprohith/nse-stock-analysis/master/ind_nifty500list.csv"
    ]
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200 and "Symbol" in res.text:
                df = pd.read_csv(io.StringIO(res.text))
                tickers = [f"{str(s).strip()}.NS" for s in df['Symbol'].dropna().tolist() if "NIFTY" not in str(s)]
                if len(tickers) > 100:
                    return tickers
        except Exception:
            continue
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

def run_specific_command_scan(tickers, tf_key, mode, title):
    cfg = TIMEFRAMES[tf_key]
    send_telegram_msg(f"⏳ Scanning {title} (Nifty 500)...")
    
    results = []
    batch_size = 40
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        try:
            data = yf.download(batch, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            for t in batch:
                try:
                    close = get_close_series(data, t)
                    if len(close) > 15:
                        rsi_s = calculate_rsi(close, 14)
                        ema_s = calculate_ema(close, 50)
                        curr_p = round(float(close.iloc[-1]), 2)
                        curr_rsi = round(float(rsi_s.iloc[-1]), 1)
                        curr_ema = round(float(ema_s.iloc[-1]), 2)
                        sym = t.replace('.NS', '')

                        if mode == "rsi60" and curr_rsi > 60:
                            results.append({'Symbol': sym, 'Price': curr_p, 'Val': curr_rsi, 'Tag': 'RSI>60 🔥'})
                        elif mode == "rsi30" and curr_rsi < 30:
                            results.append({'Symbol': sym, 'Price': curr_p, 'Val': curr_rsi, 'Tag': 'RSI<30 ❄️'})
                        elif mode == "ema50" and curr_p > curr_ema:
                            results.append({'Symbol': sym, 'Price': curr_p, 'Val': curr_ema, 'Tag': '>50EMA 🚀'})
                except Exception:
                    continue
        except Exception:
            continue

    if not results:
        send_telegram_msg(f"❌ <b>{title}:</b> Is samay koi bhi stock match nahi hua.")
        return

    # Agar mode rsi30 hai toh ascending=True rakhenge taaki sabse kam RSI sabse upar dikhe
    res_df = pd.DataFrame(results).sort_values(by='Val', ascending=(mode == "rsi30"))
    lines = [f"<b>{title}</b>\n<code>Symbol     | Price  | Value  | Signal</code>\n<code>----------------------------------</code>"]
    for _, r in res_df.head(30).iterrows():
        lines.append(f"<code>{r['Symbol']:<10} | ₹{r['Price']:<6} | {r['Val']:<6} | {r['Tag']}</code>")
    send_telegram_msg("\n".join(lines))

def run_full_scan_report(tickers):
    send_telegram_msg("🔍 <b>Nifty 500 Full All-in-One Report Scan Shuru ho gaya hai...</b>")
    cfg = TIMEFRAMES["1d"]
    results_bo, results_bd = [], []
    
    batch_size = 40
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        try:
            data = yf.download(batch, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            for t in batch:
                try:
                    close = get_close_series(data, t)
                    if len(close) > 15:
                        curr_p = round(float(close.iloc[-1]), 2)
                        curr_r = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                        sym = t.replace('.NS', '')
                        if curr_r > 60:
                            results_bo.append(f"<code>{sym:<10} | ₹{curr_p:<6} | {curr_r:<4} | >60 🔥</code>")
                        elif curr_r < 30:
                            results_bd.append(f"<code>{sym:<10} | ₹{curr_p:<6} | {curr_r:<4} | <30 ❄️</code>")
                except Exception:
                    continue
        except Exception:
            continue

    if results_bo:
        msg = [f"📊 <b>1 Day — Nifty 500 RSI > 60 Report</b>", "<code>Symbol     | Price  | RSI  | Zone</code>", "<code>----------------------------------</code>"]
        msg.extend(results_bo[:25])
        send_telegram_msg("\n".join(msg))
        
    if results_bd:
        msg = [f"📊 <b>1 Day — Nifty 500 RSI < 30 Report</b>", "<code>Symbol     | Price  | RSI  | Zone</code>", "<code>----------------------------------</code>"]
        msg.extend(results_bd[:25])
        send_telegram_msg("\n".join(msg))
    else:
        send_telegram_msg("📊 <b>1 Day — RSI < 30 Report:</b> Is samay 1 Day timeframe par koi bhi stock RSI < 30 mein nahi hai.")

def process_user_commands(tickers):
    global CHAT_ID, LAST_UPDATE_ID
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={LAST_UPDATE_ID}&timeout=2"
        res = requests.get(url, timeout=5).json()
        if not res.get("ok") or not res.get("result"):
            return

        for item in res["result"]:
            LAST_UPDATE_ID = item["update_id"] + 1
            msg = item.get("message", {})
            if msg.get("chat", {}).get("id"):
                CHAT_ID = str(msg["chat"]["id"])
            text = msg.get("text", "").strip()
            
            if text.startswith("/"):
                parts = text.split()
                base_cmd = parts[0].lower().split("@")[0]

                if base_cmd == "/check" and len(parts) >= 2:
                    sym = parts[1].upper()
                    ticker = f"{sym}.NS"
                    reply = [f"📊 <b>{sym} — Status</b>\n<code>TF   | Price  | RSI  | EMA50</code>\n<code>-------------------------</code>"]
                    for tf_key, cfg in TIMEFRAMES.items():
                        try:
                            df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False)
                            if not df.empty:
                                close = get_close_series(df, ticker)
                                if len(close) > 15:
                                    curr_p = round(float(close.iloc[-1]), 2)
                                    r_val = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                                    e_val = round(float(calculate_ema(close, 50).iloc[-1]), 2)
                                    reply.append(f"<code>{cfg['label']:<4} | ₹{curr_p:<5} | {r_val:<4} | {e_val}</code>")
                        except Exception:
                            continue
                    send_telegram_msg("\n".join(reply))

                elif base_cmd == "/scan":
                    run_full_scan_report(tickers)

                elif base_cmd in COMMAND_MAP:
                    tf_key, mode, title = COMMAND_MAP[base_cmd]
                    run_specific_command_scan(tickers, tf_key, mode, title)
    except Exception as e:
        print("Command error:", e)

if __name__ == "__main__":
    print("Bot started successfully and listening for commands & 15-min auto-updates...")
    tickers = get_nifty500_tickers()
    print(f"Total Nifty 500 Tickers Loaded: {len(tickers)}")
    
    last_auto_scan_time = 0
    AUTO_SCAN_INTERVAL = 900 # 15 minutes

    while True:
        try:
            current_time = time.time()
            
            # Har 15 minute mein automatic scan chalega
            if current_time - last_auto_scan_time >= AUTO_SCAN_INTERVAL:
                send_telegram_msg("⏰ <b>15-Minute Auto-Scan Update Shuru ho raha hai...</b>")
                run_full_scan_report(tickers)
                last_auto_scan_time = time.time()

            # Commands ke liye lagatar check karega
            process_user_commands(tickers)
            
        except Exception as e:
            print("Error:", e)
        
        time.sleep(3)
