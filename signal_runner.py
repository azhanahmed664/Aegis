import os
import time
from datetime import datetime
import yfinance as yf
import pandas as pd

from perpetuals_engine import PerpetualsEngine
from xau_strategy_engine import XAUStrategyEngine
from ml_memory_engine import LancasterMLEngine
from telegram_engine import TelegramBroadcaster
from outcome_tracker import TradeOutcomeTracker
from htf_engine import HTFConfluenceEngine

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8985731081:AAEd5EYlLq7y-wsrtCE7r_ZZ2-5Vs-_2oI8")
TELEGRAM_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID", "8037730810"))
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.55"))

# Assets to continuously scan
CRYPTO_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "ADA/USDT:USDT"]
CRYPTO_EXCHANGE = "binance"  # or 'mexc'

def fetch_live_xau_5m(limit=200) -> pd.DataFrame:
    ticker = yf.Ticker("GC=F")
    df = ticker.history(period="5d", interval="5m")
    if df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    time_col = 'Datetime' if 'Datetime' in df.columns else 'Date'
    df.rename(columns={time_col: 'Timestamp', 'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'}, inplace=True)
    df['Timestamp'] = pd.to_datetime(df['Timestamp']).dt.tz_localize(None)
    return df.tail(limit)

def run_aegis_signal_loop():
    print("🛡️ AEGIS MULTI-ASSET ENGINE ONLINE | XAU + CRYPTO PERPETUALS | 2-WAY TELEGRAM")
    
    broadcaster = TelegramBroadcaster(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    ml_engine = LancasterMLEngine()
    ml_engine.train_purged_walk_forward()
    tracker = TradeOutcomeTracker()
    htf_engine = HTFConfluenceEngine()
    perp_engine = PerpetualsEngine()

    def get_status_summary():
        active = tracker.load_active_trades()
        htf = htf_engine.fetch_htf_bias()
        return (
            f"● Open Positions: {len(active)}\n"
            f"● Gold HTF Bias: {htf.get('bias')}\n"
            f"● Active Markets: XAU/USD, {', '.join([s.split('/')[0] for s in CRYPTO_SYMBOLS])}"
        )

    def trigger_scan():
        report = []
        # Gold scan
        df_gold = fetch_live_xau_5m(100)
        if not df_gold.empty:
            sigs = XAUStrategyEngine(df_gold).scan_all_strategies()
            report.append(f"XAU/USD: {len(sigs)} setups")
        # Crypto scan
        for sym in CRYPTO_SYMBOLS:
            df_c = perp_engine.fetch_futures_data(CRYPTO_EXCHANGE, sym, timeframe="5m", limit=100)
            if not df_c.empty:
                sigs_c = XAUStrategyEngine(df_c).scan_all_strategies()
                report.append(f"{sym.split(':')[0]}: {len(sigs_c)} setups")
        return "\n".join(report)

    broadcaster.start_command_listener(status_callback=get_status_summary, scan_callback=trigger_scan)

    last_bars = {}

    while True:
        try:
            # -------------------------------------------------------------
            # 1. EVALUATE GOLD (XAU/USD)
            # -------------------------------------------------------------
            df_gold = fetch_live_xau_5m(150)
            if not df_gold.empty:
                latest_gold = df_gold.iloc[-1]
                bar_time_gold = latest_gold['Timestamp']
                
                tracker.evaluate_open_trades(latest_gold['High'], latest_gold['Low'], broadcaster=broadcaster)

                if last_bars.get("XAU") != bar_time_gold:
                    last_bars["XAU"] = bar_time_gold
                    htf = htf_engine.fetch_htf_bias()
                    macro_bias = htf.get('bias', 'NEUTRAL')

                    strat_engine = XAUStrategyEngine(df_gold)
                    signals = strat_engine.scan_all_strategies(idx=len(df_gold) - 1)

                    for sig in signals:
                        if "BULLISH" in macro_bias and sig['action'] == "SHORT":
                            continue
                        if "BEARISH" in macro_bias and sig['action'] == "LONG":
                            continue

                        features = ml_engine.extract_lancaster_features(strat_engine.df, len(df_gold) - 1)
                        win_prob = ml_engine.predict_win_probability(features)

                        if win_prob >= ML_CONFIDENCE_THRESHOLD:
                            tracker.register_trade("XAU/USD", sig['strategy'], sig['action'], sig['entry'], sig['sl'], sig['tp'], features)
                            msg = broadcaster.format_signal(
                                "XAU/USD (Gold)", sig['strategy'], sig['entry'], sig['sl'], sig['tp'],
                                sig['confluence'] + [f"HTF Confluence: {macro_bias}", f"ML Confidence: {win_prob*100:.0f}%"]
                            )
                            broadcaster.send_alert(msg)

            # -------------------------------------------------------------
            # 2. EVALUATE CRYPTO PERPETUALS (BINANCE / MEXC)
            # -------------------------------------------------------------
            for symbol in CRYPTO_SYMBOLS:
                df_crypto = perp_engine.fetch_futures_data(CRYPTO_EXCHANGE, symbol, timeframe="5m", limit=120)
                if df_crypto.empty:
                    continue

                latest_c = df_crypto.iloc[-1]
                bar_time_c = latest_c['Timestamp']

                if last_bars.get(symbol) != bar_time_c:
                    last_bars[symbol] = bar_time_c
                    strat_crypto = XAUStrategyEngine(df_crypto)
                    c_signals = strat_crypto.scan_all_strategies(idx=len(df_crypto) - 1)

                    for sig in c_signals:
                        features = ml_engine.extract_lancaster_features(strat_crypto.df, len(df_crypto) - 1)
                        win_prob = ml_engine.predict_win_probability(features)

                        if win_prob >= ML_CONFIDENCE_THRESHOLD:
                            clean_name = symbol.split(':')[0]
                            tracker.register_trade(clean_name, sig['strategy'], sig['action'], sig['entry'], sig['sl'], sig['tp'], features)
                            msg = broadcaster.format_signal(
                                f"{clean_name} Perp", sig['strategy'], sig['entry'], sig['sl'], sig['tp'],
                                sig['confluence'] + [f"ML Confidence: {win_prob*100:.0f}%"]
                            )
                            broadcaster.send_alert(msg)
                            print(f"✅ Crypto Alert Sent: {clean_name} {sig['action']}")

            time.sleep(60)

        except Exception as e:
            print(f"❌ Runner Loop Error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    run_aegis_signal_loop()