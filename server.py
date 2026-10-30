
import os
import time
import threading
import requests
from datetime import datetime, timezone
from flask import Flask

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = "-1003953683540"

app = Flask(__name__)
session = requests.Session()

MIN_SCORE = 70
SCAN_INTERVAL = 900
SYMBOL = "XAUUSD=X"

last_candle = None
last_signal_key = None
last_signal_time = 0

pending_breakout = None


def send_msg(message):
    if not BOT_TOKEN:
        print("BOT_TOKEN missing")
        return False

    try:
        r = session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHANNEL_ID,
                "text": message
            },
            timeout=15
        )
        r.raise_for_status()
        return r.json().get("ok", False)
    except Exception as e:
        print("Telegram error:", e)
        return False


# REAL XAU/USD DATA
def get_candles():
    try:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + SYMBOL
            + "?interval=15m&range=5d"
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

        current_slot = int(time.time() // 900) * 900

        for i, ts in enumerate(timestamps):
            o = quote["open"][i]
            h = quote["high"][i]
            l = quote["low"][i]
            c = quote["close"][i]

            if None in (o, h, l, c):
                continue

            if ts >= current_slot:
                continue

            candles.append({
                "time": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c)
            })

        if len(candles) < 60:
            return None

        # Reject stale market data
        if time.time() - candles[-1]["time"] > 3600:
            return None

        return candles[-100:]

    except Exception as e:
        print("Market data error:", e)
        return None


def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    value = sum(values[:period]) / period

    for p in values[period:]:
        value = p * k + value * (1 - k)

    return value


def calculate_rsi(values, period=14):
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


def calculate_atr(candles, period=14):
    trs = []

    for i in range(1, len(candles)):
        c = candles[i]
        prev = candles[i - 1]["close"]

        trs.append(max(
            c["high"] - c["low"],
            abs(c["high"] - prev),
            abs(c["low"] - prev)
        ))

    if len(trs) < period:
        return None

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = (
            value * (period - 1) + tr
        ) / period

    return value


