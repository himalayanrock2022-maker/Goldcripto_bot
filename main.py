
import os
import yfinance as yf
import pandas as pd
import ta
from datetime import datetime
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

PAIRS = {
    "XAUUSD GOLD": "GC=F",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD"
}

def get_signal(yf_symbol, timeframe="5m"):
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

        signal = None
        confidence = 0
        reasons = []

        if ema20 > ema50 and prev['EMA20'] <= prev['EMA50']:
            signal = "BUY"
            confidence += 35
            reasons.append("EMA20 > EMA50 bullish cross")
        if rsi < 42 and rsi > prev['RSI']:
            signal = signal or "BUY"
            confidence += 25
            reasons.append(f"RSI bounce {rsi:.1f}")
        
        if ema20 < ema50 and prev['EMA20'] >= prev['EMA50']:
            signal = "SELL"
            confidence += 35
            reasons.append("EMA20 < EMA50 bearish cross")
        if rsi > 58 and rsi < prev['RSI']:
            signal = signal or "SELL"
            confidence += 25
            reasons.append(f"RSI reversal {rsi:.1f}")

        if not signal or confidence < 40:
            return None

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
        else:
            sl = price + sl_dist
            tp1 = price - tp1_dist
            tp2 = price - tp2_dist

        rr1 = abs(tp1 - price) / abs(price - sl) if abs(price - sl) else 0
        
        return {
            "price": price, "signal": signal, "confidence": min(confidence+20, 88),
            "sl": sl, "tp1": tp1, "tp2": tp2, "rr1": rr1, "rsi": rsi, "atr": atr,
            "reasons": reasons
        }
    except Exception as e:
        print(f"Error: {e}")
        return None

def format_msg(sig, pair_name, tf):
    emoji = "🟢" if sig['signal'] == "BUY" else "🔴"
    return f"{emoji} *{sig['signal']} {pair_name} | {tf} | {sig['confidence']}%*\n\n💰 Entry: `{sig['price']:.2f}`\n🛑 SL: `{sig['sl']:.2f}`\n🎯 TP1: `{sig['tp1']:.2f}` (1:{sig['rr1']:.1f})\n🎯 TP2: `{sig['tp2']:.2f}`\n\n📊 {', '.join(sig['reasons'])}\nRSI {sig['rsi']:.1f} | ATR {sig['atr']:.2f}\n⏰ {datetime.now().strftime('%H:%M PKT')}\n⚠️ Risk 1% | Exness MT5"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gold & Crypto Bot Live!\n/gold - Gold\n/btc - BTC\n/eth - ETH\nAuto 5M ON")

async def gold_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for tf in ["5m", "15m"]:
        sig = get_signal("GC=F", tf)
        if sig:
           
