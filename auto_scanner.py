import io
import logging
import os
import threading
import time
from datetime import date, datetime
import pandas as pd
import pytz
import requests
import warnings
import yfinance as yf

warnings.simplefilter(action="ignore", category=FutureWarning)
logger = logging.getLogger("yfinance")
logger.setLevel(logging.CRITICAL)

BOT_TOKEN = "7965983989:AAGtgF6o3WjuiRpADcEjDrECJqdL9O6MJls"
CHAT_ID = "907465056"

TIMEFRAMES = {
    "15m": {"interval": "15m", "period": "5d", "label": "15 Min"},
    "30m": {"interval": "30m", "period": "10d", "label": "30 Min"},
    "1h": {"interval": "1h", "period": "3mo", "label": "1 Hour"},
    "1d": {"interval": "1d", "period": "6mo", "label": "1 Day"},
    "1wk": {"interval": "1wk", "period": "2y", "label": "1 Week"},
}

COMMAND_MAP = {
    "/rsi60_1h": ("1h", "rsi60", "🟢 1 Hour RSI > 60"),
    "/rsi60_1d": ("1d", "rsi60", "🟢 1 Day RSI > 60"),
    "/rsi60_1w": ("1wk", "rsi60", "🟢 1 Week RSI > 60"),
    "/rsi30_1h": ("1h", "rsi30", "🔴 1 Hour RSI ≤ 30 (Oversold)"),
    "/rsi30_1d": ("1d", "rsi30", "🔴 1 Day RSI ≤ 30 (Oversold)"),
    "/rsi30_1w": ("1wk", "rsi30", "🔴 1 Week RSI ≤ 30 (Oversold)"),
    "/ema50_1h": ("1h", "ema50", "📈 1 Hour Price > 50 EMA"),
    "/ema50_1d": ("1d", "ema50", "📈 1 Day Price > 50 EMA"),
    "/ema50_1w": ("1wk", "ema50", "📈 1 Week Price > 50 EMA"),
    # First Candle Bollinger Band Breakout Commands
    "/bb_15m": ("15m", "bb_upper_first", "🚀 15 Min First Candle BB Breakout"),
    "/bb_30m": ("30m", "bb_upper_first", "🚀 30 Min First Candle BB Breakout"),
    "/bb_1h": ("1h", "bb_upper_first", "🚀 1 Hour First Candle BB Breakout"),
}

CACHED_TICKERS = []
LAST_FETCH_DATE = None
LAST_HIGHER_TF_SCAN = 0

PREVIOUS_SCAN_STATES = {}


def get_nifty500_tickers():
  global CACHED_TICKERS, LAST_FETCH_DATE
  today = date.today()
  if CACHED_TICKERS and LAST_FETCH_DATE == today:
    return CACHED_TICKERS

  urls = [
      "https://raw.githubusercontent.com/kprohith/nse-stock-analysis/master/ind_nifty500list.csv",
      "https://raw.githubusercontent.com/anuj-singh-01/nse-stocks-list/main/ind_nifty500list.csv",
      "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
      "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
  ]

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      ),
      "Accept-Language": "en-US,en;q=0.9",
      "Referer": "https://www.google.com/",
  }

  for url in urls:
    try:
      res = requests.get(url, headers=headers, timeout=15)
      if res.status_code == 200 and (
          "Symbol" in res.text or "symbol" in res.text
      ):
        df = pd.read_csv(io.StringIO(res.text))
        col_name = (
            "Symbol"
            if "Symbol" in df.columns
            else ("SYMBOL" if "SYMBOL" in df.columns else df.columns[0])
        )
        tickers = [
            f"{str(s).strip()}.NS"
            for s in df[col_name].dropna().tolist()
            if "NIFTY" not in str(s)
        ]
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
  avg_gain = gain.ewm(
      alpha=1 / period, min_periods=period, adjust=False
  ).mean()
  avg_loss = loss.ewm(
      alpha=1 / period, min_periods=period, adjust=False
  ).mean()
  rs = avg_gain / avg_loss
  return 100 - (100 / (1 + rs))


def calculate_ema(series, period=50):
  return series.ewm(span=period, adjust=False).mean()


def calculate_bollinger_bands(series, period=20, std_dev=2):
  middle = series.rolling(window=period).mean()
  std = series.rolling(window=period).std()
  upper = middle + (std_dev * std)
  lower = middle - (std_dev * std)
  return upper, middle, lower


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
      requests.post(
          url, json={"chat_id": CHAT_ID, "text": msg_part, "parse_mode": "HTML"}
      )
      chunk = [line]
      curr_len = len(line)
    else:
      chunk.append(line)
      curr_len += len(line) + 1

  if chunk:
    msg_part = "\n".join(chunk)
    requests.post(
        url, json={"chat_id": CHAT_ID, "text": msg_part, "parse_mode": "HTML"}
    )


