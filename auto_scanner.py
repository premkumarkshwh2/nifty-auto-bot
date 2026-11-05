"""
Nifty 500 RSI / EMA Telegram Scanner Bot (refactored)

Setup:
    pip install yfinance pandas requests pytz
    export BOT_TOKEN="naya_token_botfather_se"
    export CHAT_ID="907465056"
    python nifty_bot.py
"""

import html
import io
import json
import logging
import os
import threading
import time
import warnings
from datetime import datetime

import pandas as pd
import pytz
import requests
import yfinance as yf

warnings.simplefilter(action="ignore", category=FutureWarning)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("bot")

# ───────────────────────── CONFIG ─────────────────────────
BOT_TOKEN = os.environ["7965983989:AAGtgF6o3WjuiRpADcEjDrECJqdL9O6MJls"]
CHAT_ID = str(os.environ["907465056"])  # sirf yahi chat commands de sakti hai

IST = pytz.timezone("Asia/Kolkata")
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)

RSI_PERIOD = 14
RSI_HIGH = 60
RSI_LOW = 30
EMA_PERIOD = 50
MIN_CANDLES = 30
DROP_LAST_CANDLE = False  # True = sirf complete candles use karo

BATCH_SIZE = 100
MAX_ROWS = 30
SCAN_INTERVAL = 900          # 15 min
HIGHER_TF_INTERVAL = 1800    # 30 min
SCAN_CACHE_TTL = 300         # auto-scan cache (sec)
CMD_CACHE_TTL = 600          # command cache (sec)
STATE_FILE = "scan_state.json"

TIMEFRAMES = {
    "1h": {"interval": "1h", "period": "3mo", "label": "1 Hour"},
    "1d": {"interval": "1d", "period": "6mo", "label": "1 Day"},
    "1wk": {"interval": "1wk", "period": "2y", "label": "1 Week"},
}

# mode -> (title, filter fn, sort column, ascending, value column)
MODES = {
    "rsi60": {
        "title": f"RSI > {RSI_HIGH}",
        "icon": "🟢",
        "test": lambda r: r["rsi"] > RSI_HIGH,
        "sort": "rsi", "asc": False, "col": "RSI", "val": "rsi",
    },
    "rsi30": {
        "title": f"RSI ≤ {RSI_LOW} (Oversold)",
        "icon": "🔴",
        "test": lambda r: r["rsi"] <= RSI_LOW,
        "sort": "rsi", "asc": True, "col": "RSI", "val": "rsi",
    },
    "ema50": {
        "title": f"Price > {EMA_PERIOD} EMA",
        "icon": "📈",
        "test": lambda r: r["price"] > r["ema"],
        "sort": "price", "asc": False, "col": "EMA50", "val": "ema",
    },
}

SUFFIX = {"1h": "1h", "1d": "1d", "1wk": "1w"}
COMMAND_MAP = {
    f"/{mode}_{SUFFIX[tf]}": (tf, mode)
    for mode in MODES
    for tf in TIMEFRAMES
}


