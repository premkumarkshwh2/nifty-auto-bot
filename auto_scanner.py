import requests
import pandas as pd
import yfinance as yf
import os
import io
from datetime import datetime
import pytz

# GitHub Secrets se Token aur Chat ID lega
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TIMEFRAMES = {
    "1h":  {"interval": "1h",  "period": "3mo", "label": "1 Hour"},
    "1d":  {"interval": "1d",  "period": "6mo", "label": "1 Day"},
    "1wk": {"interval": "1wk", "period": "2y",  "label": "1 Week"}
}

# Command Mapping Dictionary
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.nseindia.com/"
    }
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
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})

def send_telegram_file(filepath, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(filepath, "rb") as f:
        requests.post(url, data={"chat_id": CHAT_ID, "caption": caption}, files={"document": f})

# ==========================================================
# SINGLE SPECIFIC COMMAND SCANNER (RSI60, RSI30, OR EMA50)
# ==========================================================
def run_specific_command_scan( tickers, tf_key, mode, title ):
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
                prev_ema = round(float(ema_s.iloc[-2]), 2)
                sym = t.replace('.NS', '')

                if mode == "rsi60" and curr_rsi > 60:
                    results.append({
                        'Symbol': sym, 'Price': curr_p, 'RSI': curr_rsi, 'EMA_50': curr_ema,
                        'Above_50EMA': 'Yes ✅' if curr_p > curr_ema else 'No',
                        'Fresh_Breakout': 'YES 🔥' if prev_rsi <= 60 else 'No'
                    })
                elif mode == "rsi30" and curr_rsi < 30:
                    results.append({
                        'Symbol': sym, 'Price': curr_p, 'RSI': curr_rsi, 'EMA_50': curr_ema,
                        'Above_50EMA': 'Yes ✅' if curr_p > curr_ema else 'No',
                        'Fresh_Breakdown': 'YES ❄️' if prev_rsi >= 30 else 'No'
                    })
                elif mode == "ema50" and curr_p > curr_ema:
                    pct_diff = round(((curr_p - curr_ema) / curr_ema) * 100, 2)
                    results.append({
                        'Symbol': sym, 'Price': curr_p, 'EMA_50': curr_ema, 'Diff_%': pct_diff,
                        'RSI': curr_rsi, 'Fresh_EMA_Cross': 'YES 🚀' if prev_p <= prev_ema else 'No'
                    })
        except Exception:
            continue

    if not results:
        send_telegram_msg(f"❌ *{title}:* Koi stock nahi mila.")
        return

    res_df = pd.DataFrame(results)
    if mode == "rsi60":
        res_df = res_df.sort_values(by='RSI', ascending=False)
    elif mode == "rsi30":
        res_df = res_df.sort_values(by='RSI', ascending=True)
    else:
        res_df = res_df.sort_values(by='RSI', ascending=False)

    total = len(res_df)
    lines = [f"{title}\nTotal Found: *{total} stocks*\n\n*Top 25 Stocks:*"]
    for _, r in res_df.head(25).iterrows():
        if mode == "ema50":
            tag = "🚀" if "YES" in r['Fresh_EMA_Cross'] else ""
            lines.append(f"• `{r['Symbol']:<10}` | ₹{r['Price']} (EMA: {r['EMA_50']}) | RSI: {r['RSI']} {tag}")
        else:
            ema_tag = "✅>EMA" if "Yes" in r['Above_50EMA'] else ""
            lines.append(f"• `{r['Symbol']:<10}` | ₹{r['Price']} | *RSI: {r['RSI']}* {ema_tag}")

    send_telegram_msg("\n".join(lines))
    csv_name = f"Scan_{mode}_{tf_key}.csv"
    res_df.to_csv(csv_name, index=False)
    send_telegram_file(csv_name, f"📂 Full List ({total} stocks) — {title}")
    os.remove(csv_name)

# ==========================================================
# CHECK TELEGRAM COMMANDS SENT BY USER
# ==========================================================
def process_user_commands(tickers):
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
            msg_date = msg.get("date", 0)
            text = msg.get("text", "").strip()
            if (now_ts - msg_date) <= 1200 and text.startswith("/"):
                recent_cmds.append(text)

        if last_update_id:
            requests.get(f"{url}?offset={last_update_id + 1}", timeout=5)

        force_full = False
        for cmd in recent_cmds:
            parts = cmd.split()
            base_cmd = parts[0].lower().split("@")[0]

            # 1. Single Stock Check (/check RELIANCE)
            if base_cmd == "/check" and len(parts) >= 2:
                sym = parts[1].upper()
                ticker = f"{sym}.NS"
                reply = [f"📊 *{sym} — RSI (14) & 50 EMA Status*"]
                price_shown = False
                for tf_key, cfg in TIMEFRAMES.items():
                    df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False)
                    if not df.empty and len(df) > 50:
                        close = (df['Close'][ticker] if isinstance(df.columns, pd.MultiIndex) else df['Close']).dropna()
                        curr_p = round(float(close.iloc[-1]), 2)
                        if not price_shown:
                            reply.append(f"💰 *Live Price:* ₹{curr_p}\n")
                            price_shown = True
                        r_val = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                        e_val = round(float(calculate_ema(close, 50).iloc[-1]), 2)
                        r_icon = "🟢(>60)" if r_val > 60 else ("🔴(<30)" if r_val < 30 else "🟡")
                        e_icon = "📈 Above 50EMA" if curr_p > e_val else "📉 Below 50EMA"
                        reply.append(f"⏱ *{cfg['label']}:*\n   • RSI: `{r_val}` {r_icon}\n   • 50 EMA: `₹{e_val}` ({e_icon})")
                send_telegram_msg("\n".join(reply))

            # 2. Specific Timeframe Commands (/rsi60_1h, /ema50_1d, etc.)
            elif base_cmd in COMMAND_MAP:
                tf_key, mode, title = COMMAND_MAP[base_cmd]
                run_specific_command_scan(tickers, tf_key, mode, title)

            # 3. Full Scan Command (/scan)
            elif base_cmd in ["/scan", "/start"]:
                force_full = True

        return force_full
    except Exception as e:
        print("Command check error:", e)
        return False

