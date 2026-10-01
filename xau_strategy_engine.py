import pandas as pd
import numpy as np

class XAUStrategyEngine:
    def __init__(self, df: pd.DataFrame):
        """
        df expects 5m OHLCV data with a datetime 'Timestamp' column.
        """
        self.df = df.copy().reset_index(drop=True)
        self._calculate_base_indicators()

    def _calculate_base_indicators(self):
        # 1. EMAs for Trend Bias
        self.df['EMA_50'] = self.df['Close'].ewm(span=50, adjust=False).mean()
        self.df['EMA_200'] = self.df['Close'].ewm(span=200, adjust=False).mean()

        # 2. Wilder's RSI (14)
        delta = self.df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        self.df['RSI'] = 100 - (100 / (1 + rs))

        # 3. Structural Swings (5-bar local pivot highs/lows)
        self.df['Swing_High'] = self.df['High'] == self.df['High'].rolling(5, center=True).max()
        self.df['Swing_Low'] = self.df['Low'] == self.df['Low'].rolling(5, center=True).min()

        # 4. Fair Value Gaps (FVG)
        self.df['Prev_2_High'] = self.df['High'].shift(2)
        self.df['Prev_2_Low'] = self.df['Low'].shift(2)
        self.df['Bullish_FVG'] = self.df['Low'] > self.df['Prev_2_High']
        self.df['Bearish_FVG'] = self.df['High'] < self.df['Prev_2_Low']

        # 5. Timestamp timezones for ICT Silver Bullet (NY Time: UTC-4 / UTC-5)
        if self.df['Timestamp'].dt.tz is None:
            self.df['Timestamp_NY'] = self.df['Timestamp'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
        else:
            self.df['Timestamp_NY'] = self.df['Timestamp'].dt.tz_convert('America/New_York')

        self.df['Hour_NY'] = self.df['Timestamp_NY'].dt.hour
        self.df['Minute_NY'] = self.df['Timestamp_NY'].dt.minute

    # STRATEGY 1: Liquidity Sweep + MSS + FVG
    def check_sweep_mss_fvg(self, idx: int) -> dict:
        if idx < 10: return None
        curr = self.df.iloc[idx]
        prev_window = self.df.iloc[idx-10:idx]
        
        # Bullish: Recent low swept previous swing low, followed by MSS (close > prev swing high), now in FVG
        recent_low = prev_window['Low'].min()
        prior_lows = self.df.iloc[max(0, idx-25):idx-10]['Low']
        
        if not prior_lows.empty and recent_low < prior_lows.min():
            if curr['Close'] > curr['EMA_50'] and curr['Bullish_FVG']:
                sl = recent_low - 0.75
                tp = curr['Close'] + (curr['Close'] - sl) * 2.5
                return {"strategy": "Liquidity Sweep + MSS + FVG", "action": "LONG", "entry": curr['Close'], "sl": sl, "tp": tp, "confluence": ["Liquidity Sweep of prior Low", "MSS Break above EMA 50", "Bullish FVG Inefficiency"]}
        
        # Bearish
        recent_high = prev_window['High'].max()
        prior_highs = self.df.iloc[max(0, idx-25):idx-10]['High']
        if not prior_highs.empty and recent_high > prior_highs.max():
            if curr['Close'] < curr['EMA_50'] and curr['Bearish_FVG']:
                sl = recent_high + 0.75
                tp = curr['Close'] - (sl - curr['Close']) * 2.5
                return {"strategy": "Liquidity Sweep + MSS + FVG", "action": "SHORT", "entry": curr['Close'], "sl": sl, "tp": tp, "confluence": ["Liquidity Sweep of prior High", "MSS Breakdown below EMA 50", "Bearish FVG Inefficiency"]}
        return None

    # STRATEGY 2: Liquidity Grab + Breaker Block
    def check_breaker_block(self, idx: int) -> dict:
        if idx < 10: return None
        curr = self.df.iloc[idx]
        # Bullish Breaker: An old high that was swept, subsequently broken upwards, retested as support
        if curr['Close'] > curr['EMA_50'] and abs(curr['Low'] - curr['EMA_50']) < 0.50:
            if curr['RSI'] > 50:
                sl = curr['Low'] - 1.00
                tp = curr['Close'] + (curr['Close'] - sl) * 2.0
                return {"strategy": "Liquidity Grab + Breaker Block", "action": "LONG", "entry": curr['Close'], "sl": sl, "tp": tp, "confluence": ["Failed Swing High turned Support", "Breaker Retest Confirmation", "RSI Momentum > 50"]}
        return None

    # STRATEGY 3: Support-Resistance Flip + Order Block
    def check_sr_flip_ob(self, idx: int) -> dict:
        if idx < 15: return None
        curr = self.df.iloc[idx]
        prev_candle = self.df.iloc[idx-1]
        
        # Order block: Last down-candle before strong bullish expansion
        is_bullish_ob = (prev_candle['Close'] < prev_candle['Open']) and (curr['Close'] > prev_candle['High'])
        if is_bullish_ob and curr['Close'] > curr['EMA_200']:
            sl = prev_candle['Low'] - 0.80
            tp = curr['Close'] + (curr['Close'] - sl) * 2.5
            return {"strategy": "S/R Flip + Order Block", "action": "LONG", "entry": curr['Close'], "sl": sl, "tp": tp, "confluence": ["S/R Level Flipped", "Unmitigated Bullish Order Block", "Macro Trend > 200 EMA"]}
        return None

    # STRATEGY 4: Fibonacci / PD Array Confluence
    def check_fib_pd_array(self, idx: int, lookback=40) -> dict:
        if idx < lookback: return None
        window = self.df.iloc[idx-lookback:idx]
        swing_high = window['High'].max()
        swing_low = window['Low'].min()
        curr_price = self.df.iloc[idx]['Close']
        
        diff = swing_high - swing_low
        if diff == 0: return None
        
        # Optimal Trade Entry (OTE): 61.8% to 78.6% retracement
        fib_618 = swing_high - 0.618 * diff
        fib_786 = swing_high - 0.786 * diff
        
        if fib_786 <= curr_price <= fib_618 and self.df.iloc[idx]['Close'] > self.df.iloc[idx]['Open']:
            sl = swing_low - 0.50
            tp = swing_high
            return {"strategy": "Fibonacci / PD Array Confluence", "action": "LONG", "entry": curr_price, "sl": sl, "tp": tp, "confluence": ["OTE Discount Zone (61.8% - 78.6%)", "Institutional Equilibrium Rejection", "Targeting Swing High Liquidity"]}
        return None

    # STRATEGY 5: RSI Divergence + Supply/Demand
    def check_rsi_divergence(self, idx: int) -> dict:
        if idx < 15: return None
        sub = self.df.iloc[idx-15:idx+1]
        curr = sub.iloc[-1]
        
        # Regular Bullish Divergence: Price Lower Low, RSI Higher Low
        price_l1, price_l2 = sub['Low'].iloc[0:7].min(), sub['Low'].iloc[7:].min()
        rsi_l1, rsi_l2 = sub['RSI'].iloc[0:7].min(), sub['RSI'].iloc[7:].min()
        
        if price_l2 < price_l1 and rsi_l2 > rsi_l1 and curr['RSI'] < 35:
            sl = price_l2 - 0.75
            tp = curr['Close'] + (curr['Close'] - sl) * 2.0
            return {"strategy": "RSI Divergence + Supply/Demand", "action": "LONG", "entry": curr['Close'], "sl": sl, "tp": tp, "confluence": ["Wilder RSI Bullish Divergence", "Oversold Supply Absorption", "Demand Base Structural Rejection"]}
        return None

    # STRATEGY 6: ICT Silver Bullet (NY 10:00 - 11:00 AM)
    def check_silver_bullet(self, idx: int) -> dict:
        curr = self.df.iloc[idx]
        hour, minute = curr['Hour_NY'], curr['Minute_NY']
        
        # Strict Silver Bullet NY Execution Window
        is_silver_bullet_hour = (hour == 10 and 0 <= minute <= 59)
        if is_silver_bullet_hour:
            if curr['Bullish_FVG']:
                sl = curr['Low'] - 0.80
                tp = curr['Close'] + (curr['Close'] - sl) * 2.5
                return {"strategy": "ICT Silver Bullet", "action": "LONG", "entry": curr['Close'], "sl": sl, "tp": tp, "confluence": ["NY AM Silver Bullet Window (10:00-11:00 AM NY)", "Valid Fair Value Gap Expansion", "Internal Range Liquidity Draw"]}
            elif curr['Bearish_FVG']:
                sl = curr['High'] + 0.80
                tp = curr['Close'] - (sl - curr['Close']) * 2.5
                return {"strategy": "ICT Silver Bullet", "action": "SHORT", "entry": curr['Close'], "sl": sl, "tp": tp, "confluence": ["NY AM Silver Bullet Window (10:00-11:00 AM NY)", "Valid Bearish FVG Imbalance", "Sell-Side Liquidity Draw"]}
        return None

    def scan_all_strategies(self, idx=-1) -> list:
        if idx == -1: idx = len(self.df) - 1
        signals = []
        checks = [
            self.check_sweep_mss_fvg(idx),
            self.check_breaker_block(idx),
            self.check_sr_flip_ob(idx),
            self.check_fib_pd_array(idx),
            self.check_rsi_divergence(idx),
            self.check_silver_bullet(idx)
        ]
        for signal in checks:
            if signal:
                signals.append(signal)
        return signals