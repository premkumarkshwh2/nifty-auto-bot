import requests
import pandas as pd
import yfinance as yf
import os
import io
from datetime import datetime
import time
import pytz

# Yahan apna Bot Token aur Chat ID daal dein (Agar Colab par hain)
BOT_TOKEN ="8855321186:AAE6pMGrgT5VS9DHip3z6otENLPwRYRM4lo "
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
    raise Exception("Nifty 500 list fetch nahi ho payi.")

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
        print("BOT_TOKEN or CHAT_ID missing!")
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

def run_specific_command_scan(tickers, tf_key, mode, title):
    cfg = TIMEFRAMES[tf_key]
    data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
    results = []

    for t in tickers:
        try:
            close = data[t]['Close'].dropna()
            if len(close) > 50:
                rsi_s = calculate_rsi(close, 14)
                ema_s = calculate_ema(close, 50)
                curr_p = round(float(close.iloc[-1]), 2)
                prev_p = round(float(close.iloc[-2]), 2)
                curr_rsi = round(float(rsi_s.iloc[-1]), 1)
                prev_rsi = round(float(rsi_s.iloc[-2]), 1)
                curr_ema = round(float(ema_s.iloc[-1]), 2)
                sym = t.replace('.NS', '')

                if mode == "rsi60" and curr_rsi > 60:
                    results.append({'Symbol': sym, 'Price': curr_p, 'RSI': curr_rsi, 'EMA_50': curr_ema, 'Fresh': prev_rsi <= 60})
                elif mode == "rsi30" and curr_rsi < 30:
                    results.append({'Symbol': sym, 'Price': curr_p, 'RSI': curr_rsi, 'EMA_50': curr_ema, 'Fresh': prev_rsi >= 30})
                elif mode == "ema50" and curr_p > curr_ema:
                    results.append({'Symbol': sym, 'Price': curr_p, 'EMA_50': curr_ema, 'RSI': curr_rsi, 'Fresh': prev_p <= prev_ema})
        except Exception:
            continue

    if not results:
        send_telegram_msg(f"❌ <b>{title}:</b> Koi stock nahi mila.")
        return

    res_df = pd.DataFrame(results).sort_values(by='RSI', ascending=(mode == "rsi30"))
    
    lines = [f"<b>{title}</b>\n<code>Symbol     | Price  | RSI  | Signal</code>\n<code>----------------------------------</code>"]
    for _, r in res_df.head(40).iterrows():
        tag = "RSI>60 🔥" if mode == "rsi60" else ("RSI<30 ❄️" if mode == "rsi30" else ">50EMA 🚀")
        lines.append(f"<code>{r['Symbol']:<10} | ₹{r['Price']:<6} | {r['RSI']:<4} | {tag}</code>")

    send_telegram_msg("\n".join(lines))

def process_user_commands(tickers):
    global CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        res = requests.get(url, timeout=10).json()
        if not res.get("ok") or not res.get("result"):
            return

        now_ts = datetime.now().timestamp()
        for item in res["result"]:
            msg = item.get("message", {})
            if msg.get("chat", {}).get("id"):
                CHAT_ID = str(msg["chat"]["id"])
            msg_date = msg.get("date", 0)
            text = msg.get("text", "").strip()
            
            if (now_ts - msg_date) <= 600 and text.startswith("/"):
                parts = text.split()
                base_cmd = parts[0].lower().split("@")[0]

                if base_cmd == "/check" and len(parts) >= 2:
                    sym = parts[1].upper()
                    ticker = f"{sym}.NS"
                    reply = [f"📊 <b>{sym} — Status</b>\n<code>TF   | Price  | RSI  | EMA50</code>\n<code>-------------------------</code>"]
                    for tf_key, cfg in TIMEFRAMES.items():
                        df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False)
                        if not df.empty and len(df) > 50:
                            close = (df['Close'][ticker] if isinstance(df.columns, pd.MultiIndex) else df['Close']).dropna()
                            curr_p = round(float(close.iloc[-1]), 2)
                            r_val = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                            e_val = round(float(calculate_ema(close, 50).iloc[-1]), 2)
                            reply.append(f"<code>{cfg['label']:<4} | ₹{curr_p:<5} | {r_val:<4} | {e_val}</code>")
                    send_telegram_msg("\n".join(reply))

                elif base_cmd in COMMAND_MAP:
                    tf_key, mode, title = COMMAND_MAP[base_cmd]
                    run_specific_command_scan(tickers, tf_key, mode, title)
    except Exception as e:
        print("Command check error:", e)

