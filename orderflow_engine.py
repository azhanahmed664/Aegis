"""Binance USD-M depth snapshots and visible-liquidity anomaly scoring."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import ccxt
import numpy as np


class OrderFlowEngine:
    """Read Binance linear-perpetual order books and return JSON-safe metrics.

    Gold is proxied by the Binance PAXG/USDT perpetual book. A large visible
    order is described as a depth anomaly, not asserted to be spoofing; intent
    cannot be inferred from one static snapshot.
    """

    def __init__(self, exchange_id: str = "binance"):
        if str(exchange_id).lower() != "binance":
            raise ValueError("Aegis order flow is pinned to Binance USD-M")
        self.client = ccxt.binanceusdm({
            "enableRateLimit": True,
            "timeout": 20000,
        })
        # Binance's liquid PAXG/USDT spot book is the commodity proxy; it is
        # kept on Binance and avoids assuming a nonexistent PAXG perpetual.
        self.gold_client = ccxt.binance({
            "enableRateLimit": True,
            "timeout": 20000,
        })

    @staticmethod
    def _levels(rows: list[Any]) -> list[dict[str, float]]:
        levels = []
        for row in rows or []:
            try:
                price, amount = float(row[0]), float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if np.isfinite(price) and np.isfinite(amount) and price > 0 and amount > 0:
                levels.append({"price": price, "amount": amount, "notional": price * amount})
        return levels

    @staticmethod
    def _anomalies(levels: list[dict[str, float]], side: str) -> list[dict[str, Any]]:
        if len(levels) < 2:
            return []
        volumes = np.asarray([row["amount"] for row in levels], dtype=float)
        sigma = float(np.std(volumes, ddof=1))
        if not np.isfinite(sigma) or sigma <= 0:
            return []
        threshold = float(np.mean(volumes) + 4.5 * sigma)
        anomalies = [
            {
                "price": row["price"],
                "amount": row["amount"],
                "notional": row["notional"],
                "z_score": (row["amount"] - float(np.mean(volumes))) / sigma,
                "side": side,
            }
            for row in levels if row["amount"] > threshold
        ]
        return sorted(anomalies, key=lambda row: row["notional"], reverse=True)[:10]

    def scan_l2_book(self, symbol: str, limit: int = 500) -> dict[str, Any]:
        """Fetch one depth snapshot. All returned fields are JSON-serializable."""
        if not isinstance(symbol, str) or not symbol.strip():
            return {"error": "A nonempty market symbol is required"}
        try:
            safe_limit = max(5, min(int(limit), 1000))
        except (TypeError, ValueError):
            return {"error": "Order book limit must be an integer"}
        is_gold = "XAU" in symbol.upper() or "GOLD" in symbol.upper()
        target = "PAXG/USDT" if is_gold else symbol.strip().upper()
        if not is_gold and ":" not in target:
            target = f"{target}:{target.split('/')[-1]}"
        try:
            client = self.gold_client if is_gold else self.client
            client.load_markets()
            market = client.market(target)
            if not is_gold and (not market.get("swap") or not market.get("linear")):
                return {"error": f"{target} is not a Binance USD-M perpetual market"}
            book = client.fetch_order_book(target, limit=safe_limit)
            bids, asks = self._levels(book.get("bids", [])), self._levels(book.get("asks", []))
            if not bids or not asks:
                return {"error": f"Order book empty for {target}"}
            bid_total = sum(row["notional"] for row in bids)
            ask_total = sum(row["notional"] for row in asks)
            total = bid_total + ask_total
            if not np.isfinite(total) or total <= 0:
                return {"error": "Visible order book has no finite notional depth"}
            bid_pct = 100.0 * bid_total / total
            ask_pct = 100.0 * ask_total / total
            delta = bid_pct - ask_pct
            walls = self._anomalies(bids, "BID") + self._anomalies(asks, "ASK")
            magnet = max(walls, key=lambda row: row["notional"]) if walls else None
            if delta >= 20:
                risk = "BID_HEAVY / SHORT_SQUEEZE_RISK"
            elif delta <= -20:
                risk = "ASK_HEAVY / LONG_TRAP_RISK"
            else:
                risk = "BALANCED"
            return {
                "symbol": symbol,
                "book_symbol": target,
                "source": "Binance USD-M" + (" · PAXG depth proxy for Gold" if is_gold else ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "bid_pressure_pct": round(bid_pct, 4),
                "ask_pressure_pct": round(ask_pct, 4),
                "volume_delta_pct": round(delta, 4),
                "bid_notional": round(bid_total, 4),
                "ask_notional": round(ask_total, 4),
                "trap_squeeze_risk": risk,
                "liquidity_magnet": magnet,
                "spoof_walls_bids": self._anomalies(bids, "BID"),
                "spoof_walls_asks": self._anomalies(asks, "ASK"),
                "top_bids": bids[:25],
                "top_asks": asks[:25],
            }
        except Exception as exc:
            return {"symbol": symbol, "error": f"Binance order book unavailable: {exc}"}


if __name__ == "__main__":
    import json
    print(json.dumps(OrderFlowEngine("binance").scan_l2_book("BTC/USDT:USDT"), indent=2))
