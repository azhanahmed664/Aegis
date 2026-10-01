import pandas as pd
from perpetuals_engine import PerpetualsEngine

class SMTDivergenceScanner:
    def __init__(self, asset_a_name: str, df_a: pd.DataFrame, asset_b_name: str, df_b: pd.DataFrame):
        self.asset_a = asset_a_name
        self.asset_b = asset_b_name
        
        # Standardize index for clean structural joining
        self.df_a = df_a.set_index('Timestamp')
        self.df_b = df_b.set_index('Timestamp')

    def scan(self, lookback=20):
        """
        Scans for SMT Divergence by comparing the structural highs/lows 
        between two correlated assets over the recent lookback window.
        """
        # Join dataframes on timestamp to ensure exact temporal alignment
        df = self.df_a.join(self.df_b, lsuffix='_A', rsuffix='_B', how='inner').tail(lookback)
        
        if df.empty or len(df) < lookback:
            return "Insufficient aligned data between assets."

        # Split the lookback window to find the two most recent structural swings
        mid_point = len(df) // 2
        first_half = df.iloc[:mid_point]
        second_half = df.iloc[mid_point:]

        # Asset A Swings
        a_high_1, a_high_2 = first_half['High_A'].max(), second_half['High_A'].max()
        a_low_1, a_low_2 = first_half['Low_A'].min(), second_half['Low_A'].min()

        # Asset B Swings
        b_high_1, b_high_2 = first_half['High_B'].max(), second_half['High_B'].max()
        b_low_1, b_low_2 = first_half['Low_B'].min(), second_half['Low_B'].min()

        bullish_smt = False
        bearish_smt = False
        details = []

        # Bearish SMT: Asset A makes Higher High, Asset B makes Lower High (or vice versa)
        if a_high_2 > a_high_1 and b_high_2 < b_high_1:
            bearish_smt = True
            details.append(f"🚨 BEARISH SMT: {self.asset_a} swept liquidity (Higher High), but {self.asset_b} failed (Lower High).")
        elif a_high_2 < a_high_1 and b_high_2 > b_high_1:
            bearish_smt = True
            details.append(f"🚨 BEARISH SMT: {self.asset_b} swept liquidity (Higher High), but {self.asset_a} failed (Lower High).")

        # Bullish SMT: Asset A makes Lower Low, Asset B makes Higher Low (or vice versa)
        if a_low_2 < a_low_1 and b_low_2 > b_low_1:
            bullish_smt = True
            details.append(f"🟢 BULLISH SMT: {self.asset_a} swept liquidity (Lower Low), but {self.asset_b} failed (Higher Low).")
        elif a_low_2 > a_low_1 and b_low_2 < b_low_1:
            bullish_smt = True
            details.append(f"🟢 BULLISH SMT: {self.asset_b} swept liquidity (Lower Low), but {self.asset_a} failed (Higher Low).")

        if not bullish_smt and not bearish_smt:
            return "✅ Structural Alignment Confirmed: No SMT Divergence detected."
        
        return "\n".join(details)

if __name__ == "__main__":
    print("⚡ Fetching Correlated Perpetuals Data (BTC vs ETH)...")
    engine = PerpetualsEngine()
    
    # Fetch 15m data for the two most heavily correlated crypto assets
    df_btc = engine.fetch_futures_data('binance', 'BTC/USDT:USDT', timeframe='15m', limit=50)
    df_eth = engine.fetch_futures_data('binance', 'ETH/USDT:USDT', timeframe='15m', limit=50)
    
    if not df_btc.empty and not df_eth.empty:
        scanner = SMTDivergenceScanner('BTC', df_btc, 'ETH', df_eth)
        result = scanner.scan(lookback=20)
        
        print("\n🔍 Institutional SMT Scan Results:")
        print(result)