def run_smart_scan():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    now_str = now.strftime('%d-%b %I:%M %p')
    
    tickers = get_nifty500_tickers()
    
    # Sabse pehle user ki commands check karke turant jawab dega
    process_user_commands(tickers)
    
    is_morning_0900_scan = (now.hour == 9 and now.minute <= 10)
    
    # MODE 1: MORNING 9:00 AM FULL REPORT (Sabhi timeframes ki saaf list)
    if is_morning_0900_scan:
        for tf_key, cfg in TIMEFRAMES.items():
            data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            bo_rows, bd_rows = [], []
            
            for t in tickers:
                try:
                    close = data[t]['Close'].dropna()
                    if len(close) > 50:
                        curr_p = round(float(close.iloc[-1]), 2)
                        curr_r = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                        sym = t.replace('.NS', '')
                        
                        if curr_r > 60:
                            bo_rows.append(f"<code>{sym:<10} | ₹{curr_p:<6} | {curr_r:<4} | >60 🔥</code>")
                        elif curr_r < 30:
                            bd_rows.append(f"<code>{sym:<10} | ₹{curr_p:<6} | {curr_r:<4} | <30 ❄️</code>")
                except Exception:
                    continue
            
            if bo_rows:
                msg = [f"🌅 <b>{cfg['label']} — Morning RSI > 60 ({now_str})</b>", "<code>Symbol     | Price  | RSI  | Zone</code>", "<code>----------------------------------</code>"]
                msg.extend(bo_rows[:25])
                send_telegram_msg("\n".join(msg))
                
            if bd_rows:
                msg = [f"🌅 <b>{cfg['label']} — Morning RSI < 30 ({now_str})</b>", "<code>Symbol     | Price  | RSI  | Zone</code>", "<code>----------------------------------</code>", ]
                msg.extend(bd_rows[:25])
                send_telegram_msg("\n".join(msg))

    # MODE 2: EVERY 5-MIN AUTO BREAKOUT / BREAKDOWN STATUS (9:15 ke baad lagatar)
    else:
        for tf_key, cfg in TIMEFRAMES.items():
            data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            
            bo_rows, bd_rows, ema_rows = [], [], []
            
            for t in tickers:
                try:
                    close = data[t]['Close'].dropna()
                    if len(close) > 50:
                        rsi = calculate_rsi(close, 14)
                        ema50 = calculate_ema(close, 50)
                        
                        curr_p = round(float(close.iloc[-1]), 2)
                        prev_p = round(float(close.iloc[-2]), 2)
                        curr_r, prev_r = round(float(rsi.iloc[-1]), 1), round(float(rsi.iloc[-2]), 1)
                        curr_e = round(float(ema50.iloc[-1]), 2)
                        sym = t.replace('.NS', '')
                        
                        if curr_r > 60 and prev_r <= 60:
                            bo_rows.append(f"<code>{sym:<10} | ₹{curr_p:<6} | {curr_r:<4} | RSI>60 🔥</code>")
                        elif curr_r < 30 and prev_r >= 30:
                            bd_rows.append(f"<code>{sym:<10} | ₹{curr_p:<6} | {curr_r:<4} | RSI<30 ❄️</code>")
                        if curr_p > curr_e and prev_p <= prev_e:
                            ema_rows.append(f"<code>{sym:<10} | ₹{curr_p:<6} | {curr_e:<6} | >50EMA 🚀</code>")
                except Exception:
                    continue
            
            if bo_rows:
                msg = [f"🔥 <b>{cfg['label']} — RSI > 60 Breakout ({now_str})</b>", "<code>Symbol     | Price  | RSI  | Signal</code>", "<code>----------------------------------</code>"]
                msg.extend(bo_rows[:25])
                send_telegram_msg("\n".join(msg))
            
            if bd_rows:
                msg = [f"❄️ <b>{cfg['label']} — RSI < 30 Breakdown ({now_str})</b>", "<code>Symbol     | Price  | RSI  | Signal</code>", "<code>----------------------------------</code>"]
                msg.extend(bd_rows[:25])
                send_telegram_msg("\n".join(msg))
            
            if ema_rows:
                msg = [f"🚀 <b>{cfg['label']} — Price > 50 EMA ({now_str})</b>", "<code>Symbol     | Price  | EMA50  | Signal</code>", "<code>----------------------------------</code>"]
                msg.extend(ema_rows[:25])
                send_telegram_msg("\n".join(msg))

if __name__ == "__main__":
    print("Bot is running continuously...")
    while True:
        try:
            run_smart_scan()
        except Exception as e:
            print("Error:", e)
        print("Waiting 5 minutes for next scan...")
        time.sleep(300) # Har 5 minute mein auto-scan chalega
