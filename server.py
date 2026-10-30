
import os
import time
import threading
import requests
from datetime import datetime, timezone
from flask import Flask

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = "-1003953683540"

app = Flask(__name__)

last_signal_price = None
last_signal_time = 0
last_signal_side = None
last_candle_time = None

SCAN_INTERVAL = 900
MIN_SCORE = 70

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})


def send_msg(text):
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing")
        return False

    try:
        r = session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHANNEL_ID,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=15
        )
        r.raise_for_status()
        return r.json().get("ok", False)

    except Exception as e:
        print("Telegram error:", e)
        return False


# REAL GOLD MARKET DATA - XAU/USD
def get_gold_candles():

    try:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            "XAUUSD=X?interval=15m&range=5d"
        )

        r = session.get(url, timeout=15)
        r.raise_for_status()

        result = r.json()["chart"]["result"]

        if not result:
            return None

        data = result[0]

        timestamps = data["timestamp"]
        quote = data["indicators"]["quote"][0]

        candles = []

        for i, ts in enumerate(timestamps):

            close = quote["close"][i]
            high = quote["high"][i]
            low = quote["low"][i]

            if close is None or high is None or low is None:
                continue

            candles.append({
                "time": ts,
                "close": float(close),
                "high": float(high),
                "low": float(low)
            })

        # Only completed 15-minute candles
        current_slot = int(time.time() // 900) * 900

        candles = [
            c for c in candles
            if c["time"] < current_slot
        ]

        if len(candles) < 60:
            return None

        return candles[-100:]

    except Exception as e:
        print("Gold data error:", e)
        return None


def ema(values, period):

    if len(values) < period:
        return None

    k = 2 / (period + 1)

    value = sum(values[:period]) / period

    for price in values[period:]:
        value = price * k + value * (1 - k)

    return value


def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):

        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(candles, period=14):

    trs = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - previous),
            abs(low - previous)
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = (
            value * (period - 1) + tr
        ) / period

    return value


def analyze_gold():

    candles = get_gold_candles()

    if not candles:
        return None

    closes = [c["close"] for c in candles]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi_value = rsi(closes)
    atr_value = atr(candles)

    if None in (ema20, ema50, rsi_value, atr_value):
        return None

    if atr_value <= 0:
        return None

    previous_ema20 = ema(closes[:-1], 20)

    if previous_ema20 is None:
        return None

    # MACD
    macd = ema(closes, 12) - ema(closes, 26)

    macd_signal = ema(
        [
            ema(closes[:i + 1], 12) -
            ema(closes[:i + 1], 26)
            for i in range(25, len(closes))
        ],
        9
    )

    if macd_signal is None:
        return None

    # Market structure
    support = min(c["low"] for c in candles[-20:])
    resistance = max(c["high"] for c in candles[-20:])

    bullish = 0
    bearish = 0

    # Trend confirmation
    if price > ema20 and ema20 > ema50:
        bullish += 25

    if price < ema20 and ema20 < ema50:
        bearish += 25

    # Price position
    if price > ema20:
        bullish += 10

    if price < ema20:
        bearish += 10

    # RSI confirmation
    if 52 <= rsi_value <= 68:
        bullish += 15

    if 32 <= rsi_value <= 48:
        bearish += 15

    # MACD confirmation
    if macd > macd_signal:
        bullish += 15

    if macd < macd_signal:
        bearish += 15

    # Momentum confirmation
    if closes[-1] > closes[-2] > closes[-3]:
        bullish += 15

    if closes[-1] < closes[-2] < closes[-3]:
        bearish += 15

    # EMA direction
    if ema20 > previous_ema20:
        bullish += 10

    if ema20 < previous_ema20:
        bearish += 10

    # Candle confirmation
    last_candle = candles[-1]

    if (
        last_candle["close"] >
        last_candle["low"] +
        (last_candle["high"] - last_candle["low"]) * 0.65
    ):
        bullish += 10

    if (
        last_candle["close"] <
        last_candle["low"] +
        (last_candle["high"] - last_candle["low"]) * 0.35
    ):
        bearish += 10

    side = "WAIT"
    score = max(bullish, bearish)

    if bullish >= MIN_SCORE and bullish > bearish:
        side = "BUY"

    elif bearish >= MIN_SCORE and bearish > bullish:
        side = "SELL"

    result = {
        "side": side,
        "price": price,
        "rsi": rsi_value,
        "ema20": ema20,
        "ema50": ema50,
        "atr": atr_value,
        "score": score,
        "support": support,
        "resistance": resistance,
        "candle_time": candles[-1]["time"]
    }

    if side == "BUY":

        result["sl"] = price - atr_value * 1.5
        result["tp1"] = price + atr_value * 1.5
        result["tp2"] = price + atr_value * 2.5
        result["tp_big"] = price + atr_value * 3.5

    elif side == "SELL":

        result["sl"] = price + atr_value * 1.5
        result["tp1"] = price - atr_value * 1.5
        result["tp2"] = price - atr_value * 2.5
        result["tp_big"] = price - atr_value * 3.5

    return result


