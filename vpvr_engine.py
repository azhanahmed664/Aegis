import pandas as pd
import numpy as np

class VolumeProfileEngine:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    def calculate_profile(self, bins=50, value_area_pct=0.70) -> dict:
        if self.df.empty:
            return {}

        min_price = self.df['Low'].min()
        max_price = self.df['High'].max()
        
        # Create price bins
        price_bins = np.linspace(min_price, max_price, bins)
        volume_profile = np.zeros(bins)

        # Distribute volume across the price bins intersected by each candle
        for _, row in self.df.iterrows():
            high, low, vol = row['High'], row['Low'], row['Volume']
            
            if high == low:
                idx = (np.abs(price_bins - high)).argmin()
                volume_profile[idx] += vol
                continue
                
            # Find all bins that fall inside this candle's wick-to-wick range
            in_range = (price_bins >= low) & (price_bins <= high)
            num_bins = in_range.sum()
            
            if num_bins > 0:
                # Evenly distribute the candle's volume across the intersected bins
                volume_profile[in_range] += vol / num_bins
            else:
                idx = (np.abs(price_bins - (high+low)/2)).argmin()
                volume_profile[idx] += vol

        # 1. Identify Point of Control (POC)
        poc_idx = np.argmax(volume_profile)
        poc_price = price_bins[poc_idx]

        # 2. Calculate Value Area (70% of total volume)
        total_vol = np.sum(volume_profile)
        target_vol = total_vol * value_area_pct
        
        current_vol = volume_profile[poc_idx]
        up_idx = poc_idx + 1
        down_idx = poc_idx - 1
        
        # Expand outwards from POC until 70% volume is captured
        while current_vol < target_vol and (up_idx < bins or down_idx >= 0):
            vol_up = volume_profile[up_idx] if up_idx < bins else -1
            vol_down = volume_profile[down_idx] if down_idx >= 0 else -1
            
            if vol_up >= vol_down and vol_up != -1:
                current_vol += vol_up
                up_idx += 1
            elif vol_down > vol_up and vol_down != -1:
                current_vol += vol_down
                down_idx -= 1
            else:
                break
                
        # The bounds of the expansion are the Value Area High/Low
        vah = price_bins[min(up_idx, bins - 1)]
        val = price_bins[max(down_idx, 0)]
        
        return {
            "poc": round(poc_price, 2),
            "vah": round(vah, 2),
            "val": round(val, 2),
            "total_volume": round(total_vol, 2)
        }

if __name__ == "__main__":
    from perpetuals_engine import PerpetualsEngine
    print("⚡ Calculating Institutional Volume Profile...")
    engine = PerpetualsEngine()
    df = engine.fetch_futures_data('binance', 'BTC/USDT:USDT', timeframe='15m', limit=300)
    
    vpvr = VolumeProfileEngine(df)
    profile = vpvr.calculate_profile()
    
    print(f"🎯 Point of Control (POC): ${profile['poc']}")
    print(f"📈 Value Area High (VAH): ${profile['vah']}")
    print(f"📉 Value Area Low (VAL): ${profile['val']}")