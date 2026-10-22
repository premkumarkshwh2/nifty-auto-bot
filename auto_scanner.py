import requests
import pandas as pd
import yfinance as yf
import os
import io
from datetime import datetime
import pytz

# GitHub Secrets se Token aur Chat ID lega
BOT_TOKEN = os.getenv("BOT_TOKEN", "8855321186:AAE6pMGrgT5VS9DHip3z6otENLPwRYRM4lo").strip()
CHAT_ID = os.getenv("CHAT_ID", "907465056").strip()

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
    """Sends clean text messages (auto-splits if message > 4000 chars, NO CSV)"""
    global CHAT_ID
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN or CHAT_ID missing!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # Split long messages safely so Telegram never blocks them
    lines = text.split("\n")
    chunk = []
    curr_len = 0
    for line in lines:
        if curr_len + len(line) + 1 > 3800:
            msg_part = "\n".join(chunk)
            r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg_part, "parse_mode": "HTML"})
            if r.status_code != 200:
                requests.post(url, json={"chat_id": CHAT_ID, "text": msg_part})
            chunk = [line]
            curr_len = len(line)
        else:
            chunk.append(line)
            curr_len += len(line) + 1
            
    if chunk:
        msg_part = "\n".join(chunk)
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg_part, "parse_mode": "HTML"})
        if r.status_code != 200:
            requests.post(url, json={"chat_id": CHAT_ID, "text": msg_part})

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
                curr_p, prev_p = round(float(close.iloc[-1]), 2), round(float(close.iloc[-2]), 2)
                curr_rsi, prev_rsi = round(float(rsi_s.iloc[-1]), 1), round(float(rsi_s.iloc[-2]), 1)
                curr_ema, prev_ema = round(float(ema_s.iloc[-1]), 2), round(float(ema_s.iloc[-2]), 2)
                sym = t.replace('.NS', '')

                if mode == "rsi60" and curr_rsi > 60:
                    results.append({'Symbol': sym, 'Price': curr_p, 'RSI': curr_rsi, 'EMA_50': curr_ema, 'Above_EMA': curr_p > curr_ema, 'Fresh': prev_rsi <= 60})
                elif mode == "rsi30" and curr_rsi < 30:
                    results.append({'Symbol': sym, 'Price': curr_p, 'RSI': curr_rsi, 'EMA_50': curr_ema, 'Above_EMA': curr_p > curr_ema, 'Fresh': prev_rsi >= 30})
                elif mode == "ema50" and curr_p > curr_ema:
                    results.append({'Symbol': sym, 'Price': curr_p, 'EMA_50': curr_ema, 'RSI': curr_rsi, 'Fresh': prev_p <= prev_ema})
        except Exception:
            continue

    if not results:
        send_telegram_msg(f"❌ <b>{title}:</b> Koi stock nahi mila.")
        return

    res_df = pd.DataFrame(results).sort_values(by='RSI', ascending=(mode == "rsi30"))
    total = len(res_df)
    lines = [f"<b>{title}</b>\nTotal Found: <b>{total} stocks</b>\n"]
    
    # Send top 60 stocks directly in message (no CSV)
    for _, r in res_df.head(60).iterrows():
        if mode == "ema50":
            tag = "🚀(New)" if r['Fresh'] else ""
            lines.append(f"• <code>{r['Symbol']}</code> | ₹{r['Price']} (EMA:{r['EMA_50']}) | RSI:{r['RSI']} {tag}")
        else:
            ema_tag = "✅>EMA" if r['Above_EMA'] else ""
            fresh_tag = "🔥(New)" if r['Fresh'] else ""
            lines.append(f"• <code>{r['Symbol']}</code> | ₹{r['Price']} | <b>RSI:{r['RSI']}</b> {ema_tag} {fresh_tag}")

    send_telegram_msg("\n".join(lines))

def process_user_commands(tickers):
    global CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        res = requests.get(url, timeout=10).json()
        if not res.get("ok") or not res.get("result"):
            return False

        now_ts = datetime.now().timestamp()
        recent_cmds = []
        last_update_id = None

        for item in res["result"]:
            last_update_id = item["update_id"]
            msg = item.get("message", {})
            if msg.get("chat", {}).get("id"):
                CHAT_ID = str(msg["chat"]["id"])
            msg_date = msg.get("date", 0)
            text = msg.get("text", "").strip()
            if (now_ts - msg_date) <= 600 and text.startswith("/"):
                recent_cmds.append(text)

        if last_update_id:
            requests.get(f"{url}?offset={last_update_id + 1}", timeout=5)

        force_full = False
        for cmd in recent_cmds:
            parts = cmd.split()
            base_cmd = parts[0].lower().split("@")[0]

            if base_cmd == "/check" and len(parts) >= 2:
                sym = parts[1].upper()
                ticker = f"{sym}.NS"
                reply = [f"📊 <b>{sym} — RSI (14) & 50 EMA Status</b>"]
                price_shown = False
                for tf_key, cfg in TIMEFRAMES.items():
                    df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False)
                    if not df.empty and len(df) > 50:
                        close = (df['Close'][ticker] if isinstance(df.columns, pd.MultiIndex) else df['Close']).dropna()
                        curr_p = round(float(close.iloc[-1]), 2)
                        if not price_shown:
                            reply.append(f"💰 <b>Live Price:</b> ₹{curr_p}\n")
                            price_shown = True
                        r_val = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                        e_val = round(float(calculate_ema(close, 50).iloc[-1]), 2)
                        r_icon = "🟢(>60)" if r_val > 60 else ("🔴(<30)" if r_val < 30 else "🟡")
                        e_icon = "📈 Above 50EMA" if curr_p > e_val else "📉 Below 50EMA"
                        reply.append(f"⏱ <b>{cfg['label']}:</b>\n   • RSI: <code>{r_val}</code> {r_icon}\n   • 50 EMA: <code>₹{e_val}</code> ({e_icon})")
                send_telegram_msg("\n".join(reply))

            elif base_cmd in COMMAND_MAP:
                tf_key, mode, title = COMMAND_MAP[base_cmd]
                run_specific_command_scan(tickers, tf_key, mode, title)

            elif base_cmd in ["/scan", "/start"]:
                force_full = True

        return force_full
    except Exception as e:
        print("Command check error:", e)
        return False

