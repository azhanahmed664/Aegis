import pandas as pd
import numpy as np

class SmartMoneyEngine:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    def map_fair_value_gaps(self) -> pd.DataFrame:
        """
        Mathematically identifies Fair Value Gaps (FVG) where price moved too quickly,
        creating an inefficiency between candles i and i-2.
        """
        # Shift data to compare current candle with the candle 2 periods ago
        self.df['Prev_2_High'] = self.df['High'].shift(2)
        self.df['Prev_2_Low'] = self.df['Low'].shift(2)
        
        # Bullish FVG: Current Low is higher than the High from 2 candles ago
        self.df['Bullish_FVG'] = np.where(self.df['Low'] > self.df['Prev_2_High'], True, False)
        self.df['Bullish_FVG_Size'] = np.where(self.df['Bullish_FVG'], self.df['Low'] - self.df['Prev_2_High'], 0)
        
        # Bearish FVG: Current High is lower than the Low from 2 candles ago
        self.df['Bearish_FVG'] = np.where(self.df['High'] < self.df['Prev_2_Low'], True, False)
        self.df['Bearish_FVG_Size'] = np.where(self.df['Bearish_FVG'], self.df['Prev_2_Low'] - self.df['High'], 0)
        
        return self.df

    def map_order_blocks(self) -> pd.DataFrame:
        """
        Identifies Order Blocks (OB): The last opposite-close candle before a strong impulsive move (FVG).
        """
        if 'Bullish_FVG' not in self.df.columns:
            self.map_fair_value_gaps()

        # Identify candle direction
        self.df['Is_Bearish_Candle'] = self.df['Close'] < self.df['Open']
        self.df['Is_Bullish_Candle'] = self.df['Close'] > self.df['Open']

        # Bullish Order Block: A bearish candle preceding a sequence that creates a Bullish FVG
        self.df['Bullish_OB'] = self.df['Bullish_FVG'].shift(-2) & self.df['Is_Bearish_Candle']
        
        # Bearish Order Block: A bullish candle preceding a sequence that creates a Bearish FVG
        self.df['Bearish_OB'] = self.df['Bearish_FVG'].shift(-2) & self.df['Is_Bullish_Candle']

        return self.df

    def scan_market(self):
        self.map_fair_value_gaps()
        self.map_order_blocks()
        
        # Filter only rows where an FVG or OB was detected
        signals = self.df[(self.df['Bullish_FVG']) | (self.df['Bearish_FVG']) | 
                          (self.df['Bullish_OB']) | (self.df['Bearish_OB'])].copy()
        
        # Export the structural price bounds (High, Low, Prev_2) to the charting engine
        return signals[['Timestamp', 'Close', 'High', 'Low', 'Prev_2_High', 'Prev_2_Low', 
                        'Bullish_FVG', 'Bearish_FVG', 'Bullish_OB', 'Bearish_OB']]
if __name__ == "__main__":
    from perpetuals_engine import PerpetualsEngine
    
    print("⚡ Fetching Live Perpetuals Data for SMC Mapping...")
    perp_engine = PerpetualsEngine()
    
    # Fetch 15m Binance BTC/USDT Perpetuals
    df = perp_engine.fetch_futures_data('binance', 'BTC/USDT', timeframe='15m', limit=100)
    
    if not df.empty:
        smc = SmartMoneyEngine(df)
        detected_zones = smc.scan_market()
        
        print("\n🎯 Institutional Zones Detected (Latest 5):")
        print(detected_zones.tail(5).to_string(index=False))