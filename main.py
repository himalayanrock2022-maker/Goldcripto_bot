import os
import threading
from flask import Flask
import yfinance as yf
import pandas as pd
import ta
from datetime import datetime
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot Running @Goldcripto_bot"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

def get_signal(symbol):
    try:
        df = yf.download(symbol, period="2d", interval="5m", progress=False, auto_adjust=True)
        if len(df) < 50:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df['Close']
        high = df['High']
        low = df['Low']
        df['EMA20'] = ta.trend.ema_indicator(close, window=20)
        df['EMA50'] = ta.trend.ema_indicator(close, window=50)
        df['RSI'] = ta.momentum.rsi(close, window=14)
        df['ATR'] = ta.volatility.average_true_range(high, low, close, window=14)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(last['Close'])
        atr = float(last['ATR'])
        rsi = float(last['RSI'])
        ema20 = float(last['EMA20'])
        ema50 = float(last['EMA50'])
        sig = None
        conf = 0
        reason = []
        if ema20 > ema50 and prev['EMA20'] <= prev['EMA50']:
            sig = "BUY"
            conf += 40
            reason.append("EMA bullish cross")
        if rsi < 40 and rsi > float(prev['RSI']):
            sig = "BUY" if sig is None else sig
            conf += 25
            reason.append(f"RSI bounce {rsi:.1f}")
        if ema20 < ema50 and prev['EMA20'] >= prev['EMA50']:
            sig = "SELL"
            conf += 40
            reason.append("EMA bearish cross")
        if rsi > 60 and rsi < float(prev['RSI']):
            sig = "SELL" if sig is None else sig
            conf += 25
            reason.append(f"RSI reversal {rsi:.1f}")
        if sig is None or conf < 40:
            return None
        is_gold = "GC" in symbol
        sl_m = 1.5 if is_gold else 1.2
        tp1_m = 2.0 if is_gold else 1.8
        tp2_m = 3.5 if is_gold else 3.0
        sl_d = atr * sl_m
        tp1_d = atr * tp1_m
        tp2_d = atr * tp2_m
        if sig == "BUY":
            sl = price - sl_d
            tp1 = price + tp1_d
            tp2 = price + tp2_d
        else:
            sl = price + sl_d
            tp1 = price - tp1_d
            tp2 = price - tp2_d
        rr = abs(tp1 - price) / abs(price - sl) if abs(price - sl) > 0 else 0
        return {"price": price, "sig": sig, "conf": min(conf+15, 85), "sl": sl, "tp1": tp1, "tp2": tp2, "rr": rr, "rsi": rsi, "reason": ",".join(reason)}
    except Exception as e:
        print(e)
        return None

def fmt(s, pair, tf):
    e = "🟢" if s["sig"] == "BUY" else "🔴"
    return f"{e} *{s['sig']} {pair} {tf} {s['conf']}%*\n\nEntry: `{s['price']:.2f}`\nSL: `{s['sl']:.2f}`\nTP1: `{s['tp1']:.2f}` (1:{s['rr']:.1f})\nTP2: `{s['tp2']:.2f}`\n\n{s['reason']}\nRSI {s['rsi']:.1f}\nRisk 1%"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Live! /gold /btc /eth")

async def gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_signal("GC=F")
    if s:
        await update.message.reply_text(fmt(s, "XAUUSD GOLD", "5M"), parse_mode="Markdown")
    else:
        await update.message.reply_text("Gold - No strong signal now, wait candle")

async def btc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_signal("BTC-USD")
    if s:
        await update.message.reply_text(fmt(s, "BTCUSD", "5M"), parse_mode="Markdown")
    else:
        await update.message.reply_text("BTC - No signal now")

async def eth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_signal("ETH-USD")
    if s:
        await update.message.reply_text(fmt(s, "ETHUSD", "5M"), parse_mode="Markdown")
    else:
        await update.message.reply_text("ETH - No signal")

async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    if CHAT_ID is None or CHAT_ID == "":
        return
    for name, sym in [("GOLD", "GC=F"), ("BTC", "BTC-USD")]:
        s = get_signal(sym)
        if s and s["conf"] >= 70:
            try:
                await context.bot.send_message(chat_id=CHAT_ID, text=fmt(s, name, "5M AUTO"), parse_mode="Markdown")
            except:
                pass

def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gold", gold))
    app.add_handler(CommandHandler("btc", btc))
    app.add_handler(CommandHandler("eth", eth))
    app.job_queue.run_repeating(auto_check, interval=300, first=20)
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