def run_smart_scan():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    now_str = now.strftime('%d-%b %I:%M %p')
    
    tickers = get_nifty500_tickers()
    cmd_requested_full = process_user_commands(tickers)
    
    is_morning_0900_scan = (
        (now.hour == 8 and now.minute >= 45) or 
        (now.hour == 9 and now.minute <= 10) or 
        os.getenv("FORCE_FULL_SCAN") == "true" or
        cmd_requested_full
    )
    
    # MODE 1: 09:00 AM FULL REPORT (Text Message Only, No CSV)
    if is_morning_0900_scan:
        msg_lines = [f"🌅 <b>Full RSI & 50 EMA Report ({now_str})</b>"]
        
        for tf_key, cfg in TIMEFRAMES.items():
            data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            gt60_list, lt30_list, ema50_list = [], [], []
            
            for t in tickers:
                try:
                    close = data[t]['Close'].dropna()
                    if len(close) > 50:
                        curr_p = round(float(close.iloc[-1]), 2)
                        curr_r = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                        curr_e = round(float(calculate_ema(close, 50).iloc[-1]), 2)
                        sym = t.replace('.NS', '')
                        
                        if curr_r > 60:
                            gt60_list.append(f"<code>{sym}</code>({curr_r})")
                        elif curr_r < 30:
                            lt30_list.append(f"<code>{sym}</code>({curr_r})")
                        if curr_p > curr_e:
                            ema50_list.append(f"<code>{sym}</code>")
                except Exception:
                    continue
                    
            msg_lines.append(
                f"\n📌 <b>{cfg['label']} Timeframe:</b>\n"
                f"🟢 <b>RSI > 60 ({len(gt60_list)}):</b> " + (", ".join(gt60_list[:20]) if gt60_list else "None") + "\n"
                f"🔴 <b>RSI < 30 ({len(lt30_list)}):</b> " + (", ".join(lt30_list[:20]) if lt30_list else "None") + "\n"
                f"📈 <b>Above 50 EMA ({len(ema50_list)} stocks)</b>"
            )
                
        send_telegram_msg("\n".join(msg_lines))

    # MODE 2: EVERY 5-MIN AUTO BREAKOUT & BREAKDOWN STATUS (Text Message Only)
    else:
        alert_lines = [f"⚡ <b>5-Min Auto Breakout Status ({now_str})</b>"]
        
        for tf_key, cfg in TIMEFRAMES.items():
            data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            new_rsi_bo, new_rsi_bd, new_ema_bo = [], [], []
            
            for t in tickers:
                try:
                    close = data[t]['Close'].dropna()
                    if len(close) > 50:
                        rsi = calculate_rsi(close, 14)
                        ema50 = calculate_ema(close, 50)
                        
                        curr_p, prev_p = round(float(close.iloc[-1]), 2), round(float(close.iloc[-2]), 2)
                        curr_r, prev_r = round(float(rsi.iloc[-1]), 1), round(float(rsi.iloc[-2]), 1)
                        curr_e, prev_e = round(float(ema50.iloc[-1]), 2), round(float(ema50.iloc[-2]), 2)
                        sym = t.replace('.NS', '')
                        
                        if curr_r > 60 and prev_r <= 60:
                            ema_tag = "✅>EMA" if curr_p > curr_e else ""
                            new_rsi_bo.append(f"<code>{sym}</code> (₹{curr_p} | RSI:{curr_r} {ema_tag})")
                        elif curr_r < 30 and prev_r >= 30:
                            new_rsi_bd.append(f"<code>{sym}</code> (₹{curr_p} | RSI:{curr_r})")
                        if curr_p > curr_e and prev_p <= prev_e:
                            new_ema_bo.append(f"<code>{sym}</code> (₹{curr_p} > EMA:{curr_e})")
                except Exception:
                    continue
            
            alert_lines.append(f"\n⏱ <b>{cfg['label']} Timeframe:</b>")
            alert_lines.append(f"🔥 <b>New RSI > 60 [{len(new_rsi_bo)}]:</b>\n" + ("\n".join(["• " + x for x in new_rsi_bo[:15]]) if new_rsi_bo else "• None"))
            alert_lines.append(f"❄️ <b>New RSI < 30 [{len(new_rsi_bd)}]:</b>\n" + ("\n".join(["• " + x for x in new_rsi_bd[:15]]) if new_rsi_bd else "• None"))
            alert_lines.append(f"🚀 <b>New > 50EMA [{len(new_ema_bo)}]:</b>\n" + ("\n".join(["• " + x for x in new_ema_bo[:15]]) if new_ema_bo else "• None"))
        
        send_telegram_msg("\n".join(alert_lines))

if __name__ == "__main__":
    run_smart_scan()
    
