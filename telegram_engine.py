import requests
import threading
import time
from datetime import datetime

class TelegramBroadcaster:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id = 0
        self.polling = False

    def format_signal(self, asset: str, strategy: str, entry: float, sl: float, tp: float, confluences: list) -> str:
        direction = "🟢 LONG" if tp > entry else "🔴 SHORT"
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0
        confluence_text = "\n".join([f"   • {c}" for c in confluences])

        return (
            f"🛡️ **AEGIS AUTONOMOUS SIGNAL**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Asset:** {asset}\n"
            f"**Action:** {direction}\n"
            f"**Strategy:** {strategy}\n\n"
            f"🎯 **Entry:** {entry:,.2f}\n"
            f"🛑 **Stop Loss:** {sl:,.2f}\n"
            f"🏁 **Take Profit:** {tp:,.2f} (R:R 1:{rr_ratio})\n\n"
            f"⚙️ **Confluences:**\n"
            f"{confluence_text}\n\n"
            f"⏱️ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

    def send_alert(self, message: str):
        try:
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=8)
        except Exception as e:
            print(f"❌ Telegram Send Error: {e}")

    def start_command_listener(self, status_callback=None, scan_callback=None):
        """Starts a background thread to listen for incoming Telegram commands."""
        self.polling = True
        thread = threading.Thread(target=self._poll_updates, args=(status_callback, scan_callback), daemon=True)
        thread.start()
        print("🤖 Telegram 2-Way Command Listener Active (/status, /scan, /trades).")

    def _poll_updates(self, status_callback, scan_callback):
        while self.polling:
            try:
                url = f"{self.base_url}/getUpdates?offset={self.last_update_id + 1}&timeout=10"
                res = requests.get(url, timeout=12).json()
                if res.get("ok"):
                    for item in res.get("result", []):
                        self.last_update_id = item["update_id"]
                        msg = item.get("message", {})
                        sender_id = str(msg.get("chat", {}).get("id"))
                        text = msg.get("text", "").strip()

                        if sender_id == self.chat_id and text.startswith("/"):
                            self._handle_command(text, status_callback, scan_callback)
            except Exception:
                time.sleep(3)
            time.sleep(1)

    def _handle_command(self, cmd: str, status_cb, scan_cb):
        if cmd == "/status":
            info = status_cb() if status_cb else "System active. Runner polling."
            self.send_alert(f"🛡️ **AEGIS CORE TELEMETRY**\n━━━━━━━━━━━━━━━━━━━━━━\n{info}")
        elif cmd == "/scan":
            self.send_alert("🔍 Initiating multi-timeframe scan across XAU & Perpetuals...")
            scan_result = scan_cb() if scan_cb else "Scan finished. No setups."
            self.send_alert(f"📡 **SCAN REPORT**\n{scan_result}")
        elif cmd == "/help":
            self.send_alert("Commands:\n/status - System health & open trades\n/scan - Run instant setup detection\n/trades - Review last logged outcomes")
        else:
            self.send_alert("Unknown command. Type /help for options.")