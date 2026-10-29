import os, threading
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
    return "Bot Running"

PAIRS = {"XAUUSD GOLD": "GC=F","BTCUSD": "BTC-USD","ETHUSD": "ETH-USD"}

def get_analysis(yf_symbol, timeframe="5m"):
    try:
        df = yf.download(yf_symbol, period="2d", interval=timeframe, progress=False, auto_adjust=True)
        if len(df) < 60: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        close, high, low = df['Close'], df['High'], df['Low']
        df['EMA20'] = ta.trend.ema_indicator(close, window=20)
        df['EMA50'] = ta.trend.ema_indicator(close, window=50)
        df['RSI'] = ta.momentum.rsi(close, window=14)
        df['ATR'] = ta.volatility.average_true_range(high, low, close, window=14)
        last, prev = df.iloc[-1], df.iloc[-2]
        price, atr, rsi = float(last['Close']), float(last['ATR']), float(last['RSI'])
        ema20, ema50 = float(last['EMA20']), float(last['EMA50'])
        signal, trend, conf = ("BUY","Uptrend",55) if ema20>ema50 else ("SELL","Downtrend",55) if ema20<ema50 else ("WAIT","Sideways",30)
        reasons = [f"RSI {rsi:.1f}","EMA20 {'above' if ema20>ema50 else 'below'} EMA50"]
        is_gold = "GC" in yf_symbol
        sl_dist, tp1_dist, tp2_dist = atr*(1.5 if is_gold else 1.2), atr*(2.0 if is_gold else 1.8), atr*(3.5 if is_gold else 3.0)
        sl, tp1, tp2 = (price-sl_dist, price+tp1_dist, price+tp2_dist) if signal=="BUY" else (price+sl_dist, price-tp1_dist, price-tp2_dist) if signal=="SELL" else (price-sl_dist, price+tp1_dist, price+tp2_dist)
        strength = "STRONG" if conf>=70 else "MODERATE" if conf>=55 else "WEAK - WAIT"
        rr1 = abs(tp1-price)/abs(price-sl) if abs(price-sl) else 0
        return {"price":price,"signal":signal,"trend":trend,"confidence":min(conf+20,85),"strength":strength,"sl":sl,"tp1":tp1,"tp2":tp2,"rr1":rr1,"rsi":rsi,"atr":atr,"reasons":reasons}
    except: return None

def format_analysis(sig, pair_name, tf):
    emoji = "🟢" if sig['signal']=="BUY" else "🔴" if sig['signal']=="SELL" else "⚪"
    return f"{emoji} *{sig['signal']} {pair_name} | {tf} | {sig['confidence']}% - {sig['strength']}*\n\n💰 Price: `{sig['price']:.2f}`\n📈 Trend: {sig['trend']}\n🛑 SL: `{sig['sl']:.2f}`\n🎯 TP1: `{sig['tp1']:.2f}` (1:{sig['rr1']:.1f})\n🎯 TP2: `{sig['tp2']:.2f}`\n\n📊 {sig['reasons'][0]}\nRSI {sig['rsi']:.1f}\n⏰ {datetime.now().strftime('%H:%M PKT')}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Live - Always Analysis!\n/gold - Gold\n/btc - BTC\n/eth - ETH")
async def gold_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for tf in ["5m","15m"]:
        sig=get_analysis("GC=F",tf)
        if sig: await update.message.reply_text(format_analysis(sig,"XAUUSD GOLD",tf),parse_mode="Markdown")
async def btc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sig=get_analysis("BTC-USD","5m")
    if sig: await update.message.reply_text(format_analysis(sig,"BTCUSD","5M"),parse_mode="Markdown")
async def eth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sig=get_analysis("ETH-USD","5m")
    if sig: await update.message.reply_text(format_analysis(sig,"ETHUSD","5M"),parse_mode="Markdown")
async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID: return
    for name,yf_sym in PAIRS.items():
        sig=get_analysis(yf_sym,"5m")
        if sig and sig['confidence']>=70:
            try: await context.bot.send_message(chat_id=CHAT_ID, text=format_analysis(sig,name,"5M AUTO"), parse_mode="Markdown")
            except: pass
def run_bot():
    if not TELEGRAM_TOKEN: return
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("gold",gold_cmd))
    app.add_handler(CommandHandler("btc",btc_cmd))
    app.add_handler(CommandHandler("eth",eth_cmd))
    app.job_queue.run_repeating(auto_check,interval=300,first=15)
    print("Bot running - Always Analysis")
    app.run_polling()
if __name__ == "__main__":
    threading.Thread(target=run_bot,daemon=True).start()
    port=int(os.environ.get("PORT",10000))
    app_flask.run(host="0.0.0.0",port=port)
