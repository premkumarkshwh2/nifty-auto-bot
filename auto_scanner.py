import time
import telebot
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from apscheduler.schedulers.background import BackgroundScheduler

# --- CONFIGURATION (Added) ---
TOKEN = "8855321186:AAE6pMGrgT5VS9DHip3z6otENLPwRYRM4lo"
CHAT_ID = "907465056"

bot = telebot.TeleBot(TOKEN)

# Aapki Watchlist (NSE Stocks) - Aap isme apne hisaab se aur stocks add kar sakte hain
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", 
    "ICICIBANK.NS", "SBIN.NS", "ITC.NS", "TATAMOTORS.NS"
]

def scan_single_timeframe(period, interval, tf_name):
    """Kisi ek specific timeframe ko scan karne ka function"""
    results = []
    for symbol in WATCHLIST:
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            if not df.empty:
                df['RSI'] = ta.rsi(df['Close'], length=14)
                rsi_val = df['RSI'].iloc[-1]
                if pd.notna(rsi_val) and rsi_val < 30:
                    results.append(f"📉 *{symbol}* -> RSI: *{rsi_val:.2f}*")
        except Exception as e:
            print(f"Error {symbol}: {e}")
    return results

def run_full_scan():
    """Sabhi timeframes (1H, 1D, 1W) ka full scan karne ka function"""
    alerts = []
    for symbol in WATCHLIST:
        try:
            df_1h = yf.download(symbol, period="1mo", interval="1h", progress=False)
            df_1d = yf.download(symbol, period="6mo", interval="1d", progress=False)
            df_1w = yf.download(symbol, period="1y", interval="1wk", progress=False)
            
            stock_signals = []
            if not df_1h.empty:
                r1h = ta.rsi(df_1h['Close'], length=14).iloc[-1]
                if pd.notna(r1h) and r1h < 30: stock_signals.append(f"1H ({r1h:.2f})")
            
            if not df_1d.empty:
                r1d = ta.rsi(df_1d['Close'], length=14).iloc[-1]
                if pd.notna(r1d) and r1d < 30: stock_signals.append(f"1D ({r1d:.2f})")
                
            if not df_1w.empty:
                r1w = ta.rsi(df_1w['Close'], length=14).iloc[-1]
                if pd.notna(r1w) and r1w < 30: stock_signals.append(f"1W ({r1w:.2f})")

            if stock_signals:
                alerts.append(f"📉 *{symbol}* -> {', '.join(stock_signals)}")
        except Exception as e:
            print(f"Error {symbol}: {e}")
    return alerts

# --- TELEGRAM COMMANDS HANDLERS ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    help_text = (
        "🤖 *RSI Scanner Bot Menu*:\n\n"
        "🔹 `/1h` - Check 1 Hour timeframe (RSI < 30)\n"
        "🔹 `/1d` - Check 1 Day timeframe (RSI < 30)\n"
        "🔹 `/1w` - Check 1 Week timeframe (RSI < 30)\n"
        "🔹 `/scan` - Full All-Timeframe Scan\n"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['1h'])
def handle_1h(message):
    bot.reply_to(message, "⏳ Scanning **1 Hour** timeframe for RSI < 30...", parse_mode="Markdown")
    res = scan_single_timeframe("1mo", "1h", "1H")
    if res:
        bot.send_message(message.chat.id, "⏱️ *1 Hour RSI < 30 Stocks:*\n\n" + "\n".join(res), parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "✅ No stocks found below RSI 30 on 1 Hour timeframe.")

@bot.message_handler(commands=['1d'])
def handle_1d(message):
    bot.reply_to(message, "⏳ Scanning **1 Day** timeframe for RSI < 30...", parse_mode="Markdown")
    res = scan_single_timeframe("6mo", "1d", "1D")
    if res:
        bot.send_message(message.chat.id, "📅 *1 Day RSI < 30 Stocks:*\n\n" + "\n".join(res), parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "✅ No stocks found below RSI 30 on 1 Day timeframe.")

@bot.message_handler(commands=['1w'])
def handle_1w(message):
    bot.reply_to(message, "⏳ Scanning **1 Week** timeframe for RSI < 30...", parse_mode="Markdown")
    res = scan_single_timeframe("1y", "1wk", "1W")
    if res:
        bot.send_message(message.chat.id, "📆 *1 Week RSI < 30 Stocks:*\n\n" + "\n".join(res), parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "✅ No stocks found below RSI 30 on 1 Week timeframe.")

@bot.message_handler(commands=['scan'])
def handle_scan(message):
    bot.reply_to(message, "🔍 Running Full Multi-Timeframe Scan (1H, 1D, 1W)...", parse_mode="Markdown")
    alerts = run_full_scan()
    if alerts:
        msg = "🚨 *Manual Full Scan Results (RSI < 30)* 🚨\n\n" + "\n".join(alerts)
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "✅ No stocks found below RSI 30 in any timeframe right now.")


# --- AUTOMATIC BACKGROUND JOB (Har 15 Min mein) ---
def auto_background_scanner():
    print("Running 15-min automated background scan...")
    alerts = run_full_scan()
    if alerts:
        msg = "⏰ *Auto-Update (Every 15 Min)* ⏰\n\n" + "\n".join(alerts)
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

scheduler = BackgroundScheduler()
scheduler.add_job(auto_background_scanner, 'interval', minutes=15)
scheduler.start()


# --- START BOT ---
print("Bot is running and listening to commands...")
bot.infinity_polling()
                             