def extract_close_series(data, t):
  try:
    if isinstance(data.columns, pd.MultiIndex):
      try:
        if t in data.columns.get_level_values(0):
          sub = data[t]
          if isinstance(sub, pd.DataFrame) and "Close" in sub.columns:
            return sub["Close"].dropna()
      except Exception:
        pass
      try:
        if t in data.columns.get_level_values(1):
          sub = data.xs(t, level=1, axis=1)
          if isinstance(sub, pd.DataFrame) and "Close" in sub.columns:
            return sub["Close"].dropna()
          elif isinstance(sub, pd.Series):
            return sub.dropna()
      except Exception:
        pass
    else:
      if "Close" in data.columns:
        return data["Close"].dropna()
  except Exception:
    pass
  return pd.Series(dtype=float)


def run_specific_command_scan(tickers, tf_key, mode, title):
  try:
    send_telegram_msg(
        f"⏳ <b>{title}</b> ke liye scan shuru ho gaya hai, kripya 10-15 seconds"
        " intezaar karein..."
    )
    cfg = TIMEFRAMES[tf_key]
    results = []

    data = yf.download(
        tickers,
        period=cfg["period"],
        interval=cfg["interval"],
        group_by="ticker",
        progress=False,
        threads=True,
        auto_adjust=False,
    )

    for t in tickers:
      try:
        close = extract_close_series(data, t)
        if close.empty or len(close) <= 25:
          continue

        # Get today's date or the latest available date's first candle
        last_time = close.index[-1]
        first_idx = 0
        if isinstance(last_time, pd.Timestamp):
          # Find the index of the first candle of the latest date present in data
          latest_date = last_time.date()
          day_candles = [
              i
              for i, idx in enumerate(close.index)
              if isinstance(idx, pd.Timestamp) and idx.date() == latest_date
          ]
          if day_candles:
            first_idx = day_candles[
                0
            ]  # Din ki sabhi se pehli candle ka index

        rsi_s = calculate_rsi(close, 14)
        ema_s = calculate_ema(close, 50)
        upper_bb, _, _ = calculate_bollinger_bands(close, 20, 2)

        curr_p = round(float(close.iloc[first_idx]), 2)
        sym = t.replace(".NS", "")

        if mode == "rsi60" and not rsi_s.empty:
          curr_rsi = round(float(rsi_s.iloc[first_idx]), 1)
          if not pd.isna(curr_rsi) and curr_rsi > 60:
            results.append({"Symbol": sym, "Price": curr_p, "Val": curr_rsi})

        elif mode == "rsi30" and not rsi_s.empty:
          curr_rsi = round(float(rsi_s.iloc[first_idx]), 1)
          if not pd.isna(curr_rsi) and curr_rsi <= 30:
            results.append({"Symbol": sym, "Price": curr_p, "Val": curr_rsi})

        elif mode == "ema50" and not ema_s.empty:
          curr_ema = round(float(ema_s.iloc[first_idx]), 2)
          if not pd.isna(curr_ema) and curr_p > curr_ema:
            results.append({"Symbol": sym, "Price": curr_p, "Val": curr_ema})

        elif mode == "bb_upper_first" and not upper_bb.empty:
          curr_upper = float(upper_bb.iloc[first_idx])
          if curr_p > curr_upper:
            results.append(
                {"Symbol": sym, "Price": curr_p, "Val": round(curr_upper, 2)}
            )
      except Exception:
        continue

    if not results:
      send_telegram_msg(
          f"❌ <b>{title}:</b> Is samay criteria match karne wala koi stock"
          " nahi mila."
      )
      return

    res_df = pd.DataFrame(results)
    if mode == "bb_upper_first":
      res_df = res_df.sort_values(by="Price", ascending=False)
      lines = [
          f"<b>{title}</b>\n<code>Symbol     | Price    | Upper"
          " BB</code>\n<code>------------------------------</code>"
      ]
      for _, r in res_df.head(30).iterrows():
        lines.append(
            f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} |"
            f" ₹{r['Val']:<6}</code>"
        )
    elif mode in ["rsi30", "rsi60"]:
      res_df = res_df.sort_values(
          by="Val", ascending=False if mode == "rsi60" else True
      )
      lines = [
          f"<b>{title}</b>\n<code>Symbol     | Price    |"
          " RSI</code>\n<code>------------------------------</code>"
      ]
      for _, r in res_df.head(30).iterrows():
        lines.append(
            f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} |"
            f" {r['Val']:<5}</code>"
        )
    else:
      res_df = res_df.sort_values(by="Price", ascending=False)
      lines = [
          f"<b>{title}</b>\n<code>Symbol     | Price    | 50"
          " EMA</code>\n<code>------------------------------</code>"
      ]
      for _, r in res_df.head(30).iterrows():
        lines.append(
            f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} |"
            f" ₹{r['Val']:<6}</code>"
        )

    send_telegram_msg("\n".join(lines))
  except Exception as e:
    send_telegram_msg(f"⚠️ Command error: {str(e)}")


