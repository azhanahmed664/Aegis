import ccxt
import pandas as pd
import numpy as np

class OrderFlowEngine:
    def __init__(self, exchange_id: str):
        self.exchange_id = exchange_id.lower()
        if self.exchange_id == 'binance':
            self.client = ccxt.binanceusdm({'enableRateLimit': True})
        else:
            self.client = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    def scan_l2_book(self, symbol: str, limit: int = 500) -> dict:
        is_gold = "XAU" in symbol.upper() or "GOLD" in symbol.upper()
        target_symbol = "PAXG/USDT:USDT" if is_gold else (symbol if ":" in symbol else f"{symbol.upper()}:USDT")
        source_note = "PAXG/USDT (Tokenized Physical Gold L2 Depth)" if is_gold else f"{target_symbol} Direct Orderbook"

        try:
            orderbook = self.client.fetch_order_book(target_symbol, limit=limit)
            raw_bids = orderbook.get('bids', [])
            raw_asks = orderbook.get('asks', [])

            if not raw_bids or not raw_asks:
                return {"error": f"Orderbook empty for {target_symbol}"}

            bids = pd.DataFrame([[float(r[0]), float(r[1])] for r in raw_bids], columns=['Price', 'Volume'])
            asks = pd.DataFrame([[float(r[0]), float(r[1])] for r in raw_asks], columns=['Price', 'Volume'])

            total_bid_vol = bids['Volume'].sum()
            total_ask_vol = asks['Volume'].sum()
            total_vol = total_bid_vol + total_ask_vol

            if total_vol == 0:
                return {"error": "Zero volume in visible depth."}

            bid_imbalance = (total_bid_vol / total_vol) * 100
            ask_imbalance = (total_ask_vol / total_vol) * 100

            bid_mean, bid_std = bids['Volume'].mean(), bids['Volume'].std()
            ask_mean, ask_std = asks['Volume'].mean(), asks['Volume'].std()

            spoof_bids = bids[bids['Volume'] > (bid_mean + (bid_std * 4.5))]
            spoof_asks = asks[asks['Volume'] > (ask_mean + (ask_std * 4.5))]

            spoof_support = [
                {"Price": row['Price'], "Volume": round(row['Volume'], 2), "Type": "Fake Buy Wall"}
                for _, row in spoof_bids.head(5).iterrows()
            ]
            spoof_resistance = [
                {"Price": row['Price'], "Volume": round(row['Volume'], 2), "Type": "Fake Sell Wall"}
                for _, row in spoof_asks.head(5).iterrows()
            ]

            return {
                "source": source_note,
                "bid_imbalance": round(bid_imbalance, 2),
                "ask_imbalance": round(ask_imbalance, 2),
                "total_bids": round(total_bid_vol, 2),
                "total_asks": round(total_ask_vol, 2),
                "spoof_walls_bids": pd.DataFrame(spoof_support),
                "spoof_walls_asks": pd.DataFrame(spoof_resistance)
            }
        except Exception as e:
            return {"error": str(e)}

if __name__ == "__main__":
    engine = OrderFlowEngine('binance')
    print(engine.scan_l2_book('XAU/USD'))