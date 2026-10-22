
import requests
import pandas as pd
import yfinance as yf
import os
import io
from datetime import datetime
import pytz

# 👇 APNA BOT TOKEN AUR CHAT ID YAHAN DALEIN 👇
BOT_TOKEN = "APNA_BOT_TOKEN_YAHAN_DALEIN"
CHAT_ID = "APNI_CHAT_ID_YAHAN_DALEIN"

# Timeframes: 1 Hour, 1 Day, 1 Week
TIMEFRAMES = {
    "1h":  {"interval": "1h",  "period": "1mo", "label": "1 Hour"},
    "1d":  {"interval": "1d",  "period": "3mo", "label": "1 Day"},
    "1wk": {"interval": "1wk", "period": "1y",  "label": "1 Week"}
}

def get_nifty500_tickers():
    """NSE + GitHub Mirror Fallback (100% Cloud Safe)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/csv,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
                    print(f"Loaded {len(tickers)} tickers from {url}")
                    return tickers
        except Exception as e:
            print(f"URL failed ({url}): {e}")
            
    raise Exception("Nifty 500 list fetch nahi ho payi.")

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
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    print("Telegram Msg Status:", r.status_code, r.text)

def send_telegram_file(filepath, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(filepath, "rb") as f:
        r = requests.post(url, data={"chat_id": CHAT_ID, "caption": caption}, files={"document": f})
    print("Telegram File Status:", r.status_code)

def run_smart_scan():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    now_str = now.strftime('%d-%b %I:%M %p')
    
    # 09:00 AM Morning Full Scan Window (between 08:45 AM and 09:10 AM IST) OR Manual Test Run
    is_morning_0900_scan = (
        (now.hour == 8 and now.minute >= 45) or 
        (now.hour == 9 and now.minute <= 10) or 
        os.getenv("FORCE_FULL_SCAN") == "true"
    )
    
    tickers = get_nifty500_tickers()
    
    # ==========================================================
    # MODE 1: SUBAH 09:00 AM -> SABHI STOCKS KI FULL REPORT
    # ==========================================================
    if is_morning_0900_scan:
        msg_lines = [f"🌅 *09:00 AM Morning Full RSI Report ({now_str})*\n_(Timeframes: 1 Hour, 1 Day, 1 Week)_"]
        all_records = []
        
        for tf_key, cfg in TIMEFRAMES.items():
            print(f"Scanning {cfg['label']}...")
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
                    
            msg_lines.append(f"\n📌 *{cfg['label']}:* 🟢 `>60`: *{len(gt60_list)}* | 🔴 `<30`: *{len(lt30_list)}*")
            if gt60_list:
                msg_lines.append("   Top >60: " + ", ".join(gt60_list[:6]))
            if lt30_list:
                msg_lines.append("   Top <30: " + ", ".join(lt30_list[:6]))
                
        send_telegram_msg("\n".join(msg_lines))
        
        if all_records:
            csv_file = "Morning_0900_Full_RSI_List.csv"
            pd.DataFrame(all_records).to_csv(csv_file, index=False)
            send_telegram_file(csv_file, f"📂 09:00 AM Full RSI List ({len(all_records)} stocks across 1H, 1D, 1W)")
            os.remove(csv_file)

    # ==========================================================
    # MODE 2: HAR 15 MIN AUTO UPDATE -> NEW BREAKOUT & BREAKDOWN STATUS
    # ==========================================================
    else:
        alert_lines = [f"⚡ *15-Min Auto RSI Status ({now_str})*"]
        fresh_records = []
        
        for tf_key, cfg in TIMEFRAMES.items():
            data = yf.download(tickers, period=cfg["period"], interval=cfg["interval"], group_by='ticker', progress=False, threads=True)
            new_breakouts, new_breakdowns = [], []
            
            for t in tickers:
                try:
                    close = data[t]['Close'].dropna()
                    if len(close) > 14:
                        rsi = calculate_rsi(close, 14)
                        curr = round(float(rsi.iloc[-1]), 1)
                        prev = round(float(rsi.iloc[-2]), 1)
                        price = round(float(close.iloc[-1]), 2)
                        sym = t.replace('.NS', '')
                        
                        # Naya Breakout (Crossed Above 60)
                        if curr > 60 and prev <= 60:
                            new_breakouts.append(f"`{sym}` (₹{price} | {prev}➡️*{curr}*)")
                            fresh_records.append({
                                'Timeframe': cfg['label'], 'Signal': 'NEW BREAKOUT (>60) 🔥',
                                'Symbol': sym, 'Price': price, 'Prev_RSI': prev, 'Current_RSI': curr
                            })
                        # Naya Breakdown (Crossed Below 30)
                        elif curr < 30 and prev >= 30:
                            new_breakdowns.append(f"`{sym}` (₹{price} | {prev}➡️*{curr}*)")
                            fresh_records.append({
                                'Timeframe': cfg['label'], 'Signal': 'NEW BREAKDOWN (<30) ❄️',
                                'Symbol': sym, 'Price': price, 'Prev_RSI': prev, 'Current_RSI': curr
                            })
                except Exception:
                    continue
            
            alert_lines.append(f"\n⏱ *{cfg['label']} Timeframe:*")
            if new_breakouts:
                alert_lines.append(f"🔥 *New Breakout (>60) [{len(new_breakouts)}]:*\n• " + "\n• ".join(new_breakouts[:10]))
            else:
                alert_lines.append("🔥 *New Breakout (>60):* None")
                
            if new_breakdowns:
                alert_lines.append(f"❄️ *New Breakdown (<30) [{len(new_breakdowns)}]:*\n• " + "\n• ".join(new_breakdowns[:10]))
            else:
                alert_lines.append("❄️ *New Breakdown (<30):* None")
        
        # Har 15 min mein status bhejega
        send_telegram_msg("\n".join(alert_lines))
        
        # Agar naye breakout/breakdown mile hain toh unki CSV file bhi bhej dega
        if fresh_records:
            csv_file = "New_RSI_Breakout_Breakdown.csv"
            pd.DataFrame(fresh_records).to_csv(csv_file, index=False)
            send_telegram_file(csv_file, f"⚡ {len(fresh_records)} New Breakouts/Breakdowns at {now_str}")
            os.remove(csv_file)

if __name__ == "__main__":
    run_smart_scan()
