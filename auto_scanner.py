import requests
import pandas as pd
import yfinance as yf
import os
import io
from datetime import datetime, date
import time
import pytz
import warnings
import logging
import threading

warnings.simplefilter(action='ignore', category=FutureWarning)
logger = logging.getLogger('yfinance')
logger.setLevel(logging.CRITICAL)

BOT_TOKEN = "8855321186:AAE6pMGrgT5VS9DHip3z6otENLPwRYRM4lo"
CHAT_ID = "907465056"

TIMEFRAMES = {
    "1h":  {"interval": "1h",  "period": "3mo", "label": "1 Hour"},
    "1d":  {"interval": "1d",  "period": "6mo", "label": "1 Day"},
    "1wk": {"interval": "1wk", "period": "2y",  "label": "1 Week"}
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

CACHED_TICKERS = []
LAST_FETCH_DATE = None
LAST_HIGHER_TF_SCAN = 0

def get_nifty500_tickers():
    global CACHED_TICKERS, LAST_FETCH_DATE
    today = date.today()
    if CACHED_TICKERS and LAST_FETCH_DATE == today:
        return CACHED_TICKERS

    urls = [
        "https://raw.githubusercontent.com/kprohith/nse-stock-analysis/master/ind_nifty500list.csv",
        "https://raw.githubusercontent.com/anuj-singh-01/nse-stocks-list/main/ind_nifty500list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200 and ("Symbol" in res.text or "symbol" in res.text):
                df = pd.read_csv(io.StringIO(res.text))
                col_name = 'Symbol' if 'Symbol' in df.columns else ('SYMBOL' if 'SYMBOL' in df.columns else df.columns[0])
                tickers = [f"{str(s).strip()}.NS" for s in df[col_name].dropna().tolist() if "NIFTY" not in str(s)]
                if len(tickers) > 100:
                    CACHED_TICKERS = tickers
                    LAST_FETCH_DATE = today
                    return tickers
        except Exception:
            continue
            
    if CACHED_TICKERS:
        return CACHED_TICKERS
    raise Exception("Nifty 500 list kisi bhi source se fetch nahi ho payi.")

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
    chunk = []
    curr_len = 0
    for line in lines:
        if curr_len + len(line) + 1 > 3800:
            msg_part = "\n".join(chunk)
            requests.post(url, json={"chat_id": CHAT_ID, "text": msg_part, "parse_mode": "HTML"})
            chunk = [line]
            curr_len = len(line)
        else:
            chunk.append(line)
            curr_len += len(line) + 1

    if chunk:
        msg_part = "\n".join(chunk)
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg_part, "parse_mode": "HTML"})

def extract_close_series(data, t):
    """Safely extract Close price series for a ticker from multiindex or single index yfinance download."""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if t in data.columns.levels[1]:
                s = data[('Close', t)].dropna()
                return s
        else:
            if 'Close' in data.columns:
                return data['Close'].dropna()
    except Exception:
        pass
    return pd.Series(dtype=float)

