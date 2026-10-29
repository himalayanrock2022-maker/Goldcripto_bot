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
    return "Gold Crypto Bot - STRONG ONLY 80%+ - Running"

PAIRS = {
    "XAUUSD GOLD": "GC=F",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD"
}

def get_strong_only(yf_symbol, timeframe="15m"):
    try:
        df = yf.download(yf_symbol, period="5d", interval=timeframe, progress=False, auto_adjust=True)
        if len(df) < 100:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df['Close']
        high = df['High']
        low = df['Low']
        
        df['EMA20'] = ta.trend.ema_indicator(close, window=20)
        df['EMA50'] = ta.trend.ema_indicator(close, window=50)
        df['EMA200'] = ta.trend.ema_indicator(close, window=200)
        df['RSI'] = ta.momentum.rsi(close, window=14)
        df['ATR'] = ta.volatility.average_true_range(high, low, close, window=14)
        df['MACD'] = ta.trend.macd_diff(close)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        price = float(last['Close'])
        atr = float(last['ATR'])
        rsi = float(last['RSI'])
        ema20 = float(last['EMA20'])
        ema50 = float(last['EMA50'])
        ema200 = float(last['EMA200'])
        macd = float(last['MACD'])
        macd_prev = float(prev['MACD'])
        
        confidence = 0
        reasons = []
        
        if rsi < 32 or rsi > 68:
            return None
        
        is_strong_uptrend = ema20 > ema50 > ema200
        is_strong_downtrend = ema20 < ema50 < ema200
        
        macd_bull = macd > 0 and macd > macd_prev
        macd_bear = macd < 0 and macd < macd_prev
        
        if is_strong_uptrend:
            confidence += 30
            reasons.append("Strong Uptrend EMA20>50>200")
        if 40 < rsi < 60 and rsi > prev['RSI']:
            confidence += 25
            reasons.append(f"RSI healthy momentum {rsi:.1f}")
        if macd_bull:
            confidence += 25
            reasons.append("MACD bullish")
        if ema20 > ema50 and prev['EMA20'] <= prev['EMA50']:
            confidence += 30
            reasons.append("Fresh EMA crossover")
        if abs(ema20 - ema50) > atr*0.8:
            confidence += 15
            reasons.append("Wide trend gap")
        
        if is_strong_downtrend and confidence < 50:
            confidence = 0
            reasons = []
            confidence += 30
            reasons.append("Strong Downtrend EMA20<50<200")
        if 40 < rsi < 60 and rsi < prev['RSI'] and not is_strong_uptrend:
            confidence += 25
            reasons.append(f"RSI bearish momentum {rsi:.1f}")
        if macd_bear and not is_strong_uptrend:
            confidence += 25
            reasons.append("MACD bearish")
        if ema20 < ema50 and prev['EMA20'] >= prev['EMA50'] and not is_strong_uptrend:
            confidence += 30
            reasons.append("Fresh EMA bear cross")
        
        if confidence < 80:
            return None
        
        if is_strong_uptrend or (ema20 > ema50 and macd_bull and rsi < 65):
            signal = "BUY"
            trend = "STRONG Uptrend - Big Move Expected"
        else:
            signal = "SELL"
            trend = "STRONG Downtrend - Big Move Expected"
        
        is_gold = "GC" in yf_symbol
        if is_gold:
            mult_sl = 3.0
            mult_tp1 = 5.0
            mult_tp2 = 9.0
        else:
            mult_sl = 2.5
            mult_tp1 = 4.5
            mult_tp2 = 8.0
        
        sl_dist = atr * mult_sl
        tp1_dist = atr * mult_tp1
        tp2_dist = atr * mult_tp2
        
        if signal == "BUY":
            sl = price - sl_dist
            tp1 = price + tp1_dist
            tp2 = price + tp2_dist
        else:
            sl = price + sl_dist
            tp1 = price - tp1_dist
            tp2 = price - tp2_dist
        
        rr1 = abs(tp1 - price) / abs(price - sl) if abs(price - sl) else 0
        points_tp1 = abs(tp1 - price)
        points_sl = abs(price - sl)
        
        return {
            "price": price, "signal": signal, "trend": trend, "confidence": min(confidence, 92),
            "sl": sl, "tp1": tp1, "tp2": tp2, "rr1": rr1,
            "points_tp1": points_tp1, "points_sl": points_sl,
            "rsi": rsi, "atr": atr, "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "reasons": reasons
        }
    except Exception as e:
        print(f"Error: {e}")
        return None

def format_strong(sig, pair_name, tf):
    emoji = "🟢" if sig['signal'] == "BUY" else "🔴"
    return f"""{emoji} *{sig['signal']} {pair_name} | {tf} | {sig['confidence']}% - STRONG*

💰 Entry: `{sig['price']:.2f}`
🛑 SL: `{sig['sl']:.2f}` ({sig['points_sl']:.1f} pts)
🎯 TP1: `{sig['tp1']:.2f}` ({sig['points_tp1']:.1f} pts) (1:{sig['rr1']:.1f})
🎯 TP2: `{sig['tp2']:.2f}`

📈 {sig['trend']}
📊 {', '.join(sig['reasons'])}

EMA20 {sig['ema20']:.1f} | EMA50 {sig['ema50']:.1f} | EMA200 {sig['ema200']:.1f}
RSI {sig['rsi']:.1f} | ATR {sig['atr']:.2f}

✅ HIGH ACCURACY - Big Move Trade
⏰ {datetime.now().strftime('%H:%M PKT')}
⚠️ Risk 1% | Swing/Scalp Mix - London Session Best
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gold & Crypto Bot - STRONG ONLY MODE!\n✅ Only 80%+ signals\n✅ Big points, no short scalps\n✅ No MODERATE/WEAK\n\n/gold - Gold STRONG\n/btc - BTC STRONG\n/eth - ETH STRONG\n\nNo signal = No trade - Market ranging")

async def gold_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sent = False
    for tf in ["15m", "1h"]:
        sig = get_strong_only("GC=F", tf)
        if sig:
            await update.message.reply_text(format_strong(sig, "XAUUSD GOLD", tf), parse_mode="Markdown")
            sent = True
    if not sent:
        await update.message.reply_text("⚪ GOLD - No STRONG signal now\nMarket is ranging - Wait for London session (1:30 PM - 9 PM PKT)\nBot only sends 80%+ high accuracy signals with big points")

async def btc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sent = False
    for tf in ["15m", "1h"]:
        sig = get_strong_only("BTC-USD", tf)
        if sig:
            await update.message.reply_text(format_strong(sig, "BTCUSD", tf), parse_mode="Markdown")
            sent = True
    if not sent:
        await update.message.reply_text("⚪ BTC - No STRONG signal now - Wait")

async def eth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sig = get_strong_only("ETH-USD", "15m")
    if sig:
        await update.message.reply_text(format_strong(sig, "ETHUSD", "15M"), parse_mode="Markdown")
    else:
        await update.message.reply_text("⚪ ETH - No STRONG signal now - Wait")

async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:
        return
    for name, yf_sym in PAIRS.items():
        for tf in ["15m", "1h"]:
            sig = get_strong_only(yf_sym, tf)
            if sig:
                try:
                    await context.bot.send_message(chat_id=CHAT_ID, text=format_strong(sig, name, f"{tf} AUTO"), parse_mode="Markdown")
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
    app.job_queue.run_repeating(auto_check, interval=900, first=30)
    print("Bot running - STRONG ONLY 80%+ - Big Points")
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 8000))
    app_flask.run(host="0.0.0.0", port=port)
