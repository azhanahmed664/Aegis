import os
import requests
import json

class SupabaseEngine:
    def __init__(self):
        # Demo credentials explicitly loaded
        raw_url = os.getenv("SUPABASE_URL", "https://dsoxzpbataleytsamzqi.supabase.co/rest/v1/")
        self.url = raw_url.rstrip('/')  # Strip trailing slash to prevent double slashes in API endpoints
        self.key = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRzb3h6cGJhdGFsZXl0c2FtenFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTA4NDcxMzYsImV4cCI6MjEwNjQyMzEzNn0.iJVPJFcrPrtga6y6i2VnjiS8qwDNETGO456bOMuG7Mw")
        
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    def is_configured(self) -> bool:
        # Validate that a real key is present rather than a placeholder string
        return bool(self.key and len(self.key) > 50)

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
            # Broadcast the active position queue to the cloud
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
            # Delete resolved trades from the active queue monitor
            requests.delete(f"{self.url}/aegis_active_trades?id=eq.{trade_id}", headers=self.headers, timeout=5)
        except Exception as e:
            print(f"Supabase Trade Close Error: {e}")