def run_wait_logic():

    global last_signal_price
    global last_signal_time
    global last_signal_side
    global last_candle_time

    data = analyze_gold()

    if data is None:

        print("WAIT: Real Gold data unavailable")

        send_msg(
            "⚠️ *GOLD DATA UNAVAILABLE*\n\n"
            "Real market candles could not be verified.\n"
            "No trade signal generated.\n"
            "⏳ WAIT"
        )

        return

    side = data["side"]
    price = data["price"]

    candle_time = data["candle_time"]

    candle_text = datetime.fromtimestamp(
        candle_time,
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    # No duplicate candle processing
    if candle_time == last_candle_time:
        return

    last_candle_time = candle_time

    # Signal suppression
    if side in ("BUY", "SELL"):

        same_trade = (
            last_signal_side == side
            and last_signal_price is not None
            and abs(price - last_signal_price) < 3
            and time.time() - last_signal_time < 7200
        )

        if same_trade:
            print("Duplicate signal suppressed")
            return

        message = (
            f"📊 *{side} - XAU/USD GOLD*\n"
            f"*Setup Score: {data['score']}/100*\n\n"

            f"💰 Live Price: {price:.2f}\n"
            f"📈 RSI: {data['rsi']:.1f}\n"
            f"EMA20: {data['ema20']:.2f}\n"
            f"EMA50: {data['ema50']:.2f}\n"
            f"ATR: {data['atr']:.2f}\n\n"

            f"Support: {data['support']:.2f}\n"
            f"Resistance: {data['resistance']:.2f}\n\n"

            f"🎯 Entry: {price:.2f}\n"
            f"🛑 SL: {data['sl']:.2f}\n"
            f"✅ TP1: {data['tp1']:.2f}\n"
            f"✅ TP2: {data['tp2']:.2f}\n"
            f"🚀 BIG TP: {data['tp_big']:.2f}\n\n"

            f"⏰ Candle: {candle_text}\n"
            f"Gold Only | 15M | Real Market Data\n"
            f"⚠️ Setup score is not guaranteed accuracy."
        )

        if send_msg(message):

            last_signal_price = price
            last_signal_time = time.time()
            last_signal_side = side

    else:

        direction = (
            "BUY setup confirmation ka wait"
            if price > data["ema20"]
            else "SELL setup confirmation ka wait"
        )

        message = (
            "⏳ *WAIT - NO TRADE*\n"
            "*XAU/USD GOLD*\n\n"

            f"💰 Live: {price:.2f}\n"
            f"RSI: {data['rsi']:.1f}\n"
            f"EMA20: {data['ema20']:.2f}\n"
            f"EMA50: {data['ema50']:.2f}\n\n"

            f"Setup Score: {data['score']}/100\n"
            f"Required: {MIN_SCORE}/100\n\n"

            f"Support: {data['support']:.2f}\n"
            f"Resistance: {data['resistance']:.2f}\n\n"

            f"📌 {direction}\n"
            f"⏰ Next scan: 15 minutes\n"
            f"🚫 No random trade."
        )

        send_msg(message)


@app.route("/")
def home():

    data = get_gold_candles()

    if not data:
        return "Gold data unavailable - WAIT"

    return (
        f"GOLD SIGNAL BOT ACTIVE | "
        f"XAU/USD: {data[-1]['close']:.2f}"
    )


@app.route("/test")
def test():

    run_wait_logic()

    return "Gold scan completed. Check Telegram."


def auto():

    while True:

        try:
            run_wait_logic()

        except Exception as e:
            print("Bot error:", e)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":

    threading.Thread(
        target=auto,
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