def process_user_commands(tickers):
  global CHAT_ID
  try:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    res = requests.get(url, params={"timeout": 10}, timeout=15).json()
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
          reply = [
              f"📊 <b>{sym} — Status</b>\n<code>TF   | Price  | RSI  |"
              " EMA50</code>\n<code>-------------------------</code>"
          ]
          for tf_key, cfg in TIMEFRAMES.items():
            if tf_key in ["15m", "30m"]:
              continue
            try:
              df = yf.download(
                  ticker,
                  period=cfg["period"],
                  interval=cfg["interval"],
                  progress=False,
                  auto_adjust=False,
              )
              close = extract_close_series(df, ticker)
              if len(close) > 30:
                curr_p = round(float(close.iloc[-1]), 2)
                r_val = round(float(calculate_rsi(close, 14).iloc[-1]), 1)
                e_val = round(float(calculate_ema(close, 50).iloc[-1]), 2)
                reply.append(
                    f"<code>{cfg['label']:<4} | ₹{curr_p:<5} | {r_val:<4} |"
                    f" {e_val}</code>"
                )
            except Exception:
              continue

          if len(reply) > 1:
            send_telegram_msg("\n".join(reply))
          else:
            send_telegram_msg(
                f"❌ <b>{sym}:</b> Data fetch nahi ho paya ya symbol galat hai."
            )

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
  global LAST_HIGHER_TF_SCAN, PREVIOUS_SCAN_STATES
  ist = pytz.timezone("Asia/Kolkata")
  now = datetime.now(ist)
  now_str = now.strftime("%d-%b %I:%M %p")

  current_hour = now.hour
  current_min = now.minute
  total_mins = current_hour * 60 + current_min

  is_market_active = 9 * 60 <= total_mins <= 16 * 60
  tickers = get_nifty500_tickers()

  if not is_market_active:
    print(
        f"[{now_str}] Market closed hours. Auto-scan paused, but commands are"
        " active..."
    )
    return

  is_morning_0900_scan = current_hour == 9 and current_min <= 10

  timeframes_to_scan = ["1h", "15m", "30m"]
  current_ts = time.time()

  should_scan_higher_tf = is_morning_0900_scan or (
      current_ts - LAST_HIGHER_TF_SCAN >= 1800
  )

  if should_scan_higher_tf:
    timeframes_to_scan = ["15m", "30m", "1h", "1d", "1wk"]
    LAST_HIGHER_TF_SCAN = current_ts

  for tf_key in timeframes_to_scan:
    cfg = TIMEFRAMES[tf_key]
    data = yf.download(
        tickers,
        period=cfg["period"],
        interval=cfg["interval"],
        group_by="ticker",
        progress=False,
        threads=True,
        auto_adjust=False,
    )
    bo_list, bd_list, ema_list, bb_first_list = [], [], [], []

    for t in tickers:
      try:
        close = extract_close_series(data, t)
        if close.empty or len(close) <= 25:
          continue

        last_time = close.index[-1]
        first_idx = 0
        if isinstance(last_time, pd.Timestamp):
          latest_date = last_time.date()
          day_candles = [
              i
              for i, idx in enumerate(close.index)
              if isinstance(idx, pd.Timestamp) and idx.date() == latest_date
          ]
          if day_candles:
            first_idx = day_candles[0]

        rsi = calculate_rsi(close, 14)
        ema50 = calculate_ema(close, 50)
        upper_bb, _, _ = calculate_bollinger_bands(close, 20, 2)

        curr_p = round(float(close.iloc[first_idx]), 2)
        sym = t.replace(".NS", "")

        if not rsi.empty:
          curr_r = round(float(rsi.iloc[first_idx]), 1)
          if not pd.isna(curr_r):
            if curr_r > 60:
              bo_list.append({"Symbol": sym, "Price": curr_p, "Val": curr_r})
            if curr_r <= 30:
              bd_list.append({"Symbol": sym, "Price": curr_p, "Val": curr_r})

        if not ema50.empty:
          curr_e = round(float(ema50.iloc[first_idx]), 2)
          if not pd.isna(curr_e) and curr_p > curr_e:
            ema_list.append({"Symbol": sym, "Price": curr_p, "Val": curr_e})

        if not upper_bb.empty:
          curr_upper = float(upper_bb.iloc[first_idx])
          if curr_p > curr_upper:
            bb_first_list.append(
                {"Symbol": sym, "Price": curr_p, "Val": round(curr_upper, 2)}
            )
      except Exception:
        continue

    if tf_key not in PREVIOUS_SCAN_STATES:
      PREVIOUS_SCAN_STATES[tf_key] = {
          "rsi60": {item["Symbol"] for item in bo_list},
          "rsi30": {item["Symbol"] for item in bd_list},
          "ema50": {item["Symbol"] for item in ema_list},
          "bb_upper_first": {item["Symbol"] for item in bb_first_list},
      }
      continue

    prev_bo = PREVIOUS_SCAN_STATES[tf_key]["rsi60"]
    prev_bd = PREVIOUS_SCAN_STATES[tf_key]["rsi30"]
    prev_ema = PREVIOUS_SCAN_STATES[tf_key]["ema50"]
    prev_bb_first = PREVIOUS_SCAN_STATES[tf_key]["bb_upper_first"]

    current_bo_set = {item["Symbol"] for item in bo_list}
    current_bd_set = {item["Symbol"] for item in bd_list}
    current_ema_set = {item["Symbol"] for item in ema_list}
    current_bb_first_set = {item["Symbol"] for item in bb_first_list}

    new_bo_list = [item for item in bo_list if item["Symbol"] not in prev_bo]
    new_bd_list = [item for item in bd_list if item["Symbol"] not in prev_bd]
    new_ema_list = [
        item for item in ema_list if item["Symbol"] not in prev_ema
    ]
    new_bb_first_list = [
        item for item in bb_first_list if item["Symbol"] not in prev_bb_first
    ]

    PREVIOUS_SCAN_STATES[tf_key]["rsi60"] = current_bo_set
    PREVIOUS_SCAN_STATES[tf_key]["rsi30"] = current_bd_set
    PREVIOUS_SCAN_STATES[tf_key]["ema50"] = current_ema_set
    PREVIOUS_SCAN_STATES[tf_key]["bb_upper_first"] = current_bb_first_set

    if new_bo_list:
      bo_df = pd.DataFrame(new_bo_list).sort_values(by="Val", ascending=False)
      msg = [
          f"🔥 <b>{cfg['label']} — New RSI > 60 Breakout ({now_str})</b>",
          "<code>Symbol     | Price    | RSI</code>",
          "<code>------------------------------</code>",
      ]
      for _, r in bo_df.head(25).iterrows():
        msg.append(
            f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} |"
            f" {r['Val']:<5}</code>"
        )
      send_telegram_msg("\n".join(msg))

    if new_bd_list:
      bd_df = pd.DataFrame(new_bd_list).sort_values(by="Val", ascending=True)
      msg = [
          f"❄️ <b>{cfg['label']} — New RSI ≤ 30 Breakdown ({now_str})</b>",
          "<code>Symbol     | Price    | RSI</code>",
          "<code>------------------------------</code>",
      ]
      for _, r in bd_df.head(25).iterrows():
        msg.append(
            f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} |"
            f" {r['Val']:<5}</code>"
        )
      send_telegram_msg("\n".join(msg))

    if new_bb_first_list:
      bb_df = pd.DataFrame(new_bb_first_list).sort_values(
          by="Price", ascending=False
      )
      msg = [
          (
              f"🚀 <b>{cfg['label']} — First Candle BB Upper Breakout"
              f" ({now_str})</b>"
          ),
          "<code>Symbol     | Price    | Upper BB</code>",
          "<code>------------------------------</code>",
      ]
      for _, r in bb_df.head(25).iterrows():
        msg.append(
            f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} |"
            f" ₹{r['Val']:<6}</code>"
        )
      send_telegram_msg("\n".join(msg))

    if new_ema_list and not is_morning_0900_scan and tf_key not in ["15m", "30m"]:
      ema_df = pd.DataFrame(new_ema_list).sort_values(by="Price", ascending=False)
      msg = [
          f"🚀 <b>{cfg['label']} — New Price > 50 EMA ({now_str})</b>",
          "<code>Symbol     | Price    | 50 EMA</code>",
          "<code>------------------------------</code>",
      ]
      for _, r in ema_df.head(25).iterrows():
        msg.append(
            f"<code>{r['Symbol']:<10} | ₹{r['Price']:<7} |"
            f" ₹{r['Val']:<6}</code>"
        )
      send_telegram_msg("\n".join(msg))


if __name__ == "__main__":
  print("Bot is running with Flexible First Candle BB filters...")
  send_telegram_msg(
      "🤖 Bot start ho gaya hai! Ab market closed ho ya live, First Candle BB"
      " Breakout command proper result degi."
  )

  listener_thread = threading.Thread(
      target=background_command_listener, daemon=True
  )
  listener_thread.start()

  while True:
    try:
      run_smart_scan()
    except Exception as e:
      print("Error:", e)
    print("Waiting 15 minutes for next scan...")
    time.sleep(900)
              
