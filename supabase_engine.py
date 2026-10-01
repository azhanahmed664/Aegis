import requests
import json

class SupabaseEngine:
    def __init__(self):
        # Read from environment or fallback
        self.url = "https://YOUR_SUPABASE_PROJECT_REF.supabase.co/rest/v1"
        self.key = "YOUR_SUPABASE_ANON_KEY"
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    def is_configured(self) -> bool:
        return "YOUR_SUPABASE" not in self.url

    def insert_trade_memory(self, record: dict):
        if not self.is_configured(): return
        try:
            requests.post(f"{self.url}/aegis_trade_memory", headers=self.headers, json=record, timeout=5)
        except Exception as e:
            print(f"Supabase Memory Insert Error: {e}")

    def fetch_trade_memory(self) -> list:
        if not self.is_configured(): return []
        try:
            res = requests.get(f"{self.url}/aegis_trade_memory?select=*&order=id.desc&limit=500", headers=self.headers, timeout=5)
            return res.json() if res.status_code == 200 else []
        except Exception:
            return []

    def save_active_trades(self, trades: list):
        if not self.is_configured(): return
        try:
            # Upsert active trades
            for t in trades:
                requests.post(f"{self.url}/aegis_active_trades", headers=self.headers, json=t, timeout=5)
        except Exception as e:
            print(f"Supabase Active Trades Save Error: {e}")

    def load_active_trades(self) -> list:
        if not self.is_configured(): return []
        try:
            res = requests.get(f"{self.url}/aegis_active_trades?status=eq.OPEN", headers=self.headers, timeout=5)
            return res.json() if res.status_code == 200 else []
        except Exception:
            return []

    def close_active_trade(self, trade_id: str):
        if not self.is_configured(): return
        try:
            requests.delete(f"{self.url}/aegis_active_trades?id=eq.{trade_id}", headers=self.headers, timeout=5)
        except Exception as e:
            print(f"Supabase Trade Close Error: {e}")