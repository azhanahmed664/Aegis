import time
from datetime import datetime
import yfinance as yf
import pandas as pd

from xau_strategy_engine import XAUStrategyEngine
from ml_memory_engine import LancasterMLEngine
from telegram_engine import TelegramBroadcaster
from outcome_tracker import TradeOutcomeTracker
from htf_engine import HTFConfluenceEngine

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
ML_CONFIDENCE_THRESHOLD = 0.55

def fetch_live_xau_5m(limit=200) -> pd.DataFrame:
    ticker = yf.Ticker("GC=F")
    df = ticker.history(period="5d", interval="5m")
    if df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    time_col = 'Datetime' if 'Datetime' in df.columns else 'Date'
    df.rename(columns={time_col: 'Timestamp', 'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'}, inplace=True)
    return df.tail(limit)

def run_aegis_signal_loop():
    print("🛡️ AEGIS XAU PROPHET ONLINE | HTF GATED | 2-WAY TELEGRAM | PURGED ML")
    
    broadcaster = TelegramBroadcaster(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    ml_engine = LancasterMLEngine()
    ml_engine.train_purged_walk_forward()
    tracker = TradeOutcomeTracker()
    htf_engine = HTFConfluenceEngine()

    def get_status_summary():
        active = tracker.load_active_trades()
        htf = htf_engine.fetch_htf_bias()
        return f"● Open Positions: {len(active)}\n● HTF Macro Bias: {htf.get('bias')}\n● 1h Trend: {htf.get('1h_trend')} | 4h: {htf.get('4h_trend')}"

    def trigger_scan():
        df = fetch_live_xau_5m(100)
        if df.empty: return "Feed error."
        strat = XAUStrategyEngine(df)
        found = strat.scan_all_strategies()
        return f"Detected {len(found)} candidate setups on 5m."

    broadcaster.start_command_listener(status_callback=get_status_summary, scan_callback=trigger_scan)

    last_bar = None

    while True:
        try:
            df = fetch_live_xau_5m(150)
            if not df.empty:
                latest = df.iloc[-1]
                bar_time = latest['Timestamp']

                tracker.evaluate_open_trades(latest['High'], latest['Low'], broadcaster=broadcaster)

                if bar_time != last_bar:
                    last_bar = bar_time
                    htf = htf_engine.fetch_htf_bias()
                    macro_bias = htf.get('bias', 'NEUTRAL')
                    print(f"⏱️ 5m Bar Close: {bar_time} | XAU: {latest['Close']:,.2f} | HTF: {macro_bias}")

                    strategy_engine = XAUStrategyEngine(df)
                    signals = strategy_engine.scan_all_strategies(idx=len(df)-1)

                    for sig in signals:
                        # HTF Gate Check
                        if "BULLISH" in macro_bias and sig['action'] == "SHORT":
                            print(f"🛑 SHORT rejected by {macro_bias} macro trend.")
                            continue
                        if "BEARISH" in macro_bias and sig['action'] == "LONG":
                            print(f"🛑 LONG rejected by {macro_bias} macro trend.")
                            continue

                        features = ml_engine.extract_lancaster_features(strategy_engine.df, len(df)-1)
                        win_prob = ml_engine.predict_win_probability(features)

                        print(f"🎯 Setup: {sig['strategy']} ({sig['action']}) | ML Win Prob: {win_prob*100:.1f}%")

                        if win_prob >= ML_CONFIDENCE_THRESHOLD:
                            confluences = sig['confluence'] + [
                                f"HTF Confluence: {macro_bias} (1h/4h aligned)",
                                f"Lancaster ML Confidence: {win_prob*100:.0f}%"
                            ]

                            tracker.register_trade(
                                asset="XAU/USD",
                                strategy=sig['strategy'],
                                action=sig['action'],
                                entry=sig['entry'],
                                sl=sig['sl'],
                                tp=sig['tp'],
                                features=features
                            )

                            msg = broadcaster.format_signal(
                                asset="XAU/USD (Gold)",
                                strategy=sig['strategy'],
                                entry=sig['entry'],
                                sl=sig['sl'],
                                tp=sig['tp'],
                                confluences=confluences
                            )
                            broadcaster.send_alert(msg)
                            print("✅ Alert dispatched to Telegram.")
                        else:
                            print(f"⚠ Suppressed: Prob ({win_prob*100:.1f}%) < Threshold.")

            time.sleep(60)
        except Exception as e:
            print(f"❌ Signal Loop Error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    run_aegis_signal_loop()