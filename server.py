
import os
import time
import threading
import logging
import requests
import yfinance as yf
import pandas as pd
from flask import Flask, jsonify

# =============== CONFIGURATION ===============

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_SECONDS = 900  # 15 minutes
TIMEFRAME = "15m"

ASSETS = {
    "XAUUSD": "XAUUSD=X",
    "ETHUSD": "ETH-USD",
    "BTCUSD": "BTC-USD",
    "USOIL": "CL=F"
}

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

last_signals = {}
last_candle_times = {}
bot_started = False

# =============== TELEGRAM ===============

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        logging.error("Telegram credentials missing")
        return False

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": message},
            timeout=20
        )

        result = response.json()
        logging.info("Telegram: %s", result)
        return result.get("ok", False)

    except Exception as e:
        logging.error("Telegram error: %s", e)
        return False


# =============== MARKET DATA ===============

def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(
            period="5d",
            interval=TIMEFRAME,
            auto_adjust=False
        )

        if df is None or len(df) < 60:
            logging.warning("Insufficient data: %s", symbol)
            return None

        df = df.dropna()

        # Ignore the latest possibly incomplete candle
        df = df.iloc[:-1].copy()

        if len(df) < 55:
            return None

        # Reject stale data
        latest_time = df.index[-1]
        now = pd.Timestamp.now(tz="UTC")

        if latest_time.tzinfo is None:
            latest_time = latest_time.tz_localize("UTC")

        if (now - latest_time).total_seconds() > 3600:
            logging.warning("Stale data: %s", symbol)
            return None

        return df

    except Exception as e:
        logging.error("Data error %s: %s", symbol, e)
        return None


# =============== INDICATORS ===============

def indicators(df):
    df = df.copy()

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    df["EMA20"] = close.ewm(span=20, adjust=False).mean()
    df["EMA50"] = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, 0.000001)
    df["RSI"] = 100 - (100 / (1 + rs))

    previous_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - previous_close).abs(),
        (low - previous_close).abs()
    ], axis=1).max(axis=1)

    df["ATR"] = tr.rolling(14).mean()

    return df.dropna()


# =============== ANALYSIS ===============

def analyze_asset(name, symbol):
    df = get_data(symbol)

    if df is None:
        return None

    df = indicators(df)

    if len(df) < 25:
        return None

    current = df.iloc[-1]
    previous = df.iloc[-2]

    price = float(current["Close"])
    ema20 = float(current["EMA20"])
    ema50 = float(current["EMA50"])
    rsi = float(current["RSI"])
    atr = float(current["ATR"])

    candle_time = str(df.index[-1])

    if atr <= 0:
        return None

    # Support/resistance from previous candles
    support = float(df["Low"].iloc[-22:-2].min())
    resistance = float(df["High"].iloc[-22:-2].max())

    bullish = ema20 > ema50
    bearish = ema20 < ema50

    candle_range = float(current["High"] - current["Low"])

    if candle_range <= 0:
        return None

    lower_wick = min(
        float(current["Open"]),
        float(current["Close"])
    ) - float(current["Low"])

    upper_wick = float(current["High"]) - max(
        float(current["Open"]),
        float(current["Close"])
    )

    # BUY: support rejection or confirmed resistance breakout
    support_rejection = (
        float(current["Low"]) <= support + atr * 0.20
        and price > support
        and lower_wick > candle_range * 0.30
        and price > float(current["Open"])
    )

    breakout_buy = (
        float(previous["Close"]) <= resistance
        and price > resistance + atr * 0.10
    )

    # SELL: resistance rejection or support breakdown
    resistance_rejection = (
        float(current["High"]) >= resistance - atr * 0.20
        and price < resistance
        and upper_wick > candle_range * 0.30
        and price < float(current["Open"])
    )

    breakout_sell = (
        float(previous["Close"]) >= support
        and price < support - atr * 0.10
    )

    direction = None
    reason = None

    if bullish and 45 <= rsi <= 68:
        if support_rejection:
            direction = "BUY"
            reason = "Support rejection"
        elif breakout_buy:
            direction = "BUY"
            reason = "Resistance breakout"

    if bearish and 32 <= rsi <= 55:
        if resistance_rejection:
            direction = "SELL"
            reason = "Resistance rejection"
        elif breakout_sell:
            direction = "SELL"
            reason = "Support breakdown"

    if direction is None:
        logging.info(
            "%s WAIT | Price %.4f | RSI %.1f",
            name, price, rsi
        )
        return None

    # Avoid duplicate signal on the same candle
    signal_key = f"{name}_{direction}_{candle_time}"

    if last_signals.get(name) == signal_key:
        return None

    # ATR-based risk management
    if direction == "BUY":
        sl = price - (atr * 1.5)
        tp1 = price + (atr * 1.5)
        tp2 = price + (atr * 2.5)
    else:
        sl = price + (atr * 1.5)
        tp1 = price - (atr * 1.5)
        tp2 = price - (atr * 2.5)

    message = (
        f"📊 {name} | {direction}\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Entry: {price:.4f}\n"
        f"🛑 Stop Loss: {sl:.4f}\n"
        f"🎯 TP1: {tp1:.4f}\n"
        f"🎯 TP2: {tp2:.4f}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 RSI: {rsi:.1f}\n"
        f"EMA20: {ema20:.4f}\n"
        f"EMA50: {ema50:.4f}\n"
        f"Support: {support:.4f}\n"
        f"Resistance: {resistance:.4f}\n"
        f"📌 Setup: {reason}\n"
        f"⏱ Timeframe: 15 Minutes\n"
        f"⚠️ Demo signal - confirm broker price"
    )

    if send_telegram(message):
        last_signals[name] = signal_key
        return message

    return None


# =============== BOT LOOP ===============

def trading_loop():
    logging.info("Trading bot started")

    while True:
        try:
            for name, symbol in ASSETS.items():
                try:
                    analyze_asset(name, symbol)
                except Exception as e:
                    logging.error("%s analysis error: %s", name, e)

                time.sleep(3)

        except Exception as e:
            logging.error("Main loop error: %s", e)

        time.sleep(CHECK_SECONDS)


def start_bot():
    global bot_started

    if not bot_started:
        bot_started = True

        thread = threading.Thread(
            target=trading_loop,
            daemon=True
        )
        thread.start()


# =============== FLASK / RENDER ===============

@app.route("/")
def home():
    return "GOLD + ETH + BTC + USOIL SIGNAL BOT ACTIVE"


@app.route("/test")
def test():
    return jsonify({
        "status": "running",
        "assets": list(ASSETS.keys()),
        "timeframe": TIMEFRAME
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


start_bot()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