def run_specific_command_scan(tickers, tf_key, mode, title):
    try:
        send_telegram_msg(f"⏳ <b>{title}</b> ke liye scan shuru ho gaya hai, kripya 10-15 seconds intezaar karein...")
        cfg = TIMEFRAMES[tf_key]
        results = []

        data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True, auto_adjust=False)

        for t in tickers:
            try:
                close = extract_close_series(data, t)
                if len(close) > 30:
                    rsi_s = calculate_rsi(close, 14)
                    ema_s = calculate_ema(close, 50)
                    
                    if rsi_s.empty or ema_s.empty:
                        continue
                        
                    curr_p = round(float(close.iloc[-1]), 2)
                    curr_rsi = round(float(rsi_s.iloc[-1]), 1)
                    curr_ema = round(float(ema_s.iloc[-1]), 2)
                    sym = t.replace('.NS', '')

                    if pd.isna(curr_rsi):
                        continue

                    if mode == "rsi60" and curr_rsi > 60:
                        results.append({'Symbol': sym, 'Price': curr_p, 'RSI': curr_rsi})
                    elif mode == "rsi30" and curr_rsi < 30:
                        results.append({'Symbol': sym, 'Price': curr_p, 'RSI': curr_rsi})
                    elif mode == "ema50" and not pd.isna(curr_ema) and curr_p > curr_ema:
                        results.append({'Symbol': sym, 'Price': curr_p, 'EMA50': curr_ema})
            except Exception:
                continue

        if not results:
            send_telegram_msg(f"❌ <b>{title}:</b> Is samay criteria match karne wala koi stock nahi mila.")
            return

        is_rsi = "rsi" in mode

        if is_rsi:
            res_df = pd.DataFrame(results).sort_values(by='RSI', ascending=(mode == "rsi30"))
            lines = [f"<b>{title}</b>\n<code>Symbol     | Price    | RSI</code>\n<code>------------------------------</code>"]
            for _, r in res_df.head(30).iterrows():
                lines.append(f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} | {r['RSI']:<5}</code>")
        else:
            res_df = pd.DataFrame(results).sort_values(by='Price', ascending=False)
            lines = [f"<b>{title}</b>\n<code>Symbol     | Price    | 50 EMA</code>\n<code>------------------------------</code>"]
            for _, r in res_df.head(30).iterrows():
                lines.append(f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} | ₹{r['EMA50']:<6}</code>")

        send_telegram_msg("\n".join(lines))
    except Exception as e:
        send_telegram_msg(f"⚠️ Command error: {str(e)}")

def process_user_commands(tickers):
    global CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        res = requests.get(url, timeout=10).json()
        if not res.get("ok") or not res.get("result"):
            return

        now_ts = datetime.now().timestamp()
        last_update_id = None

        for item in res["result"]:
            last_update_id = item["update_id"]
            msg = item.get("message", {})
            if msg.get("chat", {}).get("id"):
                CHAT_ID = str(msg["chat"]["id"])
            msg_date = msg.get("date", 0)
            text = msg.get("text", "").strip()

            if (now_ts - msg_date) <= 900 and text.startswith("/"):
                parts = text.split()
                base_cmd = parts[0].lower().split("@")[0]

                if base_cmd == "/check" and len(parts) >= 2:
                    sym = parts[1].upper()
                    ticker = f"{sym}.NS"
                    reply = [f"📊 <b>{sym} — Status</b>\n<code>TF   | Price  | RSI  | EMA50</code>\n<code>-------------------------</code>"]
                    for tf_key, cfg in TIMEFRAMES.items():
                        try:
                            df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False, auto_adjust=False)
                            close = extract_close_series(df, ticker)
                            if len(close) > 30:
                                curr_p = round(float(close.iloc[-1]), 2)
                                r_val = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                                e_val = round(float(calculate_ema(close, 50).iloc[-1]), 2)
                                reply.append(f"<code>{cfg['label']:<4} | ₹{curr_p:<5} | {r_val:<4} | {e_val}</code>")
                        except Exception as tf_err:
                            continue
                    
                    if len(reply) > 1:
                        send_telegram_msg("\n".join(reply))
                    else:
                        send_telegram_msg(f"❌ <b>{sym}:</b> Data fetch nahi ho paya ya symbol galat hai.")

                elif base_cmd in COMMAND_MAP:
                    tf_key, mode, title = COMMAND_MAP[base_cmd]
                    run_specific_command_scan(tickers, tf_key, mode, title)

        if last_update_id:
            requests.get(f"{url}?offset={last_update_id + 1}", timeout=5)

    except Exception as e:
        print("Command check error:", e)

def background_command_listener():
    while True:
        try:
            tickers = get_nifty500_tickers()
            process_user_commands(tickers)
        except Exception as e:
            pass
        time.sleep(5)

