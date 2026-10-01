import pandas as pd
import yfinance as yf

class HTFConfluenceEngine:
    def __init__(self, symbol="GC=F"):
        self.symbol = symbol

    def fetch_htf_bias(self) -> dict:
        try:
            ticker = yf.Ticker(self.symbol)
            df_1h = ticker.history(period="1mo", interval="1h")
            df_4h = ticker.history(period="3mo", interval="1h")
            
            if df_1h.empty:
                return {"bias": "NEUTRAL", "reason": "Insufficient 1h data"}

            # Resample 1h to 4h
            df_4h = df_1h.resample('4h').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

            # 1h Metrics
            df_1h['EMA_50'] = df_1h['Close'].ewm(span=50, adjust=False).mean()
            df_1h['EMA_200'] = df_1h['Close'].ewm(span=200, adjust=False).mean()
            curr_1h = df_1h.iloc[-1]
            trend_1h = "BULLISH" if curr_1h['Close'] > curr_1h['EMA_50'] else "BEARISH"

            # 4h Metrics
            df_4h['EMA_50'] = df_4h['Close'].ewm(span=50, adjust=False).mean()
            curr_4h = df_4h.iloc[-1]
            trend_4h = "BULLISH" if curr_4h['Close'] > curr_4h['EMA_50'] else "BEARISH"

            # Unified Confluence Decision
            if trend_1h == "BULLISH" and trend_4h == "BULLISH":
                macro_bias = "STRONG_BULLISH"
            elif trend_1h == "BEARISH" and trend_4h == "BEARISH":
                macro_bias = "STRONG_BEARISH"
            elif trend_1h == "BULLISH":
                macro_bias = "LEAN_BULLISH"
            else:
                macro_bias = "LEAN_BEARISH"

            return {
                "bias": macro_bias,
                "1h_trend": trend_1h,
                "4h_trend": trend_4h,
                "1h_ema50": round(curr_1h['EMA_50'], 2),
                "4h_ema50": round(curr_4h['EMA_50'], 2)
            }
        except Exception as e:
            return {"bias": "NEUTRAL", "error": str(e)}

if __name__ == "__main__":
    htf = HTFConfluenceEngine()
    print(htf.fetch_htf_bias())