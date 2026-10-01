import pandas as pd
import yfinance as yf
import ccxt
from datetime import datetime, timedelta

class UniversalDataEngine:
    def __init__(self):
        # Initialize public exchange client for Crypto (no API keys needed for public ticker data)
        self.crypto_client = ccxt.binance({
            'enableRateLimit': True,
            'timeout': 10000
        })

    def fetch_data(self, symbol: str, asset_type: str = "stock", interval: str = "1d", lookback_days: int = 180) -> pd.DataFrame:
        """
        Unified fetcher for all asset classes.
        Returns a standardized DataFrame: ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
        """
        asset_type = asset_type.lower()
        print(f"📡 Ingesting {symbol.upper()} [{asset_type.upper()}] | Interval: {interval}...")

        if asset_type in ["stock", "forex", "commodity", "index"]:
            return self._fetch_yfinance(symbol, interval, lookback_days)
        elif asset_type == "crypto":
            return self._fetch_crypto(symbol, interval, lookback_days)
        else:
            raise ValueError(f"Unsupported asset type: {asset_type}")

    def _fetch_yfinance(self, ticker: str, interval: str, lookback_days: int) -> pd.DataFrame:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        
        # Download historical data
        df = yf.download(
            ticker, 
            start=start_date.strftime('%Y-%m-%d'), 
            end=end_date.strftime('%Y-%m-%d'), 
            interval=interval, 
            progress=False
        )

        if df.empty:
            raise ValueError(f"No market data returned for symbol: {ticker}")

        # Flatten multi-index columns if returned by newer yfinance versions
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.reset_index()
        
        # Standardize column naming
        date_col = 'Date' if 'Date' in df.columns else 'Datetime'
        df.rename(columns={date_col: 'Timestamp'}, inplace=True)
        
        df = df[['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        return df

    def _fetch_crypto(self, symbol: str, timeframe: str, lookback_days: int) -> pd.DataFrame:
        # Standardize timeframe to CCXT format (e.g., '1d', '1h', '15m')
        ccxt_tf = timeframe if timeframe in ['1m', '5m', '15m', '1h', '4h', '1d'] else '1d'
        since = int((datetime.now() - timedelta(days=lookback_days)).timestamp() * 1000)

        # Ensure pair format (e.g. BTC/USDT)
        if "/" not in symbol:
            symbol = f"{symbol.upper()}/USDT"

        ohlcv = self.crypto_client.fetch_ohlcv(symbol, timeframe=ccxt_tf, since=since, limit=lookback_days)
        
        df = pd.DataFrame(ohlcv, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='ms')
        return df

if __name__ == "__main__":
    engine = UniversalDataEngine()

    # 1. Test Commodity: Gold Futures (GC=F)
    gold_df = engine.fetch_data("GC=F", asset_type="commodity", interval="1d", lookback_days=30)
    print("Gold Latest Close:", round(gold_df['Close'].iloc[-1], 2))

    # 2. Test Forex: EUR/USD (EURUSD=X)
    fx_df = engine.fetch_data("EURUSD=X", asset_type="forex", interval="1d", lookback_days=30)
    print("EUR/USD Latest Close:", round(fx_df['Close'].iloc[-1], 4))

    # 3. Test Crypto: Bitcoin (BTC/USDT)
    btc_df = engine.fetch_data("BTC/USDT", asset_type="crypto", interval="1d", lookback_days=30)
    print("BTC/USDT Latest Close:", round(btc_df['Close'].iloc[-1], 2))

    print("\n✅ Universal Data Engine is fully operational across all asset classes.")