import os
import json
from datetime import datetime
from ml_memory_engine import LancasterMLEngine
from telegram_engine import TelegramBroadcaster
from supabase_engine import SupabaseEngine

class TradeOutcomeTracker:
    def __init__(self, active_trades_file="aegis_active_trades.json", memory_file="aegis_trade_memory.csv"):
        self.active_trades_file = active_trades_file
        self.memory_file = memory_file
        self.ml_engine = LancasterMLEngine(memory_file=self.memory_file)
        self.supabase = SupabaseEngine()
        self._init_files()

    def _init_files(self):
        if not os.path.exists(self.active_trades_file):
            with open(self.active_trades_file, "w") as f:
                json.dump([], f)

    def load_active_trades(self) -> list:
        cloud = self.supabase.load_active_trades()
        if cloud:
            return cloud
        try:
            with open(self.active_trades_file, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def save_active_trades(self, trades: list):
        with open(self.active_trades_file, "w") as f:
            json.dump(trades, f, indent=4)
        self.supabase.save_active_trades(trades)

    def register_trade(self, asset: str, strategy: str, action: str, entry: float, sl: float, tp: float, features: dict):
        trades = self.load_active_trades()
        trade_id = f"T_{int(datetime.utcnow().timestamp())}"
        record = {
            "id": trade_id,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "asset": asset,
            "strategy": strategy,
            "action": action,
            "entry": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "features": features,
            "status": "OPEN"
        }
        trades.append(record)
        self.save_active_trades(trades)
        print(f"📝 Trade {trade_id} registered into active monitoring.")

    def evaluate_open_trades(self, current_high: float, current_low: float, broadcaster: TelegramBroadcaster = None):
        trades = self.load_active_trades()
        if not trades:
            return

        remaining_trades = []
        retrain_needed = False

        for trade in trades:
            action, tp, sl = trade["action"], trade["tp"], trade["sl"]
            trade_id = trade["id"]
            outcome = None

            if action == "LONG":
                if current_high >= tp:
                    outcome = 1
                    status_text = "🎯 TAKE PROFIT REACHED (+WIN)"
                elif current_low <= sl:
                    outcome = 0
                    status_text = "🛑 STOP LOSS TRIGGERED (-LOSS)"
            elif action == "SHORT":
                if current_low <= tp:
                    outcome = 1
                    status_text = "🎯 TAKE PROFIT REACHED (+WIN)"
                elif current_high >= sl:
                    outcome = 0
                    status_text = "🛑 STOP LOSS TRIGGERED (-LOSS)"

            if outcome is not None:
                retrain_needed = True
                self.supabase.close_active_trade(trade_id)

                row = {
                    "timestamp": trade["timestamp"],
                    "strategy": trade["strategy"],
                    **trade["features"],
                    "risk_reward": round(abs(tp - trade["entry"]) / (abs(trade["entry"] - sl) + 1e-9), 2),
                    "win_label": int(outcome)
                }
                self.ml_engine.log_trade(row)

                if broadcaster:
                    msg = (
                        f"🛡️ **AEGIS TRADE RESOLUTION**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"**Asset:** {trade['asset']}\n"
                        f"**Strategy:** {trade['strategy']}\n"
                        f"**Result:** {status_text}\n"
                        f"**Entry:** {trade['entry']:,.2f} | **Target:** {tp:,.2f} | **Exit SL:** {sl:,.2f}\n"
                        f"🧠 Vector integrated into Supabase & Purged ML Memory."
                    )
                    broadcaster.send_alert(msg)
            else:
                remaining_trades.append(trade)

        self.save_active_trades(remaining_trades)

        if retrain_needed:
            print("🔄 Running Purged Walk-Forward Retraining...")
            self.ml_engine.train_purged_walk_forward()