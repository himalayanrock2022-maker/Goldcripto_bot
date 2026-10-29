import os
import threading
from flask import Flask
import yfinance as yf
import pandas as pd
import ta
from datetime import datetime
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Gold Crypto Bot Always Analysis - Running!"

PAIRS = {
    "XAUUSD GOLD": "GC=F",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD"
}

def get_analysis(yf_symbol, timeframe="5m"):
    try:
        df = yf.download(yf_symbol, period="2d", interval=timeframe, progress=False, auto_adjust=True)
        if len(df) < 60:
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
        if ema20 > ema50:
            signal = "BUY"
            trend = "Uptrend"
            confidence = 50
        elif ema20 < ema50:
            signal = "SELL"
            trend = "Downtrend"
            confidence = 50
        else:
            signal = "WAIT"
            trend = "Sideways"
            confidence = 30
        reasons = []
        if rsi < 35:
            reasons.append(f"RSI oversold {rsi:.1f} - BUY chance")
            if signal == "BUY": confidence += 20
        elif rsi > 65:
            reasons.append(f"RSI overbought {rsi:.1f} - SELL chance")
            if signal == "SELL": confidence += 20
        else:
            reasons.append(f"RSI neutral {rsi:.1f}")
        if ema20 > ema50:
            reasons.append("EMA20 above EMA50 - bullish")
        else:
            reasons.append("EMA20 below EMA50 - bearish")
        is_gold = "GC" in yf_symbol
        mult_sl = 1.5 if is_gold else 1.2
        mult_tp1 = 2.0 if is_gold else 1.8
        mult_tp2 = 3.5 if is_gold else 3.0
        sl_dist = atr * mult_sl
        tp1_dist = atr * mult_tp1
        tp2_dist = atr * mult_tp2
        if signal == "BUY":
            sl = price - sl_dist
            tp1 = price + tp1_dist
            tp2 = price + tp2_dist
        elif signal == "SELL":
            sl = price + sl_dist
            tp1 = price - tp1_dist
            tp2 = price - tp2_dist
        else:
            sl = price - sl_dist
            tp1 = price + tp1_dist
            tp2 = price + tp2_dist
        if abs(ema20 - ema50) > atr*0.5:
            confidence += 15
        confidence = min(max(confidence, 25), 88)
        strength = "STRONG" if confidence >= 70 else "MODERATE" if confidence >= 55 else "WEAK - WAIT"
        rr1 = abs(tp1 - price) / abs(price - sl) if abs(price - sl) else 0
        return {"price": price, "signal": signal, "trend": trend, "confidence": confidence, "strength": strength, "sl": sl, "tp1": tp1, "tp2": tp2, "rr1": rr1, "rsi": rsi, "atr": atr, "ema20": ema20, "ema50": ema50, "reasons": reasons}
    except Exception as e:
        print(f"Error: {e}")
        return None

def format_analysis(sig, pair_name, tf):
    emoji = "🟢" if sig['signal'] == "BUY" and sig['confidence'] >= 70 else "🔴" if sig['signal'] == "SELL" and sig['confidence'] >= 70 else "🟡" if sig['confidence'] >= 55 else "⚪"
    return f"{emoji} *{sig['signal']} {pair_name} | {tf} | {sig['confidence']}% - {sig['strength']}*\n\n💰 Price: `{sig['price']:.2f}`\n📈 Trend: {sig['trend']}\n🛑 SL: `{sig['sl']:.2f}`\n🎯 TP1: `{sig['tp1']:.2f}` (1:{sig['rr1']:.1f})\n🎯 TP2: `{sig['tp2']:.2f}`\n\n📊 {sig['reasons'][0]}\n• {sig['reasons'][1]}\nRSI {sig['rsi']:.1f} | ATR {sig['atr']:.2f}\n⏰ {datetime.now().strftime('%H:%M PKT')}\n⚠️ {sig['strength']}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gold & Crypto Bot - Always Analysis!\n/gold - Gold\n/btc - BTC\n/eth - ETH")

async def gold_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for tf in ["5m", "15m"]:
        sig = get_analysis("GC=F", tf)
        if sig:
            await update.message.reply_text(format_analysis(sig, "XAUUSD GOLD", tf), parse_mode="Markdown")

async def btc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sig = get_analysis("BTC-USD", "5m")
    if sig:
        await update.message.reply_text(format_analysis(sig, "BTCUSD", "5M"), parse_mode="Markdown")

async def eth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sig = get_analysis("ETH-USD", "5m")
    if sig:
        await update.message.reply_text(format_analysis(sig, "ETHUSD", "5M"), parse_mode="Markdown")

async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:
        return
    for name, yf_sym in PAIRS.items():
        sig = get_analysis(yf_sym, "5m")
        if sig and sig['confidence'] >= 70:
            try:
                await context.bot.send_message(chat_id=CHAT_ID, text=format_analysis(sig, name, "5M AUTO"), parse_mode="Markdown")
            except Exception as e:
                print(e)

def run_bot():
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN not set!")
        return
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gold", gold_cmd))
    app.add_handler(CommandHandler("btc", btc_cmd))
    app.add_handler(CommandHandler("eth", eth_cmd))
    app.job_queue.run_repeating(auto_check, interval=300, first=15)
    print("Bot running - Always Analysis Mode")
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)
