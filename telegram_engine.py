"""Telegram alerts and non-blocking two-way command listener for Aegis."""
import os
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import requests


class TelegramBroadcaster:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = (bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = str(chat_id or os.getenv("TELEGRAM_CHAT_ID", "")).strip()
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""
        self.last_update_id = 0
        self.polling = False
        self._state_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._listener_thread = None
        self._stop_event = threading.Event()
        self._scan_lock = threading.Lock()

    def format_signal(self, asset: str, strategy: str, entry: float, sl: float,
                      tp: float, confluences: list) -> str:
        direction = "🟢 LONG" if tp > entry else "🔴 SHORT"
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0
        confluence_text = "\n".join(f"   • {item}" for item in (confluences or []))
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            "🛡️ **AEGIS AUTONOMOUS SIGNAL**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Asset:** {asset}\n**Action:** {direction}\n"
            f"**Strategy:** {strategy}\n\n"
            f"🎯 **Entry:** {entry:,.8g}\n🛑 **Stop Loss:** {sl:,.8g}\n"
            f"🏁 **Take Profit:** {tp:,.8g} (R:R 1:{rr_ratio:.2f})\n\n"
            f"⚙️ **Confluences:**\n{confluence_text}\n\n⏱️ {timestamp}"
        )

    def send_alert(self, message: str) -> bool:
        """Send a Markdown alert; retry as plain text if Telegram rejects formatting."""
        if not self.base_url or not self.chat_id:
            print("Telegram alert skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is unset.")
            return False
        url = f"{self.base_url}/sendMessage"
        with self._send_lock:
            try:
                response = requests.post(
                    url,
                    json={"chat_id": self.chat_id, "text": str(message), "parse_mode": "Markdown"},
                    timeout=8,
                )
                if response.status_code == 400:
                    response = requests.post(
                        url, json={"chat_id": self.chat_id, "text": str(message)}, timeout=8
                    )
                response.raise_for_status()
                body = response.json()
                if not body.get("ok", False):
                    print(f"Telegram send rejected: {body.get('description', 'unknown API error')}")
                    return False
                return True
            except (requests.RequestException, ValueError) as exc:
                print(f"Telegram send error: {exc}")
                return False

    def start_command_listener(self, status_callback: Optional[Callable] = None,
                               scan_callback: Optional[Callable] = None,
                               trades_callback: Optional[Callable] = None) -> bool:
        """Start exactly one daemon polling thread; commands run off that thread."""
        if not self.base_url or not self.chat_id:
            print("Telegram command listener disabled: credentials are not configured.")
            return False
        with self._state_lock:
            if self._listener_thread and self._listener_thread.is_alive():
                return True
            self._stop_event.clear()
            self.polling = True
            self._listener_thread = threading.Thread(
                target=self._poll_updates,
                args=(status_callback, scan_callback, trades_callback),
                name="aegis-telegram-listener",
                daemon=True,
            )
            self._listener_thread.start()
        print("Telegram 2-way command listener active (/status, /scan, /trades).")
        return True

    def stop_command_listener(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        self.polling = False
        thread = self._listener_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def _poll_updates(self, status_callback, scan_callback, trades_callback=None):
        # getUpdates cannot be used while a webhook is active. Clear any old
        # webhook before the first poll, dropping stale queued commands.
        try:
            webhook_response = requests.post(
                f"{self.base_url}/deleteWebhook",
                json={"drop_pending_updates": True},
                timeout=5,
            )
            webhook_response.raise_for_status()
            webhook_payload = webhook_response.json()
            if not webhook_payload.get("ok", False):
                print(
                    "Telegram deleteWebhook rejected: "
                    f"{webhook_payload.get('description', 'unknown API error')}"
                )
        except (requests.RequestException, ValueError, TypeError) as exc:
            # Polling may still work if there was no webhook; keep the listener
            # alive and make the failure visible for operators.
            print(f"Telegram deleteWebhook error: {exc}")

        conflict_backoff = 10
        while not self._stop_event.is_set():
            try:
                with self._state_lock:
                    offset = self.last_update_id + 1
                response = requests.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": offset, "timeout": 10},
                    timeout=12,
                )
                response.raise_for_status()
                conflict_backoff = 10
                payload = response.json()
                if payload.get("ok"):
                    for update in payload.get("result", []):
                        update_id = int(update.get("update_id", 0))
                        with self._state_lock:
                            self.last_update_id = max(self.last_update_id, update_id)
                        message = update.get("message") or update.get("edited_message") or {}
                        sender_id = str((message.get("chat") or {}).get("id", ""))
                        command_text = str(message.get("text", "")).strip()
                        if sender_id == self.chat_id and command_text.startswith("/"):
                            self._handle_command(
                                command_text, status_callback, scan_callback, trades_callback
                            )
            except requests.RequestException as exc:
                if getattr(getattr(exc, "response", None), "status_code", None) == 409:
                    print(
                        "Telegram getUpdates conflict (409); "
                        f"retrying in {conflict_backoff} seconds."
                    )
                    self._stop_event.wait(conflict_backoff)
                    conflict_backoff = min(conflict_backoff * 2, 120)
                    continue
                print(f"Telegram listener polling error: {exc}")
                self._stop_event.wait(3)
            except (ValueError, TypeError) as exc:
                print(f"Telegram listener polling error: {exc}")
                self._stop_event.wait(3)
            self._stop_event.wait(0.5)
        self.polling = False

    def _callback_worker(self, label: str, callback: Optional[Callable], report_title: str,
                         exclusive: bool = False):
        if callback is None:
            self.send_alert(f"{report_title}\nCallback is not configured.")
            return
        if exclusive and not self._scan_lock.acquire(blocking=False):
            self.send_alert("A scan is already running. Please wait for its report.")
            return
        try:
            result = callback()
            body = str(result).strip() if result is not None else "Completed. No report returned."
            self.send_alert(f"{report_title}\n{body or 'Completed. No results.'}")
        except Exception as exc:
            self.send_alert(f"{report_title}\nCommand failed: {exc}")
        finally:
            if exclusive:
                self._scan_lock.release()

    def _handle_command(self, cmd: str, status_cb, scan_cb, trades_cb=None):
        command = cmd.split(maxsplit=1)[0].split("@", 1)[0].lower()
        if command == "/status":
            threading.Thread(
                target=self._callback_worker,
                args=("status", status_cb, "🛡️ **AEGIS CORE TELEMETRY**"),
                daemon=True,
            ).start()
        elif command == "/scan":
            self.send_alert("🔍 Initiating multi-timeframe scan across Gold and perpetuals...")
            threading.Thread(
                target=self._callback_worker,
                args=("scan", scan_cb, "📡 **SCAN REPORT**"),
                kwargs={"exclusive": True},
                name="aegis-telegram-scan",
                daemon=True,
            ).start()
        elif command == "/trades":
            threading.Thread(
                target=self._callback_worker,
                args=("trades", trades_cb, "📚 **RECENT TRADE OUTCOMES**"),
                daemon=True,
            ).start()
        elif command == "/help":
            self.send_alert(
                "Commands:\n/status - System health and open trades\n"
                "/scan - Run an immediate MTF scan\n/trades - Review recent outcomes"
            )
        else:
            self.send_alert("Unknown command. Type /help for available commands.")