# ───────────────────────── TELEGRAM ─────────────────────────
API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg_send(text):
    """Text bhejo (HTML). Retry + timeout ke saath."""
    for attempt in range(3):
        try:
            r = requests.post(
                f"{API}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            if r.status_code == 200:
                return True
            log.warning("Telegram %s: %s", r.status_code, r.text[:200])
            if r.status_code == 429:
                time.sleep(r.json().get("parameters", {}).get("retry_after", 3))
            else:
                return False
        except requests.RequestException as e:
            log.warning("Telegram send error: %s", e)
            time.sleep(2)
    return False


def tg_table(title, header, rows, limit=MAX_ROWS):
    """Table ko chunks me bhejo; har chunk apna <pre> block khud band karta hai."""
    rows = rows[:limit]
    sep = "-" * len(header)
    chunk, size = [], 0
    first = True
    for row in rows + [None]:
        if row is None or size + len(row) > 3000:
            if chunk:
                head = f"<b>{html.escape(title)}</b>\n" if first else ""
                body = "\n".join([header, sep] + chunk)
                tg_send(f"{head}<pre>{html.escape(body)}</pre>")
                first = False
            chunk, size = [], 0
        if row is not None:
            chunk.append(row)
            size += len(row) + 1


# ───────────────────────── TICKERS ─────────────────────────
_tickers = {"list": [], "day": None}
_tickers_lock = threading.Lock()

TICKER_URLS = [
    "https://raw.githubusercontent.com/kprohith/nse-stock-analysis/master/ind_nifty500list.csv",
    "https://raw.githubusercontent.com/anuj-singh-01/nse-stocks-list/main/ind_nifty500list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


def get_tickers():
    today = datetime.now(IST).date()
    with _tickers_lock:
        if _tickers["list"] and _tickers["day"] == today:
            return _tickers["list"]
        for url in TICKER_URLS:
            try:
                res = requests.get(url, headers=HEADERS, timeout=15)
                if res.status_code != 200 or "symbol" not in res.text.lower():
                    continue
                df = pd.read_csv(io.StringIO(res.text))
                col = next(
                    (c for c in df.columns if c.strip().lower() == "symbol"),
                    df.columns[0],
                )
                tickers = [
                    f"{str(s).strip()}.NS"
                    for s in df[col].dropna()
                    if "NIFTY" not in str(s).upper()
                ]
                if len(tickers) > 100:
                    _tickers.update(list=tickers, day=today)
                    log.info("Loaded %d tickers", len(tickers))
                    return tickers
            except Exception as e:
                log.warning("Ticker source failed (%s): %s", url, e)
        if _tickers["list"]:
            return _tickers["list"]
        raise RuntimeError("Nifty 500 list kisi bhi source se fetch nahi hui.")


# ───────────────────────── INDICATORS ─────────────────────────
def calc_rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_ema(series, period=EMA_PERIOD):
    return series.ewm(span=period, adjust=False).mean()


def extract_close(data, ticker):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if ticker in data.columns.get_level_values(0):
                sub = data[ticker]
            elif ticker in data.columns.get_level_values(1):
                sub = data.xs(ticker, level=1, axis=1)
            else:
                return pd.Series(dtype=float)
            if "Close" in sub.columns:
                return sub["Close"].dropna()
        elif "Close" in data.columns:
            return data["Close"].dropna()
    except Exception as e:
        log.debug("extract_close %s: %s", ticker, e)
    return pd.Series(dtype=float)


def compute_row(close):
    """Close series se latest price/RSI/EMA nikalo. None agar data kam ho."""
    if DROP_LAST_CANDLE:
        close = close.iloc[:-1]
    if len(close) <= MIN_CANDLES:
        return None
    rsi = calc_rsi(close).iloc[-1]
    ema = calc_ema(close).iloc[-1]
    if pd.isna(rsi) or pd.isna(ema):
        return None
    return {
        "price": round(float(close.iloc[-1]), 2),
        "rsi": round(float(rsi), 1),
        "ema": round(float(ema), 2),
    }


# ───────────────────────── DATA CACHE ─────────────────────────
_snap_cache = {}  # tf -> (timestamp, {symbol: row})
_tf_locks = {tf: threading.Lock() for tf in TIMEFRAMES}


def download_batch(batch, cfg, retries=2):
    for attempt in range(retries + 1):
        try:
            data = yf.download(
                batch,
                period=cfg["period"],
                interval=cfg["interval"],
                group_by="ticker",
                progress=False,
                threads=True,
                auto_adjust=False,
            )
            if data is not None and not data.empty:
                return data
        except Exception as e:
            log.warning("Download error (try %d): %s", attempt + 1, e)
        time.sleep(2 * (attempt + 1))
    return pd.DataFrame()


def get_snapshot(tf, max_age=CMD_CACHE_TTL):
    """Ek timeframe ka poora Nifty500 snapshot. Cache + lock => duplicate download nahi."""
    with _tf_locks[tf]:
        cached = _snap_cache.get(tf)
        if cached and time.time() - cached[0] < max_age:
            return cached[1]

        cfg = TIMEFRAMES[tf]
        tickers = get_tickers()
        snap = {}
        for i in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[i : i + BATCH_SIZE]
            data = download_batch(batch, cfg)
            if data.empty:
                continue
            for t in batch:
                row = compute_row(extract_close(data, t))
                if row:
                    snap[t.replace(".NS", "")] = row
        log.info("Snapshot %s: %d symbols", tf, len(snap))
        if snap:
            _snap_cache[tf] = (time.time(), snap)
        return snap


# ───────────────────────── SCAN LOGIC ─────────────────────────
def filter_snapshot(snap, mode):
    m = MODES[mode]
    rows = [{"sym": s, **r} for s, r in snap.items() if m["test"](r)]
    rows.sort(key=lambda r: r[m["sort"]], reverse=not m["asc"])
    return rows


def format_rows(rows, mode):
    col = MODES[mode]["val"]
    return [
        f"{r['sym']:<12}{r['price']:>9.2f}{r[col]:>9}" for r in rows
    ]


def table_header(mode):
    return f"{'Symbol':<12}{'Price':>9}{MODES[mode]['col']:>9}"


def run_command_scan(tf, mode):
    m = MODES[mode]
    title = f"{m['icon']} {TIMEFRAMES[tf]['label']} {m['title']}"
    tg_send(f"⏳ <b>{html.escape(title)}</b> scan ho raha hai...")
    snap = get_snapshot(tf, CMD_CACHE_TTL)
    if not snap:
        tg_send("⚠️ Data fetch nahi ho paya, thodi der baad try karo.")
        return
    rows = filter_snapshot(snap, mode)
    if not rows:
        tg_send(f"❌ <b>{html.escape(title)}</b>: koi stock match nahi hua.")
        return
    tg_table(
        f"{title} ({len(rows)} stocks)", table_header(mode),
        format_rows(rows, mode),
    )


def run_check(symbols):
    for sym in symbols[:5]:
        sym = sym.upper()
        lines = []
        for tf, cfg in TIMEFRAMES.items():
            data = download_batch([f"{sym}.NS"], cfg, retries=1)
            row = compute_row(extract_close(data, f"{sym}.NS")) if not data.empty else None
            if row:
                lines.append(
                    f"{cfg['label']:<8}{row['price']:>9.2f}"
                    f"{row['rsi']:>7}{row['ema']:>10.2f}"
                )
        if lines:
            header = f"{'TF':<8}{'Price':>9}{'RSI':>7}{'EMA50':>10}"
            tg_table(f"📊 {sym} — Status", header, lines)
        else:
            tg_send(f"❌ <b>{html.escape(sym)}</b>: data nahi mila ya symbol galat hai.")


HELP_TEXT = (
    "<b>Commands</b>\n"
    "/rsi60_1h /rsi60_1d /rsi60_1w — RSI &gt; 60\n"
    "/rsi30_1h /rsi30_1d /rsi30_1w — RSI ≤ 30\n"
    "/ema50_1h /ema50_1d /ema50_1w — Price &gt; 50 EMA\n"
    "/check SYMBOL [SYMBOL...] — ek ya zyada stocks ka status\n"
    "/help — ye message"
)


def handle_command(text):
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    if cmd in ("/start", "/help"):
        tg_send(HELP_TEXT)
    elif cmd == "/check" and len(parts) >= 2:
        run_check(parts[1:])
    elif cmd in COMMAND_MAP:
        run_command_scan(*COMMAND_MAP[cmd])
    else:
        tg_send("Samajh nahi aaya. /help dekho.")


# ───────────────────────── COMMAND LISTENER ─────────────────────────
def command_listener():
    """Long polling. Sirf CHAT_ID ke messages process hote hain."""
    offset = None
    try:  # purane pending messages skip karo
        r = requests.get(f"{API}/getUpdates", params={"offset": -1}, timeout=15).json()
        if r.get("result"):
            offset = r["result"][-1]["update_id"] + 1
    except Exception as e:
        log.warning("Initial getUpdates failed: %s", e)

    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            res = requests.get(f"{API}/getUpdates", params=params, timeout=40).json()
            for item in res.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != CHAT_ID:
                    continue  # anjaan user ignore
                text = (msg.get("text") or "").strip()
                if text.startswith("/"):
                    try:
                        handle_command(text)
                    except Exception as e:
                        log.exception("Command failed")
                        tg_send(f"⚠️ Command error: {html.escape(str(e))}")
        except Exception as e:
            log.warning("Listener error: %s", e)
            time.sleep(5)


# ───────────────────────── AUTO SCAN ─────────────────────────
_state_lock = threading.Lock()
_last_higher_tf = 0.0


def load_state():
    try:
        with open(STATE_FILE) as f:
            raw = json.load(f)
        return {tf: {m: set(v) for m, v in d.items()} for tf, d in raw.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({tf: {m: sorted(v) for m, v in d.items()} for tf, d in state.items()}, f)
    except OSError as e:
        log.warning("State save failed: %s", e)


STATE = load_state()


def is_market_open(now):
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return (MARKET_OPEN[0] * 60 + MARKET_OPEN[1]) <= mins <= (
        MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1]
    )


def run_smart_scan():
    global _last_higher_tf
    now = datetime.now(IST)
    now_str = now.strftime("%d-%b %I:%M %p")

    if not is_market_open(now):
        log.info("[%s] Market band. Auto-scan paused.", now_str)
        return

    first_scan = now.hour == 9 and now.minute <= 30
    tfs = ["1h"]
    if first_scan or time.time() - _last_higher_tf >= HIGHER_TF_INTERVAL:
        tfs = ["1h", "1d", "1wk"]
        _last_higher_tf = time.time()

    for tf in tfs:
        snap = get_snapshot(tf, SCAN_CACHE_TTL)
        if not snap:
            continue
        label = TIMEFRAMES[tf]["label"]

        for mode, m in MODES.items():
            rows = filter_snapshot(snap, mode)
            current = {r["sym"] for r in rows}

            with _state_lock:
                prev = STATE.get(tf, {}).get(mode)
                STATE.setdefault(tf, {})[mode] = current
                save_state(STATE)

            if prev is None:  # pehli baar: sirf baseline save
                continue
            if mode == "ema50" and first_scan:
                continue

            new_rows = [r for r in rows if r["sym"] not in prev]
            if new_rows:
                tg_table(
                    f"{m['icon']} {label} — New {m['title']} ({now_str})",
                    table_header(mode),
                    format_rows(new_rows, mode),
                    limit=25,
                )


# ───────────────────────── MAIN ─────────────────────────
if __name__ == "__main__":
    log.info("Bot start ho raha hai...")
    tg_send("🤖 Bot start ho gaya. /help se commands dekho.")

    threading.Thread(target=command_listener, daemon=True).start()

    while True:
        try:
            run_smart_scan()
        except Exception:
            log.exception("Scan error")
        log.info("Next scan %d min me...", SCAN_INTERVAL // 60)
        time.sleep(SCAN_INTERVAL)
