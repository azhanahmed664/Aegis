import ccxt
import json

class WatchlistEngine:
    def __init__(self):
        # binanceusdm natively targets the USDT-margined futures API
        self.binance = ccxt.binanceusdm({'enableRateLimit': True})
        
        # mexc defaults to spot; we override to target perpetual swaps
        self.mexc = ccxt.mexc({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

    def generate_perpetual_universe(self):
        print("⚡ Syncing live market data from Binance & MEXC...")
        
        universe = {
            "BINANCE_USDT_PERP": [],
            "MEXC_USDT_PERP": []
        }
        
        # 1. Fetch Binance Universe
        print("📡 Fetching Binance USD-M Swaps...")
        binance_markets = self.binance.load_markets()
        for symbol, market in binance_markets.items():
            # Strict filter: Must be a swap, linear (USDT-margined), and currently active
            if market.get('swap') and market.get('linear') and market.get('active'):
                universe["BINANCE_USDT_PERP"].append(symbol)
                
        # 2. Fetch MEXC Universe
        print("📡 Fetching MEXC USDT Swaps...")
        mexc_markets = self.mexc.load_markets()
        for symbol, market in mexc_markets.items():
            if market.get('swap') and market.get('linear') and market.get('active'):
                universe["MEXC_USDT_PERP"].append(symbol)
                
        # Sort alphabetically for clean UI rendering later
        universe["BINANCE_USDT_PERP"].sort()
        universe["MEXC_USDT_PERP"].sort()
        
        # Save to local JSON to avoid re-fetching directory lists
        with open("aegis_universe.json", "w") as f:
            json.dump(universe, f, indent=4)
            
        print("\n✅ Institutional Universe Synchronized")
        print(f"📊 Total Binance Pairs: {len(universe['BINANCE_USDT_PERP'])}")
        print(f"📊 Total MEXC Pairs: {len(universe['MEXC_USDT_PERP'])}")
        print("💾 Universe saved locally to 'aegis_universe.json'")

if __name__ == "__main__":
    engine = WatchlistEngine()
    engine.generate_perpetual_universe()