def run_smart_scan():
    global LAST_HIGHER_TF_SCAN
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    now_str = now.strftime('%d-%b %I:%M %p')

    current_hour = now.hour
    current_min = now.minute
    total_mins = current_hour * 60 + current_min

    is_market_active = (9 * 60 <= total_mins <= 16 * 60)
    tickers = get_nifty500_tickers()

    if not is_market_active:
        print(f"[{now_str}] Market closed hours. Auto-scan paused, but commands are active...")
        return

    is_morning_0900_scan = (current_hour == 9 and current_min <= 10)

    timeframes_to_scan = ["1h"]
    current_ts = time.time()
    should_scan_higher_tf = is_morning_0900_scan or (current_ts - LAST_HIGHER_TF_SCAN >= 1800)

    if should_scan_higher_tf:
        timeframes_to_scan = ["1h", "1d", "1wk"]
        LAST_HIGHER_TF_SCAN = current_ts

    for tf_key in timeframes_to_scan:
        cfg = TIMEFRAMES[tf_key]
        data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True, auto_adjust=False)
        bo_list, bd_list, ema_list = [], [], []

        for t in tickers:
            try:
                close = extract_close_series(data, t)
                if len(close) > 30:
                    rsi = calculate_rsi(close, 14)
                    ema50 = calculate_ema(close, 50)

                    curr_p = round(float(close.iloc[-1]), 2)
                    curr_r = round(float(rsi.iloc[-1]), 1)
                    curr_e = round(float(ema50.iloc[-1]), 2)
                    sym = t.replace('.NS', '')

                    if pd.isna(curr_r):
                        continue

                    # Auto-scan logic for RSI > 60 and RSI < 30
                    if curr_r > 60:
                        bo_list.append({'Symbol': sym, 'Price': curr_p, 'RSI': curr_r})
                    if curr_r < 30:
                        bd_list.append({'Symbol': sym, 'Price': curr_p, 'RSI': curr_r})
                    
                    if not pd.isna(curr_e) and curr_p > curr_e:
                        ema_list.append({'Symbol': sym, 'Price': curr_p, 'EMA50': curr_e})
            except Exception:
                continue

        if bo_list:
            bo_df = pd.DataFrame(bo_list).sort_values(by='RSI', ascending=False)
            msg = [f"🔥 <b>{cfg['label']} — RSI > 60 Scan ({now_str})</b>", "<code>Symbol     | Price    | RSI</code>", "<code>------------------------------</code>"]
            for _, r in bo_df.head(25).iterrows():
                msg.append(f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} | {r['RSI']:<5}</code>")
            send_telegram_msg("\n".join(msg))

        if bd_list:
            bd_df = pd.DataFrame(bd_list).sort_values(by='RSI', ascending=True)
            msg = [f"❄️ <b>{cfg['label']} — RSI < 30 Oversold Scan ({now_str})</b>", "<code>Symbol     | Price    | RSI</code>", "<code>------------------------------</code>"]
            for _, r in bd_df.head(25).iterrows():
                msg.append(f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} | {r['RSI']:<5}</code>")
            send_telegram_msg("\n".join(msg))

        if ema_list and not is_morning_0900_scan:
            ema_df = pd.DataFrame(ema_list).sort_values(by='Price', ascending=False)
            msg = [f"🚀 <b>{cfg['label']} — Price > 50 EMA ({now_str})</b>", "<code>Symbol     | Price    | 50 EMA</code>", "<code>------------------------------</code>"]
            for _, r in ema_df.head(25).iterrows():
                msg.append(f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} | ₹{r['EMA50']:<6}</code>")
            send_telegram_msg("\n".join(msg))

if __name__ == "__main__":
    print("Bot is running continuously with background command listener...")
    send_telegram_msg("🤖 Bot successfully start ho gaya hai aur commands ab independent thread par active hain!")
    
    listener_thread = threading.Thread(target=background_command_listener, daemon=True)
    listener_thread.start()
    
    while True:
        try:
            run_smart_scan()
        except Exception as e:
            print("Error:", e)
        print("Waiting 5 minutes for next scan...")
        time.sleep(300)
    
