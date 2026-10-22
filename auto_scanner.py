import requests
import pandas as pd
import yfinance as yf
import os
from datetime import datetime
import pytz

# 👇 APNA BOT TOKEN AUR CHAT ID YAHAN DALEIN 👇
BOT_TOKEN =''8855321186:AAE6pMGrgT5VS9DHip3z6otENLPwRYRM4lo"
CHAT_ID = "907465056"

TIMEFRAMES = {
    "15m": {"interval": "15m", "period": "5d",  "label": "15 Min"},
    "1h":  {"interval": "1h",  "period": "1mo", "label": "1 Hour"},
    "1d":  {"interval": "1d",  "period": "3mo", "label": "1 Day"},
    "1wk": {"interval": "1wk", "period": "1y",  "label": "1 Week"}
}

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})

def send_telegram_file(filepath, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(filepath, "rb") as f:
        requests.post(url, data={"chat_id": CHAT_ID, "caption": caption}, files={"document": f})

def run_smart_scan():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    now_str = now.strftime('%d-%b %I:%M %p')
    
    # Check if this is the 9:15 AM Morning Run (9:00 AM to 9:24 AM window) or Manual Test Run
    is_morning_full_scan = (now.hour == 9 and now.minute < 25) or os.getenv("FORCE_FULL_SCAN") == "true"
    
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    df = pd.read_csv(url, storage_options={'User-Agent': 'Mozilla/5.0'})
    tickers = [f"{s}.NS" for s in df['Symbol'].tolist()]
    
    # ==========================================================
    # MODE 1: SUBAH 09:15 AM -> SABHI STOCKS KI FULL REPORT
    # ==========================================================
    if is_morning_full_scan:
        msg_lines = [f"🌅 *09:15 AM Morning Full RSI Report ({now_str})*\n_(Sabhi Timeframes ke RSI > 60 & RSI < 30 Stocks)_"]
        all_records = []
        
        for tf_key, cfg in TIMEFRAMES.items():
            data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            gt60_list, lt30_list = [], []
            
            for t in tickers:
                try:
                    close = data[t]['Close'].dropna()
                    if len(close) > 14:
                        rsi = calculate_rsi(close, 14)
                        curr = round(float(rsi.iloc[-1]), 1)
                        prev = round(float(rsi.iloc[-2]), 1)
                        price = round(float(close.iloc[-1]), 2)
                        sym = t.replace('.NS', '')
                        
                        if curr > 60:
                            gt60_list.append(f"`{sym}`({curr})")
                            all_records.append({
                                'Timeframe': cfg['label'], 'Symbol': sym, 'Price': price, 
                                'RSI': curr, 'Status': 'Bullish (>60)',
                                'Fresh_Cross': 'YES 🔥' if prev <= 60 else 'No'
                            })
                        elif curr < 30:
                            lt30_list.append(f"`{sym}`({curr})")
                            all_records.append({
                                'Timeframe': cfg['label'], 'Symbol': sym, 'Price': price, 
                                'RSI': curr, 'Status': 'Oversold (<30)',
                                'Fresh_Cross': 'YES ❄️' if prev >= 30 else 'No'
                            })
                except Exception:
                    continue
                    
            msg_lines.append(f"\n📌 *{cfg['label']}:* 🟢 `>60`: *{len(gt60_list)} stocks* | 🔴 `<30`: *{len(lt30_list)} stocks*")
            if gt60_list:
                msg_lines.append("   Top >60: " + ", ".join(gt60_list[:8]))
            if lt30_list:
                msg_lines.append("   Top <30: " + ", ".join(lt30_list[:8]))
                
        send_telegram_msg("\n".join(msg_lines))
        
        if all_records:
            csv_file = "Morning_0915_Full_RSI_List.csv"
            pd.DataFrame(all_records).to_csv(csv_file, index=False)
            send_telegram_file(csv_file, f"📂 09:15 AM Full List ({len(all_records)} entries across 15m, 1H, 1D, 1W)")
            os.remove(csv_file)

    # ==========================================================
    # MODE 2: 09:30 AM SE 03:30 PM -> SIRF NEW BREAKOUT & BREAKDOWN
    # ==========================================================
    else:
        alert_lines = [f"⚡ *New RSI Breakout / Breakdown Alert ({now_str})*"]
        new_signals_found = False
        fresh_records = []
        
        for tf_key, cfg in TIMEFRAMES.items():
            data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            new_breakouts = []   # Prev <= 60 and Current > 60
            new_breakdowns = []  # Prev >= 30 and Current < 30
            
            for t in tickers:
                try:
                    close = data[t]['Close'].dropna()
                    if len(close) > 14:
                        rsi = calculate_rsi(close, 14)
                        curr = round(float(rsi.iloc[-1]), 1)
                        prev = round(float(rsi.iloc[-2]), 1)
                        price = round(float(close.iloc[-1]), 2)
                        sym = t.replace('.NS', '')
                        
                        # SIRF NAYA BREAKOUT (Crossed Above 60)
                        if curr > 60 and prev <= 60:
                            new_breakouts.append(f"`{sym}` (₹{price} | RSI: {prev}➡️*{curr}*)")
                            fresh_records.append({
                                'Timeframe': cfg['label'], 'Signal': 'NEW BREAKOUT (>60) 🔥',
                                'Symbol': sym, 'Price': price, 'Prev_RSI': prev, 'Current_RSI': curr
                            })
                            
                        # SIRF NAYA BREAKDOWN (Crossed Below 30)
                        elif curr < 30 and prev >= 30:
                            new_breakdowns.append(f"`{sym}` (₹{price} | RSI: {prev}➡️*{curr}*)")
                            fresh_records.append({
                                'Timeframe': cfg['label'], 'Signal': 'NEW BREAKDOWN (<30) ❄️',
                                'Symbol': sym, 'Price': price, 'Prev_RSI': prev, 'Current_RSI': curr
                            })
                except Exception:
                    continue
            
            if new_breakouts or new_breakdowns:
                new_signals_found = True
                alert_lines.append(f"\n⏱ *{cfg['label']} Timeframe:*")
                if new_breakouts:
                    alert_lines.append("🔥 *New RSI > 60 Breakout:*\n• " + "\n• ".join(new_breakouts[:15]))
                if new_breakdowns:
                    alert_lines.append("❄️ *New RSI < 30 Breakdown:*\n• " + "\n• ".join(new_breakdowns[:15]))
        
        # Message tabhi bhejega jab koi NAYA Breakout ya Breakdown milega
        if new_signals_found:
            send_telegram_msg("\n".join(alert_lines))
            if len(fresh_records) > 10:
                csv_file = "New_RSI_Signals.csv"
                pd.DataFrame(fresh_records).to_csv(csv_file, index=False)
                send_telegram_file(csv_file, f"⚡ Total {len(fresh_records)} New Breakouts/Breakdowns at {now_str}")
                os.remove(csv_file)
        else:
            print(f"[{now_str}] Koi naya RSI breakout/breakdown nahi mila. No message sent.")

if __name__ == "__main__":
    run_smart_scan()
