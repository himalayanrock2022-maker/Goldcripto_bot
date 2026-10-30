
import os
import threading
from datetime import datetime, timezone

import yfinance as yf
import pandas as pd
import ta

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Trading Signal Bot - Running"


# Har instrument ka apna Yahoo Finance symbol
PAIRS = {
    "XAUUSD GOLD": "GC=F",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "USOIL": "CL=F"
}

TIMEFRAMES = ["15m", "1h"]

# Same candle par duplicate automatic alerts rokne ke liye
last_alerted = {}


def download_data(symbol, timeframe):
    period = "60d"

    df = yf.download(
        symbol,
        period=period,
        interval=timeframe,
        auto_adjust=True,
        progress=False,
        threads=False
    )

    if df is None or df.empty:
        return None

    # Different yfinance MultiIndex formats handle karein
    if isinstance(df.columns, pd.MultiIndex):
        found = False

        for level in range(df.columns.nlevels):
            values = df.columns.get_level_values(level)

            if symbol in values:
                df = df.xs(
                    symbol,
                    axis=1,
                    level=level,
                    drop_level=True
                )
                found = True
                break

        if not found and isinstance(df.columns, pd.MultiIndex):
            new_columns = {}

            for col in df.columns:
                parts = list(col)
                for part in parts:
                    if str(part).lower() in [
                        "open", "high", "low", "close", "volume"
                    ]:
                        new_columns[part] = col
                        break

            if not all(
                key in new_columns
                for key in ["Open", "High", "Low", "Close"]
            ):
                return None

            df = df[
                [new_columns[k] for k in
                 ["Open", "High", "Low", "Close"]]
            ]
            df.columns = ["Open", "High", "Low", "Close"]

    required = ["Open", "High", "Low", "Close"]

    if not all(col in df.columns for col in required):
        return None

    df = df[required].copy()
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna()

    # Last candle incomplete ho sakti hai.
    # Sirf completed candles par calculation.
    if len(df) > 1:
        df = df.iloc[:-1]

    if len(df) < 220:
        return None

    return df


def get_signal(symbol, timeframe):
    try:
        df = download_data(symbol, timeframe)

        if df is None:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]

        # Genuine technical indicators
        df["EMA20"] = ta.trend.ema_indicator(close, window=20)
        df["EMA50"] = ta.trend.ema_indicator(close, window=50)
        df["EMA200"] = ta.trend.ema_indicator(close, window=200)

        df["RSI"] = ta.momentum.rsi(close, window=14)
        df["MACD"] = ta.trend.macd_diff(close)
        df["ATR"] = ta.volatility.average_true_range(
            high, low, close, window=14
        )
        df["ADX"] = ta.trend.adx(
            high, low, close, window=14
        )

        df = df.dropna()

        if len(df) < 5:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        price = float(last["Close"])
        atr = float(last["ATR"])
        rsi = float(last["RSI"])
        adx = float(last["ADX"])

        ema20 = float(last["EMA20"])
        ema50 = float(last["EMA50"])
        ema200 = float(last["EMA200"])

        macd = float(last["MACD"])
        prev_macd = float(prev["MACD"])

        if atr <= 0 or price <= 0:
            return None

        # Extreme RSI conditions mein entry avoid
        if rsi >= 70 or rsi <= 30:
            return None

        bullish_score = 0
        bearish_score = 0

        buy_reasons = []
        sell_reasons = []

        # BUY conditions
        if ema20 > ema50 > ema200:
            bullish_score += 25
            buy_reasons.append("EMA20 > EMA50 > EMA200")

        if price > ema20:
            bullish_score += 10
            buy_reasons.append("Price above EMA20")

        if 50 < rsi < 68 and rsi > float(prev["RSI"]):
            bullish_score += 15
            buy_reasons.append("RSI bullish momentum")

        if macd > 0 and macd > prev_macd:
            bullish_score += 20
            buy_reasons.append("MACD bullish")

        if adx >= 20:
            bullish_score += 15
            buy_reasons.append(f"ADX trend strength {adx:.1f}")

        if ema20 > ema50 and float(prev["EMA20"]) <= float(prev["EMA50"]):
            bullish_score += 15
            buy_reasons.append("Fresh bullish EMA crossover")

        # SELL conditions
        if ema20 < ema50 < ema200:
            bearish_score += 25
            sell_reasons.append("EMA20 < EMA50 < EMA200")

        if price < ema20:
            bearish_score += 10
            sell_reasons.append("Price below EMA20")

        if 32 < rsi < 50 and rsi < float(prev["RSI"]):
            bearish_score += 15
            sell_reasons.append("RSI bearish momentum")

        if macd < 0 and macd < prev_macd:
            bearish_score += 20
            sell_reasons.append("MACD bearish")

        if adx >= 20:
            bearish_score += 15
            sell_reasons.append(f"ADX trend strength {adx:.1f}")

        if ema20 < ema50 and float(prev["EMA20"]) >= float(prev["EMA50"]):
            bearish_score += 15
            sell_reasons.append("Fresh bearish EMA crossover")

        # Ek waqt mein sirf ek direction select hogi
        if bullish_score >= 80 and bullish_score > bearish_score:
            signal = "BUY"
            score = bullish_score
            reasons = buy_reasons

        elif bearish_score >= 80 and bearish_score > bullish_score:
            signal = "SELL"
            score = bearish_score
            reasons = sell_reasons

        else:
            return None

        # ATR-based risk management
        sl_distance = atr * 1.5
        tp1_distance = atr * 2.0
        tp2_distance = atr * 3.0

        if signal == "BUY":
            sl = price - sl_distance
            tp1 = price + tp1_distance
            tp2 = price + tp2_distance
        else:
            sl = price + sl_distance
            tp1 = price - tp1_distance
            tp2 = price - tp2_distance

        rr = tp1_distance / sl_distance

        return {
            "symbol": symbol,
            "time": str(df.index[-1]),
            "price": price,
            "signal": signal,
            "score": score,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "rr": rr,
            "rsi": rsi,
            "atr": atr,
            "adx": adx,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "reasons": reasons
        }

    except Exception as e:
        print(f"{symbol} {timeframe} ERROR: {e}")
        return None


