import os
import requests
import json
from datetime import datetime, timezone


STATE_TABLES = {
    "aegis_market_state",
    "aegis_orderflow_state",
    "aegis_macro_briefing",
}

class SupabaseEngine:
    def __init__(self, service_role: bool = False):
        # Demo credentials explicitly loaded
        raw_url = os.getenv("SUPABASE_URL", "https://dsoxzpbataleytsamzqi.supabase.co/rest/v1/")
        self.url = raw_url.rstrip('/')  # Strip trailing slash to prevent double slashes in API endpoints
        self.service_role = service_role
        if service_role:
            # Only the headless daemon should use this key. Streamlit reads with
            # SUPABASE_KEY and must never receive the service-role credential.
            self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        else:
            self.key = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJIUzI1NiIsInJlZiI6ImRzb3h6cGJhdGFsZXl0c2FtenFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTA4NDcxMzYsImV4cCI6MjEwNjQyMzEzNn0.iJVPJFcrPrtga6y6i2VnjiS8qwDNETGO456bOMuG7Mw")
        
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

    def save_state(self, table: str, state_key: str, payload: dict) -> bool:
        """Upsert one current-state JSON payload into an approved state table.

        State tables use the shared columns `state_key` (unique text), `payload`
        (json/jsonb), and `updated_at` (timestamptz). This does not alter any
        table or trade-memory schema; a missing/mismatched table is reported and
        the daemon continues with its in-memory state.
        """
        if table not in STATE_TABLES:
            raise ValueError(f"Unsupported Aegis state table: {table}")
        if not self.is_configured():
            return False
        row = {
            "state_key": str(state_key),
            "payload": payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        headers = dict(self.headers)
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        try:
            response = requests.post(
                f"{self.url}/{table}?on_conflict=state_key",
                headers=headers,
                json=row,
                timeout=(3, 8),
            )
            if response.status_code not in (200, 201, 204):
                print(f"Supabase {table} upsert failed ({response.status_code}): {response.text[:240]}")
                return False
            return True
        except Exception as exc:
            print(f"Supabase {table} upsert error: {exc}")
            return False

    def load_states(self, table: str, limit: int = 100) -> list[dict]:
        """Load the newest persisted state rows, returning [] on DB outages."""
        if table not in STATE_TABLES:
            raise ValueError(f"Unsupported Aegis state table: {table}")
        if not self.is_configured():
            return []
        try:
            response = requests.get(
                f"{self.url}/{table}",
                params={
                    "select": "state_key,payload,updated_at",
                    "order": "updated_at.desc",
                    "limit": max(1, min(int(limit), 1000)),
                },
                headers=self.headers,
                timeout=(3, 8),
            )
            if response.status_code != 200:
                print(f"Supabase {table} read failed ({response.status_code}): {response.text[:240]}")
                return []
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as exc:
            print(f"Supabase {table} read error: {exc}")
            return []