def analyze():

    global pending_breakout

    candles = get_candles()

    if not candles:
        return None

    closes = [c["close"] for c in candles]

    current = candles[-1]
    previous = candles[-2]

    price = current["close"]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rsi = calculate_rsi(closes)
    atr = calculate_atr(candles)

    if None in (e20, e50, rsi, atr) or atr <= 0:
        return None

    # Levels calculated from preceding candles
    history = candles[-21:-1]

    support = min(c["low"] for c in history)
    resistance = max(c["high"] for c in history)

    bullish = 0
    bearish = 0

    # Trend
    if price > e20 > e50:
        bullish += 20

    if price < e20 < e50:
        bearish += 20

    # Momentum
    if price > previous["close"]:
        bullish += 10

    if price < previous["close"]:
        bearish += 10

    # RSI - avoid extreme entries
    if 45 <= rsi <= 68:
        bullish += 15

    if 32 <= rsi <= 55:
        bearish += 15

    # EMA position
    if price > e20:
        bullish += 10

    if price < e20:
        bearish += 10

    # Strong candle body
    body = abs(current["close"] - current["open"])
    candle_range = current["high"] - current["low"]

    if candle_range > 0:
        if (
            current["close"] > current["open"]
            and body / candle_range >= 0.55
        ):
            bullish += 15

        if (
            current["close"] < current["open"]
            and body / candle_range >= 0.55
        ):
            bearish += 15

    # SUPPORT REJECTION
    lower_wick = (
        min(current["open"], current["close"])
        - current["low"]
    )

    upper_wick = (
        current["high"]
        - max(current["open"], current["close"])
    )

    buy_rejection = (
        current["low"] <= support + atr * 0.25
        and current["close"] > support + atr * 0.15
        and current["close"] > current["open"]
        and lower_wick > max(body * 1.2, atr * 0.15)
        and 40 <= rsi <= 70
    )

    # RESISTANCE REJECTION
    sell_rejection = (
        current["high"] >= resistance - atr * 0.25
        and current["close"] < resistance - atr * 0.15
        and current["close"] < current["open"]
        and upper_wick > max(body * 1.2, atr * 0.15)
        and 30 <= rsi <= 60
    )

    # BREAKOUT DETECTION
    buffer = atr * 0.15

    if (
        current["close"] > resistance + buffer
        and current["close"] > current["open"]
    ):
        pending_breakout = {
            "side": "BUY",
            "level": resistance,
            "time": current["time"]
        }

    elif (
        current["close"] < support - buffer
        and current["close"] < current["open"]
    ):
        pending_breakout = {
            "side": "SELL",
            "level": support,
            "time": current["time"]
        }

    # BREAKOUT RETEST
    buy_retest = False
    sell_retest = False

    if pending_breakout:

        level = pending_breakout["level"]
        age = current["time"] - pending_breakout["time"]

        if age > 0 and age <= 4 * 900:

            if pending_breakout["side"] == "BUY":
                buy_retest = (
                    current["low"] <= level + atr * 0.25
                    and current["close"] > level + atr * 0.05
                    and current["close"] > current["open"]
                    and rsi < 75
                )

            if pending_breakout["side"] == "SELL":
                sell_retest = (
                    current["high"] >= level - atr * 0.25
                    and current["close"] < level - atr * 0.05
                    and current["close"] < current["open"]
                    and rsi > 25
                )

        else:
            pending_breakout = None

    # SETUP DECISION
    side = "WAIT"
    setup = "NONE"
    score = 0

    if buy_retest:
        side = "BUY"
        setup = "BREAKOUT RETEST"
        score = min(95, 70 + bullish // 5)
        pending_breakout = None

    elif sell_retest:
        side = "SELL"
        setup = "BREAKDOWN RETEST"
        score = min(95, 70 + bearish // 5)
        pending_breakout = None

    elif buy_rejection and bullish >= 35:
        side = "BUY"
        setup = "SUPPORT REJECTION"
        score = min(95, 65 + bullish // 3)

    elif sell_rejection and bearish >= 35:
        side = "SELL"
        setup = "RESISTANCE REJECTION"
        score = min(95, 65 + bearish // 3)

    # RSI extreme protection
    if side == "BUY" and rsi >= 75:
        side = "WAIT"

    if side == "SELL" and rsi <= 25:
        side = "WAIT"

    if score < MIN_SCORE:
        side = "WAIT"

    return {
        "side": side,
        "setup": setup,
        "score": score,
        "price": price,
        "rsi": rsi,
        "ema20": e20,
        "ema50": e50,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "time": current["time"]
    }


def run_bot():

    global last_candle
    global last_signal_key
    global last_signal_time

    data = analyze()

    if not data:
        print("WAIT: Gold market data unavailable")
        return

    candle_time = data["time"]

    # One scan per completed candle
    if candle_time == last_candle:
        return

    last_candle = candle_time

    side = data["side"]
    price = data["price"]

    candle_label = datetime.fromtimestamp(
        candle_time, timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    if side == "WAIT":

        msg = (
            "⏳ WAIT - XAU/USD GOLD\n\n"
            f"Price: {price:.2f}\n"
            f"RSI: {data['rsi']:.1f}\n"
            f"EMA20: {data['ema20']:.2f}\n"
            f"EMA50: {data['ema50']:.2f}\n\n"
            f"Support: {data['support']:.2f}\n"
            f"Resistance: {data['resistance']:.2f}\n\n"
            "No confirmed rejection/retest.\n"
            "Wait for next completed 15M candle."
        )

        send_msg(msg)
        return

    signal_key = (
        side,
        data["setup"],
        round(price, 1)
    )

    if signal_key == last_signal_key:
        return

    if time.time() - last_signal_time < 1800:
        return

    if side == "BUY":
        sl = price - data["atr"] * 1.5
        tp1 = price + data["atr"] * 1.5
        tp2 = price + data["atr"] * 2.5
        tp3 = price + data["atr"] * 3.5

    else:
        sl = price + data["atr"] * 1.5
        tp1 = price - data["atr"] * 1.5
        tp2 = price - data["atr"] * 2.5
        tp3 = price - data["atr"] * 3.5

    msg = (
        f"📈 {side} - XAU/USD GOLD\n"
        f"Setup: {data['setup']}\n"
        f"Technical Score: {data['score']}/100\n\n"

        f"Entry: {price:.2f}\n"
        f"SL: {sl:.2f}\n"
        f"TP1: {tp1:.2f}\n"
        f"TP2: {tp2:.2f}\n"
        f"BIG TP: {tp3:.2f}\n\n"

        f"RSI: {data['rsi']:.1f}\n"
        f"EMA20: {data['ema20']:.2f}\n"
        f"EMA50: {data['ema50']:.2f}\n\n"

        f"Support: {data['support']:.2f}\n"
        f"Resistance: {data['resistance']:.2f}\n\n"

        f"Candle: {candle_label}\n"
        "Gold Only | 15M | Real Market Feed\n"
        "Score is not guaranteed win probability."
    )

    if send_msg(msg):
        last_signal_key = signal_key
        last_signal_time = time.time()


@app.route("/")
def home():
    candles = get_candles()

    if not candles:
        return "Gold data unavailable - WAIT"

    return (
        "GOLD REJECTION + BREAKOUT BOT ACTIVE | "
        + str(candles[-1]["close"])
    )


@app.route("/test")
def test():
    run_bot()
    return "Gold scan completed. Check Telegram."


def auto():
    while True:
        try:
            run_bot()
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
