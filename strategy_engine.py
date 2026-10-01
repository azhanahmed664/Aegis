import vectorbt as vbt
from data_engine import UniversalDataEngine

class BacktestEngine:
    def __init__(self, initial_capital: float = 10000, fee_rate: float = 0.001):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate # 0.1% standard exchange fee

    def run_moving_average_crossover(self, symbol: str, asset_type: str, fast_window: int = 20, slow_window: int = 50, days: int = 730):
        print(f"⚙️ Running VectorBT Matrix Simulation for {symbol.upper()}...")
        
        # 1. Ingest Data
        engine = UniversalDataEngine()
        df = engine.fetch_data(symbol, asset_type=asset_type, interval="1d", lookback_days=days)
        
        # VectorBT requires a datetime index for time-series math
        close_price = df.set_index('Timestamp')['Close']

        # 2. Compute Technical Indicators (Instantly on CPU)
        fast_ma = vbt.MA.run(close_price, window=fast_window)
        slow_ma = vbt.MA.run(close_price, window=slow_window)

        # 3. Generate Trade Logic (Golden Cross / Death Cross)
        entries = fast_ma.ma_crossed_above(slow_ma)
        exits = fast_ma.ma_crossed_below(slow_ma)

        # 4. Simulate the Portfolio execution
        portfolio = vbt.Portfolio.from_signals(
            close=close_price,
            entries=entries,
            exits=exits,
            init_cash=self.initial_capital,
            fees=self.fee_rate
        )

        # 5. Extract core institutional metrics
        stats = {
            "Total Return (%)": round(portfolio.total_return() * 100, 2),
            "Win Rate (%)": round(portfolio.trades.win_rate() * 100, 2),
            "Profit Factor": round(portfolio.trades.profit_factor(), 2),
            "Max Drawdown (%)": round(portfolio.max_drawdown() * 100, 2),
            "Total Trades": portfolio.trades.count()
        }
        
        return stats

if __name__ == "__main__":
    backtester = BacktestEngine()
    
    # Run a 2-year simulation on Bitcoin
    results = backtester.run_moving_average_crossover("BTC/USDT", asset_type="crypto", days=730)
    
    print("\n📊 Strategy Results (20/50 MA Crossover):")
    for metric, value in results.items():
        print(f"{metric}: {value}")