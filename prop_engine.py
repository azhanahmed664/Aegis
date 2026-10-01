import vectorbt as vbt
import pandas as pd
import numpy as np
from smc_engine import SmartMoneyEngine

class ProprietaryBacktester:
    def __init__(self, df: pd.DataFrame, initial_cash=10000, fee_rate=0.0004):
        self.df = df.copy()
        self.initial_cash = initial_cash
        self.fee_rate = fee_rate # 0.04% average taker fee on Binance/MEXC

    def build_custom_signals(self):
        """
        CODE YOUR PROPRIETARY RULES HERE.
        This template buys when a Bullish FVG forms while price is above the 50 EMA.
        It shorts when a Bearish FVG forms while price is below the 50 EMA.
        """
        # 1. Calculate Technicals
        self.df['EMA_50'] = self.df['Close'].ewm(span=50, adjust=False).mean()
        
        # 2. Calculate SMC Structural Zones
        smc = SmartMoneyEngine(self.df)
        self.df = smc.map_fair_value_gaps()
        self.df = smc.map_order_blocks()

        # 3. Define Entry Logic (Boolean Arrays)
        # LONG: Bullish FVG detected AND Close price is above 50 EMA
        long_entries = self.df['Bullish_FVG'] & (self.df['Close'] > self.df['EMA_50'])
        
        # SHORT: Bearish FVG detected AND Close price is below 50 EMA
        short_entries = self.df['Bearish_FVG'] & (self.df['Close'] < self.df['EMA_50'])

        # 4. Define Exit Logic (Holding for 4 candles / 1 hour on a 15m chart)
        # In a real scenario, you would code your specific Take Profit / Stop Loss array here
        long_exits = long_entries.shift(4).fillna(False)
        short_exits = short_entries.shift(4).fillna(False)

        return long_entries, long_exits, short_entries, short_exits

def execute_backtest(self):
        # 1. Generate custom boolean signals
        long_in_raw, long_out_raw, short_in_raw, short_out_raw = self.build_custom_signals()
        
        # 2. FORCE STRICT C-TYPES FOR NUMBA COMPILER (CRITICAL FIX)
        close_price = self.df.set_index('Timestamp')['Close'].astype('float64')
        long_in = long_in_raw.astype(bool)
        long_out = long_out_raw.astype(bool)
        short_in = short_in_raw.astype(bool)
        short_out = short_out_raw.astype(bool)

        # 3. Align indices perfectly
        long_in.index = close_price.index
        long_out.index = close_price.index
        short_in.index = close_price.index
        short_out.index = close_price.index

        print("⚙️ Executing VectorBT Matrix Simulation (C-Compiled)...")
        
        try:
            portfolio = vbt.Portfolio.from_signals(
                close=close_price,
                entries=long_in,
                exits=long_out,
                short_entries=short_in,
                short_exits=short_out,
                init_cash=self.initial_cash,
                fees=self.fee_rate
            )
            
            trades = portfolio.trades.count()
            if trades == 0:
                return None
                
            return {
                "total_return": round(portfolio.total_return() * 100, 2),
                "win_rate": round(portfolio.trades.win_rate() * 100, 2),
                "max_dd": round(portfolio.max_drawdown() * 100, 2),
                "profit_factor": round(portfolio.trades.profit_factor(), 2),
                "total_trades": trades,
                "equity_curve": portfolio.value()
            }
        except Exception as e:
            print(f"❌ VectorBT Execution Error: {e}")
            return None
            
        # 4. Return clean, raw metrics for the Streamlit UI
        return {
            "total_return": round(portfolio.total_return() * 100, 2),
            "win_rate": round(portfolio.trades.win_rate() * 100, 2),
            "max_dd": round(portfolio.max_drawdown() * 100, 2),
            "profit_factor": round(portfolio.trades.profit_factor(), 2),
            "total_trades": trades,
            "equity_curve": portfolio.value() # Pandas Series for Streamlit charting
        }