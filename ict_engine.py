import pandas as pd
import numpy as np

class ICTKillzoneEngine:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        # Convert timestamps to UTC for standardized session windows
        if self.df['Timestamp'].dt.tz is None:
            self.df['Timestamp'] = self.df['Timestamp'].dt.tz_localize('UTC')
        else:
            self.df['Timestamp'] = self.df['Timestamp'].dt.tz_convert('UTC')
            
        self.df['Hour'] = self.df['Timestamp'].dt.hour
        self.df['Date'] = self.df['Timestamp'].dt.date

    def tag_sessions(self) -> pd.DataFrame:
        """
        Standard ICT Killzone hours (UTC):
        - Asian Range: 00:00 - 08:00 UTC
        - London Open Killzone: 07:00 - 10:00 UTC
        - New York Open Killzone: 12:00 - 15:00 UTC
        """
        conditions = [
            (self.df['Hour'] >= 0) & (self.df['Hour'] < 8),
            (self.df['Hour'] >= 7) & (self.df['Hour'] < 10),
            (self.df['Hour'] >= 12) & (self.df['Hour'] < 15)
        ]
        choices = ['Asian Range', 'London Open', 'New York Open']
        self.df['Session'] = np.select(conditions, choices, default='Off-Hours')
        return self.df

    def detect_asian_liquidity_sweeps(self) -> dict:
        """
        Calculates Asian High/Low and flags sweeps during London or New York sessions.
        """
        self.tag_sessions()
        latest_date = self.df['Date'].iloc[-1]
        today_data = self.df[self.df['Date'] == latest_date]
        
        asian = today_data[today_data['Session'] == 'Asian Range']
        if asian.empty:
            return {"status": "Awaiting Asian Session data"}
            
        asian_high = asian['High'].max()
        asian_low = asian['Low'].min()
        
        # Post-Asian price action
        post_asian = today_data[today_data['Timestamp'] > asian['Timestamp'].max()]
        
        swept_high = False
        swept_low = False
        
        if not post_asian.empty:
            swept_high = post_asian['High'].max() > asian_high
            swept_low = post_asian['Low'].min() < asian_low
            
        latest_price = self.df['Close'].iloc[-1]
        
        return {
            "asian_high": round(asian_high, 2),
            "asian_low": round(asian_low, 2),
            "latest_price": round(latest_price, 2),
            "high_swept": bool(swept_high),
            "low_swept": bool(swept_low),
            "bias": "Bearish Expansion" if swept_high and not swept_low else ("Bullish Expansion" if swept_low and not swept_high else "Ranging / Neutral")
        }

if __name__ == "__main__":
    from perpetuals_engine import PerpetualsEngine
    engine = PerpetualsEngine()
    df = engine.fetch_futures_data('binance', 'BTC/USDT:USDT', timeframe='15m', limit=200)
    ict = ICTKillzoneEngine(df)
    print(ict.detect_asian_liquidity_sweeps())