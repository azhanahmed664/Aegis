import numpy as np
import pandas as pd

class QuantitativeRiskEngine:
    def __init__(self, confidence_level=0.95):
        self.confidence_level = confidence_level

    def calculate_metrics(self, df: pd.DataFrame) -> dict:
        """
        Calculates key risk metrics with zero LLM tokens.
        """
        # Calculate daily percentage returns
        returns = df['Close'].pct_change().dropna()

        # 1. Historical Value at Risk (VaR)
        percentile_cutoff = (1 - self.confidence_level) * 100
        var_pct = np.percentile(returns, percentile_cutoff)

        # 2. Maximum Drawdown
        cumulative = (1 + returns).cumprod()
        peak = cumulative.cummax()
        drawdown = (cumulative - peak) / peak
        max_dd = drawdown.min()

        # 3. Annualized Volatility (assuming 252 trading days)
        volatility = np.std(returns, ddof=1) * np.sqrt(252)

        # 4. Current Trend (Simple 20-day SMA vs Close)
        sma_20 = df['Close'].rolling(window=20).mean().iloc[-1]
        latest_close = df['Close'].iloc[-1]
        trend = "Bullish" if latest_close > sma_20 else "Bearish"

        # Pack into a highly token-efficient JSON payload for the local LLM
        return {
            "latest_close": round(latest_close, 2),
            "var_95_pct": round(var_pct * 100, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "annual_volatility_pct": round(volatility * 100, 2),
            "trend": trend
        }

if __name__ == "__main__":
    from data_engine import UniversalDataEngine
    
    # 1. Fetch 1 year of daily Bitcoin data
    data_engine = UniversalDataEngine()
    btc_df = data_engine.fetch_data("BTC/USDT", asset_type="crypto", interval="1d", lookback_days=365)
    
    # 2. Calculate Risk
    risk_engine = QuantitativeRiskEngine()
    metrics = risk_engine.calculate_metrics(btc_df)
    
    print("\n✅ Risk Calculation Complete (0 Tokens Used)")
    print("Pre-processed LLM Payload:", metrics)