# ==========================================================
# MAIN SMART SCANNER (09:00 AM FULL + 15-MIN AUTO BREAKOUTS)
# ==========================================================
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
    
    # MODE 1: 09:00 AM FULL REPORT (RSI > 60, RSI < 30, & PRICE > 50 EMA)
    if is_morning_0900_scan:
        msg_lines = [f"🌅 *09:00 AM Full RSI & 50 EMA Report ({now_str})*\n_(Timeframes: 1 Hour, 1 Day, 1 Week)_"]
        all_records = []
        
        for tf_key, cfg in TIMEFRAMES.items():
            data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            gt60_cnt, lt30_cnt, ema50_cnt, combo_list = 0, 0, 0, []
            
            for t in tickers:
                try:
                    close = data[t]['Close'].dropna()
                    if len(close) > 50:
                        rsi = calculate_rsi(close, 14)
                        ema50 = calculate_ema(close, 50)
                        
                        curr_p = round(float(close.iloc[-1]), 2)
                        curr_r = round(float(rsi.iloc[-1]), 1)
                        curr_e = round(float(ema50.iloc[-1]), 2)
                        sym = t.replace('.NS', '')
                        
                        above_ema = curr_p > curr_e
                        if above_ema:
                            ema50_cnt += 1
                        if curr_r > 60:
                            gt60_cnt += 1
                        elif curr_r < 30:
                            lt30_cnt += 1
                            
                        if curr_r > 60 and above_ema:
                            combo_list.append(f"`{sym}`({curr_r})")
                            
                        if curr_r > 60 or curr_r < 30 or above_ema:
                            all_records.append({
                                'Timeframe': cfg['label'], 'Symbol': sym, 'Price': curr_p,
                                'EMA_50': curr_e, 'Price_Above_50EMA': 'YES' if above_ema else 'No',
                                'RSI_14': curr_r,
                                'RSI_Zone': 'Bullish (>60)' if curr_r > 60 else ('Oversold (<30)' if curr_r < 30 else 'Neutral')
                            })
                except Exception:
                    continue
                    
            msg_lines.append(
                f"\n📌 *{cfg['label']} Summary:*\n"
                f"   🟢 RSI > 60: *{gt60_cnt}* | 🔴 RSI < 30: *{lt30_cnt}*\n"
                f"   📈 Price > 50 EMA: *{ema50_cnt} stocks*\n"
                f"   🔥 *Both (RSI>60 + >50EMA):* " + (", ".join(combo_list[:6]) if combo_list else "None")
            )
                
        send_telegram_msg("\n".join(msg_lines))
        
        if all_records:
            csv_file = "Morning_0900_RSI_EMA50_Full.csv"
            pd.DataFrame(all_records).to_csv(csv_file, index=False)
            send_telegram_file(csv_file, f"📂 Full List (RSI>60, RSI<30 & Price>50EMA across 1H, 1D, 1W)")
            os.remove(csv_file)

    # MODE 2: EVERY 15-MIN AUTO BREAKOUT & BREAKDOWN STATUS
    else:
        alert_lines = [f"⚡ *15-Min Auto Breakout Status ({now_str})*"]
        fresh_records = []
        
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
                        
                        # 1. New RSI > 60 Breakout
                        if curr_r > 60 and prev_r <= 60:
                            ema_tag = "✅>50EMA" if curr_p > curr_e else ""
                            new_rsi_bo.append(f"`{sym}` (₹{curr_p} | RSI:{curr_r} {ema_tag})")
                            fresh_records.append({
                                'Timeframe': cfg['label'], 'Signal': 'NEW RSI > 60 🔥',
                                'Symbol': sym, 'Price': curr_p, 'RSI': curr_r, 'EMA_50': curr_e,
                                'Above_50EMA': 'YES' if curr_p > curr_e else 'No'
                            })
                        # 2. New RSI < 30 Breakdown
                        elif curr_r < 30 and prev_r >= 30:
                            new_rsi_bd.append(f"`{sym}` (₹{curr_p} | RSI:{curr_r})")
                            fresh_records.append({
                                'Timeframe': cfg['label'], 'Signal': 'NEW RSI < 30 ❄️',
                                'Symbol': sym, 'Price': curr_p, 'RSI': curr_r, 'EMA_50': curr_e,
                                'Above_50EMA': 'YES' if curr_p > curr_e else 'No'
                            })
                        # 3. New Price Crossed Above 50 EMA
                        if curr_p > curr_e and prev_p <= prev_e:
                            new_ema_bo.append(f"`{sym}` (₹{curr_p} > EMA:{curr_e} | RSI:{curr_r})")
                            fresh_records.append({
                                'Timeframe': cfg['label'], 'Signal': 'NEW PRICE > 50 EMA 🚀',
                                'Symbol': sym, 'Price': curr_p, 'RSI': curr_r, 'EMA_50': curr_e,
                                'Above_50EMA': 'YES'
                            })
                except Exception:
                    continue
            
            alert_lines.append(f"\n⏱ *{cfg['label']} Timeframe:*")
            alert_lines.append(f"🔥 *New RSI > 60 [{len(new_rsi_bo)}]:* " + (", ".join(new_rsi_bo[:8]) if new_rsi_bo else "None"))
            alert_lines.append(f"❄️ *New RSI < 30 [{len(new_rsi_bd)}]:* " + (", ".join(new_rsi_bd[:8]) if new_rsi_bd else "None"))
            alert_lines.append(f"🚀 *New Price > 50EMA [{len(new_ema_bo)}]:* " + (", ".join(new_ema_bo[:8]) if new_ema_bo else "None"))
        
        send_telegram_msg("\n".join(alert_lines))
        
        if fresh_records:
            csv_file = "New_Breakouts_RSI_EMA50.csv"
            pd.DataFrame(fresh_records).to_csv(csv_file, index=False)
            send_telegram_file(csv_file, f"⚡ {len(fresh_records)} New Signals (RSI & 50 EMA) at {now_str}")
            os.remove(csv_file)

if __name__ == "__main__":
    run_smart_scan()
()