def format_signal(sig, pair_name, timeframe):
    emoji = "🟢" if sig["signal"] == "BUY" else "🔴"

    return f"""
{emoji} *{sig['signal']} {pair_name}*
⏱ Timeframe: {timeframe}

💰 Entry: `{sig['price']:.3f}`
🛑 Stop Loss: `{sig['sl']:.3f}`
🎯 Take Profit 1: `{sig['tp1']:.3f}`
🎯 Take Profit 2: `{sig['tp2']:.3f}`

📊 Setup Score: {sig['score']}/100
⚖️ Risk Reward: 1:{sig['rr']:.2f}

📈 RSI: {sig['rsi']:.1f}
📉 ADX: {sig['adx']:.1f}
📊 ATR: {sig['atr']:.4f}

EMA20: {sig['ema20']:.3f}
EMA50: {sig['ema50']:.3f}
EMA200: {sig['ema200']:.3f}

✅ Conditions:
{chr(10).join('• ' + r for r in sig['reasons'])}

🕒 Candle: {sig['time']}
⚠️ Setup score is NOT a guaranteed win probability.
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Trading Signal Bot Running\n\n"
        "/gold - Gold signals\n"
        "/btc - Bitcoin signals\n"
        "/eth - Ethereum signals\n"
        "/oil - Crude Oil signals\n"
        "/all - All markets\n\n"
        "Only strong technical setups are shown."
    )


async def send_pair(update, pair_name):
    symbol = PAIRS[pair_name]
    sent = False

    for tf in TIMEFRAMES:
        sig = get_signal(symbol, tf)

        if sig:
            await update.message.reply_text(
                format_signal(sig, pair_name, tf),
                parse_mode="Markdown"
            )
            sent = True

    if not sent:
        await update.message.reply_text(
            f"⚪ {pair_name}: No strong setup right now. Wait."
        )


async def gold_cmd(update, context):
    await send_pair(update, "XAUUSD GOLD")


async def btc_cmd(update, context):
    await send_pair(update, "BTCUSD")


async def eth_cmd(update, context):
    await send_pair(update, "ETHUSD")


async def oil_cmd(update, context):
    await send_pair(update, "USOIL")


async def all_cmd(update, context):
    for pair_name in PAIRS:
        await send_pair(update, pair_name)


async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:
        return

    for pair_name, symbol in PAIRS.items():
        for tf in TIMEFRAMES:
            sig = get_signal(symbol, tf)

            if not sig:
                continue

            # Pair + timeframe + candle + direction unique key
            alert_key = (
                symbol,
                tf,
                sig["time"],
                sig["signal"]
            )

            if alert_key in last_alerted:
                continue

            try:
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=format_signal(sig, pair_name, tf),
                    parse_mode="Markdown"
                )

                last_alerted[alert_key] = True

            except Exception as e:
                print(f"Telegram error: {e}")


def run_bot():
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN missing!")
        return

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gold", gold_cmd))
    application.add_handler(CommandHandler("btc", btc_cmd))
    application.add_handler(CommandHandler("eth", eth_cmd))
    application.add_handler(CommandHandler("oil", oil_cmd))
    application.add_handler(CommandHandler("all", all_cmd))

    application.job_queue.run_repeating(
        auto_check,
        interval=900,
        first=30
    )

    print("Trading bot started.")
    application.run_polling()


if __name__ == "__main__":
    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 8000))

    app_flask.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False
    )
