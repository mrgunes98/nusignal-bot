"""
Numan Sinyal Botu
TwelveData'dan veri çeker, MACD+EMA200+RSI mantığıyla sinyal üretir, Telegram'a gönderir.
"""

import requests
import time
import os
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ─── AYARLAR ───
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY", "07b603fcf22448b79325b844641c6a76")
TELEGRAM_BOT_TOKEN = "8886558665:AAEBUpBtax_rm4WqvjFDltTQ1gnMHYSwhDI"
TELEGRAM_CHAT_ID = "7492355509"

# İzlenecek pariteler ve zaman dilimleri
SYMBOLS = ["XAU/USD", "XAG/USD", "EUR/USD", "GBP/USD", "USD/JPY"]
TIMEFRAMES = ["5min", "15min", "30min", "1h"]

# Strateji parametreleri
EMA_TREND = 200
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_LEN = 14
ATR_SL_MULT = 1.5
ATR_TP_MULT = 2.0

# Aynı sinyal tekrar gönderilmesin diye hafıza
last_signals = {}

# ─── TELEGRAM MESAJ GÖNDER ───
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram hatasi: {e}")

# ─── VERİ ÇEK ───
def get_candles(symbol, interval, outputsize=250):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if "values" not in data:
            print(f"Veri hatasi {symbol} {interval}: {data}")
            return None
        candles = data["values"]
        candles.reverse()  # eskiden yeniye sırala
        closes = [float(c["close"]) for c in candles]
        highs  = [float(c["high"])  for c in candles]
        lows   = [float(c["low"])   for c in candles]
        return {"close": closes, "high": highs, "low": lows}
    except Exception as e:
        print(f"Cekme hatasi {symbol} {interval}: {e}")
        return None

# ─── GÖSTERGE HESAPLAMALARI ───
def ema(values, period):
    k = 2 / (period + 1)
    ema_vals = [values[0]]
    for price in values[1:]:
        ema_vals.append(price * k + ema_vals[-1] * (1 - k))
    return ema_vals

def rsi(values, period=14):
    if len(values) < period + 1:
        return [50] * len(values)
    deltas = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsis = [50] * (period + 1)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 999
        rsis.append(100 - (100 / (1 + rs)))
    return rsis

def macd(values, fast=12, slow=26, signal=9):
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line

def atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    if len(trs) < period:
        return [0] * len(closes)
    atr_vals = [sum(trs[:period]) / period]
    for tr in trs[period:]:
        atr_vals.append((atr_vals[-1] * (period - 1) + tr) / period)
    # uzunluk eşitle
    pad = [atr_vals[0]] * (len(closes) - len(atr_vals))
    return pad + atr_vals

# ─── SİNYAL KONTROLÜ ───
def check_signal(symbol, interval):
    data = get_candles(symbol, interval)
    if data is None or len(data["close"]) < EMA_TREND + 10:
        return

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]

    ema_trend = ema(closes, EMA_TREND)
    macd_line, signal_line = macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    rsi_vals = rsi(closes, RSI_LEN)
    atr_vals = atr(highs, lows, closes, 14)

    # son iki mum (kesişim kontrolü için)
    i = len(closes) - 1
    price = closes[i]

    trend_up = price > ema_trend[i]
    trend_down = price < ema_trend[i]

    macd_cross_up = macd_line[i-1] <= signal_line[i-1] and macd_line[i] > signal_line[i]
    macd_cross_down = macd_line[i-1] >= signal_line[i-1] and macd_line[i] < signal_line[i]

    rsi_ok_long = 40 < rsi_vals[i] < 72
    rsi_ok_short = 28 < rsi_vals[i] < 60

    long_signal = macd_cross_up and trend_up and rsi_ok_long
    short_signal = macd_cross_down and trend_down and rsi_ok_short

    key = f"{symbol}_{interval}"

    if long_signal or short_signal:
        # aynı sinyali tekrar gönderme (son 1 mum içinde)
        if last_signals.get(key) == i:
            return
        last_signals[key] = i

        direction = "LONG 📈" if long_signal else "SHORT 📉"
        sl = price - atr_vals[i] * ATR_SL_MULT if long_signal else price + atr_vals[i] * ATR_SL_MULT
        tp = price + atr_vals[i] * ATR_TP_MULT if long_signal else price - atr_vals[i] * ATR_TP_MULT

        message = (
            f"🔔 <b>{direction}</b>\n\n"
            f"<b>Parite:</b> {symbol}\n"
            f"<b>Zaman Dilimi:</b> {interval}\n"
            f"<b>Giriş:</b> {price:.4f}\n"
            f"<b>SL:</b> {sl:.4f}\n"
            f"<b>TP:</b> {tp:.4f}\n"
            f"<b>RSI:</b> {rsi_vals[i]:.1f}\n"
            f"<b>Saat:</b> {datetime.now().strftime('%H:%M:%S')}"
        )
        send_telegram(message)
        print(f"Sinyal gonderildi: {symbol} {interval} {direction}")

# ─── ANA DÖNGÜ ───
def main():
    send_telegram("✅ Numan Sinyal Botu başlatıldı ve çalışıyor!")
    print("Bot calismaya basladi...")

    while True:
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                try:
                    check_signal(symbol, tf)
                    time.sleep(8)  # API rate limit (8 istek/dakika) için güvenli bekleme
                except Exception as e:
                    print(f"Hata {symbol} {tf}: {e}")

        print(f"Tur tamamlandi: {datetime.now().strftime('%H:%M:%S')} - 5 dakika bekleniyor...")
        time.sleep(300)  # 5 dakikada bir tüm paritelerin taranması

# ─── RENDER İÇİN SAHTE WEB SUNUCUSU (botu uyanık tutmak için) ───
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Numan Sinyal Botu calisiyor!")
    def log_message(self, format, *args):
        pass  # log spamini engelle

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

if __name__ == "__main__":
    # Web sunucusunu ayrı thread'de başlat (Render'ı mutlu etmek için)
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # Asıl botu çalıştır
    main()
